"""Fast checks of the pure logic (no models needed)."""

import numpy as np

from screenscribe.screen import blocks, fix_scripts, fresh, headline, key, rows
from screenscribe.speech import MAX_CHUNK, sentences, split, stray
from screenscribe.timeline import build, clock, markdown


def test_sentences_get_their_own_times_and_numbers_stay_whole():
    tokens = [" До", "бр", "ый", ".", " В", " 3", ".", "18", " все", "?"]
    stamps = [0.1, 0.2, 0.3, 0.4, 1.0, 1.2, 1.3, 1.4, 1.6, 1.9]
    assert sentences(tokens, stamps, 10.0, 13.0) == [(10.1, 11.0, "Добрый."), (11.0, 13.0, "В 3.18 все?")]


def test_text_without_final_punctuation_is_kept():
    assert sentences([" да", " конечно"], [0.0, 0.5], 5.0, 7.0) == [(5.0, 7.0, "да конечно")]


def test_small_voices_are_not_participants():
    assert stray({0: 1278.0, 1: 366.0, 2: 258.0, 3: 17.0, 4: 6.0}) == {3, 4}  # a webinar: under 1% of the speech
    assert stray({0: 20.0, 1: 10.0, 2: 18.0}) == set()  # a one-minute call: everyone is real
    assert stray({0: 40.0, 1: 3.0}) == {1}  # never count under 5 s


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
    found = [text for block in blocks(cells, 20.0) for row in rows(block, 20.0) for _, text in row]
    assert found == ["doc 0", "doc 1", "doc 2", "code 0", "code 1", "code 2"]


def test_table_cells_stay_on_one_row_and_near_boxes_merge():
    cells = [(10, 10, 100, 38, "Name"), (160, 10, 220, 30, "Price"),
             (10, 40, 60, 60, "Green"), (70, 40, 100, 60, "tea"), (160, 40, 220, 60, "5")]
    found = [row for block in blocks(cells, 20.0) for row in rows(block, 20.0)]
    # every segment carries the height of its tallest box (the largest new text names the screen)
    assert found == [[(28, "Name"), (20, "Price")], [(20, "Green tea"), (20, "5")]]


def test_screen_is_named_by_its_largest_new_text():
    table = [[(14, "my.site.ru/page")], [(40, "Регистрация и формирование")], [(41, "команды"), (60, "000000")],
             [(18, "Подайте заявку до 19 ноября")], [(18, "Соберите команду")], [(16, "сообщение в чате")], [(16, "ещё одно сообщение")]]
    found = [[text for _, text in row] for row in table]
    # both lines of the heading, not the address bar and not the big misread icon;
    # the heading is new, so this is a new screen even if a chat panel holds more lines
    assert headline(table, found) == ("Регистрация и формирование команды", True)
    # only a small line is new under the same heading: a change of the same screen
    assert headline(table, [["Подайте заявку до 19 ноября"]]) == ("Подайте заявку до 19 ноября", False)
    page = [[(16, f"Строка текста номер {n}")] for n in range(6)]  # a chat or body text: nothing is a heading
    assert headline(page, [[text for _, text in row] for row in page]) == ("Строка текста номер 0", False)


def test_only_new_text_counts_despite_ocr_jitter():
    seen = [key(line) for line in ["File Edit View", "Срок сдачи: 15 декабря", "на стажировку в МГТС"]]
    assert fresh(["File Edit View", "Срок сдачи: 15 декабpя", "Бюджет: 480 000"], seen) == ["Бюджет: 480 000"]
    # an old slide line that shares a row with a new chat message is not repeated
    assert fresh(["на стажировку в МГТС", "всем привет из чата"], seen) == ["всем привет из чата"]
    # a short cell stays with its row, but does not make a row new on its own
    assert fresh(["Цена", "5"], seen) == ["Цена", "5"] and fresh(["File Edit View", "5"], seen) == []


def _screen(start, lines, new=None):
    new = new or lines
    return {"start": start, "title": new[0], "major": len(new) * 2 > len(lines), "lines": lines, "new": new, "image": b""}


def test_speech_lands_under_the_screen_it_was_said_over():
    screens = [_screen(0.0, ["Plan", "Deadline"]), _screen(20.0, ["Architecture", "Backend"])]
    segments = [
        {"start": 1.0, "end": 8.0, "speaker": 1, "text": "Look at the plan."},
        {"start": 8.0, "end": 12.0, "speaker": 1, "text": "Here is the deadline."},
        {"start": 18.0, "end": 26.0, "speaker": 2, "text": "This slide is our stack."},  # mostly over screen 2
    ]
    chapters = build(segments, screens)
    assert [chapter["title"] for chapter in chapters] == ["Plan", "Architecture"]
    assert chapters[0]["items"] == [{"start": 1.0, "speaker": 1, "text": "Look at the plan. Here is the deadline."}]
    assert chapters[1]["items"][0]["speaker"] == 2


def test_small_change_is_a_note_inside_the_chapter_and_a_return_is_one_line():
    first, other = ["Plan", "Deadline", "Budget", "Team"], ["Risks", "API delay", "No test stand"]
    screens = [_screen(0.0, first), _screen(10.0, first + ["Extra"], ["Extra"]), _screen(20.0, other), _screen(30.0, first)]
    segments = [{"start": 4.0, "end": 8.0, "speaker": 1, "text": "Before."}, {"start": 12.0, "end": 16.0, "speaker": 1, "text": "After."}]
    chapters = build(segments, screens)
    assert [chapter["screen"] for chapter in chapters] == [0, 2, 3]  # the small change opens no chapter
    assert [chapter["back_to"] for chapter in chapters] == [None, None, 0]
    # the note sits between the two sentences, where it happened
    assert [item.get("text", "update") for item in chapters[0]["items"]] == ["Before.", "update", "After."]
    text = markdown("call.mp4", chapters, screens, 40.0)
    assert "> [00:10] Screen update: `Extra`" in text
    screens[1]["new"] = ["a1", "b2", "c3", "d4"]  # a longer addition gets a block of its own
    assert "> [00:10] Screen update:\n\n```text\na1\nb2\nc3\nd4\n```" in markdown("call.mp4", chapters, screens, 40.0)
    assert '## [00:30] `Screen: back to "Plan" (first shown at 00:00)`' in text
    assert text.count("Deadline") == 1  # the returned-to screen is not printed again
    assert "screens: 3" in text


def test_audio_only_recording_has_no_screen_headings():
    segments = [{"start": 0.0, "end": 2.0, "speaker": 1, "text": "Привет."}, {"start": 2.0, "end": 2.4, "speaker": 0, "text": "Угу."}]
    text = markdown("call.mp3", build(segments, []), [], 2.4)
    assert "**[00:00] Speaker 1:** Привет." in text and "## " not in text
    # speaker 0 is an unidentified fragment: shown, but not counted as a participant
    assert "**[00:02] Speaker ?:** Угу." in text and "speakers: 1," in text


def test_clock():
    assert clock(59.9) == "00:59" and clock(3725) == "1:02:05"
