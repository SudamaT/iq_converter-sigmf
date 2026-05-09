#!/usr/bin/env python3
"""Generate icon.ico — wave + IQ logo for the IQ Converter application."""

import math
from PIL import Image, ImageDraw, ImageFont


def create_icon(path="icon.ico"):
    sizes = [16, 32, 48, 64, 128, 256]
    frames = []

    for sz in sizes:
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # ── Rounded background ──────────────────────────────────────────
        r = sz // 6
        draw.rounded_rectangle(
            [0, 0, sz - 1, sz - 1],
            radius=r,
            fill=(22, 22, 40, 255),
        )

        # ── Sine wave ───────────────────────────────────────────────────
        wave_y = int(sz * 0.60)
        amplitude = int(sz * 0.18)
        period = sz * 0.55
        lw = max(1, sz // 22)

        pts = [
            (px, wave_y + int(amplitude * math.sin(2 * math.pi * px / period)))
            for px in range(sz)
        ]

        # glow pass
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=(80, 160, 255, 60), width=lw * 3)

        # main wave (blue → cyan gradient)
        for i in range(len(pts) - 1):
            t = i / max(len(pts) - 1, 1)
            draw.line(
                [pts[i], pts[i + 1]],
                fill=(int(80 + 57 * t), int(140 + 74 * t), 255, 255),
                width=lw,
            )

        # ── "IQ" text ────────────────────────────────────────────────────
        font_size = max(6, int(sz * 0.40))
        font = None
        for face in [
            "arialbd.ttf", "Arial Bold.ttf",
            "DejaVuSans-Bold.ttf", "FreeSansBold.ttf",
        ]:
            try:
                font = ImageFont.truetype(face, font_size)
                break
            except Exception:
                pass
        if font is None:
            font = ImageFont.load_default()

        text = "IQ"
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            tw, th = draw.textsize(text, font=font)

        tx = (sz - tw) // 2
        ty = int(sz * 0.05)

        # shadow
        draw.text((tx + 1, ty + 1), text, fill=(0, 0, 0, 180), font=font)
        # main text
        draw.text((tx, ty), text, fill=(205, 214, 244, 255), font=font)

        frames.append(img)

    # Pillow ICO: найнадійніший спосіб — зберегти 256x256 і вказати всі розміри.
    # Pillow сам відресайзить кожен шар при збереженні.
    big = frames[-1]  # 256x256
    ico_images = [f.convert("RGBA") for f in frames]
    # Зберігаємо через окремий список об'єктів Image
    ico_images[0].save(
        path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=ico_images[1:],
    )

    # Fallback: якщо файл вийшов занадто маленьким (< 2 KB) — записуємо інакше
    import os
    if os.path.getsize(path) < 2048:
        import io, struct
        entries = []
        png_blobs = []
        for img_obj in ico_images:
            buf = io.BytesIO()
            img_obj.save(buf, format="PNG")
            png_blobs.append(buf.getvalue())

        # ICO header
        header = struct.pack("<HHH", 0, 1, len(sizes))
        offset = 6 + 16 * len(sizes)
        dir_entries = b""
        for i, (blob, sz) in enumerate(zip(png_blobs, sizes)):
            w = h = sz if sz < 256 else 0
            dir_entries += struct.pack("<BBBBHHII",
                w, h, 0, 0, 1, 32, len(blob), offset)
            offset += len(blob)

        with open(path, "wb") as f:
            f.write(header + dir_entries + b"".join(png_blobs))

    print(f"Icon saved: {path}  ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":
    create_icon()
