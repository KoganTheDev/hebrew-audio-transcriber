"""Application metadata, window geometry and dependency-install settings."""

import os

APP_NAME = "Hebrew Audio Transcriber"
APP_VERSION = "2.0.0"
APP_ID = "speechtotext.transcriber.2"  # Windows AppUserModelID, for taskbar icon grouping

# config/ sits inside the package root that assets/ lives beside.
ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.ico"
)

# Every runtime import the app cannot start without, as {import name: pip name}.
# It must cover all of them: a partial list passes the startup check and then
# dies on the first missing import with a bare exit.
REQUIRED_PACKAGES = {
    "PyQt5": "PyQt5",
    "faster_whisper": "faster-whisper",
    "sherpa_onnx": "sherpa-onnx",
    "av": "av",
    "psutil": "psutil",
    "tqdm": "tqdm",
}

# Height floor, measured with the real app stylesheet and high-DPI scaling
# (configure_application) - a bare QApplication resolves different font
# metrics. Chrome (header 50 + step strip 40 + nav bar 79) is 169px; the
# tallest page, step 3 with its result panel, needs 448px: 617px in all.
# The minimum keeps 39px above that, and any change to the chrome or step 3
# means re-measuring. The default height leaves the result panel ~100px of
# room without forcing a scroll at 1080p. Width: the model card caption, the
# tightest element, only clips below ~545px.
GUI_WINDOW_WIDTH = 650
GUI_WINDOW_HEIGHT = 720
GUI_WINDOW_MIN_WIDTH = 600
GUI_WINDOW_MIN_HEIGHT = 656

# A floor at the zone's own content height (icon + three lines); anything
# larger is a floor the layout cannot compress. It grows past this by its
# layout stretch whenever the step has room.
GUI_DROP_ZONE_HEIGHT = 170
GUI_DROP_ZONE_PADDING = 20
GUI_DROP_ZONE_SPACING = 10

INSTALL_TIMEOUT_SECONDS = 120  # per package, so a stalled install cannot hang setup
