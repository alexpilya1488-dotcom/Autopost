"""
Загрузка видео на YouTube через официальный YouTube Data API v3.

Настройка (один раз):
1. https://console.cloud.google.com -> создать проект
2. Включить "YouTube Data API v3" (APIs & Services -> Library)
3. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID
   -> Application type: Desktop app
4. Скачать JSON и сохранить рядом со скриптом как client_secret.json
5. При первом запуске откроется браузер — войди в тот аккаунт YouTube,
   на который нужно публиковать, и разреши доступ. Токен сохранится в
   token.json и дальше будет обновляться автоматически, без браузера.

Пока приложение в режиме "Testing" в Google Cloud, работать будет только
с аккаунтами, которые ты явно добавишь в Test users (в OAuth consent screen) —
этого достаточно для одного личного канала, публиковать может кто угодно.
"""

import os
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.http
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILE = "client_secret.json"
TOKEN_FILE = "token.json"


def _get_credentials() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

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
