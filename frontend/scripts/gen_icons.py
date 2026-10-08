"""Generate PWA / home-screen icons from a source PNG."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

SRC = Path(
    r"C:\Users\poilly\.cursor\projects\e-Project-huangguo\assets"
    r"\c__Users_poilly_AppData_Roaming_Cursor_User_workspaceStorage_"
    r"b2ce752ebd5e12c8222b5e540e85d0ca_images_IMG_0017-f0b3801f-88af-4b32-80a6-94f2ad6c2e36.png"
)
OUT = Path(__file__).resolve().parents[1] / "public" / "icons"


def sample_bg(img: Image.Image) -> tuple[int, int, int, int]:
    p = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = p[x, y]
            if a > 240:
                return (r, g, b, 255)
    return (255, 180, 60, 255)


def fill_transparent(img: Image.Image) -> Image.Image:
    bg = sample_bg(img)
    base = Image.new("RGBA", img.size, bg)
    return Image.alpha_composite(base, img.convert("RGBA"))


def make_square(img: Image.Image, size: int, pad_ratio: float = 0.0) -> Image.Image:
    filled = fill_transparent(img)
    edge = filled.getpixel((filled.size[0] // 2, min(4, filled.size[1] - 1)))
    if edge[3] < 200:
        edge = sample_bg(filled)
    canvas = Image.new("RGBA", (size, size), edge)

    content = int(round(size * (1 - pad_ratio * 2))) if pad_ratio > 0 else size
    fw, fh = filled.size
    scale = max(content / fw, content / fh)
    nw, nh = max(1, int(round(fw * scale))), max(1, int(round(fh * scale)))
    resized = filled.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - content) // 2
    top = (nh - content) // 2
    cropped = resized.crop((left, top, left + content, top + content))
    if pad_ratio > 0:
        offset = ((size - content) // 2, (size - content) // 2)
        canvas.paste(cropped, offset)
        return canvas
    return cropped


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    im = Image.open(SRC).convert("RGBA")
    print("source", im.size, im.mode)

    targets = [
        ("icon-192.png", 192, 0.0),
        ("icon-512.png", 512, 0.0),
        ("apple-touch-icon.png", 180, 0.0),
        ("icon-maskable-512.png", 512, 0.10),
    ]
    for name, size, pad in targets:
        out = make_square(im, size, pad_ratio=pad).convert("RGB")
        dest = OUT / name
        out.save(dest, format="PNG", optimize=True)
        print("wrote", dest, out.size, dest.stat().st_size)


if __name__ == "__main__":
    main()
