"""Model files: downloaded once into the user cache, then everything runs offline."""

import http.client
import os
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

CACHE = Path(os.environ.get("SCREENSCRIBE_CACHE") or Path.home() / ".cache" / "screenscribe")

_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
# GigaAM v3 end-to-end RNN-T: Russian, outputs punctuation and capitalization.
ASR = _RELEASES + "asr-models/sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16.tar.bz2"
SEGMENTATION = _RELEASES + "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMBEDDING = _RELEASES + "speaker-recongition-models/nemo_en_titanet_small.onnx"


def fetch(url: str) -> Path:
    """Return the local path of a model file (or of the directory a .tar.bz2 unpacks to)."""
    name = url.rsplit("/", 1)[1]
    target = CACHE / name.removesuffix(".tar.bz2")
    if target.exists():
        return target
    CACHE.mkdir(parents=True, exist_ok=True)
    part = CACHE / (name + ".part")
    print(f"Downloading {name} (first run only) ...", file=sys.stderr)
    _download(url, part)
    if name.endswith(".tar.bz2"):
        unpacked = CACHE / (name + ".unpack")  # unpack aside, so a killed run never leaves a half model
        with tarfile.open(part) as tar:
            tar.extractall(unpacked, filter="data")
        (unpacked / target.name).rename(target)
        shutil.rmtree(unpacked)
        part.unlink()
    else:
        part.rename(target)
    return target


def _download(url: str, part: Path, attempts: int = 6) -> None:
    """Download with retries, resuming from the bytes already on disk (flaky networks)."""
    for attempt in range(attempts):
        done = part.stat().st_size if part.exists() else 0
        request = urllib.request.Request(url, headers={"Range": f"bytes={done}-"} if done else {})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                with open(part, "ab" if response.status == 206 else "wb") as file:
                    shutil.copyfileobj(response, file, 1 << 20)
            return
        except urllib.error.HTTPError as error:
            if error.code == 416:  # nothing left to fetch: the file was already complete
                return
            if attempt == attempts - 1:
                raise
        except (OSError, http.client.HTTPException):
            if attempt == attempts - 1:
                raise
        time.sleep(2)
