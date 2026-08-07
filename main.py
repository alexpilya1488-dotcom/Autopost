"""
Полный цикл: факт -> озвучка -> видео -> публикация на YouTube.
За один запуск делает несколько видео подряд (по умолчанию 2), на разные
темы, чтобы не повторяться в рамках одного запуска.
"""

import argparse
import random
import sys
import traceback

from generate_fact import generate_fact, TOPICS
from tts import synthesize_speech
from build_video import build_video
from upload_youtube import upload_video


def make_one_video(topic: str | None, index: int, privacy_status: str, dry_run: bool) -> None:
    print(f"\n=== Видео {index}: 1/4 Генерирую факт... ===", flush=True)
    fact = generate_fact(topic=topic)
    print(f"   Тема: {fact['topic']}", flush=True)
    print(f"   Заголовок: {fact['title']}", flush=True)

    print(f"Видео {index}: 2/4 Озвучиваю...", flush=True)
    audio_path = synthesize_speech(fact["script"], out_path=f"voice_{index}.mp3")

    print(f"Видео {index}: 3/4 Собираю видео...", flush=True)
    video_path = build_video(audio_path, fact["script"], out_path=f"output_{index}.mp4")
    print(f"Видео {index}: видео собрано -> {video_path}", flush=True)

    if dry_run:
        print(f"Видео {index}: готово (dry-run, без публикации): {video_path}", flush=True)
        return

    print(f"Видео {index}: 4/4 Публикую на YouTube...", flush=True)
    upload_video(
        video_path,
        title=fact["title"],
        description=fact["description"],
        tags=fact.get("tags", []),
        privacy_status=privacy_status,
    )


def run(privacy_status: str = "public", dry_run: bool = False, topic: str | None = None, count: int = 2) -> None:
    if topic:
        topics_for_run = [topic] * count
    else:
        pool = TOPICS.copy()
        random.shuffle(pool)
        if count <= len(pool):
            topics_for_run = pool[:count]
        else:
            topics_for_run = pool + [random.choice(TOPICS) for _ in range(count - len(pool))]

    for i, t in enumerate(topics_for_run, start=1):
        try:
            make_one_video(topic=t, index=i, privacy_status=privacy_status, dry_run=dry_run)
        except Exception:
            print(f"\n!!! ОШИБКА на видео {i} !!!", flush=True)
            traceback.print_exc()
            sys.stdout.flush()
            raise

    print(f"\nГотово: собрано и {'подготовлено' if dry_run else 'опубликовано'} видео: {count}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--topic", default=None)
    parser.add_argument("--count", type=int, default=2)
    args = parser.parse_args()

    run(privacy_status=args.privacy, dry_run=args.dry_run, topic=args.topic, count=args.count)
