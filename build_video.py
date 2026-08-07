"""
Сборка вертикального видео (1080x1920, формат YouTube Shorts) из:
  - озвучки (mp3)
  - кадров персонажа (папка с PNG для цикла "разговора"; пока арт не готов —
    используется простая заглушка-кружок, чтобы пайплайн работал целиком)
  - подписей: показываются ПО ПРЕДЛОЖЕНИЯМ, синхронно с длиной озвучки —
    больше не наезжают друг на друга, как раньше, когда висел весь текст сразу.

Как только будут готовы настоящие спрайты персонажа (см.
faktik-animation-guide.md), просто положи PNG-кадры разговора в папку
и передай её путь в CHARACTER_FRAMES_DIR.
"""

import glob
import os
import re
import textwrap

from moviepy.editor import (
    AudioFileClip, ImageClip, CompositeVideoClip, concatenate_videoclips
)
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1080, 1920
BG_COLOR = (10, 3, 3)          # тёмный фон под стиль карты безопасности :)
ACCENT_COLOR = (220, 38, 38)
CHARACTER_FRAMES_DIR = "character_frames"  # папка с PNG-кадрами рта (talk-loop)
FONT_PATH = None  # укажи путь к .ttf с кириллицей, если системный шрифт не подходит

CAPTION_MAX_LINES = 3  # если предложение не влезает в столько строк — уменьшаем шрифт
MIN_SEGMENT_DURATION = 0.6  # секунд, чтобы даже короткое "Да!" не мелькало мгновенно
MAX_TEXT_WIDTH = 940  # пикселей — оставляем поля по бокам от края 1080px


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    if FONT_PATH and os.path.exists(FONT_PATH):
        return ImageFont.truetype(FONT_PATH, size)
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]:
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


_measure_img = Image.new("RGB", (10, 10))
_measure_draw = ImageDraw.Draw(_measure_img)


def _line_width(line: str, font: ImageFont.FreeTypeFont) -> float:
    return _measure_draw.textlength(line, font=font)


def _wrap_and_size(text: str, start_size: int = 64, min_size: int = 34):
    """Подбирает размер шрифта и перенос строк по РЕАЛЬНОЙ измеренной ширине
    текста (не на глаз), чтобы строки гарантированно не вылезали за экран."""
    size = start_size
    while size >= min_size:
        font = _load_font(size)
        wrap_width = 40
        while wrap_width > 4:
            wrapped = textwrap.fill(text, width=wrap_width)
            lines = wrapped.split("\n")
            widest = max(_line_width(line, font) for line in lines)
            if widest <= MAX_TEXT_WIDTH:
                if len(lines) <= CAPTION_MAX_LINES:
                    return wrapped, font
                break  # влезло по ширине, но слишком много строк — нужен шрифт мельче
            wrap_width -= 2
        size -= 4
    # совсем длинная фраза — берём минимальный размер и как можно более узкий перенос
    font = _load_font(min_size)
    wrap_width = 40
    while wrap_width > 4:
        wrapped = textwrap.fill(text, width=wrap_width)
        widest = max(_line_width(line, font) for line in wrapped.split("\n"))
        if widest <= MAX_TEXT_WIDTH:
            break
        wrap_width -= 2
    return wrapped, font


def _caption_frame(text: str) -> Image.Image:
    """Рисует один кадр с подписью (одно предложение) поверх прозрачного слоя."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    wrapped, font = _wrap_and_size(text)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center")
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (WIDTH - text_w) / 2
    y = HEIGHT - 480  # субтитры в нижней трети, над персонажем

    for dx in (-3, 0, 3):
        for dy in (-3, 0, 3):
            draw.multiline_text((x + dx, y + dy), wrapped, font=font,
                                 fill=(0, 0, 0, 255), align="center")
    draw.multiline_text((x, y), wrapped, font=font, fill=(255, 255, 255, 255), align="center")
    return img


def _pil_to_array(img: Image.Image):
    import numpy as np
    return np.array(img)


def _split_sentences(script: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+', script.strip())
    return [p.strip() for p in parts if p.strip()]


def _caption_clips(script: str, total_duration: float):
    """Разбивает текст на предложения и показывает их по очереди, с
    длительностью пропорциональной длине предложения — чтобы подписи
    примерно совпадали с темпом озвучки и не накладывались друг на друга."""
    sentences = _split_sentences(script) or [script]
    lengths = [max(len(s), 1) for s in sentences]
    total_len = sum(lengths)

    clips = []
    t = 0.0
    for i, (sentence, length) in enumerate(zip(sentences, lengths)):
        is_last = i == len(sentences) - 1
        dur = total_duration - t if is_last else total_duration * (length / total_len)
        dur = max(dur, MIN_SEGMENT_DURATION)
        img = _caption_frame(sentence)
        clip = ImageClip(_pil_to_array(img)).set_start(t).set_duration(dur)
        clips.append(clip)
        t += dur
    return clips


def _character_clip(duration: float):
    """Зацикленная анимация персонажа. Пока нет готового арта — простая
    пульсирующая заглушка; замени на реальные кадры talk-loop."""
    frames = sorted(glob.glob(os.path.join(CHARACTER_FRAMES_DIR, "*.png")))
    if frames:
        fps_frames = 6  # кадров персонажа в секунду
        clips = []
        t = 0.0
        i = 0
        while t < duration:
            step = 1 / fps_frames
            clips.append(ImageClip(frames[i % len(frames)]).set_duration(min(step, duration - t)))
            t += step
            i += 1
        clip = concatenate_videoclips(clips, method="compose")
    else:
        placeholder = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
        d = ImageDraw.Draw(placeholder)
        d.ellipse([20, 20, 480, 480], fill=ACCENT_COLOR + (255,))
        clip = ImageClip(_pil_to_array(placeholder)).set_duration(duration)

    clip = clip.resize(width=560)
    clip = clip.set_position(("center", HEIGHT - 900))
    return clip


def build_video(audio_path: str, script_text: str, out_path: str = "output.mp4") -> str:
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    bg = ImageClip(_pil_to_array(Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR))).set_duration(duration)
    character = _character_clip(duration)
    captions = _caption_clips(script_text, duration)

    video = CompositeVideoClip([bg, character] + captions, size=(WIDTH, HEIGHT))
    video = video.set_audio(audio)
    video.write_videofile(out_path, fps=30, codec="libx264", audio_codec="aac")
    return out_path


if __name__ == "__main__":
    build_video("voice.mp3", "Осьминоги имеют три сердца. Два из них перестают биться во время плавания. Вот такие дела!")
