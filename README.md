# screenscribe

Local transcriber for calls and screen recordings. One recording goes in, one timeline comes
out: what was said, who said it, and what was on the screen at that moment.

It runs on an ordinary laptop CPU. No GPU, no account, no system FFmpeg, and nothing leaves
the machine after the models are downloaded once.

````markdown
## [00:19] `Screen: Архитектура`

```text
Архитектура
Frontend: React + TypeScript
Backend: FastAPl, Python 3.12
База данных: PostgreSQL 16
Очередь задач: RabbitMQ
Деплой: Docker, Kubernetes
```

**[00:19] Speaker 3:** Конечно, на этом слайде наш текст. Обратите внимание на последнюю строку, деплей будет кубернейтес.

**[00:26] Speaker 2:** А почему для очереди выбрали именно это решение?
````

Speech and screen text are kept together on purpose: "the last line" and "this solution" mean
nothing without the slide, and the slide carries the spelling ("Kubernetes") that the speech
model writes phonetically. Why this layout and not two files or a table:
[docs/research/merged-transcript-format.md](docs/research/merged-transcript-format.md).

## Install

Needs [uv](https://docs.astral.sh/uv/) and Python 3.10 or newer.

```bash
uv tool install git+https://github.com/Chillibumbik/screenscribe
```

The first run downloads about 280 MB of models into `~/.cache/screenscribe`.

## Use

### Web page

```bash
screenscribe serve
```

Opens `http://127.0.0.1:8765`. Drop a video or audio file on the page, or press
**Start recording** to record the screen with sound and transcribe it when you stop.
Recordings and transcripts are kept in `~/screenscribe`, one folder per recording.

The page records what the browser gives it. Your microphone is always included. The sound of
the other participants is captured only if the browser shares it: in Chrome and Edge, share a
browser tab with "Also share tab audio" (a call running in that tab), or the entire screen with
system audio on Windows. Other combinations usually give the picture and your microphone only.
For calls in a desktop app (Zoom, Telemost, Teams) use the app's own recording and drop the
file on the page.

### Command line

```bash
screenscribe call.mp4
```

Writes `call.md`, `call.html` and `call.json` next to the file.

| Option | Meaning |
|---|---|
| `-o DIR` | write the outputs to `DIR` |
| `--no-screen` | speech only, skip on-screen text |
| `--threads N` | CPU threads (default: half of the cores, at most 4; more does not help) |

## What you get

- `call.md`: the timeline as plain Markdown. Read it, or give it to an LLM as context.
- `call.html`: the same timeline as a page. Each screen is shown with its screenshot and stays
  pinned beside the speech said over it. Click a time to hear that moment, a speaker name to
  rename it (give two numbers the same name if one person was split in two), a picture to
  enlarge it. Keep it next to the recording: the player uses the original file.
- `call.json`: the raw sentences and screens with timings, for other tools.

## How it works

1. PyAV decodes the audio to 16 kHz mono and samples one video frame per second.
2. Speakers: pyannote segmentation 3.0 finds who speaks when, TitaNet-small voiceprints are
   clustered into speakers. The number of speakers is detected automatically.
3. Speech: every speaker segment is recognized by GigaAM v3 (Russian, with punctuation) in
   pieces of at most 20 seconds and split into sentences by token timestamps.
4. Screen: a frame is read only when the picture has changed and settled. PP-OCRv5 (Cyrillic
   and Latin) reads it, side-by-side panes are read one after another, and only the lines the
   previous screen did not have are kept.
5. Merge: each screen opens a chapter, and each sentence goes under the screen that was
   visible while it was said.

Steps 2 and 3 run on [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), step 4 on
[RapidOCR](https://github.com/RapidAI/RapidOCR). There is no PyTorch in the dependency tree.

## Speed and memory

Measured on a laptop with an Intel i5-12450H and 16 GB RAM, no GPU.

SPEED_TABLE

A screen that changed takes 1 to 4 seconds to read (720p slide to dense 1080p page). Reading
is capped at about two thirds of real time, so a busy screen on a slow machine is sampled
less often instead of taking hours.

## Limits

- The speech model knows Russian only. English terms are written in Cyrillic ("кубернейтес");
  the screen text next to them usually has the right spelling.
- Speaker detection makes mistakes, mostly with similar voices, short remarks and people
  talking over each other. It was tuned on five short recordings; accuracy on long real
  calls has not been measured.
- OCR misreads look-alike characters now and then ("FastAPl"), and text with confidence
  below 50% is dropped.
- Transcription starts after the recording ends. There are no live captions.
- Developed and tested on Linux. PLATFORM_NOTE

## Development

```bash
uv sync
uv run pytest
```

The end-to-end test needs a synthetic call (three synthetic voices over four slides):

```bash
uv run --script tests/make_sample.py sample/sample.webm
```

```bash
SCREENSCRIBE_SAMPLE=sample/sample.webm uv run pytest tests/test_end_to_end.py
```

## Models

| Purpose | Model | Source |
|---|---|---|
| Speech | GigaAM v3 e2e RNN-T (MIT) | [salute-developers/GigaAM](https://github.com/salute-developers/GigaAM), sherpa-onnx export |
| Who speaks when | pyannote segmentation 3.0 | [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0), sherpa-onnx export |
| Voiceprints | NVIDIA NeMo TitaNet-small | sherpa-onnx speaker models |
| Screen text | PP-OCRv6 tiny detector, PP-OCRv5 Cyrillic recognizer | [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) via RapidOCR |

The code is MIT. The models have their own licenses: check them before commercial use.
