"""
Процедурная генерация спрайтов персонажа "Фактика" — неонового чёрно-красного
призрака — без каких-либо внешних ассетов, шрифтов изображений или лицензий:
всё рисуется с нуля средствами Pillow (ImageDraw/ImageFilter). Никакого
стороннего арта (OpenGameArt/itch.io и т.п.) не использовалось.

Лицензия результата: полностью авторский код и результат его исполнения,
можно использовать без ограничений (эквивалент CC0) в рамках этого проекта.

Запуск: python3 generate_ghost_sprites.py
Результат: 3 кадра character_frames/frame_1.png .. frame_3.png — цикл
"разговора" (рот закрыт -> приоткрыт -> открыт) с лёгкой пульсацией
неонового свечения контура между кадрами, чтобы анимация не выглядела
статичной даже на длинных паузах.
"""

import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageChops

OUT_DIR = "character_frames"

# Холст с большими полями по краям — там "живёт" размытое неоновое свечение,
# которое иначе обрезалось бы по границе кадра.
CANVAS_W, CANVAS_H = 1000, 1300

BODY_LEFT, BODY_RIGHT = 190, 810   # ширина тела: 620px
BODY_TOP = 160                      # верх купола головы
WAVE_BASE = 980                     # линия, от которой свисают "щупальца"-волны
WAVE_COUNT = 5
WAVE_DEPTH = 130                    # на сколько волны опускаются ниже WAVE_BASE

NEON_RED = (255, 24, 64)
NEON_RED_SOFT = (255, 70, 90)
BODY_FILL = (8, 6, 12, 195)         # чёрное полупрозрачное тело с лёгким фиолетовым оттенком
EYE_GLOW = (255, 40, 60)


def _ghost_silhouette_mask() -> Image.Image:
    """Маска силуэта: купол головы + прямые бока + волнистый "хвост" снизу,
    как у классического мультяшного привидения."""
    mask = Image.new("L", (CANVAS_W, CANVAS_H), 0)
    draw = ImageDraw.Draw(mask)

    body_w = BODY_RIGHT - BODY_LEFT
    head_r = body_w / 2

    # купол головы (верхняя половина эллипса)
    draw.pieslice(
        [BODY_LEFT, BODY_TOP, BODY_RIGHT, BODY_TOP + 2 * head_r],
        180, 360, fill=255,
    )
    # прямой торс от низа купола до линии волн
    draw.rectangle([BODY_LEFT, BODY_TOP + head_r, BODY_RIGHT, WAVE_BASE], fill=255)

    # волнистый низ: чередующиеся выпуклости-полукруги
    wave_w = body_w / WAVE_COUNT
    for i in range(WAVE_COUNT):
        cx = BODY_LEFT + wave_w * (i + 0.5)
        r = wave_w / 2 + 6  # небольшой нахлёст, чтобы не было зазоров между волнами
        draw.ellipse(
            [cx - r, WAVE_BASE - r * 0.55, cx + r, WAVE_BASE - r * 0.55 + WAVE_DEPTH],
            fill=255,
        )
    # выравниваем верх волн ровной линией, чтобы не было щели с торсом
    draw.rectangle([BODY_LEFT, WAVE_BASE - 40, BODY_RIGHT, WAVE_BASE + 5], fill=255)

    return mask


def _neon_outline(mask: Image.Image, glow_strength: float) -> Image.Image:
    """Светящийся контур: кольцо на границе силуэта, размытое в несколько
    проходов для эффекта неоновой трубки."""
    dilated = mask.filter(ImageFilter.MaxFilter(9))
    ring = ImageChops.subtract(dilated, mask)

    outline = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    colored_ring = Image.new("RGBA", mask.size, NEON_RED + (255,))
    outline = Image.composite(colored_ring, outline, ring)

    glow = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    for radius, alpha_mult in ((28, 0.35), (14, 0.55), (6, 0.85)):
        layer = outline.filter(ImageFilter.GaussianBlur(radius))
        r, g, b, a = layer.split()
        a = a.point(lambda p, m=alpha_mult * glow_strength: min(255, int(p * m)))
        layer = Image.merge("RGBA", (r, g, b, a))
        glow = Image.alpha_composite(glow, layer)

    # чёткая тонкая линия поверх размытого свечения
    crisp = outline.filter(ImageFilter.GaussianBlur(1.2))
    return Image.alpha_composite(glow, crisp)


