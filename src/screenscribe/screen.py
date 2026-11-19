"""On-screen text: notice when the picture changes, OCR that frame, keep only the new text."""

import difflib
import re
import time

import cv2
import numpy as np

from . import models
from .media import frames

CHANGED = 0.004  # share of pixels that must differ from the last OCR'ed frame
STILL = 0.002  # below this share between two samples the picture counts as settled
MIN_NEW_LETTERS = 20  # less new text than this is noise (clocks, counters, a name label)


def read_screens(path, threads: int = 4, progress=lambda message: None) -> list[dict]:
    """Return [{start, title, major, lines, new, image}], one entry per screen state that brought new text.

    `lines` is everything readable on that frame, `new` only what the previously kept
    screen did not have (so window chrome and unchanged content are not repeated),
    `title` the largest new text (a slide or page heading), `image` a JPEG of the frame.
    `major` tells a new screen from a small change of the same one: most of the text is
    new, or the largest text is. The second test is what catches a new slide when a busy
    chat panel beside it holds more lines than the slide does.
    """
    ocr = None
    screens, seen = [], []
    last = previous = since = None
    wait, sampled, read_at, gap = 3.0, 0.0, -1e9, 0.0
    for now, image in frames(path):
        small = cv2.cvtColor(cv2.resize(image, (480, 270), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        settled = previous is not None and _moved(small, previous) < STILL
        previous, before, sampled = small, sampled, now
        if last is not None and _moved(small, last) < CHANGED:
            since = None
            continue
        # the picture changed somewhere between the two samples: take the middle
        since = (before + now) / 2 if since is None else since
        # A picture that has settled (a new slide) is always read. One that keeps moving
        # (a scroll, a webcam tile in the corner) is given time to settle, but not
        # forever, and is read at most every `gap` seconds: that keeps OCR of a busy
        # screen below about two thirds of real time on a slow PC without ever skipping
        # a slide there.
        if not settled and (now - since < wait or now - read_at < gap):
            continue
        progress(f"Reading the screen: {int(now) // 60:02}:{int(now) % 60:02}")
        ocr = ocr or _engine(threads)
        began = time.perf_counter()
        table = [[(size, fix_scripts(text)) for size, text in row] for row in to_rows(ocr(image, use_cls=False))]
        read_at, gap = now, 1.5 * (time.perf_counter() - began)
        lines = [" | ".join(text for _, text in row) for row in table]
        found = [kept for row in table if (kept := fresh([text for _, text in row], seen))]
        new = [" | ".join(kept) for kept in found]
        last = small
        # letters only: digits alone are mostly clocks, counters and misread icons
        if sum(c.isalpha() for line in new for c in line) < MIN_NEW_LETTERS:
            wait = min(wait * 2, 30.0)  # nothing readable is changing: look less often
            since = None
            continue
        wait = 3.0
        height, width = image.shape[:2]
        scale = min(1.0, 1280 / width)
        thumb = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        title, heading_is_new = headline(table, found)
        screens.append({"start": since, "title": title, "major": heading_is_new or len(new) * 2 > len(lines),
                        "lines": lines, "new": new,
                        "image": cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()})
        seen = [key(text) for row in table for _, text in row]
        since = None
    return screens


def headline(table: list[list[tuple]], found: list[list[str]]) -> tuple[str, bool]:
    """Name a screen by its largest new text (usually the slide or page heading).

    Also tells whether the heading itself has changed: the new text is as large as
    anything on the screen and clearly larger than ordinary text there (when all text
    is one size, as in a chat, nothing is a heading). The first new line is often window chrome,
    so it is not used. New segments nearly as large as the largest are taken together,
    in reading order, so a heading of two lines stays whole; more than three of them
    is body text, and then the largest stands alone. Segments without words (numbers,
    misread icons) are not candidates.
    """
    def has_words(text: str) -> bool:
        return sum(c.isalpha() for c in text) > 3

    size_of = {text: size for row in table for size, text in row}
    worded = [text for kept in found for text in kept if has_words(text)]
    if not worded:
        return " ".join(found[0])[:80], False
    largest = max(size_of[text] for text in worded)
    top = [text for text in worded if size_of[text] >= 0.85 * largest]
    title = " ".join(top) if len(top) <= 3 else max(worded, key=size_of.get)
    sizes = sorted(size for row in table for size, text in row if has_words(text))
    stands_out = largest >= 0.85 * sizes[-1] and largest >= 1.3 * sizes[len(sizes) // 2]
    return title[:80], bool(stands_out)  # sizes are numpy floats; JSON wants a plain bool


def to_rows(result) -> list[list[tuple[float, str]]]:
    """Turn OCR boxes into rows of text in reading order (panes one after another, rows inside).

    A row is a list of (text height, text) segments: boxes close together make one
    segment, boxes far apart on the same row (table cells, or two panes the cut could
    not separate) stay apart.
    """
    if result.boxes is None:
        return []
    cells = [(box[:, 0].min(), box[:, 1].min(), box[:, 0].max(), box[:, 1].max(), text.strip())
             for box, text in zip(result.boxes, result.txts) if len(text.strip()) > 1]
    if not cells:
        return []
    height = float(np.median([bottom - top for _, top, _, bottom, _ in cells]))
    return [row for block in blocks(cells, height) for row in rows(block, height)]


def blocks(cells: list[tuple], height: float) -> list[list[tuple]]:
    """Split (left, top, right, bottom, text) cells into panes by recursive XY-cut.

    A screen share is often several panes side by side (file tree | editor, chat | slide).
    Reading it row by row would interleave them, so first cut at an empty vertical strip
    wider than five text heights (a gutter), else at an empty horizontal strip taller
    than one text height (a section break), and look for gutters again inside each part.
    """
    for low, high, minimum in ((0, 2, 5 * height), (1, 3, height)):
        spans = sorted((cell[low], cell[high]) for cell in cells)
        widest, edge, reach = 0.0, None, spans[0][1]
        for start, end in spans[1:]:
            if start - reach > widest:
                widest, edge = start - reach, start
            reach = max(reach, end)
        if widest > minimum:
            return (blocks([cell for cell in cells if cell[low] < edge], height)
                    + blocks([cell for cell in cells if cell[low] >= edge], height))
    return [cells]


def rows(cells: list[tuple], height: float) -> list[list[tuple[float, str]]]:
    """Rows of one pane, top to bottom, each a list of (text height, text) segments."""
    grouped = []  # [center y, [(left, right, box height, text)]]
    for left, top, right, bottom, text in sorted(cells, key=lambda cell: cell[1] + cell[3]):
        center = (top + bottom) / 2
        if grouped and abs(center - grouped[-1][0]) < 0.5 * height:
            grouped[-1][1].append((left, right, bottom - top, text))
        else:
            grouped.append([center, [(left, right, bottom - top, text)]])
    out = []
    for _, row in grouped:
        row.sort()
        segments = [row[0][2:]]
        for (_, right, _, _), (left, _, size, text) in zip(row, row[1:]):
            if left - right > 2 * height:
                segments.append((size, text))
            else:
                segments[-1] = (max(segments[-1][0], size), segments[-1][1] + " " + text)
        out.append(segments)
    return out


def fresh(row: list[str], seen: list[str]) -> list[str]:
    """Segments of one row that the previous screen did not show.

    Small OCR differences do not count as new. Segments are compared one by one, so a
    slide line that shares a row with a chat message is not repeated when only the
    message is new. One- and two-character segments cannot be judged and stay with
    their row if anything else in it is new.
    """
    known = set(seen)
    kept = [text for text in row if len(key(text)) < 3
            or key(text) not in known and not difflib.get_close_matches(key(text), seen, 1, 0.8)]
    return kept if any(len(key(text)) > 2 for text in kept) else []


_TO_LATIN = str.maketrans("асеорхукмтнвіѕјАВСЕНКМОРТХУІЅЈ", "aceopxykmthbisjABCEHKMOPTXYISJ")
_TO_CYRILLIC = str.maketrans("aceopxyABCEHKMOPTX", "асеорхуАВСЕНКМОРТХ")
_RUSSIAN = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")


def fix_scripts(text: str) -> str:
    """Repair words where OCR mixed look-alike Cyrillic and Latin letters (СRМ -> CRM).

    A word that can be spelled in only one alphabet is converted to it; if both are
    possible the majority of its letters decides. Tuned for Russian text with English
    terms: Cyrillic letters outside the Russian alphabet (і, ѕ) count as Latin.
    """
    def repair(match: re.Match) -> str:
        word = match.group()
        if word.isascii() or not any(c.isascii() for c in word):
            return word  # one alphabet only: nothing was mixed
        latin_votes = sum(c.isascii() or c.lower() not in _RUSSIAN for c in word)
        as_latin, as_cyrillic = word.translate(_TO_LATIN), word.translate(_TO_CYRILLIC)
        can_latin, can_cyrillic = as_latin.isascii(), not any(c.isascii() for c in as_cyrillic)
        if can_latin and can_cyrillic:
            if latin_votes * 2 == len(word):
                return word
            return as_latin if latin_votes * 2 > len(word) else as_cyrillic
        return as_latin if can_latin else as_cyrillic if can_cyrillic else word

    return re.sub(r"[^\W\d_]+", repair, text)


def key(line: str) -> str:
    """Comparison form of a line: letters and digits only, lower case."""
    return re.sub(r"\W+", "", line).lower()


def _moved(a: np.ndarray, b: np.ndarray) -> float:
    return float((cv2.absdiff(a, b) > 24).mean())


def _engine(threads: int):
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR  # slow import, only needed for video

    return RapidOCR(params={
        # The tiny detector found the same boxes as the default "small" one at a quarter of the time.
        "Det.ocr_version": OCRVersion.PPOCRV6,
        "Det.model_type": ModelType.TINY,
        # Cyrillic model: reads Russian and Latin text; it mixed the two alphabets less
        # than the "eslav" model on slides with English terms.
        "Rec.lang_type": LangRec.CYRILLIC,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
        "Global.log_level": "error",
        "Global.model_root_dir": str(models.CACHE / "rapidocr"),
        "EngineConfig.onnxruntime.intra_op_num_threads": threads,
    })
