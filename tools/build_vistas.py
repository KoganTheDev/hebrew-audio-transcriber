"""
One-time build step: turn the raw Unsplash JPEGs in vistas_source/ into the
small WebP backdrops shipped inside speech_to_text/core/assets/vistas/.

This is a dev tool, not runtime code. It is the only place in the whole
project allowed to import Pillow - core/formatting.py, which embeds the
finished .webp bytes at render time, stays stdlib-only (see the "no PyQt5,
no Pillow at runtime" note in that file). Run it by hand whenever
vistas_source/ changes:

    py -3.11 tools/build_vistas.py

Re-runnable and idempotent: source files are sorted by name so vista-NN always
maps to the same photo, and re-running just overwrites the same 32 outputs
with the same bytes (modulo whatever Pillow/libwebp version produced them).
"""

import sys
from pathlib import Path

from PIL import Image

_REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = _REPO_ROOT / "vistas_source"
OUTPUT_DIR = _REPO_ROOT / "speech_to_text" / "core" / "assets" / "vistas"

SOURCE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# The document is read on a phone as often as on a laptop, and a 1600px-long
# edge is already more detail than a CSS "background-size: cover" layer will
# ever show - anything bigger is bytes nobody's screen can use.
MAX_EDGE = 1600

# Every transcript pays for exactly one of these on load, so it has to stay
# small. 80KB is small enough not to be felt on a slow connection while still
# leaving enough bits for a photo (versus a flat-colour placeholder) to look
# like a photo.
MAX_BYTES = 80 * 1024

# Quality floor: below ~35 WebP starts showing visible blocking on photographic
# content, at which point a smaller image would look better than a small file.
# Dimensions get shrunk further instead once quality alone can't hit budget.
MIN_QUALITY = 35


def _downscale(image: Image.Image) -> Image.Image:
    """Shrink so the longest edge is at most MAX_EDGE. Never upscale."""
    width, height = image.size
    longest = max(width, height)
    if longest <= MAX_EDGE:
        return image
    scale = MAX_EDGE / longest
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _encode_under_budget(image: Image.Image, dest: Path) -> int:
    """
    Write `image` as WebP to `dest`, shrinking quality then dimensions until
    the file is <= MAX_BYTES. Returns the final file size, or -1 if even the
    smallest attempt didn't fit (the caller reports that; it still writes the
    best attempt rather than leaving no output).
    """
    current = image
    quality = 80

    while True:
        while quality >= MIN_QUALITY:
            current.save(dest, format="WEBP", quality=quality, method=6)
            size = dest.stat().st_size
            if size <= MAX_BYTES:
                return size
            quality -= 5

        # Quality floor reached and still too big: shrink dimensions by 15%
        # and try the whole quality ladder again from the top.
        width, height = current.size
        if width <= 200 or height <= 200:
            # Already tiny - stop rather than shrink an image into nothing.
            return -dest.stat().st_size
        current = current.resize(
            (max(1, round(width * 0.85)), max(1, round(height * 0.85))), Image.Resampling.LANCZOS
        )
        quality = 80


def build() -> int:
    """Process every source image. Returns the count that could not fit budget."""
    if not SOURCE_DIR.is_dir():
        print(f"no source directory: {SOURCE_DIR}", file=sys.stderr)
        return 1

    sources = sorted(
        p for p in SOURCE_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SOURCE_EXTS
    )
    if not sources:
        print(f"no images found in {SOURCE_DIR}", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    over_budget = []
    for index, source in enumerate(sources, start=1):
        dest = OUTPUT_DIR / f"vista-{index:02d}.webp"
        with Image.open(source) as raw:
            # Flatten to RGB: some Unsplash JPEGs carry a CMYK or palette
            # profile, and WebP encoding assumes RGB(A).
            image = raw.convert("RGB")
            image = _downscale(image)
            size = _encode_under_budget(image, dest)

        status = "ok" if size >= 0 else "OVER BUDGET"
        print(f"{source.name} -> {dest.name}  {abs(size) / 1024:.1f}KB  {status}")
        if size < 0:
            over_budget.append(dest.name)

    # Idempotent means re-running with fewer sources doesn't leave orphaned
    # vista-NN.webp files behind for a photo that no longer exists.
    for stale in OUTPUT_DIR.glob("vista-*.webp"):
        try:
            stale_index = int(stale.stem.split("-")[1])
        except (IndexError, ValueError):
            continue
        if stale_index > len(sources):
            stale.unlink()
            print(f"removed stale {stale.name}")

    print(f"\n{len(sources)} processed, {len(over_budget)} over the {MAX_BYTES // 1024}KB budget.")
    if over_budget:
        print("over budget: " + ", ".join(over_budget))

    return 0


if __name__ == "__main__":
    raise SystemExit(build())
