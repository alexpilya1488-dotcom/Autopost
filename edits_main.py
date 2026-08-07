"""
Оркестратор "нарезок" (edits): выбирает официальный трейлер игры (Steam
Storefront API) -> находит яркий момент -> берёт трек из trending_music/ ->
собирает вертикальный клип -> публикует на YouTube. Отдельный пайплайн от
main.py (тот — про "Фактика" с персонажем и озвучкой; этот — про короткие
нарезки трейлеров под музыку, без персонажа и без TTS).

Состояние (какие трейлеры/моменты/треки уже использованы) хранится в
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
from game_trailer_source import pick_trailer, get_trailer_by_id
from highlight_finder import find_highlight
from trending_music import pick_track
from build_edit_video import build_edit_clip
from upload_youtube import upload_video

STATE_FILE = "edits_state.json"
MAX_CLIPS_PER_TRAILER = 2  # трейлеры короткие (обычно 1-3 мин) — после пары нарезок берём другой

TITLE_PROMPT_TEMPLATE = """Ты придумываешь короткую цепляющую подпись для YouTube Shorts —
нарезки яркого момента из официального трейлера игры "{title}" (трейлер:
{trailer_name}). Ты НЕ видел сам момент — просто придумай интригующую, но
честную подачу (без выдуманных подробностей о сюжете/геймплее).

Напиши:
1. title — короткий цепляющий заголовок (до 60 символов), можно с эмодзи,
   в духе трендовых игровых "эдитов" (например, "Этот момент из \\"{title}\\" 🔥")
2. description — 1-2 предложения + 5 хэштегов (обязательно #shorts и
   что-то про игры/трейлеры)
3. tags — список из 6-8 ключевых слов (массив строк, включая название игры)

Верни СТРОГО валидный JSON без markdown-обёртки:
{{"title": "...", "description": "...", "tags": ["...", "..."]}}
"""


def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"trailers": {}, "current_trailer_id": None}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _generate_caption(game_title: str, trailer_name: str) -> dict:
    prompt = TITLE_PROMPT_TEMPLATE.format(title=game_title, trailer_name=trailer_name)
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


def _get_trailer_for_run(state: dict) -> dict:
    """Продолжает текущий трейлер, если у него ещё не исчерпан лимит
    нарезок, иначе берёт новый (исключая исчерпанные/уже использованные)."""
    current_id = state.get("current_trailer_id")
    if current_id:
        entry = state["trailers"].get(current_id)
        if entry and not entry.get("exhausted") and len(entry.get("used_ranges", [])) < MAX_CLIPS_PER_TRAILER:
            trailer = get_trailer_by_id(current_id)
            if trailer:
                return trailer

    exclude = {tid for tid, e in state["trailers"].items() if e.get("exhausted")}
    trailer = pick_trailer(exclude_identifiers=exclude)
    state.setdefault("trailers", {}).setdefault(
        trailer["identifier"], {"title": trailer["title"], "used_ranges": [], "exhausted": False}
    )
    state["current_trailer_id"] = trailer["identifier"]
    return trailer


def make_one_edit(index: int, privacy_status: str, dry_run: bool, state: dict) -> None:
    print(f"\n=== Нарезка {index}: 1/4 Выбираю трейлер... ===")

    # Если у выбранного трейлера не нашлось свободного яркого момента —
    # пробуем другой; ограничиваем число попыток, чтобы не зациклиться.
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        trailer = _get_trailer_for_run(state)
        entry = state["trailers"].setdefault(
            trailer["identifier"], {"title": trailer["title"], "used_ranges": [], "exhausted": False}
        )
        print(f"   Игра: {trailer['title']} — {trailer['trailer_name']} "
              f"({trailer['duration']:.0f}s) — {trailer['source_page']}")

        print(f"Нарезка {index}: 2/4 Ищу яркий момент...")
        used_ranges = [tuple(r) for r in entry["used_ranges"]]
        try:
            start, end = find_highlight(trailer["url"], trailer["duration"], used_ranges=used_ranges)
            break
        except RuntimeError as e:
            print(f"   [!] {e} — помечаю трейлер исчерпанным и беру другой (попытка {attempt}/{max_attempts}).")
            entry["exhausted"] = True
            state["current_trailer_id"] = None
            _save_state(state)
    else:
        raise RuntimeError(f"Не удалось найти яркий момент за {max_attempts} попыток подряд")
    print(f"   Момент: {start:.1f}s - {end:.1f}s")

    track = pick_track()

    print(f"Нарезка {index}: 3/4 Собираю клип...")
    # Ссылки Steam на трейлер подписаны токеном с ограниченным временем жизни
    # (?t=... в URL). Между тем, как мы её получили (в _get_trailer_for_run),
    # и этим моментом уже прошло время на поиск яркого момента — берём СВЕЖУЮ
    # ссылку прямо перед финальной сборкой, чтобы не словить протухший токен
    # и оборванное/повреждённое чтение видео (см. _validate_clip ниже —
    # дополнительная страховка на случай, если всё равно что-то пойдёт не так).
    fresh_trailer = get_trailer_by_id(trailer["identifier"]) or trailer
    video_path = build_edit_clip(fresh_trailer["url"], start, end, track, out_path=f"edit_output_{index}.mp4")

    caption = _generate_caption(trailer["title"], trailer["trailer_name"])
    description = (
        f"{caption['description']}\n\n"
        f"Момент из официального трейлера игры «{trailer['title']}» "
        f"({trailer['trailer_name']}). Источник: {trailer['source_page']}"
    )

    entry["used_ranges"].append([start, end])
    if len(entry["used_ranges"]) >= MAX_CLIPS_PER_TRAILER:
        entry["exhausted"] = True
        state["current_trailer_id"] = None
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