def _ambient_glow(mask: Image.Image, glow_strength: float) -> Image.Image:
    """Мягкое рассеянное свечение всего силуэта позади персонажа (как будто
    призрак подсвечивает пространство вокруг себя)."""
    colored = Image.new("RGBA", mask.size, NEON_RED_SOFT + (255,))
    base = Image.composite(colored, Image.new("RGBA", mask.size, (0, 0, 0, 0)), mask)
    blurred = base.filter(ImageFilter.GaussianBlur(45))
    r, g, b, a = blurred.split()
    a = a.point(lambda p: min(255, int(p * 0.5 * glow_strength)))
    return Image.merge("RGBA", (r, g, b, a))


def _draw_eyes(img: Image.Image, cy: int):
    draw = ImageDraw.Draw(img)
    eye_w, eye_h = 70, 95
    eye_y = cy
    for cx in (BODY_LEFT + 190, BODY_RIGHT - 190):
        glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer)
        gd.ellipse([cx - eye_w, eye_y - eye_h, cx + eye_w, eye_y + eye_h],
                   fill=EYE_GLOW + (255,))
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(22))
        img.alpha_composite(glow_layer)

        draw.ellipse(
            [cx - eye_w / 2, eye_y - eye_h / 2, cx + eye_w / 2, eye_y + eye_h / 2],
            fill=EYE_GLOW + (255,),
        )
        # маленький яркий блик, чтобы глаза не выглядели плоскими
        hl = 12
        draw.ellipse(
            [cx - eye_w / 4 - hl, eye_y - eye_h / 4 - hl, cx - eye_w / 4 + hl, eye_y - eye_h / 4 + hl],
            fill=(255, 220, 220, 230),
        )


def _draw_mouth(img: Image.Image, cy: int, openness: float):
    """openness: 0 = закрыт (тонкая линия), 1 = широко открыт ("о")."""
    draw = ImageDraw.Draw(img)
    w = 90
    h = 14 + openness * 90
    cx = (BODY_LEFT + BODY_RIGHT) / 2

    glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gd.ellipse([cx - w - 10, cy - h / 2 - 10, cx + w + 10, cy + h / 2 + 10],
               fill=NEON_RED + (255,))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(14))
    img.alpha_composite(glow_layer)

    draw.ellipse([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
                 fill=(30, 4, 10, 235), outline=NEON_RED + (255,), width=4)


def render_frame(mouth_openness: float, glow_strength: float) -> Image.Image:
    mask = _ghost_silhouette_mask()

    frame = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    frame = Image.alpha_composite(frame, _ambient_glow(mask, glow_strength))
    frame = Image.alpha_composite(frame, _neon_outline(mask, glow_strength))

    body = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    body.paste(Image.new("RGBA", (CANVAS_W, CANVAS_H), BODY_FILL), (0, 0), mask)
    frame = Image.alpha_composite(frame, body)

    head_center_y = int(BODY_TOP + (BODY_RIGHT - BODY_LEFT) / 2 * 0.85)
    _draw_eyes(frame, head_center_y)
    _draw_mouth(frame, head_center_y + 150, mouth_openness)

    # Обрезаем по ФИКСИРОВАННОЙ рамке вокруг силуэта (не по фактическому
    # содержимому кадра) — рамка не зависит от открытости рта, поэтому все
    # кадры цикла получаются строго одного размера и персонаж не "дёргается"
    # при смене кадров в build_video.py.
    silhouette_bbox = mask.getbbox()
    pad = 70  # запас под размытое неоновое свечение контура
    x0 = max(silhouette_bbox[0] - pad, 0)
    y0 = max(silhouette_bbox[1] - pad, 0)
    x1 = min(silhouette_bbox[2] + pad, CANVAS_W)
    y1 = min(silhouette_bbox[3] + pad, CANVAS_H)
    frame = frame.crop((x0, y0, x1, y1))

    return frame


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    # (имя_файла, открытость рта, сила свечения) — цикл "говорения" из 3 кадров
    specs = [
        ("frame_1.png", 0.05, 0.85),   # рот закрыт, свечение чуть приглушено
        ("frame_2.png", 0.45, 1.05),   # рот приоткрыт, свечение ярче
        ("frame_3.png", 1.0, 1.2),     # рот широко открыт, максимальное свечение
    ]
    for name, openness, glow in specs:
        img = render_frame(openness, glow)
        img.save(os.path.join(OUT_DIR, name))
        print(f"{name}: {img.size}")


if __name__ == "__main__":
    main()
