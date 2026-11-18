"""Build a synthetic call recording for end-to-end checks.

Three TTS voices talk over four slides; the result is a WebM file (VP8 + Opus, the same
container a browser recording produces) plus a JSON file with the ground truth.

    uv run --script tests/make_sample.py out/sample.webm

Runs in its own environment (see the script metadata below): the Piper voices need the
espeak-ng frontend, which sherpa-onnx dropped in 2.0, while the transcriber itself uses 2.x.
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["sherpa-onnx<2", "av", "numpy", "pillow"]
# ///

import json
import sys
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import sherpa_onnx
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from screenscribe.models import fetch  # noqa: E402  (stdlib only, safe to import from the source tree)

VOICE_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-ru_RU-%s-medium-int8.tar.bz2"
FONTS = [  # any font with Cyrillic glyphs
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]
SLIDES = [
    ("Проект: Личный кабинет клиента", ["Этап 2: интеграция с CRM", "Срок сдачи: 15 декабря",
                                         "Бюджет этапа: 480 000 рублей", "Команда: 3 разработчика, 1 аналитик"]),
    ("Архитектура", ["Frontend: React + TypeScript", "Backend: FastAPI, Python 3.12",
                     "База данных: PostgreSQL 16", "Очередь задач: RabbitMQ", "Деплой: Docker, Kubernetes"]),
    ("Риски", ["Задержка API со стороны CRM: высокий", "Нет тестового стенда: средний",
               "Рост нагрузки в январе: низкий"]),
    ("$ pytest tests/ -q", ["42 passed, 1 failed in 3.18s",
                            "FAILED tests/test_sync.py::test_retry - TimeoutError"]),
]
SCRIPT = [  # (slide, voice, text)
    (0, "irina", "Добрый день, коллеги! Давайте посмотрим на план второго этапа. Вот здесь на слайде указаны срок сдачи и бюджет."),
    (0, "ruslan", "Да, вижу. Скажите, а этот срок включает тестирование?"),
    (0, "irina", "Да, тестирование входит в этот срок. Денис, расскажи, пожалуйста, про архитектуру."),
    (1, "denis", "Конечно. На этом слайде наш стек. Обратите внимание на последнюю строку: деплой будет в кубернетес."),
    (1, "ruslan", "А почему для очереди выбрали именно это решение?"),
    (1, "denis", "Оно уже используется в вашей инфраструктуре, поэтому так будет проще в поддержке."),
    (2, "irina", "Теперь о рисках. Самый серьёзный риск указан в первой строке таблицы."),
    (2, "ruslan", "Мы постараемся выдать доступ к тестовому стенду до конца недели."),
    (3, "denis", "И последнее. Вот результат прогона тестов: один тест падает по таймауту, я исправлю это завтра."),
    (3, "irina", "Отлично. Тогда на сегодня всё, спасибо всем!"),
]
RATE, FPS, SIZE = 48000, 5, (1280, 720)


def speak(voice: str, text: str) -> np.ndarray:
    folder = fetch(VOICE_URL % voice)
    tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(folder / f"ru_RU-{voice}-medium.onnx"),
            tokens=str(folder / "tokens.txt"),
            data_dir=str(folder / "espeak-ng-data")))))
    audio = tts.generate(text)
    samples = np.asarray(audio.samples, np.float32)
    positions = np.arange(0, len(samples), audio.sample_rate / RATE)  # linear resample to 48 kHz
    return np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)


def slide(index: int) -> np.ndarray:
    title, lines = SLIDES[index]
    dark = index == 3  # the last slide imitates a terminal
    font = next(f for f in FONTS if Path(f).exists())
    image = Image.new("RGB", SIZE, (24, 24, 28) if dark else (255, 255, 255))
    draw = ImageDraw.Draw(image)
    color = (220, 220, 220) if dark else (20, 20, 20)
    draw.text((80, 70), title, font=ImageFont.truetype(font, 34 if dark else 54), fill=color)
    for row, line in enumerate(lines):
        draw.text((100, 200 + row * 80), line, font=ImageFont.truetype(font, 26 if dark else 36), fill=color)
    return np.asarray(image)


def main(path: str) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pause = np.zeros(int(RATE * 0.6), np.float32)
    track, truth = [pause], []
    for slide_index, voice, text in SCRIPT:
        start = sum(map(len, track)) / RATE
        track += [speak(voice, text), pause]
        truth.append({"start": round(start, 2), "end": round(sum(map(len, track)) / RATE - 0.6, 2),
                      "speaker": voice, "slide": slide_index, "text": text})
    audio = np.concatenate(track)

    with av.open(str(out_path), "w") as container:
        video = container.add_stream("libvpx", rate=FPS)
        video.width, video.height, video.pix_fmt, video.bit_rate = *SIZE, "yuv420p", 600_000
        sound = container.add_stream("libopus", rate=RATE)
        sound.layout = "mono"
        resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE, frame_size=960)
        pcm = av.AudioFrame.from_ndarray((audio * 32767).astype(np.int16)[None], format="s16", layout="mono")
        pcm.sample_rate = RATE
        sound_frames, sent = iter(resampler.resample(pcm)), 0
        images = [slide(i) for i in range(len(SLIDES))]
        for n in range(int(len(audio) / RATE * FPS)):
            now = n / FPS
            # the slide flips half a second before the first phrase about it
            shown = max((t["slide"] for t in truth if t["start"] - 0.5 <= now), default=0)
            frame = av.VideoFrame.from_ndarray(images[shown], format="rgb24")
            frame.pts, frame.time_base = n, Fraction(1, FPS)
            container.mux(video.encode(frame))
            for sound_frame in sound_frames:
                sound_frame.pts, sound_frame.time_base = sent, Fraction(1, RATE)
                sent += sound_frame.samples
                container.mux(sound.encode(sound_frame))
                if sent / RATE >= now:
                    break
        container.mux(video.encode())
        container.mux(sound.encode())

    truth_path = out_path.with_suffix(".truth.json")
    truth_path.write_text(json.dumps({"turns": truth, "slides": SLIDES}, ensure_ascii=False, indent=1), "utf-8")
    print(f"{out_path}: {len(audio) / RATE:.0f} s, {len(truth)} turns, {len(SLIDES)} slides")


if __name__ == "__main__":
    main(*sys.argv[1:])
