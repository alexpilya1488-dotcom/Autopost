"""
Сборка вертикального видео (1080x1920, формат YouTube Shorts) из:
  - озвучки (mp3)
  - кадров персонажа (папка с PNG для цикла "разговора"; пока арт не готов —
    используется простая заглушка-кружок, чтобы пайплайн работал целиком)
  - подписей (субтитры крупным текстом, как в большинстве шортсов)

Как только будут готовы настоящие спрайты персонажа (см.
faktik-animation-guide.md), просто положи PNG-кадры разговора в папку
и передай её путь в CHARACTER_FRAMES_DIR.
"""

import glob
import os
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


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    if FONT_PATH and os.path.exists(FONT_PATH):
        return ImageFont.truetype(FONT_PATH, size)
    # Пытаемся найти системный шрифт с поддержкой кириллицы
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]:
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _caption_frame(text: str) -> Image.Image:
    """Рисует один кадр с подписью поверх прозрачного слоя."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _load_font(64)

    wrapped = textwrap.fill(text, width=22)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center")
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (WIDTH - text_w) / 2
    y = HEIGHT - 480  # субтитры в нижней трети, над персонажем

    # Обводка для читаемости на любом фоне
    for dx in (-3, 0, 3):
        for dy in (-3, 0, 3):
            draw.multiline_text((x + dx, y + dy), wrapped, font=font,
                                 fill=(0, 0, 0, 255), align="center")
    draw.multiline_text((x, y), wrapped, font=font, fill=(255, 255, 255, 255), align="center")
    return img


def _character_clip(duration: float):
    """Зацикленная анимация персонажа. Пока нет готового арта — простая
    пульсирующая заглушка; замени на реальные кадры talk-loop."""
    frames = sorted(glob.glob(os.path.join(CHARACTER_FRAMES_DIR, "*.png")))
    if frames:
        clip = ImageClip(frames[0]).set_duration(duration)
        # Простейшая покадровая смена (лип-синк) — переключаем PNG по кругу
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
        # Заглушка: цветной круг вместо персонажа
        placeholder = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
        d = ImageDraw.Draw(placeholder)
        d.ellipse([20, 20, 480, 480], fill=ACCENT_COLOR + (255,))
        clip = ImageClip(_pil_to_array(placeholder)).set_duration(duration)

    clip = clip.resize(width=560)
    clip = clip.set_position(("center", HEIGHT - 900))
    return clip


def _pil_to_array(img: Image.Image):
    import numpy as np
    return np.array(img)


def build_video(audio_path: str, script_text: str, out_path: str = "output.mp4") -> str:
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    bg = ImageClip(_pil_to_array(Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR))).set_duration(duration)
    character = _character_clip(duration)
    caption = ImageClip(_pil_to_array(_caption_frame(script_text))).set_duration(duration)

    video = CompositeVideoClip([bg, character, caption], size=(WIDTH, HEIGHT))
    video = video.set_audio(audio)
    video.write_videofile(out_path, fps=30, codec="libx264", audio_codec="aac")
    return out_path


if __name__ == "__main__":
    build_video("voice.mp3", "Осьминоги имеют три сердца, и два из них перестают биться во время плавания.")
