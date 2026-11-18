"""Command line: `screenscribe FILE...` transcribes, `screenscribe serve` opens the local web page."""

import argparse
import sys
from pathlib import Path


def main() -> None:
    if sys.argv[1:2] == ["serve"]:
        parser = argparse.ArgumentParser(prog="screenscribe serve", description="Local web page: drop a file or record the screen.")
        parser.add_argument("--port", type=int, default=8765)
        parser.add_argument("--dir", type=Path, default=Path.home() / "screenscribe", help="where recordings and transcripts are kept")
        parser.add_argument("--no-browser", action="store_true", help="do not open the page automatically")
        args = parser.parse_args(sys.argv[2:])
        from .server import serve

        serve(args.dir, args.port, not args.no_browser)
        return

    parser = argparse.ArgumentParser(
        prog="screenscribe",
        description="Local transcriber: speech, speakers and on-screen text in one timeline.",
        epilog="Run `screenscribe serve` for the local web page (drop a file or record the screen).")
    parser.add_argument("files", nargs="+", type=Path, help="video or audio recordings")
    parser.add_argument("-o", "--out", type=Path, help="output directory (default: next to each file)")
    parser.add_argument("--threads", type=int, default=0, help="CPU threads (default: half of the cores, at most 4)")
    parser.add_argument("--no-screen", action="store_true", help="skip on-screen text (speech only, faster)")
    args = parser.parse_args()
    from .pipeline import process

    for file in args.files:
        if not file.is_file():
            sys.exit(f"screenscribe: no such file: {file}")
        print(f"== {file}", file=sys.stderr)
        paths = process(file, args.out, args.threads, not args.no_screen,
                        lambda message: print(f"   {message}", file=sys.stderr))
        for path in paths.values():
            print(path)
