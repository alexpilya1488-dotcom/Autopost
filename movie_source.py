"""
Источник видео для "нарезок" (edits) — ТОЛЬКО фильмы из общественного
достояния (public domain), физически хранящиеся на Internet Archive
(archive.org). Никакого скачивания с YouTube/стриминговых сервисов и
никакого пиратского контента здесь нет и не будет.

Как проверяется, что фильм действительно public domain: archive.org хранит
для каждой позиции поле метаданных `licenseurl`. Мы отбираем ТОЛЬКО записи,
где это поле явно указывает на public domain (CC0, Public Domain Mark или
"licenses/publicdomain"). Записи без явной лицензии или с обычной copyright-
пометкой ИГНОРИРУЮТСЯ — даже если формально лежат в коллекции "feature_films"
(эта коллекция сборная, туда иногда заливают и обычные копирайтные фильмы,
поэтому фильтр по licenseurl обязателен, а не опционален).

Сам видеофайл никогда не скачивается целиком на диск: highlight_finder.py и
build_edit_video.py работают с ffmpeg напрямую по прямой ссылке на файл
(ffmpeg умеет делать seek по HTTP через Range-запросы), поэтому с диска/сети
уходит только реально нужный кусок, а не весь фильм.
"""

import random

import requests

SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{identifier}"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"

# Только явные public-domain лицензии — см. докстринг модуля.
PD_QUERY = (
    "mediatype:(movies) AND collection:(feature_films) "
    "AND licenseurl:(*publicdomain*)"
)

MIN_DURATION_SEC = 25 * 60   # короче — обычно короткометражки/ролики, не то что нужно
MAX_DURATION_SEC = 180 * 60  # длиннее — слишком долго искать/тянуть по сети


def search_public_domain_movies(rows: int = 100) -> list[dict]:
    """Возвращает список {identifier, title, year} фильмов с явной
    public-domain лицензией на archive.org."""
    resp = requests.get(
        SEARCH_URL,
        params={
            "q": PD_QUERY,
            "fl[]": ["identifier", "title", "year", "licenseurl"],
            "rows": rows,
            "output": "json",
            # немного разный sort, чтобы не всегда получать одну и ту же голову списка
            "sort[]": "random",
        },
        timeout=30,
    )
    resp.raise_for_status()
    docs = resp.json().get("response", {}).get("docs", [])
    return [d for d in docs if d.get("licenseurl") and "publicdomain" in d["licenseurl"].lower()]


def _pick_video_file(files: list[dict]) -> dict | None:
    """Из списка файлов item'а выбирает подходящий mp4: предпочитаем
    веб-оптимизированный derivative (обычно быстрее отдаёт и лучше
    поддерживает seek по Range), иначе берём любой .mp4."""
    mp4_files = [f for f in files if f.get("name", "").lower().endswith(".mp4")]
    if not mp4_files:
        return None
    for f in mp4_files:
        name = f["name"].lower()
        if "512kb" in name or ".stream" in name:
            return f
    return min(mp4_files, key=lambda f: float(f.get("size") or "inf"))


def get_movie_video(identifier: str) -> dict | None:
    """Возвращает {url, duration, title, identifier} для фильма, либо None,
    если у item'а нет подходящего mp4 или длительность за пределами
    MIN/MAX_DURATION_SEC."""
    resp = requests.get(METADATA_URL.format(identifier=identifier), timeout=30)
    resp.raise_for_status()
    meta = resp.json()

    licenseurl = meta.get("metadata", {}).get("licenseurl", "") or ""
    if "publicdomain" not in licenseurl.lower():
        return None  # повторная проверка на случай гонки/устаревшего индекса поиска

    video_file = _pick_video_file(meta.get("files", []))
    if not video_file or not video_file.get("length"):
        return None

    duration = float(video_file["length"])
    if not (MIN_DURATION_SEC <= duration <= MAX_DURATION_SEC):
        return None

    title = meta.get("metadata", {}).get("title") or ""
    if len(title.strip()) < 4 or title.strip().isdigit():
        return None  # похоже на мусорную/непонятную загрузку, а не на реальный фильм

    return {
        "identifier": identifier,
        "title": title.strip(),
        "year": meta.get("metadata", {}).get("year"),
        "url": DOWNLOAD_URL.format(identifier=identifier, filename=video_file["name"]),
        "duration": duration,
        "source_page": f"https://archive.org/details/{identifier}",
        "licenseurl": licenseurl,
    }


def pick_movie(exclude_identifiers: set[str] | None = None) -> dict:
    """Ищет и возвращает случайный подходящий фильм, которого нет в
    exclude_identifiers (уже использованные/исчерпанные фильмы)."""
    exclude_identifiers = exclude_identifiers or set()
    candidates = search_public_domain_movies()
    random.shuffle(candidates)

    for doc in candidates:
        identifier = doc["identifier"]
        if identifier in exclude_identifiers:
            continue
        movie = get_movie_video(identifier)
        if movie:
            return movie

    raise RuntimeError("Не нашёл ни одного подходящего public-domain фильма (все варианты отфильтрованы)")


if __name__ == "__main__":
    m = pick_movie()
    print(f"{m['title']} ({m['year']}) — {m['duration']/60:.1f} мин")
    print(m["url"])
    print(m["source_page"])
