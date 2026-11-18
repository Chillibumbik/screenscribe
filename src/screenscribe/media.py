"""Decoding with PyAV (bundles FFmpeg, so no system install is needed)."""

import av
import numpy as np

SAMPLE_RATE = 16000


def load_audio(path) -> np.ndarray:
    """First audio track as 16 kHz mono float32; empty array if the file has no audio."""
    chunks = []
    with av.open(str(path)) as container:
        if not container.streams.audio:
            return np.zeros(0, np.float32)
        resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(audio=0):
            chunks += [out.to_ndarray()[0] for out in resampler.resample(frame)]
        chunks += [out.to_ndarray()[0] for out in resampler.resample(None)]
    return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)


def frames(path, every: float = 1.0):
    """Yield (seconds, BGR image) roughly every `every` seconds of the first video track."""
    with av.open(str(path)) as container:
        if not container.streams.video:
            return
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        next_time = 0.0
        # shortcut: decodes every frame and keeps one per interval; switch to keyframe
        # seeking if long 60 fps recordings turn out to be the bottleneck.
        for frame in container.decode(stream):
            if frame.time is None or frame.time < next_time:
                continue
            next_time = frame.time + every
            yield frame.time, frame.to_ndarray(format="bgr24")
