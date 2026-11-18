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

    def label(turn: dict) -> int:
        """The speaker number that covers most of a true turn."""
        shared = {}
        for segment in raw["segments"]:
            overlap = min(segment["end"], turn["end"]) - max(segment["start"], turn["start"])
            if overlap > 0:
                shared[segment["speaker"]] = shared.get(segment["speaker"], 0) + overlap
        return max(shared, key=shared.get)

    # The three voices get three different speaker numbers. The voices are synthesized
    # anew on every run, and a short remark right after a speaker change is sometimes
    # given to the previous speaker, so two of the ten turns may be off.
    labels = {}
    for turn in truth:
        labels.setdefault(turn["speaker"], []).append(label(turn))
    usual = {voice: max(set(found), key=found.count) for voice, found in labels.items()}
    assert len(set(usual.values())) == 3, labels
    assert sum(found.count(usual[voice]) for voice, found in labels.items()) >= 8, labels

    speech = " ".join(segment["text"] for segment in raw["segments"]).lower()
    words = ("тестирование", "архитектуру", "инфраструктуре", "недели")
    assert sum(word in speech for word in words) >= 3, speech

    assert len(raw["screens"]) == 4
    screen_text = "\n".join(line for screen in raw["screens"] for line in screen["new"])
    for term in ("CRM", "480 000", "PostgreSQL", "RabbitMQ", "Kubernetes", "pytest"):
        assert term in screen_text

    markdown = paths["md"].read_text("utf-8")
    assert markdown.count("\n## [") == 4
    # the phrase about the stack is printed under the architecture slide, not before it
    assert markdown.index("Kubernetes") < markdown.index("Обратите внимание")
    assert "data:image/jpeg;base64," in paths["html"].read_text("utf-8")
