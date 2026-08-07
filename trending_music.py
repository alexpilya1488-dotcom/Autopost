"""
Ротация треков для "нарезок" из локальной папки TRENDING_MUSIC_DIR.

ВАЖНО: этот модуль НИЧЕГО не скачивает и не ищет музыку сам. Реальные
трендовые песни — это чужой копирайтный контент, и решение использовать их
(с соответствующим риском Content ID/страйков) — осознанный выбор владельца
канала, а не то, что должен молча делать автоматический скрапер. Поэтому:
положи mp3/m4a/wav-файлы с треками в TRENDING_MUSIC_DIR САМ (купленные,
скачанные легально, с правами на использование) — скрипт лишь выбирает
из того, что там уже лежит, и ротирует их, чтобы не повторять один и тот
же трек в каждой нарезке подряд.

Если папка пуста — pick_track() вернёт None, и build_edit_video.py соберёт
клип с оригинальной звуковой дорожкой фильма вместо музыки (см. предупреждение
в логах), а не упадёт с ошибкой.
"""

import glob
import json
import os

TRENDING_MUSIC_DIR = "trending_music"
MUSIC_STATE_FILE = "trending_music_state.json"
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".aac", ".ogg")


def _list_tracks() -> list[str]:
    files = []
    for ext in AUDIO_EXTENSIONS:
        files.extend(glob.glob(os.path.join(TRENDING_MUSIC_DIR, f"*{ext}")))
    return sorted(files)


def _load_state() -> dict:
    if os.path.exists(MUSIC_STATE_FILE):
        with open(MUSIC_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"last_used": []}


def _save_state(state: dict) -> None:
    with open(MUSIC_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def pick_track() -> str | None:
    """Возвращает путь к следующему треку по кругу (наименее недавно
    использованный), либо None, если папка пуста."""
    tracks = _list_tracks()
    if not tracks:
        print(f"   [!] В папке {TRENDING_MUSIC_DIR}/ нет аудиофайлов — соберу клип с оригинальным звуком фильма.")
        return None

    state = _load_state()
    last_used = [t for t in state.get("last_used", []) if t in tracks]

    unused = [t for t in tracks if t not in last_used]
    chosen = unused[0] if unused else last_used[0]  # last_used[0] = давнее всех использованный

    last_used = [t for t in last_used if t != chosen] + [chosen]
    last_used = last_used[-len(tracks):]  # не даём списку расти бесконечно
    state["last_used"] = last_used
    _save_state(state)

    return chosen


if __name__ == "__main__":
    track = pick_track()
    print("Выбран трек:", track or "(нет — будет оригинальный звук фильма)")
