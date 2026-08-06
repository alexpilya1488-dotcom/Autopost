"""
Полный цикл: факт -> озвучка -> видео -> публикация на YouTube.
За один запуск делает несколько видео подряд (по умолчанию 2), на разные
темы, чтобы не повторяться в рамках одного запуска.

Запуск:  python main.py
Два видео (по умолчанию):  python main.py
Другое количество:          python main.py --count 3
Для теста без реальной публикации:  python main.py --dry-run
Для отправки в приватный доступ (проверить перед публикой):
                                     python main.py --privacy private
"""

import argparse
import random

from generate_fact import generate_fact, TOPICS
from tts import synthesize_speech
from build_video import build_video
from upload_youtube import upload_video


def make_one_video(topic: str | None, index: int, privacy_status: str, dry_run: bool) -> None:
    print(f"\n=== Видео {index}: 1/4 Генерирую факт... ===")
    fact = generate_fact(topic=topic)
    print(f"   Тема: {fact['topic']}")
    print(f"   Заголовок: {fact['title']}")

    print(f"Видео {index}: 2/4 Озвучиваю...")
    audio_path = synthesize_speech(fact["script"], out_path=f"voice_{index}.mp3")

    print(f"Видео {index}: 3/4 Собираю видео...")
    video_path = build_video(audio_path, fact["script"], out_path=f"output_{index}.mp4")

    if dry_run:
        print(f"Видео {index}: готово (dry-run, без публикации): {video_path}")
        return

    print(f"Видео {index}: 4/4 Публикую на YouTube...")
    upload_video(
        video_path,
        title=fact["title"],
        description=fact["description"],
        tags=fact.get("tags", []),
        privacy_status=privacy_status,
    )


def run(privacy_status: str = "public", dry_run: bool = False, topic: str | None = None, count: int = 2) -> None:
    if topic:
        # Тема задана явно — делаем на ней все count видео (факты внутри всё равно разные)
        topics_for_run = [topic] * count
    else:
        pool = TOPICS.copy()
        random.shuffle(pool)
        if count <= len(pool):
            topics_for_run = pool[:count]
        else:
            # Тем не хватает без повторов — добираем случайными
            topics_for_run = pool + [random.choice(TOPICS) for _ in range(count - len(pool))]

        import time
    for i, t in enumerate(topics_for_run, start=1):
        make_one_video(topic=t, index=i, privacy_status=privacy_status, dry_run=dry_run)
        if i < len(topics_for_run):
            time.sleep(20)


    print(f"\nГотово: собрано и {'подготовлено' if dry_run else 'опубликовано'} видео: {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--dry-run", action="store_true", help="собрать видео, но не публиковать")
    parser.add_argument("--topic", default=None, help="тема факта, иначе выбирается случайно")
    parser.add_argument("--count", type=int, default=2, help="сколько видео сделать за запуск (по умолчанию 2)")
    args = parser.parse_args()

    run(privacy_status=args.privacy, dry_run=args.dry_run, topic=args.topic, count=args.count)

