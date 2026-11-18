"""Who spoke when (diarization) and what was said (ASR). Both run on CPU via sherpa-onnx."""

import numpy as np
import sherpa_onnx

from . import models
from .media import SAMPLE_RATE

MAX_CHUNK = 20.0  # seconds; GigaAM is trained on utterances up to ~25-30 s and degrades beyond


def transcribe(audio: np.ndarray, threads: int = 4, progress=lambda message: None) -> list[dict]:
    """Return sentences [{start, end, speaker, text}]; speakers are numbered from 1 by first appearance.

    Diarization runs first and each speaker segment is recognized on its own, so no
    word-level alignment between the two models is needed.
    """
    if not len(audio):
        return []
    progress("Finding who speaks when")
    diarizer = sherpa_onnx.OfflineSpeakerDiarization(sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(models.fetch(models.SEGMENTATION) / "model.onnx")),
            num_threads=threads),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(models.fetch(models.EMBEDDING)), num_threads=threads),
        # The number of speakers is found by threshold. TitaNet-small with 0.8 was the only
        # pair that counted the speakers right on all five check recordings (the library
        # default of 0.5 splits one voice into several). A fixed num_clusters is not offered:
        # asking for 3 returned 2 on the sample, as stray segments take a cluster of their own.
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.8),
        min_duration_on=0.3,
        min_duration_off=0.5,
    ))

    def on_chunk(done: int, total: int) -> int:
        if done * 10 // total != (done - 1) * 10 // total:  # every 10%, not every chunk
            progress(f"Finding who speaks when: {100 * done // total}%")
        return 0

    turns = diarizer.process(audio, callback=on_chunk).sort_by_start_time()

    folder = models.fetch(models.ASR)
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(folder / "encoder.int8.onnx"),
        decoder=str(folder / "decoder.onnx"),
        joiner=str(folder / "joiner.onnx"),
        tokens=str(folder / "tokens.txt"),
        num_threads=threads,
        model_type="nemo_transducer",
    )
    segments, numbers = [], {}
    for index, turn in enumerate(turns):
        if index * 10 // len(turns) != (index - 1) * 10 // len(turns):
            progress(f"Recognizing speech: {100 * index // len(turns)}%")
        for start, end in split(audio, turn.start, turn.end):
            stream = recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, audio[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)])
            recognizer.decode_stream(stream)
            for begin, finish, text in sentences(stream.result.tokens, stream.result.timestamps, start, end):
                speaker = numbers.setdefault(turn.speaker, len(numbers) + 1)
                segments.append({"start": begin, "end": finish, "speaker": speaker, "text": text})
    return segments


def sentences(tokens: list[str], stamps: list[float], start: float, end: float) -> list[tuple]:
    """Split one recognized chunk into (start, end, text) sentences using token timestamps.

    Sentence-level timing lets a screen change land between two sentences instead of
    in the middle of a long turn.
    """
    found, text, begin = [], "", start
    for index, (token, stamp) in enumerate(zip(tokens, stamps)):
        if not text.strip():
            begin = start + stamp
        text += token
        last = index == len(tokens) - 1
        # a new word after the punctuation mark: "3.18" must stay in one piece
        if token.strip()[-1:] in tuple(".?!…") and (last or tokens[index + 1].startswith(" ")):
            found.append((begin, text.strip()))
            text = ""
    if text.strip():
        found.append((begin, text.strip()))
    ends = [begin for begin, _ in found[1:]] + [end]
    return [(begin, finish, text) for (begin, text), finish in zip(found, ends)]


def split(audio: np.ndarray, start: float, end: float):
    """Cut [start, end) into pieces of at most MAX_CHUNK seconds, at the quietest moment available."""
    window = SAMPLE_RATE // 5
    while end - start > MAX_CHUNK:
        low, high = int((start + MAX_CHUNK / 2) * SAMPLE_RATE), int((start + MAX_CHUNK) * SAMPLE_RATE)
        energy = np.cumsum(audio[low:high].astype(np.float64) ** 2)
        quietest = int((energy[window:] - energy[:-window]).argmin())
        cut = (low + quietest + window // 2) / SAMPLE_RATE
        yield start, cut
        start = cut
    yield start, end
