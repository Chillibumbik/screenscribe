"""Fast checks of the pure logic (no models needed)."""

import numpy as np

from screenscribe.screen import blocks, fix_scripts, fresh, key, rows
from screenscribe.speech import MAX_CHUNK, sentences, split
from screenscribe.timeline import build, clock, markdown


def test_sentences_get_their_own_times_and_numbers_stay_whole():
    tokens = [" До", "бр", "ый", ".", " В", " 3", ".", "18", " все", "?"]
    stamps = [0.1, 0.2, 0.3, 0.4, 1.0, 1.2, 1.3, 1.4, 1.6, 1.9]
    assert sentences(tokens, stamps, 10.0, 13.0) == [(10.1, 11.0, "Добрый."), (11.0, 13.0, "В 3.18 все?")]


def test_text_without_final_punctuation_is_kept():
    assert sentences([" да", " конечно"], [0.0, 0.5], 5.0, 7.0) == [(5.0, 7.0, "да конечно")]


def test_long_audio_is_cut_at_the_quiet_spot():
    rate = 16000
    audio = np.ones(50 * rate, np.float32)
    audio[15 * rate:int(15.5 * rate)] = 0  # the only pause
    pieces = list(split(audio, 0.0, 50.0))
    assert all(end - start <= MAX_CHUNK for start, end in pieces)
    assert pieces[0][0] == 0.0 and pieces[-1][1] == 50.0
    assert 15.0 <= pieces[0][1] <= 15.5


def test_mixed_alphabet_words_are_repaired():
    assert fix_scripts("Задержка АPІ со стороны СRМ: высокий") == "Задержка API со стороны CRM: высокий"
    assert fix_scripts("RаbbіtмQ и дaнных") == "RabbitmQ и данных"
    assert fix_scripts("Привет PostgreSQL 16, він") == "Привет PostgreSQL 16, він"  # nothing mixed


def test_panes_are_read_one_after_another():
    cells = [(60, 10 + 30 * i, 500, 30 + 30 * i, f"doc {i}") for i in range(3)]
    cells += [(1000, 10 + 30 * i, 1500, 30 + 30 * i, f"code {i}") for i in range(3)]
    lines = [line for block in blocks(cells, 20.0) for line in rows(block, 20.0)]
    assert lines == ["doc 0", "doc 1", "doc 2", "code 0", "code 1", "code 2"]


def test_table_cells_on_one_row_are_joined():
    cells = [(10, 10, 100, 30, "Name"), (160, 10, 220, 30, "Price"), (10, 40, 100, 60, "Tea"), (160, 40, 220, 60, "5")]
    assert [line for block in blocks(cells, 20.0) for line in rows(block, 20.0)] == ["Name | Price", "Tea | 5"]


def test_only_new_text_counts_despite_ocr_jitter():
    seen = [key(line) for line in ["File Edit View", "Срок сдачи: 15 декабря"]]
    assert fresh(["File Edit View", "Срок сдачи: 15 декабpя", "Бюджет: 480 000"], seen) == ["Бюджет: 480 000"]


def _screen(start, lines, new=None):
    return {"start": start, "lines": lines, "new": new or lines, "image": b""}


def test_speech_lands_under_the_screen_it_was_said_over():
    screens = [_screen(0.0, ["Plan", "Deadline"]), _screen(20.0, ["Architecture", "Backend"])]
    segments = [
        {"start": 1.0, "end": 8.0, "speaker": 1, "text": "Look at the plan."},
        {"start": 8.0, "end": 12.0, "speaker": 1, "text": "Here is the deadline."},
        {"start": 18.0, "end": 26.0, "speaker": 2, "text": "This slide is our stack."},  # mostly over screen 2
    ]
    chapters = build(segments, screens)
    assert [chapter["title"] for chapter in chapters] == ["Plan", "Architecture"]
    assert chapters[0]["turns"] == [{"start": 1.0, "speaker": 1, "text": "Look at the plan. Here is the deadline."}]
    assert chapters[1]["turns"][0]["speaker"] == 2


def test_update_and_return_to_an_earlier_screen():
    first, other = ["Plan", "Deadline", "Budget", "Team"], ["Risks", "API delay", "No test stand"]
    screens = [_screen(0.0, first), _screen(10.0, first + ["Extra"], ["Extra"]), _screen(20.0, other), _screen(30.0, first)]
    chapters = build([], screens)
    assert [chapter["update"] for chapter in chapters] == [False, True, False, False]
    assert [chapter["back_to"] for chapter in chapters] == [None, None, None, 0]
    text = markdown("call.mp4", chapters, screens, 40.0)
    assert '## [00:30] `Screen: back to "Plan" (first shown at 00:00)`' in text
    assert text.count("Deadline") == 1  # the returned-to screen is not printed again


def test_audio_only_recording_has_no_screen_headings():
    text = markdown("call.mp3", build([{"start": 0.0, "end": 2.0, "speaker": 1, "text": "Привет."}], []), [], 2.0)
    assert "**[00:00] Speaker 1:** Привет." in text and "## " not in text


def test_clock():
    assert clock(59.9) == "00:59" and clock(3725) == "1:02:05"
