"""Application metadata, window geometry and dependency-install settings."""

import os

# ============================================================================
# Application Configuration
# ============================================================================

APP_NAME = "Hebrew Audio Transcriber"
APP_VERSION = "2.0.0"
APP_ID = "speechtotext.transcriber.2"  # Windows AppUserModelID, for correct taskbar icon grouping
WINDOW_WIDTH = 950
WINDOW_HEIGHT = 800

# dirname twice: this module sits in speech_to_text/config/, so its own
# directory's parent is the package root that assets/ lives beside.
ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.ico"
)

# ============================================================================
# Dependencies
# ============================================================================

REQUIRED_PACKAGES = {
    "PyQt5": "PyQt5",
    "tqdm": "tqdm",
}

# ============================================================================
# GUI Configuration - Window Dimensions
# ============================================================================
# Window sizing optimized for 1080p displays. Centered on screen.
# Minimal size ensures content is not cramped on smaller displays.
#
# The window used to be setFixedSize'd at 650x600, with the maximize hint
# stripped - no resize logic anywhere had to cope with a size other than
# exactly this one. That hid a real shortfall rather than avoiding it, and
# the window became resizable with a real floor to fix it (see
# MainWindow.__init__). Re-measured with minsize.py after stepper.py's
# badge strip gained Spacing.SM (8px) of top/bottom padding (see that
# module's __init__ comment - the strip used to butt directly against the
# header's accent-colored bottom border with zero px of air), the chrome
# (header 50 + step indicator 36 + nav bar 79) is 165px, and the worst
# step - transcription, once show_result() has populated the completion
# panel - needs 448px on its own. 165 + 448 = 613px. Step 1 fares better
# (418 + 165 = 583px). Both numbers were measured with the app stylesheet
# and high-DPI scaling actually applied (see gui/main_window.py's
# configure_application and its module-level AA_EnableHighDpiScaling /
# AA_UseHighDpiPixmaps calls) - a bare, unstyled QApplication resolves
# different font metrics, so a number measured against one does not carry
# over to the other. Anyone re-measuring this after a further font/spacing
# change should do the same: run minsize.py through the real entry point's
# setup (configure_application), not a hand-rolled QApplication.
#
# GUI_WINDOW_MIN_HEIGHT is the floor this drives: it has to sit at or above
# 613px or the same clipping comes back the moment the window is resized
# down to it. 656 gives 43px of deliberate margin above that measured
# minimum rather than pinning the floor exactly on it, so the completion
# panel doesn't start touching the window edge the instant someone drags to
# the smallest allowed size. It was raised from 640 (which carried its own
# margin above the pre-padding 628px floor measured before this stepper
# fix) specifically to keep covering the new 16px the badge strip's padding
# added - a floor computed before that padding landed would have been a
# stale, and now wrong, promise.
#
# GUI_WINDOW_HEIGHT (the default, initial size) stays clearly above the
# minimum rather than sitting on it, for the same reason step 3's own
# comments give for widening its margins: a size that exactly matches the
# content floor reads as cramped even when nothing is technically clipped.
# 720 leaves the completion panel - the tallest state of any step - about
# 107px of breathing room by default, while remaining well short of forcing
# a scroll on a 1080p display.
#
# GUI_WINDOW_MIN_WIDTH is unchanged at 600: the model card caption (the
# tightest element width-wise) has 57px of slack at 600px and only starts
# clipping below roughly 545px, so 600 was already a safe floor and this
# step's overflow was purely a height problem.

GUI_WINDOW_WIDTH = 650  # Main window default width (px)
GUI_WINDOW_HEIGHT = 720  # Main window default height (px) - see note above
GUI_WINDOW_MIN_WIDTH = 600  # Minimum resizable width (px)
GUI_WINDOW_MIN_HEIGHT = 656  # Minimum resizable height (px) - measured content floor is 613px

# ============================================================================
# GUI Configuration - Drag-Drop Zone
# ============================================================================
# File selection zone styling and spacing

GUI_DROP_ZONE_HEIGHT = 170  # Drop zone MINIMUM height (px). Its own content (icon +
# three lines) floors at ~172px, so a larger value here is a
# floor the layout cannot compress below, not a target it can
# give back - which is what overflowed the fixed window. The
# zone grows well past this via its layout stretch factor
# whenever the step has slack; see file_select.py.
GUI_DROP_ZONE_PADDING = 20  # Internal padding in drop zone (px) - reduced to fit the shorter zone
GUI_DROP_ZONE_SPACING = (
    10  # Space between elements inside drop zone (px) - reduced to fit the shorter zone
)

# ============================================================================
# Dependency Installation Configuration
# ============================================================================
# Timeout for package installation to prevent hanging

INSTALL_TIMEOUT_SECONDS = 120  # 2 minutes per package installation
