"""The custom terms dialog: add and remove entries in the user's term list
without opening hebrew_terms.txt in a text editor.

Every add and remove is written to the file immediately (core.term_store),
so there is no Save/Cancel pair to get wrong and nothing to lose by closing
the window. The file stays the source of truth - the list is re-read after
each change - so a term someone added by hand appears here too.

Failures are shown inline, never as a QMessageBox: this app keeps modal
popups for unhandled crashes only (see gui/crash_dialog.py).
"""

import logging
from typing import cast

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import config
from core import term_store
from gui import theme
from gui.i18n import is_rtl, layout_direction, t
from gui.icons import ICONS, svg_to_pixmap
from gui.theme import COLORS, Fonts, Spacing
from gui.widgets import make_label

logger = logging.getLogger(__name__)

_ROW_NAME = "termRow"


def text_alignment() -> Qt.Alignment:
    """Absolute alignment per UI language.

    A QLabel or QLineEdit otherwise aligns by its own text's direction, and
    terms are usually Hebrew - so in the English UI a plain AlignLeft is
    mirrored and the list lands on the right. AlignAbsolute pins it.
    """
    side = Qt.AlignmentFlag.AlignRight if is_rtl() else Qt.AlignmentFlag.AlignLeft
    # cast for the same reason as ModelSelectStep._card_text_alignment: the
    # PyQt5 stubs widen an OR of two flags to int.
    return cast(Qt.Alignment, side | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter)


def read_term_list(path: str | None = None) -> list[str]:
    """The terms on disk, for the model step's terms panel.

    Empty when the file cannot be read: the panel must still render, and the
    dialog reports the actual problem when it is opened.
    """
    try:
        return list(term_store.read_terms(path or config.resolve_terms_path()))
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(f"Could not read the term list: {e}")
        return []


