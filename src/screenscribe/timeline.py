"""One timeline out of two sources.

Every screen state opens a chapter; a sentence goes to the chapter whose screen was
visible while it was said. The layout and its rationale: docs/research/merged-transcript-format.md
"""

import base64
import bisect
import html
import json
import os
from importlib import resources
from pathlib import Path
from string import Template
from urllib.parse import quote

from .screen import key

LEGEND = (
    "> How to read: this is one timeline. A `Screen` heading marks the moment the picture changed; "
    "the block under it is the text read from the screen (only what the previous screen did not show), "
    "and the lines after it are what was said while that screen was visible. "
    "Times are from the start of the recording. Screen text is OCR and may contain misread characters."
)


def build(segments: list[dict], screens: list[dict]) -> list[dict]:
    """Return chapters [{start, screen, title, update, back_to, turns}] in time order.

    `screen` indexes `screens`; it is None for speech before the first screen (or when
    there is no video). `update` marks a small change of the previous screen, `back_to`
    the index of an earlier screen with the same content. A turn is {start, speaker, text}.
    """
    chapters = [{"start": 0.0, "screen": None, "turns": []}]
    for index, screen in enumerate(screens):
        update = len(screen["new"]) * 2 <= len(screen["lines"])
        keys = {key(line) for line in screen["lines"]}
        back_to = None
        if not update:
            for earlier in range(index - 1):  # the previous screen is never a "return"
                other = {key(line) for line in screens[earlier]["lines"]}
                if len(keys & other) >= 0.7 * len(keys | other):
                    back_to = earlier
                    break
        chapters.append({"start": screen["start"], "screen": index, "title": screen["new"][0][:80],
                         "update": update, "back_to": back_to, "turns": []})
    starts = [screen["start"] for screen in screens]
    for segment in segments:
        # the screen shown at the middle of the sentence is the one shown for most of it
        middle = (segment["start"] + segment["end"]) / 2
        turns = chapters[bisect.bisect_right(starts, middle)]["turns"]
        if turns and turns[-1]["speaker"] == segment["speaker"] and len(turns[-1]["text"]) < 500:
            turns[-1]["text"] += " " + segment["text"]
        else:
            turns.append({"start": segment["start"], "speaker": segment["speaker"], "text": segment["text"]})
    return [chapter for chapter in chapters if chapter["screen"] is not None or chapter["turns"]]


def clock(seconds: float) -> str:
    seconds = int(seconds)
    short = f"{seconds % 3600 // 60:02}:{seconds % 60:02}"
    return f"{seconds // 3600}:{short}" if seconds >= 3600 else short


def heading(chapter: dict, screens: list[dict]) -> str:
    if chapter["back_to"] is not None:
        earlier = screens[chapter["back_to"]]
        return f'Screen: back to "{earlier["new"][0][:80]}" (first shown at {clock(earlier["start"])})'
    return ("Screen update: " if chapter["update"] else "Screen: ") + chapter["title"]


def summary(chapters: list[dict], screens: list[dict], duration: float) -> str:
    speakers = {turn["speaker"] for chapter in chapters for turn in chapter["turns"]}
    return f"Duration {clock(duration)}, speakers: {len(speakers)}, screens: {len(screens)}"


def markdown(name: str, chapters: list[dict], screens: list[dict], duration: float) -> str:
    out = [f"# {name}", "", summary(chapters, screens, duration), "", LEGEND, ""]
    for chapter in chapters:
        if chapter["screen"] is not None:
            # code span: OCR text must not be read as Markdown markup
            out += [f"## [{clock(chapter['start'])}] `{heading(chapter, screens).replace('`', chr(39))}`", ""]
            if chapter["back_to"] is None:
                lines = [line.replace("```", "'''") for line in screens[chapter["screen"]]["new"]]
                out += ["```text", *lines, "```", ""]
        for turn in chapter["turns"]:
            out += [f"**[{clock(turn['start'])}] Speaker {turn['speaker']}:** {turn['text']}", ""]
    return "\n".join(out)


def page(name: str, chapters: list[dict], screens: list[dict], duration: float, media: str) -> str:
    """The HTML viewer; `media` is the URL of the recording for the player."""
    escape = html.escape
    outline, body = [], []
    for number, chapter in enumerate(chapters):
        stamp = f'<button class="t" data-t="{chapter["start"]:.1f}">{clock(chapter["start"])}</button>'
        section = [f'<section class="chapter" id="c{number}">']
        if chapter["screen"] is not None:
            screen = screens[chapter["screen"]]
            title = escape(heading(chapter, screens))
            outline.append(f'<a href="#c{number}">{clock(chapter["start"])} {escape(chapter["title"])}</a>')
            picture = base64.b64encode(screen["image"]).decode()
            section.append(f'<aside class="screen"><h2>{stamp}{title}</h2>'
                           f'<img loading="lazy" alt="Screen at {clock(chapter["start"])}" '
                           f'src="data:image/jpeg;base64,{picture}">')
            if chapter["back_to"] is None:
                section.append(f'<pre>{escape(chr(10).join(screen["new"]))}</pre>')
            section.append("</aside>")
        section.append('<div class="speech">')
        for turn in chapter["turns"]:
            who = turn["speaker"]
            section.append(f'<p class="turn"><button class="t" data-t="{turn["start"]:.1f}">{clock(turn["start"])}</button>'
                           f'<button class="who s{(who - 1) % 8 + 1}" data-s="{who}">Speaker {who}</button>'
                           f'{escape(turn["text"])}</p>')
        section.append("</div></section>")
        body.append("".join(section))
    template = Template(resources.files(__package__).joinpath("viewer.html").read_text("utf-8"))
    return template.substitute(title=escape(name), meta=escape(summary(chapters, screens, duration)),
                               outline="".join(outline), chapters="\n".join(body), media=escape(media))


def write(stem: Path, source: Path, segments: list[dict], screens: list[dict], duration: float) -> dict[str, Path]:
    """Write <stem>.md, <stem>.html and <stem>.json; return their paths by extension."""
    chapters = build(segments, screens)
    raw = {"file": source.name, "duration": duration, "segments": segments,
           "screens": [{name: value for name, value in screen.items() if name != "image"} for screen in screens]}
    try:
        media = quote(Path(os.path.relpath(source, stem.parent)).as_posix())
    except ValueError:  # Windows: the output folder is on another drive
        media = source.resolve().as_uri()
    outputs = {
        "md": markdown(source.name, chapters, screens, duration),
        "html": page(source.name, chapters, screens, duration, media),
        "json": json.dumps(raw, ensure_ascii=False, indent=1),
    }
    paths = {}
    for extension, text in outputs.items():
        paths[extension] = stem.with_name(stem.name + "." + extension)
        paths[extension].write_text(text, "utf-8")
    return paths
