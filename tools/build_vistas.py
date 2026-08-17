"""
One-time build step: turn the raw Unsplash JPEGs in vistas_source/ into the
WebP backdrops shipped inside speech_to_text/core/assets/vistas/.

Each source produces TWO outputs: a landscape crop (vista-NN.webp, 16:9,
TARGET_W x TARGET_H) for wide viewports and a portrait crop
(vista-NN-portrait.webp, 2:3, PORTRAIT_W x PORTRAIT_H) for narrow ones. See
the "why art direction" comment above PORTRAIT_W for why one crop cannot
serve both.

Sources must be at least TARGET_W wide after the landscape centre crop (so
roughly 2560px on the short edge for a portrait original). Anything smaller
still builds, but gets upscaled by the browser and is listed as UNDERSIZED in
the run's summary - see TARGET_W's comment for why that is the failure mode
this script is shaped to avoid. The portrait crop has its own, much smaller
target and is checked against it separately.

This is a dev tool, not runtime code. It is the only place in the whole
project allowed to import Pillow - core/formatting.py, which embeds the
finished .webp bytes at render time, stays stdlib-only (see the "no PyQt5,
no Pillow at runtime" note in that file). Run it by hand whenever
vistas_source/ changes:

    py -3.11 tools/build_vistas.py

Re-runnable and idempotent: source files are sorted by name so vista-NN always
maps to the same photo, and re-running just overwrites the same outputs
with the same bytes (modulo whatever Pillow/libwebp version produced them).
"""

import sys
from pathlib import Path

from PIL import Image

_REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = _REPO_ROOT / "vistas_source"
OUTPUT_DIR = _REPO_ROOT / "speech_to_text" / "core" / "assets" / "vistas"

SOURCE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# Output geometry. Every backdrop is cropped to 16:9 and rendered at exactly
# this size, because that is the shape .backdrop actually displays: it is
# position:fixed inset:0 with background-size:cover, so the viewport - not the
# photo - decides what is on screen, and anything outside the covering crop is
# discarded by the browser at paint time. Cropping here instead means those
# pixels never ship.
#
# Why 2560x1440 and not the 1600px long edge this used to cap at: the old cap
# was on the LONG edge, but cover on a landscape window is driven by the SHORT
# one, so a portrait source capped at 1600 tall came out ~1070 wide and could
# never fill a 1920 window without being stretched. Every one of the 32
# backdrops was being upscaled (median x1.78, worst x3.45), which is the
# pixelation this replaces.
#
# The target is one image pixel per CSS pixel at the largest common CSS
# viewport, NOT per device pixel. On a DPR 2 or 3 screen the browser paints
# this at 1 image px per CSS px, which is exactly as sharp as a DPR 1 screen
# looks - matching device pixels instead would mean shipping 4K photos for a
# decorative layer. Measured cover SCALE factors at this size: 1080p x0.75,
# 1440p x1.00, tablet portrait x0.82, phone portrait x0.59 - all comfortably
# at or below 1.0, so this size is never upscaled. The two cases still above
# 1.0 are ultrawide (x1.34) and 4K at 100% scaling (x1.50), both rare and
# both mild.
#
# That scale factor is not the whole story on a narrow viewport, though: it
# says how much the image is stretched, not how much of its FRAME survives.
# background-size:cover crops on the axis it isn't scaling to, and on a
# portrait phone that axis is width - so a 16:9 image cover-scaled to a
# 390x844 phone shows only the middle ~26% of the photo's width at full
# height. Nothing is soft or upscaled there, the framing is just destroyed
# (a landscape photo's subject is rarely centred on a 22%-wide vertical
# strip). That is what PORTRAIT_W below exists to fix - see its comment.
TARGET_W, TARGET_H = 2560, 1440