class TermsDialog(QDialog):
    """Edit the term list in place, one term at a time."""

    def __init__(self, parent: QWidget | None = None, path: str | None = None) -> None:
        super().__init__(parent)
        self.path = path or config.resolve_terms_path()

        self.setWindowTitle(t("terms_title"))
        # Drop the title-bar "?" Qt gives every QDialog on Windows: it enters
        # What's This mode, and nothing here has What's This text.
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setLayoutDirection(layout_direction())
        self.setModal(True)
        self.setFixedSize(440, 460)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_secondary']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.LG)
        layout.setSpacing(Spacing.SM)

        title = make_label(t("terms_title"), font=Fonts.SUBTITLE_BOLD, color="text_primary")
        title.setAlignment(text_alignment())
        layout.addWidget(title)

        hint = make_label(t("terms_hint"), font=Fonts.CAPTION, color="text_secondary")
        hint.setWordWrap(True)
        hint.setAlignment(text_alignment())
        layout.addWidget(hint)
        layout.addSpacing(Spacing.XS)

        layout.addLayout(self._build_entry_row())

        self.message = make_label("", font=Fonts.CAPTION, color="error")
        self.message.setWordWrap(True)
        self.message.setAlignment(text_alignment())
        self.message.setVisible(False)
        layout.addWidget(self.message)

        layout.addSpacing(Spacing.XS)
        self.count_label = make_label("", font=Fonts.CAPTION_BOLD, color="text_tertiary")
        self.count_label.setAlignment(text_alignment())
        layout.addWidget(self.count_label)

        self.list_area = QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.Shape.NoFrame)
        self.list_area.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        layout.addWidget(self.list_area, 1)

        layout.addSpacing(Spacing.SM)
        footer = QHBoxLayout()
        footer.addStretch()
        self.done_button = QPushButton(t("terms_done"))
        self.done_button.setStyleSheet(theme.button_secondary_qss())
        self.done_button.setCursor(Qt.CursorShape.PointingHandCursor)
        # QDialog makes its buttons autoDefault, so Enter in the field would
        # also "click" Done and close the dialog mid-entry. Enter belongs to
        # the field alone.
        self.done_button.setAutoDefault(False)
        self.done_button.clicked.connect(self.accept)
        footer.addWidget(self.done_button)
        layout.addLayout(footer)

        self._rebuild()
        self.field.setFocus()

    def _build_entry_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(Spacing.SM)

        self.field = QLineEdit()
        self.field.setFont(Fonts.BODY)
        self.field.setPlaceholderText(t("terms_placeholder"))
        self.field.setStyleSheet(theme.line_edit_qss())
        self.field.setAlignment(text_alignment())
        self.field.setAccessibleName(t("terms_placeholder"))
        self.field.returnPressed.connect(self.add_current)
        row.addWidget(self.field, 1)

        # The primary action, beside the field it acts on - adding is what
        # the dialog is for. Disabled while there is nothing to add.
        self.add_button = QPushButton(t("terms_add"))
        self.add_button.setStyleSheet(theme.button_primary_qss())
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.setAutoDefault(False)
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self.add_current)
        self.field.textChanged.connect(lambda text: self.add_button.setEnabled(bool(text.strip())))
        row.addWidget(self.add_button)
        return row

    def terms(self) -> list[str]:
        try:
            return term_store.read_terms(self.path)
        except (OSError, UnicodeDecodeError) as e:
            self._show_message(t("terms_save_failed", error=e))
            return []

    def _save_failed(self, error: OSError) -> None:
        logger.warning(f"Could not save term list {self.path}: {error}")
        self._show_message(t("terms_save_failed", error=error))

    def add_current(self) -> None:
        """Add what the field holds, keeping it on any failure so nothing typed is lost."""
        text = self.field.text()
        if not text.strip():
            return
        try:
            added = term_store.add_term(self.path, text)
        except ValueError:
            self._show_message(t("terms_comment"))
            return
        except OSError as e:
            self._save_failed(e)
            return

        if not added:
            self._show_message(t("terms_duplicate", term=text.strip()))
            self.field.selectAll()
            return

        logger.info(f"Added a term to {self.path}")
        self.message.setVisible(False)
        self.field.clear()
        self.field.setFocus()
        self._rebuild()

    def remove(self, term: str) -> None:
        try:
            term_store.remove_term(self.path, term)
        except OSError as e:
            self._save_failed(e)
            return
        self.message.setVisible(False)
        self._rebuild()
        self.field.setFocus()

    def _show_message(self, text: str) -> None:
        self.message.setText(text)
        self.message.setVisible(True)

    def _rebuild(self) -> None:
        terms = self.terms()
        count = len(terms)
        self.count_label.setText(t("terms_count_one") if count == 1 else t("terms_count", n=count))
        self.count_label.setVisible(count > 0)

        holder = QWidget()
        rows = QVBoxLayout(holder)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(Spacing.XS)

        if not terms:
            empty = make_label(t("terms_empty"), font=Fonts.BODY, color="text_tertiary")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            rows.addStretch()
            rows.addWidget(empty)
            rows.addStretch(2)
        else:
            # Newest first: the term just added is the one being looked for.
            for term in reversed(terms):
                rows.addWidget(self._row(term))
            rows.addStretch()
        self.list_area.setWidget(holder)

    def _row(self, term: str) -> QFrame:
        row = QFrame()
        row.setObjectName(_ROW_NAME)
        row.setStyleSheet(theme.term_row_qss(_ROW_NAME))
        layout = QHBoxLayout(row)
        layout.setContentsMargins(Spacing.MD, 6, Spacing.XS, 6)

        label: QLabel = make_label(term, font=Fonts.BODY, color="text_primary")
        label.setAlignment(text_alignment())
        layout.addWidget(label, 1)

        # An SVG icon from the app's own set, as on the step 1 file list - a
        # typed glyph renders in whatever font Qt falls back to.
        remove = QPushButton()
        remove.setIcon(
            QIcon(
                svg_to_pixmap(ICONS["x"], 14, COLORS["text_tertiary"], dpr=self.devicePixelRatioF())
            )
        )
        remove.setFixedSize(24, 24)
        remove.setAutoDefault(False)
        remove.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setToolTip(t("terms_remove", term=term))
        remove.setAccessibleName(t("terms_remove", term=term))
        remove.clicked.connect(lambda _checked=False, term=term: self.remove(term))
        layout.addWidget(remove)
        return row
