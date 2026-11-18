# How to present speech and on-screen text in one transcript

Status: decided for v0.1, November 2026. This document records the question, the options
that exist in the wild, the evidence for each, and the rules screenscribe implements.

## The question

A recording gives two time-aligned text sources:

1. speech, split by speaker (who said what, when);
2. text read from the screen (slides, documents, code), captured when the picture changes.

They are linked: people say "this number here" or "the last line on this slide" and never
read the number aloud. Two separate documents force the reader to join them by timestamp,
so the output has to be one document. It has two readers with different needs:

- a person who skims the call afterwards;
- an LLM that gets the transcript as context (summary, requirements, Q&A).

## Layouts that exist

| | Layout | Where it is used | For a person | For an LLM |
|---|---|---|---|---|
| A | Parallel tracks: two streams joined only by timestamps | WebVTT (one kind of data per file), lecture-capture players, screen-memory tools that store OCR and audio as separate items | each stream is clean, the reader does the join | trivial to produce, but the referent is far from "this number" |
| B | Inline interleave: one time-ordered stream, screen events dropped between utterances | Otter slide capture, several video-QA pipelines | referent sits next to the reference; big OCR blocks interrupt the dialogue | local context, at the cost of repeated OCR |
| C | Screen-segmented chapters: B plus structure, every screen state opens a section followed by the speech said over it | structured input in Gigant et al., Visual Transcripts, scene headings in AVscript, slide-based chapters in meeting recaps | skimmable, navigable | explicit structure; boundaries rarely fall on sentence ends |
| D | Two-column table, one row per time span: Audio / Visual | the W3C descriptive-transcript example, production AV scripts | read down one column or across a row | no evidence found; awkward in Markdown (multi-line code in cells) and on narrow screens |
| E | Synchronized dual pane (viewer only) | lecture-capture viewers | transcript and screen follow each other, one search over both | not applicable |
| F | Fused transcript: a model resolves the references and rewrites | Kirstein et al., MM-VID | shortest | a derivative, not a record: lossy and can invent details |

## Evidence

Verification status is given in the source list. Numbers quoted from papers come from the
literature survey and were not re-derived here; check the paper before quoting them further.

**For the LLM reader**

- Order matters. Gigant et al. (2025) summarize 822 talks with a vision-language model and
  find that a structured input, each slide followed by the speech said over it, performs
  best, better than all slides followed by the whole transcript. Even slide boundaries
  alone help over the bare transcript.
- Placing the detail where it is referred to beats appending it. Kirstein et al. (2024)
  report higher scores, most visibly on factuality, when material from slides is inserted
  at the relevant place than when all sources are appended after the transcript. Caveat:
  their inserted text was written by an LLM, not raw OCR.
- OCR text is worth including. Video-RAG reports gains on Video-MME from adding OCR and
  more from adding ASR; the Multimodal Textbook work loses accuracy without OCR and warns
  that low-quality OCR can hurt.
- Repetition hurts. Video-RAG halves its auxiliary text with no loss in accuracy. A
  screenpipe issue describes 81 near-identical OCR results for 15 minutes of screen time
  and worse agent answers because of them. Longer inputs with distractors degrade current
  models in general (Chroma, "context rot").
- Format is secondary. Prompt-format studies find that plain text, Markdown, JSON and YAML
  shift results for weaker models and much less for stronger ones, with no universal winner.
- Not found: a text-only comparison of interleaved against separate blocks on current
  frontier models; any test of timestamp or speaker-label formats; anything specific to Russian.

**For the human reader**

- Visual Transcripts (text interleaved with the visuals it refers to) made search faster
  than a video player with a transcript, and most participants preferred it.
- Video Digests: a chapter-and-section format improved recall of key topics after a few
  minutes of browsing compared to a plain transcript or the video player.
- Slidecho: presenters never mention about a fifth of slide text, so dropping "redundant"
  screen text loses information.
- W3C WAI on descriptive transcripts: one document carrying both the speech and the visual
  information, speaker names set apart, timestamps only where they help.
- Not found: a controlled comparison of two-column against inline layouts for sighted readers.

**Failure modes named in the sources**

- near-duplicate OCR (cursor, anti-aliasing, a few pixels of scroll);
- a speaker turn that spans a screen change (prior work moves the boundary to a sentence
  or phrase start, or assigns by time overlap);
- deixis ("this chart"), the reason meeting tools started attaching screenshots to notes;
- OCR noise.

## Decision

| Output | Layout | Why |
|---|---|---|
| `.md` | C | one portable file that reads top to bottom, works as LLM input, keeps the referent directly above the speech that points at it |
| `.html` | C with a pinned screen pane (a light version of E) | on a wide window the screenshot and its text stay beside the speech of that chapter; on a narrow one it collapses to C |
| `.json` | A | the raw streams, kept as the lossless record for other tools |