# The portrait art-direction crop. background-size:cover scales an image to
# fill the viewport's SHORT axis then crops the long one, so a 16:9 landscape
# crop on a phone (aspect ~0.46) is scaled to cover the width and shows only
# the middle ~22% of the photo's height-driven crop - see the framing table
# in the task history for measured numbers. Desktop and phone viewports differ
# by more than 2x in aspect ratio, so no single crop serves both; this is a
# second, portrait-oriented crop of the SAME photo, picked at render time by
# a CSS media query (see .backdrop's comment in transcript.css and
# core/formatting.py's <style> emission) rather than a resize of the landscape
# one, so the subject is recomposed for a tall frame instead of just narrowed.
#
# 1280x1920 (2:3), not the same pixel budget as the landscape crop: a portrait
# CSS viewport tops out around 1024px wide (see TARGET_W's DPR reasoning for
# why this is CSS px, not device px), well under desktop's 1920-2560, so
# matching landscape's resolution would ship pixels no portrait viewport can
# ever show.
PORTRAIT_W, PORTRAIT_H = 1280, 1920

# Every transcript embeds one landscape and (when available) one portrait
# backdrop as base64 data URIs, so the HTML grows by about 4/3 of their
# combined size. The old single-backdrop budget was 80KB, chosen for "a slow
# connection" - but a transcript is a local file written to the user's own
# disk, and worker.py re-embeds the same pinned photo once per FILE
# checkpoint, not per second, so the download argument never really applied.
# 600KB of WebP is a ~800KB data URI: irrelevant next to the resolution it
# buys back.
MAX_BYTES = 600 * 1024

# The portrait crop has a fifth of the landscape pixel count (1280x1920 vs
# 2560x1440), so it needs proportionally fewer bytes to hit the same quality -
# a smaller budget here is not a stricter quality bar, it is the same bar
# applied to a smaller image.
PORTRAIT_MAX_BYTES = 400 * 1024

# Quality floor. Raised from 35: at 35 WebP shows visible blocking on
# photographic content, and the old budget drove most of these images down
# to it. Shared by both variants - the floor is about visible blocking, which
# doesn't change with image size.
MIN_QUALITY = 60


