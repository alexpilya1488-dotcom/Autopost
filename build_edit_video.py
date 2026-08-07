"""
Сборка одной "нарезки": вырезает сегмент [start, end] из фильма (по прямой
ссылке — без скачивания фильма целиком, ffmpeg сам делает seek по сети),
кадрирует под вертикальный формат YouTube Shorts (1080x1920, crop-to-fill —
как в примере-нарезке, без чёрных полос), и заменяет звук на трек из
trending_music.py (или оставляет оригинальный звук фильма, если треков нет).

Работает через прямой вызов ffmpeg (subprocess), а не moviepy — здесь это
проще и эффективнее: один вызов ffmpeg делает seek+crop+audio-mux+fade за
один проход, без прогона всего фильма через Python.
"""

import subprocess

WIDTH, HEIGHT = 1080, 1920
FADE_SEC = 0.35


def build_edit_clip(
    video_url: str,
    start: float,
    end: float,
    music_path: str | None,
    out_path: str = "edit_output.mp4",
) -> str:
    duration = round(end - start, 2)
    if duration <= 0:
        raise ValueError(f"Некорректный диапазон клипа: start={start} end={end}")

    # crop-to-fill под 9:16: сначала масштабируем так, чтобы кадр ПОЛНОСТЬЮ
    # накрывал 1080x1920 (по большей стороне), затем обрезаем лишнее по центру —
    # без чёрных полос, независимо от исходного соотношения сторон фильма.
    video_filter = (
        f"scale=w='if(gt(a,{WIDTH}/{HEIGHT}),-2,{WIDTH})':"
        f"h='if(gt(a,{WIDTH}/{HEIGHT}),{HEIGHT},-2)',"
        f"crop={WIDTH}:{HEIGHT},setsar=1,"
        f"fade=t=in:st=0:d={FADE_SEC},fade=t=out:st={duration - FADE_SEC:.2f}:d={FADE_SEC}"
    )

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-to", str(end), "-i", video_url]

    if music_path:
        audio_filter = (
            f"atrim=0:{duration},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={FADE_SEC},afade=t=out:st={duration - FADE_SEC:.2f}:d={FADE_SEC}"
        )
        cmd += [
            "-i", music_path,
            "-filter_complex", f"[0:v]{video_filter}[v];[1:a]{audio_filter}[a]",
            "-map", "[v]", "-map", "[a]",
        ]
    else:
        # треков нет — оставляем оригинальную звуковую дорожку фильма
        cmd += [
            "-filter_complex", f"[0:v]{video_filter}[v]",
            "-map", "[v]", "-map", "0:a?",
        ]

    cmd += [
        "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
        "-t", str(duration), out_path,
    ]

    subprocess.run(cmd, check=True)
    return out_path


if __name__ == "__main__":
    import sys

    from highlight_finder import find_highlight
    from movie_source import pick_movie
    from trending_music import pick_track

    movie = pick_movie()
    print(f"Фильм: {movie['title']} ({movie['duration']/60:.1f} мин)")
    s, e = find_highlight(movie["url"], movie["duration"])
    print(f"Момент: {s:.1f}s - {e:.1f}s")
    track = pick_track()
    path = build_edit_clip(movie["url"], s, e, track, out_path="edit_output.mp4")
    print("Готово:", path)
