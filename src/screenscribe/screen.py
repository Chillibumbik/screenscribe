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
MIN_NEW_CHARS = 12  # less new text than this is noise (clocks, counters, cursor)


def read_screens(path, threads: int = 4, progress=lambda message: None) -> list[dict]:
    """Return [{start, lines, new, image}], one entry per screen state that brought new text.

    `lines` is everything readable on that frame, `new` only what the previously kept
    screen did not have (so window chrome and unchanged content are not repeated),
    `image` is a JPEG of the frame.
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
        # Let a transition or scroll settle before reading it, but not forever:
        # a webcam tile in the corner never settles.
        if not settled and now - since < wait:
            continue
        # Keep OCR below about two thirds of real time on any machine: a slow PC reads
        # a busy screen less often instead of taking hours.
        if now - read_at < gap:
            continue
        progress(f"Reading the screen: {int(now) // 60:02}:{int(now) % 60:02}")
        ocr = ocr or _engine(threads)
        began = time.perf_counter()
        lines = [fix_scripts(line) for line in to_lines(ocr(image, use_cls=False))]
        read_at, gap = now, 1.5 * (time.perf_counter() - began)
        new = fresh(lines, seen)
        last = small
        if sum(len(key(line)) for line in new) < MIN_NEW_CHARS:
            wait = min(wait * 2, 30.0)  # nothing readable is changing: look less often
            since = None
            continue
        wait = 3.0
        height, width = image.shape[:2]
        scale = min(1.0, 1280 / width)
        thumb = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        screens.append({"start": since, "lines": lines, "new": new,
                        "image": cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()})
        seen = [key(line) for line in lines]
        since = None
    return screens


def to_lines(result) -> list[str]:
    """Turn OCR boxes into text lines in reading order (panes one after another, rows inside)."""
    if result.boxes is None:
        return []
    cells = [(box[:, 0].min(), box[:, 1].min(), box[:, 0].max(), box[:, 1].max(), text.strip())
             for box, text in zip(result.boxes, result.txts) if len(text.strip()) > 1]
    if not cells:
        return []
    height = float(np.median([bottom - top for _, top, _, bottom, _ in cells]))
    return [line for block in blocks(cells, height) for line in rows(block, height)]


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


def rows(cells: list[tuple], height: float) -> list[str]:
    """Lines of one pane, top to bottom; boxes far apart on one row (table cells) get ' | '."""
    grouped = []  # [center y, [(left, right, text)]]
    for left, top, right, bottom, text in sorted(cells, key=lambda cell: cell[1] + cell[3]):
        center = (top + bottom) / 2
        if grouped and abs(center - grouped[-1][0]) < 0.5 * height:
            grouped[-1][1].append((left, right, text))
        else:
            grouped.append([center, [(left, right, text)]])
    lines = []
    for _, row in grouped:
        row.sort()
        line = row[0][2]
        for (_, right, _), (left, _, text) in zip(row, row[1:]):
            line += (" | " if left - right > 2 * height else " ") + text
        lines.append(line)
    return lines


def fresh(lines: list[str], seen: list[str]) -> list[str]:
    """Lines whose text was not on the previous screen; small OCR differences do not count."""
    known = set(seen)
    return [line for line in lines
            if len(key(line)) > 2 and key(line) not in known
            and not difflib.get_close_matches(key(line), seen, 1, 0.8)]


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
