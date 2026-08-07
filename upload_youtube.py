"""
Загрузка видео на YouTube через официальный YouTube Data API v3.

Настроено под способ без локального сервера (подходит для телефона и для
запуска в GitHub Actions): используется готовый refresh-токен, полученный
один раз через Google OAuth Playground. Сам refresh-токен не даёт доступ
ни к чему, кроме загрузки видео (это ограничено самим OAuth client'ом).

Как получить нужные три значения (client_id, client_secret, refresh_token) —
см. README.md, раздел "Доступ к YouTube". Все три хранятся как секреты
GitHub Actions:
  YOUTUBE_CLIENT_ID
  YOUTUBE_CLIENT_SECRET
  YOUTUBE_REFRESH_TOKEN
"""

import os
import googleapiclient.discovery
import googleapiclient.http
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _get_credentials() -> Credentials:
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not (client_id and client_secret and refresh_token):
        raise RuntimeError(
            "Задай переменные окружения YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, "
            "YOUTUBE_REFRESH_TOKEN (см. README.md, раздел «Доступ к YouTube»)."
        )

    creds = Credentials(
        None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )
    creds.refresh(Request())  # получаем свежий access-токен по refresh-токену
    return creds


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list[str] | None = None,
    privacy_status: str = "public",  # "private" / "unlisted" / "public"
    made_for_kids: bool = False,
) -> str:
    """Загружает видео, возвращает YouTube video ID."""
    creds = _get_credentials()
    youtube = googleapiclient.discovery.build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags or [],
            "categoryId": "27",  # Education; см. список категорий YouTube
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }

    media = googleapiclient.http.MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Загружено {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"Готово: https://youtube.com/watch?v={video_id}")
    return video_id


if __name__ == "__main__":
    upload_video(
        "output.mp4",
        title="Тестовое видео",
        description="Проверка автозагрузки",
        tags=["факты", "shorts"],
        privacy_status="private",
    )