def _fit_to_target(image: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    Centre-crop to target_w:target_h's aspect, then scale to that exact size.

    The crop is the same one the browser would perform at paint time (see
    TARGET_W's comment), done here so the discarded pixels never ship. Centre,
    not smart-cropped on subject detection: these are landscapes and textures
    chosen for the edges of a page, and every one of them survives a centre
    crop, so a saliency pass would be machinery earning nothing. Takes the
    target size as a parameter (rather than reading TARGET_W/TARGET_H off the
    module directly) so the same crop-then-scale logic serves both the
    landscape and portrait variants instead of being duplicated per aspect.

    Never upscales. A source smaller than the target keeps its own resolution
    at the right aspect and the caller warns - inventing pixels here would
    produce exactly the soft image this rewrite exists to prevent, just soft at
    build time instead of in the browser.
    """
    width, height = image.size
    target_ratio = target_w / target_h

    if width / height > target_ratio:
        # Wider than target: trim the sides.
        crop_w, crop_h = round(height * target_ratio), height
    else:
        # Taller than target: trim top and bottom.
        crop_w, crop_h = width, round(width / target_ratio)

    left, top = (width - crop_w) // 2, (height - crop_h) // 2
    cropped = image.crop((left, top, left + crop_w, top + crop_h))

    if crop_w <= target_w:
        return cropped
    return cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)


def _encode_under_budget(image: Image.Image, dest: Path, max_bytes: int) -> tuple:
    """
    Write `image` as WebP to `dest`, walking quality down until the file is
    <= max_bytes. Returns (size, quality), with size negated if even
    MIN_QUALITY didn't fit (the caller reports that; the file is still written
    rather than left missing). The quality comes back so the build log can show
    how hard the budget is squeezing each photo - a run where most images sit
    near MIN_QUALITY means the budget, not the encoder, is setting the
    picture quality. max_bytes is a parameter, not a module constant, because
    the portrait variant budgets fewer bytes for its smaller pixel count (see
    PORTRAIT_MAX_BYTES).

    Resolution is never traded for bytes. The previous version, on reaching
    the quality floor, shrank the image 15% and restarted the quality ladder -
    which is how vista-13 and vista-26 ended up 557x836 and were then blown
    back up ~3.4x in the browser. Dimensions are now fixed by _fit_to_target
    and quality is the only dial, so a photo that cannot hit budget comes out
    over budget and visible in the build log instead of silently soft.
    """
    quality = 85

    while quality >= MIN_QUALITY:
        image.save(dest, format="WEBP", quality=quality, method=6)
        size = dest.stat().st_size
        if size <= max_bytes:
            return size, quality
        quality -= 5

    return -dest.stat().st_size, MIN_QUALITY


def _process_variant(
    source: Path, raw: Image.Image, dest: Path,
    target_w: int, target_h: int, max_bytes: int,
    over_budget: list, undersized: list,
) -> None:
    """
    Crop, encode and log one output file for one source image.

    Shared by the landscape and portrait passes in build() - the two variants
    differ only in their target size and byte budget, not in the crop/encode/
    report shape, so that shape lives once here.
    """
    image = _fit_to_target(raw, target_w, target_h)
    size, quality = _encode_under_budget(image, dest, max_bytes)

    width, height = image.size
    notes = []
    if size < 0:
        notes.append("OVER BUDGET")
        over_budget.append(dest.name)
    # A source too small to reach the target is the one remaining way a
    # backdrop can still be upscaled in the browser, so it is called out by
    # name rather than left to be noticed on screen later.
    if width < target_w:
        notes.append(f"UNDERSIZED (browser will upscale x{target_w / width:.2f})")
        undersized.append(dest.name)
    status = ", ".join(notes) if notes else "ok"
    print(
        f"{source.name} -> {dest.name}  {width}x{height}  "
        f"q{quality}  {abs(size) / 1024:.1f}KB  {status}"
    )


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
    undersized = []
    portrait_over_budget = []
    portrait_undersized = []
    for index, source in enumerate(sources, start=1):
        with Image.open(source) as raw:
            # Flatten to RGB: some Unsplash JPEGs carry a CMYK or palette
            # profile, and WebP encoding assumes RGB(A).
            image = raw.convert("RGB")
            _process_variant(
                source, image, OUTPUT_DIR / f"vista-{index:02d}.webp",
                TARGET_W, TARGET_H, MAX_BYTES, over_budget, undersized,
            )
            _process_variant(
                source, image, OUTPUT_DIR / f"vista-{index:02d}-portrait.webp",
                PORTRAIT_W, PORTRAIT_H, PORTRAIT_MAX_BYTES,
                portrait_over_budget, portrait_undersized,
            )

    # Idempotent means re-running with fewer sources doesn't leave orphaned
    # vista-NN.webp / vista-NN-portrait.webp files behind for a photo that no
    # longer exists. stem.split("-")[1] is the NN component either way
    # ("vista-05" or "vista-05-portrait" both split to ["vista", "05", ...]).
    for stale in OUTPUT_DIR.glob("vista-*.webp"):
        try:
            stale_index = int(stale.stem.split("-")[1])
        except (IndexError, ValueError):
            continue
        if stale_index > len(sources):
            stale.unlink()
            print(f"removed stale {stale.name}")

    print(
        f"\n{len(sources)} processed at {TARGET_W}x{TARGET_H} (landscape) and "
        f"{PORTRAIT_W}x{PORTRAIT_H} (portrait); landscape "
        f"{len(over_budget)} over the {MAX_BYTES // 1024}KB budget, "
        f"{len(undersized)} undersized; portrait "
        f"{len(portrait_over_budget)} over the {PORTRAIT_MAX_BYTES // 1024}KB "
        f"budget, {len(portrait_undersized)} undersized."
    )
    if over_budget:
        print("landscape over budget: " + ", ".join(over_budget))
    if undersized:
        print(
            "landscape undersized (source smaller than the target - replace "
            "these with a larger original): " + ", ".join(undersized)
        )
    if portrait_over_budget:
        print("portrait over budget: " + ", ".join(portrait_over_budget))
    if portrait_undersized:
        print(
            "portrait undersized (source smaller than the target - replace "
            "these with a larger original): " + ", ".join(portrait_undersized)
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(build())