D is rejected because code and multi-line OCR do not fit table cells. F is not produced: it
needs an LLM, and a rewritten transcript is not evidence of what was said. Anyone who wants
it can feed the `.md` to a model.

## Rules implemented

| Rule | Reason | Code |
|---|---|---|
| A new screen state opens a chapter; speech is listed under the screen visible while it was said | order and locality findings above | `timeline.build` |
| Speech is split into sentences with their own times; a sentence goes to the screen shown at its midpoint (the screen shown for most of it) and is never cut | boundaries rarely fall on sentence ends | `speech.sentences`, `timeline.build` |
| Only text that the previous kept screen did not show is printed | dedup findings; also drops window chrome | `screen.fresh` |
| Fewer than 12 new characters is not a new screen | clocks, counters, cursor | `screen.read_screens` |
| A screen that returns to an earlier one is a one-line reference, not a reprint | token cost, readability | `timeline.build` (`back_to`) |
| A change of less than half of the lines is labelled `Screen update` | tells the reader the rest is unchanged | `timeline.build` (`update`) |
| Side-by-side panes are read one after another, not row by row | interleaved panes are unreadable and break dedup | `screen.blocks` |
| A legend at the top explains that screen blocks are deltas and OCR may misread | delta-only text is untested on LLMs; the legend is the mitigation | `timeline.LEGEND` |
| `[MM:SS]` (`H:MM:SS` past an hour), bold `Speaker N:` | W3C guidance; the format video models are documented with | `timeline.clock`, `timeline.markdown` |
| Screen text sits in a fenced block, titles in code spans | OCR text must not be parsed as Markdown | `timeline.markdown` |

## Example

Output for the synthetic test call (`tests/make_sample.py`), unedited:

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

The example shows why the merge matters. "Последнюю строку" and "это решение" only make
sense next to the slide. The speech model writes English terms phonetically ("кубернейтес")
and misheard "стек" as "текст"; the screen block carries the correct "Kubernetes". The OCR
has its own error ("FastAPl"). Each source covers for the other.

## Open questions

- The evidence comes from slide talks and vision-language models. Nobody has measured live
  screen sharing (scrolling, typing, switching windows) or text-only input to frontier models.
- Delta-only screen text might confuse a model when an earlier block has scrolled far out of
  its attention. Untested.
- Headings against XML-style tags for chapter boundaries: no comparison found.

The real test is an A/B on your own recordings: give a model the `.md` and, separately, the
two streams from the `.json` one after another, ask questions whose answers need both ("which
deadline did they agree on for the item on the second slide?"), and compare.

## Sources

Opened and read during this research:

- W3C WAI, Transcripts: https://www.w3.org/WAI/media/av/transcripts/
- Gigant, Guinaudeau, Dufaux (2025). Summarization of Multimodal Presentations with Vision-Language Models: https://arxiv.org/abs/2504.10049
- Kirstein, Ruas, Kratel, Gipp (2024). Tell me what I need to know: https://aclanthology.org/2024.emnlp-industry.69/
- Luo et al. (2024). Video-RAG: https://arxiv.org/abs/2411.13093
- Multimodal Textbook (2025): https://arxiv.org/abs/2501.00958
- screenpipe issue 2285, near-duplicate OCR results: https://github.com/screenpipe/screenpipe/issues/2285
- Otter, Automated Slide Capture: https://help.otter.ai/hc/en-us/articles/5093321813911-Automated-Slide-Capture-Overview
- Anthropic, prompting best practices (long documents): https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices

Abstract read, study figures taken from excerpts:

- Visual Transcripts (Shin et al., 2015): https://people.csail.mit.edu/hishin/projects/visual_transcripts/abstract.html
- Video Digests (Pavel et al., 2014): https://vis.berkeley.edu/papers/videodigests/
- Slidecho (Peng et al., 2021): https://dl.acm.org/doi/fullHtml/10.1145/3441852.3471234

Seen in search results only, not opened:

- AVscript (2023): https://dl.acm.org/doi/fullHtml/10.1145/3544548.3581494
- He et al. (2024), prompt format sensitivity: https://arxiv.org/abs/2411.10541
- LongVideoBench: https://arxiv.org/abs/2407.15754
- MM-VID: https://arxiv.org/abs/2310.19773
- Chroma, Context Rot: https://www.trychroma.com/research/context-rot
- WebVTT: https://www.w3.org/TR/webvtt/
- Gemini video understanding (timestamp format): https://ai.google.dev/gemini-api/docs/video-understanding
