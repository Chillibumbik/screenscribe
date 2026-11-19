# screenscribe

[![ci](https://github.com/Chillibumbik/screenscribe/actions/workflows/ci.yml/badge.svg)](https://github.com/Chillibumbik/screenscribe/actions/workflows/ci.yml)

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

**[00:19] Speaker 3:** Конечно, на этом слайде наш текст. Обратите внимание на последнюю строку, где плый будет кубернетис.

**[00:26] Speaker 2:** А почему для очереди выбрали именно это решение?
````

Speech and screen text are kept together on purpose: "the last line" and "this solution" mean
nothing without the slide, and the slide carries the spelling ("Kubernetes") that the speech
model writes phonetically. The whole transcript of that test call:
[docs/example/sample.md](docs/example/sample.md). Why this layout and not two files or a table:
[docs/research/merged-transcript-format.md](docs/research/merged-transcript-format.md).

## Install

Needs [uv](https://docs.astral.sh/uv/). It uses Python 3.11 or newer and fetches one if the system has none.

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
Untick **also read the text on the screen** to transcribe the speech only, which is faster.
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

- `call.md`: the timeline as plain Markdown. Read it, or give it to an LLM as context. A screen
  with new content is a heading with its text; a small change of that screen (a chat message,
  one more line) is a one-line `Screen update` note between the sentences.
- `call.html`: the same timeline as a page. Each screen is shown with its screenshot and stays
  pinned beside the speech said over it. Click a time to hear that moment, a speaker name to
  rename it (give two numbers the same name if one person was split in two), a picture to
  enlarge it. Keep it next to the recording: the player uses the original file.
- `call.json`: the raw sentences and screens with timings, for other tools.

`Speaker ?` marks words from a voice that makes up less than 1% of the speech (or under five
seconds): too little to tell who it was. Usually it is the tail of someone's phrase.

## How it works

1. PyAV decodes the audio to 16 kHz mono and samples one video frame per second.
2. Speakers: pyannote segmentation 3.0 finds who speaks when, TitaNet-small voiceprints are
   clustered into speakers. The number of speakers is detected automatically, erring towards
   splitting one person in two rather than merging two people; a voice that makes up less
   than 1% of the speech is not counted as a participant.
3. Speech: every speaker segment is recognized by GigaAM v3 (Russian, with punctuation) in
   pieces of at most 20 seconds and split into sentences by token timestamps.
4. Screen: a frame is read only when the picture has changed and settled. PP-OCRv5 (Cyrillic
   and Latin) reads it, side-by-side panes are read one after another, and only the text the
   previous screen did not have is kept. The largest new text names the screen.
5. Merge: a screen with mostly new content opens a chapter, a small change becomes a note
   inside it, and each sentence goes under the screen that was visible while it was said.

Steps 2 and 3 run on [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), step 4 on
[RapidOCR](https://github.com/RapidAI/RapidOCR). There is no PyTorch in the dependency tree.

## Speed and memory

Measured on a laptop with an Intel i5-12450H and 16 GB RAM, no GPU, 4 threads.

| Recording | Total | Speakers | Speech | Screen | Peak memory |
|---|---|---|---|---|---|
| 41 min webinar, 720p, slides and chat | 8.0 min | 4.0 min | 2.1 min | 1.8 min | 0.9 GB |
| 48 min webinar, 720p, slides and chat | 8.4 min | 4.2 min | 2.5 min | 1.7 min | 1.2 GB |
| 42 min interview, audio only | 6.4 min | 3.9 min | 2.3 min | none | 0.9 GB |
| 7 min screencast of dense web pages, 720p | 4.9 min | 0.6 min | 0.4 min | 3.9 min | 0.7 GB |

A call takes about a fifth of its length. A recording where dense text keeps changing takes
much longer, 0.7 of its length in the worst file tried. A screen that keeps moving (scrolling, a video) is read at most often enough to
stay under two thirds of real time, so a slow machine samples it less often instead of
taking hours; a screen that has settled, such as a new slide, is always read.

Threads: the speech part took 0.31 of the recording's length on 1 thread, 0.21 on 2 and 0.19
on 4. More than 4 made it slower, so 4 is the cap.

## Limits

- The speech model knows Russian only. English terms are written in Cyrillic ("кубернетис");
  the screen text next to them usually has the right spelling.
- Speaker detection makes mistakes. A two-person interview came out as 2 speakers and three
  one-voice narrations as 1 each. Two webinars came out as 4 and 7; the 4 fits the people who
  present, the 7 was not checked by ear and may hold one person twice. What goes wrong is at
  the edges: a short remark right after a speaker change can go to the previous speaker or
  to `Speaker ?`, and when two people talk at once the same words can appear under both.
  Nobody has scored a long call against a hand-made reference.
- Music or noise is sometimes "recognized" as a few nonsense words.
- OCR misreads look-alike characters now and then ("FastAPl"), drops text with confidence
  below 50%, and garbles small text in a compressed recording of a whole desktop.
- The first time a window is shown, its menus and toolbars are printed with the content.
- A screen is named by its largest new text, which is not always the heading.
- Transcription starts after the recording ends. There are no live captions.
- Developed and tried by hand on Linux only. On Windows and macOS just the automated tests
  have run (unit tests and the end-to-end test pass on all three in CI).
- The recording button was exercised in a Chromium browser with a synthetic picture; the
  real screen picker and tab audio were not.

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
