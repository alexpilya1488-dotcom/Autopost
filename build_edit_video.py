"""
Сборка одной "нарезки": вырезает сегмент [start, end] из видео (по прямой
ссылке — без скачивания целиком, ffmpeg сам делает seek по сети), кадрирует
под вертикальный формат YouTube Shorts (1080x1920, crop-to-fill — как в
примере-нарезке, без чёрных полос), и заменяет звук на трек из
trending_music.py (или оставляет оригинальный звук исходника, если треков нет).

Работает через прямой вызов ffmpeg (subprocess), а не moviepy — здесь это
проще и эффективнее: один вызов ffmpeg делает seek+crop+audio-mux+fade за
один проход, без прогона всего видео через Python.

Трейлеры игр часто уже содержат ВШИТЫЕ чёрные полосы (кинематографичный
широкий кадр внутри обычного 16:9-контейнера) — если крутить crop-to-fill
поверх них не глядя, полосы просто съедут в вертикальный кадр вместе с
картинкой. Поэтому перед основным кропом гоняем ffmpeg-фильтр cropdetect по
паре секунд ролика и, если найдены реальные чёрные поля, сначала вырезаем
именно их (см. _detect_letterbox_crop), и только потом кадрируем под 9:16.
"""

import json
import re
import subprocess

WIDTH, HEIGHT = 1080, 1920
FADE_SEC = 0.35


def _probe_dimensions(video_url: str) -> tuple[int, int] | None:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", video_url],
            capture_output=True, text=True, timeout=30, check=True,
        )
        w, h = proc.stdout.strip().split(",")
        return int(w), int(h)
    except Exception:
        return None


def _detect_letterbox_crop(video_url: str, probe_start: float, probe_seconds: float = 6.0) -> str:
    """Гоняет cropdetect по нескольким секундам ролика (начиная с
    probe_start, чтобы не попасть на чёрный fade-in в самом начале) и, если
    находит вшитые чёрные поля, возвращает готовый фрагмент ffmpeg-фильтра
    вида "crop=W:H:X:Y,", который их обрезает. Если полос нет (или что-то
    пошло не так при анализе) — возвращает пустую строку, ничего не ломая."""
    dims = _probe_dimensions(video_url)
    if not dims:
        return ""
    in_w, in_h = dims

    try:
        proc = subprocess.run(
            ["ffmpeg", "-ss", str(probe_start), "-i", video_url,
             "-vf", "cropdetect=24:2:0", "-t", str(probe_seconds), "-f", "null", "-"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return ""

    matches = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", proc.stderr)
    if not matches:
        return ""

    cw, ch, cx, cy = map(int, matches[-1])  # последнее значение — самое стабильное
    # обрезаем, только если полосы реально заметные (не шум/погрешность на 1-2px)
    if cw < in_w * 0.98 or ch < in_h * 0.98:
        return f"crop={cw}:{ch}:{cx}:{cy},"
    return ""


def _validate_clip(path: str, expected_duration: float) -> None:
    """Проверяет, что собранный файл — реально валидное, проигрываемое видео,
    а не побитый огрызок (например, из-за протухшего токена в ссылке на
    трейлер, оборвавшего чтение сети посреди сборки). YouTube в таких
    случаях молча принимает загрузку, а потом падает с "Ошибка обработки"
    уже после публикации — дешевле поймать это тут, до аплоада."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-show_entries", "stream=codec_type", "-of", "json", path],
            capture_output=True, text=True, timeout=30, check=True,
        )
        info = json.loads(proc.stdout)
    except Exception as e:
        raise RuntimeError(f"Не удалось проверить собранный клип {path}: {e}") from e

    has_video = any(s.get("codec_type") == "video" for s in info.get("streams", []))
    duration = float((info.get("format") or {}).get("duration") or 0)

    if not has_video:
        raise RuntimeError(f"Собранный клип {path} без видеодорожки — похоже на повреждённый файл")
    if duration < expected_duration * 0.8:
        raise RuntimeError(
            f"Собранный клип {path} короче ожидаемого ({duration:.1f}s из {expected_duration:.1f}s) "
            "— похоже на обрыв чтения источника (протухшая ссылка/сетевая ошибка)"
        )


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

    letterbox_crop = _detect_letterbox_crop(video_url, probe_start=start)

    # crop-to-fill под 9:16: сначала масштабируем так, чтобы кадр ПОЛНОСТЬЮ
    # накрывал 1080x1920 (по большей стороне), затем обрезаем лишнее по центру —
    # без чёрных полос, независимо от исходного соотношения сторон видео.
    video_filter = (
        f"{letterbox_crop}"
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
    _validate_clip(out_path, duration)
    return out_path


if __name__ == "__main__":
    from highlight_finder import find_highlight
    from game_trailer_source import pick_trailer
    from trending_music import pick_track

    trailer = pick_trailer()
    print(f"Трейлер: {trailer['title']} — {trailer['trailer_name']} ({trailer['duration']:.0f}s)")
    s, e = find_highlight(trailer["url"], trailer["duration"])
    print(f"Момент: {s:.1f}s - {e:.1f}s")
    track = pick_track()
    path = build_edit_clip(trailer["url"], s, e, track, out_path="edit_output.mp4")
    print("Готово:", path)
