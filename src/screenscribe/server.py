"""Local web page: drop a recording or record the screen, get the transcript.

Standard library only. Listens on 127.0.0.1 and refuses requests that did not come
from its own page, because recordings and transcripts are private.

Each job is a folder in the data directory: the recording plus its .md/.html/.json.
"""

import json
import mimetypes
import queue
import re
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

OUTPUTS = (".md", ".html", ".json")
SAFE = re.compile(r"[\w][\w.\- ]*")  # one path segment: no slashes, no leading dot


def serve(root: Path, port: int, open_browser: bool) -> None:
    root.mkdir(parents=True, exist_ok=True)
    pending: queue.Queue = queue.Queue()
    status: dict[str, str] = {}  # job id -> "queued" | progress message | "error: ..."

    def source_of(folder: Path) -> Path | None:
        return next((p for p in sorted(folder.iterdir()) if p.is_file() and p.suffix not in OUTPUTS), None)

    def work() -> None:
        from .pipeline import process

        while True:
            job = pending.get()
            try:
                process(source_of(root / job), progress=lambda message: status.__setitem__(job, message))
                del status[job]
            except Exception as error:  # keep serving; show the reason on the page
                traceback.print_exc()
                status[job] = f"error: {error}"

    def jobs() -> list[dict]:
        found = []
        for folder in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
            source = source_of(folder)
            if not source:
                continue
            done = folder / (source.stem + ".html")
            message = status.get(folder.name, "")
            state = ("error" if message.startswith("error") else "working" if message
                     else "done" if done.exists() else "idle")
            found.append({"id": folder.name, "name": source.name, "state": state, "message": message})
        return found

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # quiet console
            pass

        def reply(self, code: int, body: bytes = b"", kind: str = "application/json", extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def allowed(self) -> bool:
            # The Host check stops DNS rebinding; the custom header on writes stops other
            # sites from posting here (a cross-site request cannot set it without CORS).
            host_ok = self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")
            write_ok = self.command == "GET" or self.headers.get("X-Screenscribe") == "1"
            if not (host_ok and write_ok):
                self.close_connection = True  # the request body was not read
                self.reply(403, b'{"error": "forbidden"}')
            return host_ok and write_ok

        def folder(self, job: str) -> Path | None:
            return root / job if SAFE.fullmatch(job) and (root / job).is_dir() else None

        def do_GET(self) -> None:
            if not self.allowed():
                return
            parts = [unquote(part) for part in urlsplit(self.path).path.split("/") if part]
            if not parts:
                page = resources.files(__package__).joinpath("index.html").read_bytes()
                self.reply(200, page, "text/html; charset=utf-8")
            elif parts == ["jobs"]:
                self.reply(200, json.dumps({"dir": str(root), "jobs": jobs()}).encode())
            elif len(parts) == 3 and parts[0] == "files" and self.folder(parts[1]) and SAFE.fullmatch(parts[2]):
                self.send_file(self.folder(parts[1]) / parts[2])
            else:
                self.reply(404, b'{"error": "not found"}')

        def send_file(self, path: Path) -> None:
            if not path.is_file():
                return self.reply(404, b'{"error": "not found"}')
            size = path.stat().st_size
            start, end = 0, size - 1
            ranged = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if ranged and (ranged[1] or ranged[2]):  # the video player seeks with Range requests
                if ranged[1]:
                    start, end = int(ranged[1]), min(int(ranged[2] or end), end)
                else:
                    start = max(0, size - int(ranged[2]))
                if start > end:
                    return self.reply(416, extra={"Content-Range": f"bytes */{size}"})
            self.send_response(206 if ranged else 200)
            kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_header("Content-Type", kind + ("; charset=utf-8" if kind.startswith("text/") else ""))
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if ranged:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with open(path, "rb") as file:
                file.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = file.read(min(1 << 20, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                    try:
                        self.wfile.write(chunk)
                    except OSError:  # the player dropped the connection after a seek
                        return

        def do_POST(self) -> None:
            if not self.allowed():
                return
            url = urlsplit(self.path)
            parts = [unquote(part) for part in url.path.split("/") if part]
            query = parse_qs(url.query)
            length = int(self.headers.get("Content-Length") or 0)
            if parts == ["jobs"]:  # new job: make its folder and an empty recording file
                name = Path(query.get("name", [""])[0]).name
                name = re.sub(r"[^\w.\- ]", "_", name).lstrip(". ") or "recording.webm"
                if Path(name).suffix.lower() in OUTPUTS:  # would be mistaken for a transcript
                    return self.reply(400, b'{"error": "not a recording"}')
                job = time.strftime("%Y%m%d-%H%M%S-") + Path(name).stem[:60]
                while (root / job).exists():
                    job += "_"
                (root / job).mkdir()
                (root / job / name).touch()
                self.reply(200, json.dumps({"id": job}).encode())
            elif len(parts) == 3 and parts[0] == "jobs" and self.folder(parts[1]) and parts[2] == "data":
                with open(source_of(self.folder(parts[1])), "ab") as file:  # append: recordings arrive in pieces
                    while length > 0:
                        chunk = self.rfile.read(min(1 << 20, length))
                        if not chunk:
                            break
                        file.write(chunk)
                        length -= len(chunk)
                self.reply(200, b"{}")
            elif len(parts) == 3 and parts[0] == "jobs" and self.folder(parts[1]) and parts[2] == "start":
                if parts[1] not in status or status[parts[1]].startswith("error"):
                    status[parts[1]] = "queued"
                    pending.put(parts[1])
                self.reply(200, b"{}")
            else:
                self.rfile.read(length)
                self.reply(404, b'{"error": "not found"}')

    threading.Thread(target=work, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"screenscribe is running at {url}  (recordings and transcripts: {root})\nPress Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
