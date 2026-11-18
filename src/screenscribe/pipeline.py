"""The whole job for one recording: speech, speakers, screen text, merged outputs."""

import os
from pathlib import Path

from . import timeline
from .media import SAMPLE_RATE, load_audio


def default_threads() -> int:
    # measured: 3-4 threads are as fast as it gets for these models, 6 are slower than 2
    return min(4, max(1, (os.cpu_count() or 2) // 2))


def process(source, out_dir=None, threads: int = 0, screen: bool = True,
            progress=lambda message: None) -> dict[str, Path]:
    """Transcribe `source` and write <name>.md/.html/.json into `out_dir` (default: next to it)."""
    from .screen import read_screens  # heavy imports: keep `--help` and the web page fast
    from .speech import transcribe

    source = Path(source)
    out_dir = Path(out_dir) if out_dir else source.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    threads = threads or default_threads()
    progress("Loading audio")
    audio = load_audio(source)
    duration = len(audio) / SAMPLE_RATE
    segments = transcribe(audio, threads, progress)
    del audio  # hundreds of MB for a long call; OCR needs the memory next
    screens = read_screens(source, threads, progress) if screen else []
    progress("Writing the transcript")
    return timeline.write(out_dir / source.stem, source, segments, screens, duration)
