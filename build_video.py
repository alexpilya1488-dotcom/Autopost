"""
Сборка вертикального видео (1080x1920, формат YouTube Shorts) из:
  - озвучки (mp3)
  - кадров персонажа (папка с PNG для цикла "разговора"; пока арт не готов —
    используется простая заглушка-кружок, чтобы пайплайн работал целиком)
  - подписей: короткие фразы (не целые предложения), показываются С АНИМАЦИЕЙ
    ПЕЧАТИ (буквы появляются слева на право, как будто их печатают),
    расположены НАД персонажем.

Как только будут готовы настоящие спрайты персонажа (см.
faktik-animation-guide.md), просто положи PNG-кадры разговора в папку
и передай её путь в CHARACTER_FRAMES_DIR.
"""

import glob
import os
import re
import textwrap

from moviepy.editor import (
    AudioFileClip, ImageClip, VideoClip, CompositeVideoClip, concatenate_videoclips
)
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1080, 1920
BACKGROUND_IMAGE = "background.png"  # положи файл в корень репозитория рядом с main.py
ACCENT_COLOR = (220, 38, 38)
CHARACTER_FRAMES_DIR = "character_frames"  # папка с PNG-кадрами рта (talk-loop)
FONT_PATH = None  # укажи путь к .ttf с кириллицей, если системный шрифт не подходит

CAPTION_MAX_LINES = 2  # фразы теперь короче — двух строк достаточно
MIN_SEGMENT_DURATION = 0.6  # секунд, чтобы даже короткое "Да!" не мелькало мгновенно
MAX_TEXT_WIDTH = 940  # пикселей — оставляем поля по бокам от края 1080px
MAX_WORDS_PER_CAPTION = 4  # дробим текст на короткие фразы, а не целые предложения

CAPTION_START_SIZE = 52  # чуть меньше, чем раньше (было 64) — фразы короче
CAPTION_MIN_SIZE = 28

CAPTION_Y = 360  # субтитры в верхней трети — ВЫШЕ персонажа
CHARACTER_Y = HEIGHT - 1180  # персонаж поднят выше (было HEIGHT - 900)

TYPEWRITER_CHARS_PER_SEC = 22  # скорость "печати" букв
TYPEWRITER_MAX_SHARE = 0.85  # печать длится не дольше этой доли времени показа фразы


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


def _wrap_and_size(text: str, start_size: int = CAPTION_START_SIZE, min_size: int = CAPTION_MIN_SIZE):
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


def _pil_to_array(img: Image.Image):
    import numpy as np
    return np.array(img)


def _split_sentences(script: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+', script.strip())
    return [p.strip() for p in parts if p.strip()]


def _split_captions(script: str) -> list[str]:
    """Дробит текст на короткие фразы (по паузам и по числу слов), а не на
    целые предложения — так подписи ближе к тому, что произносится
    "прямо сейчас", а не висят длинным куском."""
    phrases = []
    for sentence in _split_sentences(script):
        # сначала режем по естественным паузам (запятая, точка с запятой, тире)
        parts = re.split(r'(?<=[,;:—])\s+', sentence)
        for part in parts:
            words = part.split()
            for i in range(0, len(words), MAX_WORDS_PER_CAPTION):
                chunk = " ".join(words[i:i + MAX_WORDS_PER_CAPTION]).strip()
                if chunk:
                    phrases.append(chunk)
    return phrases or [script]


def _typewriter_clip(text: str, duration: float) -> VideoClip:
    """Клип с подписью, где буквы появляются последовательно, как при
    печати. Перенос строк и позиция фиксируются один раз по ПОЛНОМУ тексту
    фразы, поэтому во время печати текст не "прыгает" и не перецентровывается."""
    wrapped, font = _wrap_and_size(text)
    lines = wrapped.split("\n")

    line_widths = []
    line_heights = []
    for line in lines:
        bbox = _measure_draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1] + 8)  # небольшой запас по высоте строки

    line_gap = 10
    total_w = max(line_widths) if line_widths else 1
    x0 = (WIDTH - total_w) / 2
    y0 = CAPTION_Y

    total_chars = sum(len(l) for l in lines) or 1
    typing_time = min(duration * TYPEWRITER_MAX_SHARE, total_chars / TYPEWRITER_CHARS_PER_SEC)
    typing_time = max(typing_time, 0.01)

    def make_frame(t):
        img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        progress = min(t / typing_time, 1.0)
        chars_to_show = int(round(total_chars * progress))

        remaining = chars_to_show
        y = y0
        for line, lw, lh in zip(lines, line_widths, line_heights):
            n = min(len(line), remaining)
            shown = line[:n]
            lx = x0 + (total_w - lw) / 2  # центрируем строку по её финальной ширине

            if shown:
                for dx in (-3, 0, 3):
                    for dy in (-3, 0, 3):
                        draw.text((lx + dx, y + dy), shown, font=font, fill=(0, 0, 0, 255))
                draw.text((lx, y), shown, font=font, fill=(255, 255, 255, 255))

            y += lh + line_gap
            remaining -= n
            if remaining <= 0:
                break

        return _pil_to_array(img)

    return VideoClip(make_frame, duration=duration)


def _caption_clips(script: str, total_duration: float):
    """Разбивает текст на короткие фразы и показывает их по очереди — с
    длительностью, пропорциональной длине фразы, чтобы темп примерно
    совпадал с озвучкой. Каждая фраза "печатается" по буквам."""
    phrases = _split_captions(script)
    lengths = [max(len(p), 1) for p in phrases]
    total_len = sum(lengths)

    clips = []
    t = 0.0
    for i, (phrase, length) in enumerate(zip(phrases, lengths)):
        is_last = i == len(phrases) - 1
        dur = total_duration - t if is_last else total_duration * (length / total_len)
        dur = max(dur, MIN_SEGMENT_DURATION)
        clip = _typewriter_clip(phrase, dur).set_start(t)
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
    clip = clip.set_position(("center", CHARACTER_Y))
    return clip


def _load_background() -> Image.Image:
    if os.path.exists(BACKGROUND_IMAGE):
        img = Image.open(BACKGROUND_IMAGE).convert("RGB")
        if img.size != (WIDTH, HEIGHT):
            img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
        return img
    # запасной вариант, если картинку забыли положить в репозиторий
    return Image.new("RGB", (WIDTH, HEIGHT), (10, 3, 3))


def build_video(audio_path: str, script_text: str, out_path: str = "output.mp4") -> str:
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    bg = ImageClip(_pil_to_array(_load_background())).set_duration(duration)
    character = _character_clip(duration)
    captions = _caption_clips(script_text, duration)

    video = CompositeVideoClip([bg, character] + captions, size=(WIDTH, HEIGHT))
    video = video.set_audio(audio)
    video.write_videofile(out_path, fps=30, codec="libx264", audio_codec="aac")
    return out_path


if __name__ == "__main__":
    build_video("voice.mp3", "Осьминоги имеют три сердца. Два из них перестают биться во время плавания. Вот такие дела!")
