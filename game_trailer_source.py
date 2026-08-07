"""
Источник видео для "нарезок" — официальные трейлеры игр из Steam Storefront
API (store.steampowered.com/api/...). Это не чей-то YouTube-аплоад, а
первоисточник: сам Steam отдаёт эти ролики публично для показа на странице
игры (то же, что видит любой посетитель магазина). Никакого скачивания
геймплея или чужих видео здесь нет — только сами трейлеры-промоматериалы.

ВАЖНО про права: трейлер всё равно принадлежит издателю — доступ здесь
официальный (не скрейпинг чужого контента), но это не железная гарантия
нулевого риска (Content ID и т.п.). Индустрия к репостам трейлеров относится
терпимо (бесплатный промоушен для издателя), но это то же самое осознанное
допущение, что уже принято для trending_music.py.

Технически: Steam отдаёт трейлеры как HLS/DASH (поля hls_h264 / dash_h264
в ответе appdetails) — прямых .mp4 ссылок в текущем API уже нет. ffmpeg
прекрасно читает HLS-плейлисты напрямую по URL (так же, как обычный mp4),
так что highlight_finder.py и build_edit_video.py используют эти ссылки
без каких-либо изменений.
"""

import random
import subprocess

import requests

FEATURED_URL = "https://store.steampowered.com/api/featuredcategories"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
CANDIDATE_LISTS = ("new_releases", "top_sellers", "specials")

MIN_DURATION_SEC = 25
MAX_DURATION_SEC = 4 * 60


def _list_candidate_appids() -> list[int]:
    resp = requests.get(FEATURED_URL, params={"cc": "us", "l": "english"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    appids = []
    for key in CANDIDATE_LISTS:
        for item in data.get(key, {}).get("items", []):
            appid = item.get("id")
            if appid:
                appids.append(appid)
    return list(dict.fromkeys(appids))  # dedupe, сохраняя порядок


def _probe_duration(url: str) -> float | None:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", url],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return float(proc.stdout.strip())
    except Exception:
        return None


def _is_mature(data: dict) -> bool:
    """Steam обязывает разработчиков декларировать 18+/NSFW-контент в поле
    content_descriptors (оно же включает возрастной гейт на странице
    магазина) — это самый надёжный сигнал, который у нас есть, надёжнее
    жанров/тегов. На всякий случай подстраховываемся ещё и по required_age.
    Фильтр консервативный: пропускаем ЛЮБую игру с непустыми дескрипторами
    (даже "просто насилие"), чтобы не рисковать с автопостингом без
    человека в цикле — лучше упустить часть нормальных игр, чем один раз
    выложить что-то неприемлемое для канала."""
    descriptors = data.get("content_descriptors") or {}
    if descriptors.get("ids") or descriptors.get("notes"):
        return True
    if (data.get("required_age") or 0) >= 17:
        return True
    return False


def get_trailers(appid: int) -> list[dict]:
    """Возвращает список трейлеров игры (их может быть несколько) с прямыми
    ссылками, длительностью и метаданными. Пустой список, если игра не
    подходит (не тип "game", трейлеров нет, помечена как 18+/NSFW и т.п.)."""
    resp = requests.get(APPDETAILS_URL, params={"appids": appid, "cc": "us", "l": "english"}, timeout=30)
    resp.raise_for_status()
    payload = resp.json().get(str(appid)) or {}
    if not payload.get("success"):
        return []
    data = payload.get("data", {})
    if data.get("type") != "game":
        return []  # пропускаем DLC/саундтреки/демо/софт и т.п.
    if _is_mature(data):
        return []

    title = data.get("name") or f"app {appid}"
    release_date = (data.get("release_date") or {}).get("date")

    trailers = []
    for movie in data.get("movies", []):
        url = movie.get("hls_h264") or movie.get("dash_h264")
        if not url:
            continue
        duration = _probe_duration(url)
        if duration is None or not (MIN_DURATION_SEC <= duration <= MAX_DURATION_SEC):
            continue
        trailers.append({
            "identifier": f"{appid}_{movie['id']}",
            "appid": appid,
            "title": title,
            "trailer_name": movie.get("name") or "Trailer",
            "year": release_date,
            "url": url,
            "duration": duration,
            "source_page": f"https://store.steampowered.com/app/{appid}",
            "highlight": bool(movie.get("highlight")),
        })

    trailers.sort(key=lambda t: not t["highlight"])  # официальный "главный" трейлер первым
    return trailers


def get_trailer_by_id(identifier: str) -> dict | None:
    """Достаёт конкретный, уже известный трейлер по identifier
    ("{appid}_{movie_id}") — используется, чтобы продолжить брать моменты
    из того же трейлера в следующих запусках."""
    appid_str, _, _ = identifier.partition("_")
    if not appid_str.isdigit():
        return None
    for trailer in get_trailers(int(appid_str)):
        if trailer["identifier"] == identifier:
            return trailer
    return None


def pick_trailer(exclude_identifiers: set[str] | None = None) -> dict:
    """Ищет и возвращает случайный подходящий трейлер, которого нет в
    exclude_identifiers (уже использованные/исчерпанные)."""
    exclude_identifiers = exclude_identifiers or set()
    appids = _list_candidate_appids()
    random.shuffle(appids)

    for appid in appids:
        try:
            trailers = get_trailers(appid)
        except requests.RequestException:
            continue
        for trailer in trailers:
            if trailer["identifier"] not in exclude_identifiers:
                return trailer

    raise RuntimeError("Не нашёл ни одного подходящего трейлера (все варианты отфильтрованы)")


if __name__ == "__main__":
    t = pick_trailer()
    print(f"{t['title']} — {t['trailer_name']} ({t['duration']:.0f}s, {t['year']})")
    print(t["url"])
    print(t["source_page"])
