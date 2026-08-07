"""
Оркестратор "нарезок" (edits): выбирает public-domain фильм -> находит яркий
момент -> берёт трек из trending_music/ -> собирает вертикальный клип ->
публикует на YouTube. Отдельный пайплайн от main.py (тот — про "Фактика" с
персонажем и озвучкой; этот — про короткие нарезки из фильмов под музыку,
без персонажа и без TTS).

Состояние (какие фильмы/моменты/треки уже использованы) хранится в
edits_state.json и коммитится обратно в репозиторий воркфлоу-раннером
(см. .github/workflows/edits-bot.yml) — так пайплайн не повторяет один и тот
же момент между запусками.

Запуск:  python edits_main.py
Другое количество клипов за раз:     python edits_main.py --count 2
Для теста без реальной публикации:   python edits_main.py --dry-run
"""

import argparse
import json
import os

from generate_fact import _generate_with_gemini, _generate_with_groq, _clean_json_text
from movie_source import pick_movie, get_movie_video
from highlight_finder import find_highlight
from trending_music import pick_track
from build_edit_video import build_edit_clip
from upload_youtube import upload_video

STATE_FILE = "edits_state.json"
MAX_CLIPS_PER_MOVIE = 4  # после стольких нарезок из одного фильма берём следующий

TITLE_PROMPT_TEMPLATE = """Ты придумываешь короткую цепляющую подпись для YouTube Shorts —
нарезки яркого момента из старого фильма "{title}" ({year}), общественное
достояние (public domain). Ты НЕ видел сам момент — просто придумай
интригующую, но честную подачу (без спойлеров к несуществующему контексту,
без выдуманных фактов о сюжете).

Напиши:
1. title — короткий цепляющий заголовок (до 60 символов), можно с эмодзи,
   в духе трендовых "эдитов" (например, "Этот кадр из \\"{title}\\" 🔥")
2. description — 1-2 предложения + 5 хэштегов (обязательно #shorts и
   что-то про фильм/эдиты)
3. tags — список из 6-8 ключевых слов (массив строк)

Верни СТРОГО валидный JSON без markdown-обёртки:
{{"title": "...", "description": "...", "tags": ["...", "..."]}}
"""


def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"movies": {}, "current_movie_id": None}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _generate_caption(movie_title: str, year) -> dict:
    prompt = TITLE_PROMPT_TEMPLATE.format(title=movie_title, year=year or "?")
    try:
        raw = _generate_with_gemini(prompt)
        used = "gemini"
    except Exception as gemini_error:
        print(f"   [!] Gemini недоступен ({gemini_error}). Переключаюсь на Groq...")
        raw = _generate_with_groq(prompt)
        used = "groq"
    data = json.loads(_clean_json_text(raw))
    print(f"   (подпись сгенерирована через: {used})")
    return data


def _get_movie_for_run(state: dict) -> dict:
    """Продолжает текущий фильм, если у него ещё не исчерпан лимит нарезок,
    иначе берёт новый (исключая исчерпанные/уже использованные)."""
    current_id = state.get("current_movie_id")
    if current_id:
        entry = state["movies"].get(current_id)
        if entry and not entry.get("exhausted") and len(entry.get("used_ranges", [])) < MAX_CLIPS_PER_MOVIE:
            movie = get_movie_video(current_id)
            if movie:
                return movie

    exclude = {mid for mid, e in state["movies"].items() if e.get("exhausted")}
    movie = pick_movie(exclude_identifiers=exclude)
    state.setdefault("movies", {}).setdefault(movie["identifier"], {"title": movie["title"], "used_ranges": [], "exhausted": False})
    state["current_movie_id"] = movie["identifier"]
    return movie


def make_one_edit(index: int, privacy_status: str, dry_run: bool, state: dict) -> None:
    print(f"\n=== Нарезка {index}: 1/4 Выбираю фильм... ===")

    # Если у выбранного фильма не нашлось свободного яркого момента — пробуем
    # другой фильм; ограничиваем число попыток, чтобы не зациклиться, если
    # вдруг закончатся все подходящие public-domain фильмы.
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        movie = _get_movie_for_run(state)
        entry = state["movies"].setdefault(
            movie["identifier"], {"title": movie["title"], "used_ranges": [], "exhausted": False}
        )
        print(f"   Фильм: {movie['title']} ({movie['duration']/60:.1f} мин) — {movie['source_page']}")

        print(f"Нарезка {index}: 2/4 Ищу яркий момент...")
        used_ranges = [tuple(r) for r in entry["used_ranges"]]
        try:
            start, end = find_highlight(movie["url"], movie["duration"], used_ranges=used_ranges)
            break
        except RuntimeError as e:
            print(f"   [!] {e} — помечаю фильм исчерпанным и беру другой (попытка {attempt}/{max_attempts}).")
            entry["exhausted"] = True
            state["current_movie_id"] = None
            _save_state(state)
    else:
        raise RuntimeError(f"Не удалось найти яркий момент за {max_attempts} попыток подряд")
    print(f"   Момент: {start:.1f}s - {end:.1f}s")

    track = pick_track()

    print(f"Нарезка {index}: 3/4 Собираю клип...")
    video_path = build_edit_clip(movie["url"], start, end, track, out_path=f"edit_output_{index}.mp4")

    caption = _generate_caption(movie["title"], movie.get("year"))
    description = (
        f"{caption['description']}\n\n"
        f"Фрагмент из фильма «{movie['title']}» ({movie.get('year') or '?'}), "
        f"общественное достояние (public domain). Источник: {movie['source_page']}"
    )

    entry["used_ranges"].append([start, end])
    if len(entry["used_ranges"]) >= MAX_CLIPS_PER_MOVIE:
        entry["exhausted"] = True
        state["current_movie_id"] = None
    _save_state(state)

    if dry_run:
        print(f"Нарезка {index}: готово (dry-run, без публикации): {video_path}")
        return

    print(f"Нарезка {index}: 4/4 Публикую на YouTube...")
    upload_video(
        video_path,
        title=caption["title"],
        description=description,
        tags=caption.get("tags", []),
        privacy_status=privacy_status,
    )


def run(count: int = 1, privacy_status: str = "public", dry_run: bool = False) -> None:
    state = _load_state()
    for i in range(1, count + 1):
        make_one_edit(index=i, privacy_status=privacy_status, dry_run=dry_run, state=state)
    _save_state(state)
    print(f"\nГотово: собрано и {'подготовлено' if dry_run else 'опубликовано'} нарезок: {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--dry-run", action="store_true", help="собрать видео, но не публиковать")
    parser.add_argument("--count", type=int, default=1, help="сколько нарезок сделать за запуск (по умолчанию 1)")
    args = parser.parse_args()

    run(count=args.count, privacy_status=args.privacy, dry_run=args.dry_run)
