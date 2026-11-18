"""Whole pipeline on the synthetic call (downloads the models on first run).

    uv run --script tests/make_sample.py sample/sample.webm
    SCREENSCRIBE_SAMPLE=sample/sample.webm uv run pytest tests/test_end_to_end.py
"""

import json
import os
from pathlib import Path

import pytest

SAMPLE = os.environ.get("SCREENSCRIBE_SAMPLE")


@pytest.mark.skipif(not SAMPLE, reason="set SCREENSCRIBE_SAMPLE to a file made by tests/make_sample.py")
def test_synthetic_call(tmp_path):
    from screenscribe.pipeline import process

    paths = process(SAMPLE, tmp_path)
    truth = json.loads(Path(SAMPLE).with_suffix(".truth.json").read_text("utf-8"))["turns"]
    raw = json.loads(paths["json"].read_text("utf-8"))

    # every voice keeps one speaker number, and the three voices get three different numbers
    heard = {}
    for turn in truth:
        middle = (turn["start"] + turn["end"]) / 2
        speaker = next(s["speaker"] for s in raw["segments"] if s["start"] <= middle < s["end"])
        heard.setdefault(turn["speaker"], set()).add(speaker)
    assert all(len(numbers) == 1 for numbers in heard.values()), heard
    assert len({min(numbers) for numbers in heard.values()}) == 3, heard

    speech = " ".join(segment["text"] for segment in raw["segments"]).lower()
    for word in ("тестирование", "архитектуру", "инфраструктуре", "недели"):
        assert word in speech

    assert len(raw["screens"]) == 4
    screen_text = "\n".join(line for screen in raw["screens"] for line in screen["new"])
    for term in ("CRM", "480 000", "PostgreSQL", "RabbitMQ", "Kubernetes", "pytest"):
        assert term in screen_text

    markdown = paths["md"].read_text("utf-8")
    assert markdown.count("\n## [") == 4
    # the phrase about the stack is printed under the architecture slide, not before it
    assert markdown.index("Kubernetes") < markdown.index("Обратите внимание")
    assert "data:image/jpeg;base64," in paths["html"].read_text("utf-8")
