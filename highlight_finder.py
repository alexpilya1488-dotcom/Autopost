"""
Поиск "яркого момента" в видео (трейлере игры).

Принимает либо URL, либо путь к локальному файлу — ffmpeg одинаково читает
и то, и другое через -i. На практике edits_main.py передаёт сюда уже
скачанный локальный файл (см. game_trailer_source.download_trailer): seek
по сети на HLS/fMP4-источнике Steam оказался ненадёжным (повреждал поток),
поэтому трейлер сначала качается целиком одним линейным проходом.

ЧЕСТНО О ТОЧНОСТИ: у нас нет доступа к модели, которая реально понимает
"смешно" или "интересно" в смысле сюжета/шутки. Вместо этого используется
эвристика — окно с максимальной громкостью аудио (RMS) обычно соответствует
динамичным, "громким" моментам (экшен, музыкальный акцент, крик, драматичный
момент) — то есть не гарантированно "смешно", но заметно чаще "интересно",
чем случайная секунда с тихим диалогом. Это прозрачно указано и в
edits_main.py, и в README — никакого притворства, что тут "понимание сюжета".
"""

import subprocess

import numpy as np

SAMPLE_RATE = 8000          # для анализа громкости этого достаточно, экономит трафик/CPU
WINDOW_SEC = 1.0
CLIP_MIN_SEC = 18
CLIP_MAX_SEC = 32
EDGE_MARGIN = 0.06           # не берём первые/последние 6% фильма (титры/финал)
MIN_GAP_FROM_USED_SEC = 45   # не предлагать момент рядом с уже использованным


def _extract_energy_envelope(video_url: str, duration: float) -> np.ndarray:
    """Тянет аудиодорожку по URL через ffmpeg и считает RMS-громкость по
    односекундным окнам. Возвращает 1D-массив длиной ~duration (в секундах)."""
    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-i", video_url,
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    samples = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0

    window = int(SAMPLE_RATE * WINDOW_SEC)
    n_windows = max(len(samples) // window, 1)
    energy = np.array([
        np.sqrt(np.mean(samples[i * window:(i + 1) * window] ** 2))
        for i in range(n_windows)
    ])
    return energy


def _overlaps_used(start: float, end: float, used_ranges: list[tuple[float, float]]) -> bool:
    for u_start, u_end in used_ranges:
        if start < u_end + MIN_GAP_FROM_USED_SEC and end > u_start - MIN_GAP_FROM_USED_SEC:
            return True
    return False


def find_highlight(
    video_url: str,
    duration: float,
    used_ranges: list[tuple[float, float]] | None = None,
) -> tuple[float, float]:
    """Возвращает (start, end) — сегмент длиной 18-32с с самой высокой
    аудио-энергией, не пересекающийся с уже использованными диапазонами.
    Бросает RuntimeError, если подходящего свободного момента не нашлось
    (значит фильм уже "исчерпан" — пора брать другой)."""
    used_ranges = used_ranges or []
    energy = _extract_energy_envelope(video_url, duration)

    margin = int(len(energy) * EDGE_MARGIN)
    valid_start = max(margin, 0)
    valid_end = max(len(energy) - margin, valid_start + 1)

    order = np.argsort(energy[valid_start:valid_end])[::-1] + valid_start
    clip_len = (CLIP_MIN_SEC + CLIP_MAX_SEC) / 2

    for peak_sec in order:
        start = max(float(peak_sec) - clip_len / 2, 0.0)
        end = min(start + clip_len, duration)
        start = max(end - clip_len, 0.0)  # подровнять, если упёрлись в конец фильма
        if end - start < CLIP_MIN_SEC:
            continue
        if _overlaps_used(start, end, used_ranges):
            continue
        return round(start, 2), round(end, 2)

    raise RuntimeError("Не нашёл свободный яркий момент в этом видео (похоже, всё уже использовано)")


if __name__ == "__main__":
    from game_trailer_source import pick_trailer

    trailer = pick_trailer()
    print(f"Трейлер: {trailer['title']} — {trailer['trailer_name']} ({trailer['duration']:.0f}s)")
    s, e = find_highlight(trailer["url"], trailer["duration"])
    print(f"Момент: {s:.1f}s - {e:.1f}s ({e-s:.1f}s)")
