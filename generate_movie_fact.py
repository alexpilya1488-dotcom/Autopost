"""
Генерация видео-факта о ТРЕНДОВОМ ФИЛЬМЕ.

ВАЖНО: этот модуль НЕ скачивает и не использует кадры/фрагменты самих
фильмов или трейлеров — только текстовые метаданные (название, описание,
рейтинг) из открытого API TMDB, на основе которых нейронка пишет СВОЙ
текст: факты о съёмках, актёрах, бюджете, реакции критиков, почему фильм
в тренде — без пересказа сюжета и без спойлеров. Готовое видео собирается
тем же build_video.py (тот же персонаж и фон, что и у обычного "Фактика").

Структура сценария — "для удержания": сначала интригующие факты БЕЗ
названия фильма, и только в последнем предложении раскрывается, о каком
фильме шла речь. Это чисто текстовый приём (порядок фраз), никакого
видео/аудио из трейлера здесь не используется.

Ключи (переменные окружения, не хранить в коде):
  TMDB_API_KEY   — https://www.themoviedb.org/settings/api (бесплатно)
  GEMINI_API_KEY / GROQ_API_KEY — те же, что и в generate_fact.py
"""

import os
import json
import random
import requests

from generate_fact import _generate_with_gemini, _generate_with_groq, _clean_json_text

TMDB_TRENDING_URL = "https://api.themoviedb.org/3/trending/movie/day"
TMDB_TOP_N = 10  # берём случайный фильм из топ-N трендовых, чтобы не повторяться каждый день

MOVIE_PROMPT_TEMPLATE = """Ты — сценарист коротких видео для YouTube Shorts от лица
дерзкого мультяшного персонажа "Фактик". Расскажи о фильме, который сейчас
в тренде — БЕЗ СПОЙЛЕРОВ к сюжету и БЕЗ пересказа сюжета.

Фильм: {title} ({year})
Краткое описание (только для твоего контекста — НЕ пересказывай его в видео): {overview}
Рейтинг зрителей: {rating}/10

СТРУКТУРА СЦЕНАРИЯ (важно для удержания зрителя):
1. Начни с 2-3 самых интригующих фактов О ФИЛЬМЕ (съёмки, актёры, бюджет,
   кастинг, реакция критиков/зрителей) — но НЕ называй сам фильм и не
   произноси его название в начале. Держи зрителя в интриге "о каком
   фильме идёт речь".
2. Только в САМОМ ПОСЛЕДНЕМ предложении раскрой название фильма — как
   развязку/кульминацию ("а называется всё это... {title}!" или похоже).

Разговорный стиль, эмоции (восторг/сарказм/удивление), без канцелярита и
без спойлеров к событиям фильма. Всего 4-6 коротких предложений.

Напиши:
1. title — короткий цепляющий заголовок ВИДЕО для YouTube (до 60 символов).
   Тут название фильма упомянуть МОЖНО и НУЖНО — это для карточки видео,
   а не для самого сценария озвучки.
2. script — текст озвучки по структуре выше: название фильма только в
   последнем предложении
3. description — короткое описание видео (2-3 предложения) + 5 хэштегов
   (один из хэштегов — название фильма)
4. tags — список из 8-10 ключевых слов для YouTube (массив строк, включи
   название фильма)

Верни СТРОГО валидный JSON без markdown-обёртки:
{{"title": "...", "script": "...", "description": "...", "tags": ["...", "..."]}}
"""


def _fetch_trending_movies() -> list[dict]:
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        raise RuntimeError("Задай переменную окружения TMDB_API_KEY")

    resp = requests.get(
        TMDB_TRENDING_URL,
        params={"api_key": api_key, "language": "ru-RU"},
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        raise RuntimeError("TMDB вернул пустой список трендовых фильмов")
    return results


def generate_movie_fact(movie: dict | None = None) -> dict:
    """Возвращает dict с title/script/description/tags для видео о трендовом
    фильме. Если movie не передан — берёт случайный из топ трендовых TMDB.
    Сценарий (script) построен так, что название фильма называется только
    в последнем предложении — остальное держит зрителя в интриге."""
    if movie is None:
        movies = _fetch_trending_movies()
        movie = random.choice(movies[:TMDB_TOP_N])

    title = movie.get("title") or movie.get("original_title") or "Неизвестный фильм"
    release_date = movie.get("release_date", "") or ""
    year = release_date[:4] if release_date else "?"
    overview = movie.get("overview") or "нет описания"
    rating = movie.get("vote_average", "?")

    prompt = MOVIE_PROMPT_TEMPLATE.format(title=title, year=year, overview=overview, rating=rating)

    try:
        raw = _generate_with_gemini(prompt)
        used = "gemini"
    except Exception as gemini_error:
        print(f"   [!] Gemini недоступен ({gemini_error}). Переключаюсь на Groq...")
        raw = _generate_with_groq(prompt)
        used = "groq"

    data = json.loads(_clean_json_text(raw))
    data["topic"] = f"фильм: {title}"
    data["movie_title"] = title
    print(f"   (сгенерировано через: {used}; фильм: {title})")
    return data


if __name__ == "__main__":
    fact = generate_movie_fact()
    print(json.dumps(fact, ensure_ascii=False, indent=2))
