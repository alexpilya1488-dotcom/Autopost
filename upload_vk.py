"""
Публикация видео (и, при желании, текстовых постов) в сообщество ВКонтакте
через официальный VK API. Проще YouTube — не нужен OAuth-флоу, у сообщества
можно сразу выписать постоянный ключ доступа.

Как получить нужные два значения:
  1. Создай (или используй существующее) сообщество ВК, куда будешь постить.
  2. В настройках сообщества: Управление -> Работа с API -> Создать ключ
     доступа сообщества. Отметь права: video, wall, photos.
  3. VK_ACCESS_TOKEN — скопированный ключ доступа.
  4. VK_GROUP_ID — числовой ID сообщества БЕЗ минуса (для video.save нужен
     именно положительный ID; в ссылках на посты/видео ВК сам покажет его
     с минусом — просто убери минус для этой переменной).

Оба значения хранить как секреты GitHub Actions:
  VK_ACCESS_TOKEN
  VK_GROUP_ID

ВНИМАНИЕ: если посты будут рекламными/партнёрскими (с реф-ссылками на
маркетплейсы и т.п.) — по закону РФ они должны маркироваться через ОРД
(получать erid) ДО публикации. Этот модуль публикацию не маркирует сам —
erid нужно получать отдельно и добавлять в текст поста/описание вручную
или отдельным шагом, когда появится доступ к конкретному ОРД-провайдеру.

Точность API: этот код написан по документированной схеме VK API
(video.save + прямая загрузка на upload_url, wall.post), но не проверен
вживую — нет тестового токена. Проверь на реальном сообществе перед тем,
как ставить в расписание.
"""

import os

import requests

API_VERSION = "5.199"
API_BASE = "https://api.vk.com/method"


def _vk_call(method: str, **params) -> dict:
    access_token = os.environ.get("VK_ACCESS_TOKEN")
    if not access_token:
        raise RuntimeError("Задай переменную окружения VK_ACCESS_TOKEN")

    resp = requests.post(
        f"{API_BASE}/{method}",
        data={**params, "access_token": access_token, "v": API_VERSION},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"VK API ошибка ({method}): {data['error']}")
    return data["response"]


def _group_id() -> str:
    group_id = os.environ.get("VK_GROUP_ID")
    if not group_id:
        raise RuntimeError("Задай переменную окружения VK_GROUP_ID (положительный numeric ID сообщества)")
    return group_id


def upload_video(
    video_path: str,
    title: str,
    description: str,
    privacy_status: str = "public",  # "public" / "private"
) -> str:
    """Загружает видео в сообщество ВК с автопостом на стену
    (wallpost=1), возвращает ссылку на видео."""
    group_id = _group_id()

    save_resp = _vk_call(
        "video.save",
        name=title[:100],
        description=description,
        group_id=group_id,
        wallpost=1,
        privacy_view="all" if privacy_status == "public" else "nobody",
    )

    upload_url = save_resp["upload_url"]
    with open(video_path, "rb") as f:
        upload_resp = requests.post(upload_url, files={"video_file": f}, timeout=300)
    upload_resp.raise_for_status()

    owner_id = save_resp["owner_id"]
    video_id = save_resp["video_id"]
    video_url = f"https://vk.com/video{owner_id}_{video_id}"
    print(f"Готово: {video_url}")
    return video_url


def post_text(message: str, attachments: str | None = None) -> str:
    """Публикует текстовый пост на стену сообщества (без видео) —
    пригодится для простых обзоров товаров с фото/ссылкой без монтажа
    видео. attachments — готовая строка вложений VK (например,
    "photo-123_456"), если она уже есть; без нужды в фото просто не передавай."""
    group_id = _group_id()
    params = {"owner_id": f"-{group_id}", "message": message, "from_group": 1}
    if attachments:
        params["attachments"] = attachments

    resp = _vk_call("wall.post", **params)
    post_id = resp["post_id"]
    post_url = f"https://vk.com/wall-{group_id}_{post_id}"
    print(f"Готово: {post_url}")
    return post_url


if __name__ == "__main__":
    upload_video(
        "output.mp4",
        title="Тестовое видео",
        description="Проверка автозагрузки в VK",
        privacy_status="private",
    )
