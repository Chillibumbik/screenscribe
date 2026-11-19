"""One timeline out of two sources.

A screen with mostly new content opens a chapter; what was said while it was visible
goes under it, and small changes of that screen (a chat message, a new line) are short
notes between the sentences. The layout and its rationale:
docs/research/merged-transcript-format.md
"""

import base64
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
    "A `Screen update` line is a small addition to the screen above, such as a chat message. "
    "Times are from the start of the recording. Screen text is OCR and may contain misread characters."
)


def build(segments: list[dict], screens: list[dict]) -> list[dict]:
    """Return chapters [{start, screen, title, back_to, items}] in time order.

    `screen` indexes `screens`; it is None for speech before the first screen (or when
    there is no video). `back_to` is the index of an earlier chapter's screen with the
    same content. Items are in time order: a turn {start, speaker, text} or a small
    change of the chapter's screen {start, screen}.
    """
    # a sentence is placed by its middle: the screen shown then is the one shown for most of it
    events = [(screen["start"], 0, index) for index, screen in enumerate(screens)]
    events += [((segment["start"] + segment["end"]) / 2, 1, index) for index, segment in enumerate(segments)]
    chapters = [{"start": 0.0, "screen": None, "items": []}]
    opened = []  # screens that opened a chapter
    for _, is_speech, index in sorted(events):
        items = chapters[-1]["items"]
        if is_speech:
            segment = segments[index]
            last = items[-1] if items else {}
            if last.get("speaker") == segment["speaker"] and len(last["text"]) < 500:
                last["text"] += " " + segment["text"]
            else:
                items.append({"start": segment["start"], "speaker": segment["speaker"], "text": segment["text"]})
            continue
        screen = screens[index]
        if opened and not screen["major"]:
            items.append({"start": screen["start"], "screen": index})
            continue
        keys = {key(line) for line in screen["lines"]}
        back_to = None
        for earlier in opened[:-1]:  # the screen just before is never a "return"
            other = {key(line) for line in screens[earlier]["lines"]}
            if len(keys & other) >= 0.7 * len(keys | other):
                back_to = earlier
                break
        opened.append(index)
        chapters.append({"start": screen["start"], "screen": index, "title": screen["title"],
                         "back_to": back_to, "items": []})
    return [chapter for chapter in chapters if chapter["screen"] is not None or chapter["items"]]


def clock(seconds: float) -> str:
    seconds = int(seconds)
    short = f"{seconds % 3600 // 60:02}:{seconds % 60:02}"
    return f"{seconds // 3600}:{short}" if seconds >= 3600 else short


def heading(chapter: dict, screens: list[dict]) -> str:
    if chapter["back_to"] is not None:
        earlier = screens[chapter["back_to"]]
        return f'Screen: back to "{earlier["title"]}" (first shown at {clock(earlier["start"])})'
    return "Screen: " + chapter["title"]


def summary(chapters: list[dict], duration: float) -> str:
    speakers = {item["speaker"] for chapter in chapters for item in chapter["items"] if item.get("speaker")}
    shown = sum(chapter["screen"] is not None for chapter in chapters)
    return f"Duration {clock(duration)}, speakers: {len(speakers)}, screens: {shown}"


def speaker_name(number: int) -> str:
    return f"Speaker {number}" if number else "Speaker ?"  # 0: too little speech to tell who it was


def code(text: str) -> str:
    """Markdown code span: OCR text must not be read as markup."""
    return "`" + text.replace("`", "'") + "`"


def markdown(name: str, chapters: list[dict], screens: list[dict], duration: float) -> str:
    out = [f"# {name}", "", summary(chapters, duration), "", LEGEND, ""]
    for chapter in chapters:
        if chapter["screen"] is not None:
            out += [f"## [{clock(chapter['start'])}] {code(heading(chapter, screens))}", ""]
            if chapter["back_to"] is None:
                lines = [line.replace("```", "'''") for line in screens[chapter["screen"]]["new"]]
                out += ["```text", *lines, "```", ""]
        for item in chapter["items"]:
            if "speaker" in item:
                out += [f"**[{clock(item['start'])}] {speaker_name(item['speaker'])}:** {item['text']}", ""]
            else:
                added = screens[item["screen"]]["new"]
                if len(added) <= 3:
                    out += [f"> [{clock(item['start'])}] Screen update: {' / '.join(map(code, added))}", ""]
                else:  # too much for one line
                    lines = [line.replace("```", "'''") for line in added]
                    out += [f"> [{clock(item['start'])}] Screen update:", "", "```text", *lines, "```", ""]
    return "\n".join(out)


def page(name: str, chapters: list[dict], screens: list[dict], duration: float, media: str) -> str:
    """The HTML viewer; `media` is the URL of the recording for the player."""
    escape = html.escape

    def stamp(seconds: float) -> str:
        return f'<button class="t" data-t="{seconds:.1f}">{clock(seconds)}</button>'

    def picture(screen: dict) -> str:
        return (f'<img loading="lazy" alt="Screen at {clock(screen["start"])}" '
                f'src="data:image/jpeg;base64,{base64.b64encode(screen["image"]).decode()}">')

    outline, body = [], []
    for number, chapter in enumerate(chapters):
        section = [f'<section class="chapter" id="c{number}">']
        if chapter["screen"] is not None:
            screen = screens[chapter["screen"]]
            outline.append(f'<a href="#c{number}">{clock(chapter["start"])} {escape(chapter["title"])}</a>')
            section.append(f'<aside class="screen"><h2>{stamp(chapter["start"])}{escape(heading(chapter, screens))}</h2>'
                           + picture(screen))
            if chapter["back_to"] is None:
                section.append(f'<pre>{escape(chr(10).join(screen["new"]))}</pre>')
            section.append("</aside>")
        section.append('<div class="speech">')
        for item in chapter["items"]:
            if "speaker" in item:
                who = item["speaker"]
                section.append(f'<p class="turn">{stamp(item["start"])}'
                               f'<button class="who s{(who - 1) % 8 + 1 if who else 0}" data-s="{who}">'
                               f'{speaker_name(who)}</button>'
                               f'{escape(item["text"])}</p>')
            else:
                screen = screens[item["screen"]]
                section.append(f'<div class="update">{stamp(item["start"])}'
                               f'<pre>{escape(chr(10).join(screen["new"]))}</pre>{picture(screen)}</div>')
        section.append("</div></section>")
        body.append("".join(section))
    template = Template(resources.files(__package__).joinpath("viewer.html").read_text("utf-8"))
    return template.substitute(title=escape(name), meta=escape(summary(chapters, duration)),
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
