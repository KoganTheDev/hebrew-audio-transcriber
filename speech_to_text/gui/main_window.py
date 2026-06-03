"""
Lightweight Tool GUI for Speech-to-Text Transcription
3-step flow: Select File → Choose Model → Transcribe
"""

import os
import sys
import logging
from enum import Enum
from typing import Optional, Tuple
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QRadioButton, QButtonGroup,
    QFileDialog, QProgressBar, QMessageBox,
    QFrame, QScrollArea, QStackedWidget, QDesktopWidget
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QSize, QTimer, QRect
from PyQt5.QtGui import QFont, QColor, QDragEnterEvent, QDropEvent, QIcon, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtCore import QByteArray, QIODevice

from speech_to_text import config
from speech_to_text.hardware_detection import HardwareDetector

logger = logging.getLogger(__name__)

# Color palette - vibrant and modern
COLORS = {
    "bg_primary": "#0F1419",
    "bg_secondary": "#1A1E27",
    "bg_tertiary": "#2A2E37",
    "accent": "#6366F1",
    "accent_hover": "#818CF8",
    "accent_dark": "#4F46E5",
    "accent_secondary": "#EC4899",
    "success": "#10B981",
    "text_primary": "#F3F4F6",
    "text_secondary": "#9CA3AF",
    "text_tertiary": "#6B7280",
    "border": "#374151",
    "border_light": "#4B5563",
}

# SVG Icons from Heroicons (MIT Licensed)
ICONS = {
    "folder": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>',
    "microphone": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3zM7 8a5 5 0 1010 0M1 15h6v2H1zM17 15h6v2h-6z"/></svg>',
    "settings": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="3"/><path d="M12 1v6m0 6v6M4.22 4.22l4.24 4.24m5.08 5.08l4.24 4.24M1 12h6m6 0h6M4.22 19.78l4.24-4.24m5.08-5.08l4.24-4.24"/></svg>',
    "check": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20 6L9 17l-5-5"/></svg>',
    "arrow_left": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>',
    "file": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z"/><path d="M13 2v7h7"/></svg>',
}


class Step(Enum):
    """Application steps."""
    FILE_SELECT = 0
    MODEL_SELECT = 1
    TRANSCRIPTION = 2


class ModernStyleSheet:
    """
    Modern stylesheet system with vibrant colors and interactive states.
    
    Provides reusable stylesheet methods for consistent UI theming across the application.
    Each method returns a complete QSS (Qt Stylesheet) string for the specified component.
    
    Supports:
    - Primary buttons (accent colored, main CTAs)
    - Secondary buttons (outlined, lower prominence)
    - Hover and pressed states for user feedback
    - Disabled state styling
    
    All colors are driven by the COLORS dictionary for easy theme customization.
    """
    
    @staticmethod
    def button_primary() -> str:
        return f"""
        QPushButton {{
            background-color: {COLORS['accent']};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: 700;
            font-size: 12px;
        }}
        QPushButton:hover {{
            background-color: {COLORS['accent_hover']};
        }}
        QPushButton:pressed {{
            background-color: {COLORS['accent_dark']};
        }}
        QPushButton:disabled {{
            background-color: {COLORS['bg_tertiary']};
            color: {COLORS['text_tertiary']};
        }}
        """
    
    @staticmethod
    def button_secondary() -> str:
        return f"""
        QPushButton {{
            background-color: transparent;
            color: {COLORS['text_primary']};
            border: 2px solid {COLORS['border_light']};
            border-radius: 8px;
            padding: 8px 18px;
            font-weight: 700;
            font-size: 12px;
        }}
        QPushButton:hover {{
            background-color: {COLORS['bg_tertiary']};
            border-color: {COLORS['accent']};
            color: {COLORS['accent']};
        }}
        """


def svg_to_pixmap(svg_string: str, size: int = 24, color: str = "white") -> QPixmap:
    """
    Convert an SVG string to a QPixmap with optional color substitution.
    
    Rasterizes SVG markup to a pixmap image at the specified size, optionally replacing
    'currentColor' tokens with the provided color. Useful for rendering Heroicons and
    other dynamic SVG graphics at various sizes and colors.
    
    Args:
        svg_string: SVG markup as a string (e.g., from Heroicons library)
        size: Width and height of the resulting square pixmap in pixels (default: 24)
        color: Replacement color for 'currentColor' tokens (default: 'white')
        
    Returns:
        QPixmap with transparent background and rendered SVG at the specified size.
        
    Example:
        icon = svg_to_pixmap(HEROICON_UPLOAD, size=32, color='#3B82F6')
    """
    from PyQt5.QtGui import QPainter
    
    svg_with_color = svg_string.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg_with_color.encode()))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def get_audio_duration(file_path: str) -> int:
    """
    Get audio file duration in seconds.
    Try multiple methods and fall back to file size estimate.
    """
    try:
        # Try moviepy first
        from moviepy.editor import AudioFileClip
        try:
            clip = AudioFileClip(file_path)
            duration = int(clip.duration)
            clip.close()
            logger.debug(f"Got duration from moviepy: {duration}s")
            return duration
        except Exception as e:
            logger.debug(f"moviepy failed: {e}")
    except ImportError:
        logger.debug("moviepy not available")
    
    try:
        # Try librosa
        import librosa
        y, sr = librosa.load(file_path, sr=None)
        duration = int(librosa.get_duration(y=y, sr=sr))
        logger.debug(f"Got duration from librosa: {duration}s")
        return duration
    except ImportError:
        logger.debug("librosa not available")
    except Exception as e:
        logger.debug(f"librosa failed: {e}")
    
    # Fallback: estimate from file size
    # Typical: 128kbps MP3 ≈ 16 KB/sec, 192kbps ≈ 24 KB/sec
    # We use config.AUDIO_MINUTES_PER_100MB to keep the fallback estimate centralized.
    # This value represents average audio duration for a 100MB file in minutes.
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    estimated_seconds = int(file_size_mb * 60 * config.AUDIO_MINUTES_PER_100MB)
    logger.debug(f"Estimated duration from file size: {estimated_seconds}s ({estimated_seconds//60}m {estimated_seconds%60}s)")
    return estimated_seconds


class TranscriptionThread(QThread):
    """Worker thread for transcription."""
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, audio_file: str, model_size: str, device: str):
        super().__init__()
        self.audio_file = audio_file
        self.model_size = model_size
        self.device = device
        self._is_running = True
        logger.debug(f"TranscriptionThread created: {os.path.basename(audio_file)}")

    def run(self):
        """Run transcription in thread."""
        logger.info(f"TranscriptionThread started")
        try:
            from speech_to_text.core.transcriber import Transcriber
            
            self.progress.emit("Initializing...", 5)
            transcriber = Transcriber(
                model_size=self.model_size,
                device=self.device,
                progress_callback=self.progress.emit
            )
            
            if not transcriber.load_model():
                logger.error("Failed to load model")
                self.error.emit("Failed to load transcription model")
                return
            
            if not self._is_running:
                self.error.emit("Transcription cancelled")
                return
            
            self.progress.emit("Transcribing audio...", 30)
            text = transcriber.transcribe(self.audio_file)
            
            if text is None:
                self.error.emit("Transcription failed")
                return
            
            self.progress.emit("Formatting output...", 90)
            formatted_text = transcriber.format_output(text)
            output_file = self._get_output_path()
            
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(formatted_text)
            
            logger.info(f"✓ Transcription complete")
            self.progress.emit("Complete!", 100)
            self.finished.emit(output_file)
            
        except Exception as e:
            logger.error(f"TranscriptionThread error: {e}", exc_info=True)
            self.error.emit(str(e))
    
    def stop(self):
        """Stop the thread."""
        self._is_running = False
    
    def _get_output_path(self) -> str:
        """Get output file path."""
        input_dir = os.path.dirname(self.audio_file)
        output_file = os.path.join(input_dir, config.OUTPUT_FILENAME)
        return output_file


class FileSelectStep(QFrame):
    """Step 1: File Selection with drag-and-drop."""
    
    file_selected = pyqtSignal(str, int)  # file_path, duration_seconds
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {COLORS['bg_primary']};")
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("Select Audio File")
        title_font = QFont("Segoe UI", 14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {COLORS['text_primary']};")
        layout.addWidget(title)
        
        # Drop zone - large and spacious (NO NESTED LAYOUT, USE WIDGET)
        self.drop_zone = QFrame()
        self.drop_zone.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_tertiary']};
                border: 2px dashed {COLORS['accent']};
                border-radius: 12px;
            }}
        """)
        self.drop_zone.setAcceptDrops(True)
        self.drop_zone.dragEnterEvent = self._drag_enter
        self.drop_zone.dragLeaveEvent = lambda e: self._reset_drop_zone()
        self.drop_zone.dropEvent = self._drop
        self.drop_zone.setFixedHeight(config.GUI_DROP_ZONE_HEIGHT)
        
        # Center container inside drop zone for clean layout
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setSpacing(config.GUI_DROP_ZONE_SPACING)
        drop_layout.setContentsMargins(config.GUI_DROP_ZONE_PADDING, config.GUI_DROP_ZONE_PADDING, 
                                        config.GUI_DROP_ZONE_PADDING, config.GUI_DROP_ZONE_PADDING)
        
        # Folder icon - SVG
        icon_label = QLabel()
        icon_pixmap = svg_to_pixmap(ICONS["folder"], 64, COLORS['accent'])
        icon_label.setPixmap(icon_pixmap)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setMaximumHeight(70)
        drop_layout.addWidget(icon_label)
        
        # Main text
        main_text = QLabel("Drag your audio or video file here")
        main_text.setFont(QFont("Segoe UI", 12, QFont.Bold))
        main_text.setStyleSheet(f"color: {COLORS['text_primary']};")
        main_text.setAlignment(Qt.AlignCenter)
        main_text.setMaximumHeight(20)
        drop_layout.addWidget(main_text)
        
        # Supported formats - context (single line)
        formats_text = QLabel("MP3, WAV, M4A, FLAC, OGG, MP4, MKV")
        formats_text.setFont(QFont("Segoe UI", 9))
        formats_text.setStyleSheet(f"color: {COLORS['text_secondary']};")
        formats_text.setAlignment(Qt.AlignCenter)
        formats_text.setMaximumHeight(16)
        drop_layout.addWidget(formats_text)
        
        # Alt text
        alt_text = QLabel("or click Browse to select a file")
        alt_text.setFont(QFont("Segoe UI", 9))
        alt_text.setStyleSheet(f"color: {COLORS['text_tertiary']};")
        alt_text.setAlignment(Qt.AlignCenter)
        alt_text.setMaximumHeight(16)
        drop_layout.addWidget(alt_text)
        
        layout.addWidget(self.drop_zone)
        
        # File info display
        self.file_label = QLabel("No file selected")
        self.file_label.setFont(QFont("Segoe UI", 10))
        self.file_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self.file_label.setMaximumHeight(18)
        layout.addWidget(self.file_label)
        
        # Browse button
        browse_btn = QPushButton("Browse Files")
        browse_btn.setMinimumHeight(36)
        browse_btn.setFont(QFont("Segoe UI", 11, QFont.Bold))
        browse_btn.setStyleSheet(ModernStyleSheet.button_secondary())
        browse_btn.clicked.connect(self._browse)
        layout.addWidget(browse_btn)
        
        layout.addStretch()
        
        self.selected_file = None
        self.selected_duration = 0
    
    def _reset_drop_zone(self):
        """
        Reset drop zone to its normal (non-drag) styling.
        
        Restores the drop zone border color and background to their default state.
        Called after files are dropped or when dragging leaves the drop zone.
        """
        self.drop_zone.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_tertiary']};
                border: 2px dashed {COLORS['accent']};
                border-radius: 12px;
            }}
        """)
    
    def _drag_enter(self, event: QDragEnterEvent):
        """
        Handle drag enter event over the drop zone.
        
        Accepts drag events containing URLs (files) and provides visual feedback
        by changing the border color to indicate the zone is active.
        
        Args:
            event: QDragEnterEvent containing the dragged data
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drop_zone.setStyleSheet(f"""
                QFrame {{
                    background-color: {COLORS['bg_secondary']};
                    border: 2px dashed {COLORS['accent_hover']};
                    border-radius: 12px;
                }}
            """)
    
    def _drop(self, event: QDropEvent):
        self._reset_drop_zone()
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files:
            self._select_file(files[0])
    
    def _browse(self):
        file_filter = "Audio/Video Files (" + " ".join(config.SUPPORTED_FORMATS) + ")"
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_filter)
        if file_path:
            self._select_file(file_path)
    
    def _select_file(self, file_path: str):
        self.selected_file = file_path
        filename = os.path.basename(file_path)
        
        # Get duration
        self.selected_duration = get_audio_duration(file_path)
        duration_min = self.selected_duration // 60
        duration_sec = self.selected_duration % 60
        
        # Update display
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        self.file_label.setText(f"✓ {filename} • {duration_min}m {duration_sec}s • {size_mb:.1f} MB")
        self.file_label.setStyleSheet(f"color: {COLORS['success']}; font-weight: 600;")
        
        # Emit signal with file and duration
        self.file_selected.emit(file_path, self.selected_duration)


class ModelSelectStep(QFrame):
    """Step 2: Model Selection with recommendation and time estimates."""
    
    model_selected = pyqtSignal(str)  # model_size
    
    def __init__(self, hardware: HardwareDetector, audio_duration: int = 0, parent=None):
        super().__init__(parent)
        self.hardware = hardware
        self.audio_duration = audio_duration
        self.setStyleSheet(f"background-color: {COLORS['bg_primary']};")
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("Choose Model")
        title_font = QFont("Segoe UI", 14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {COLORS['text_primary']};")
        layout.addWidget(title)
        
        # Hardware info card
        hw_card = self._create_hardware_card()
        layout.addWidget(hw_card)
        
        # Scroll area for model options
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ background-color: {COLORS['bg_primary']}; border: none; }}")
        
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet(f"background-color: {COLORS['bg_primary']};")
        models_layout = QVBoxLayout(scroll_widget)
        models_layout.setSpacing(10)
        models_layout.setContentsMargins(0, 0, 0, 0)
        
        # Model selection
        self.model_group = QButtonGroup()
        self.model_radios = {}
        recommended_model, _ = hardware.recommend_model()
        
        for i, (model_name, model_info) in enumerate(config.MODELS.items()):
            model_card = self._create_model_card(
                i, model_name, model_info,
                is_recommended=(model_name == recommended_model)
            )
            models_layout.addWidget(model_card)
        
        models_layout.addStretch()
        scroll.setWidget(scroll_widget)
        
        layout.addWidget(scroll)
        layout.addStretch()
    
    def _create_hardware_card(self) -> QFrame:
        """
        Create and return a hardware information display card.
        
        Constructs a compact card showing system hardware specifications:
        - CPU core count and RAM capacity
        - GPU name and availability
        - Settings icon for visual indication
        
        Returns:
            QFrame: A styled card widget with hardware information and fixed height of 50px.
                    Contains horizontal layout with icon, text, and stretch.
        """
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_tertiary']};
                border-radius: 10px;
                padding: 12px;
            }}
        """)
        
        card_layout = QHBoxLayout(card)
        
        # Settings icon
        icon_label = QLabel()
        icon_pixmap = svg_to_pixmap(ICONS["settings"], 24, COLORS['accent'])
        icon_label.setPixmap(icon_pixmap)
        icon_label.setFixedSize(30, 30)
        card_layout.addWidget(icon_label)
        
        # Hardware info
        hw_info = self.hardware.get_hardware_info()
        gpu_text = hw_info['gpu_name'] if hw_info['has_gpu'] else "No GPU"
        info_text = f"{hw_info['cpu_cores']} CPU cores • {hw_info['ram_gb']}GB RAM • {gpu_text}"
        
        info_label = QLabel(info_text)
        info_label.setFont(QFont("Segoe UI", 10))
        info_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        card_layout.addWidget(info_label)
        
        card_layout.addStretch()
        card.setFixedHeight(50)
        
        return card
    
    def _create_model_card(self, idx: int, name: str, info: dict, is_recommended: bool = False) -> QFrame:
        """
        Create and return a model selection card with radio button and details.
        
        Constructs a clickable card for model selection with:
        - Radio button for selection (managed by self.model_group)
        - Model name, parameters, and description
        - Estimated transcription time based on current audio duration
        - Special gradient styling for recommended model
        
        Args:
            idx: Index of the model in the config.MODELS dict (for radio button ID)
            name: Model identifier (e.g., 'tiny', 'base', 'small')
            info: Dict with 'params' (model size), 'description' (text) keys
            is_recommended: If True, applies gradient styling and adds recommendation badge (default: False)
            
        Returns:
            QFrame: A styled, clickable card widget with integrated radio button.
                    Connected to self._on_model_selected when clicked.
        """
        card = QFrame()
        
        if is_recommended:
            card.setStyleSheet(f"""
                QFrame {{
                    background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent_secondary']} 100%);
                    border-radius: 10px;
                    padding: 0px;
                }}
            """)
        else:
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {COLORS['bg_tertiary']};
                    border: 2px solid {COLORS['border']};
                    border-radius: 10px;
                    padding: 0px;
                }}
            """)
        
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        
        # Radio button
        radio = QRadioButton()
        radio.setChecked(is_recommended)
        radio.toggled.connect(lambda checked: self.model_selected.emit(name) if checked else None)
        self.model_group.addButton(radio, idx)
        self.model_radios[name] = radio
        
        if is_recommended:
            radio.setStyleSheet("QRadioButton { color: white; }")
        else:
            radio.setStyleSheet(f"QRadioButton {{ color: {COLORS['text_primary']}; }}")
        
        layout.addWidget(radio)
        
        # Model name and description
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        
        model_label = QLabel(name.title())
        model_font = QFont("Segoe UI", 11, QFont.Bold)
        model_label.setFont(model_font)
        
        if is_recommended:
            model_label.setStyleSheet("color: white;")
        else:
            model_label.setStyleSheet(f"color: {COLORS['text_primary']};")
        
        text_layout.addWidget(model_label)
        
        # Description + time estimate
        desc = info.get('description', '')
        time_est, _ = self.hardware.estimate_transcription_time(self.audio_duration, name)
        time_str = self.hardware.get_time_estimate_display(time_est)
        
        desc_text = f"{desc} • Est: {time_str}"
        desc_label = QLabel(desc_text)
        desc_label.setFont(QFont("Segoe UI", 9))
        
        if is_recommended:
            desc_label.setStyleSheet("color: rgba(255, 255, 255, 0.8);")
        else:
            desc_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        
        text_layout.addWidget(desc_label)
        
        layout.addLayout(text_layout)
        layout.addStretch()
        
        # Recommended badge
        if is_recommended:
            badge = QLabel("RECOMMENDED")
            badge.setFont(QFont("Segoe UI", 9, QFont.Bold))
            badge.setStyleSheet("color: white;")
            layout.addWidget(badge)
        
        card.setFixedHeight(70)
        return card


class TranscriptionStep(QFrame):
    """Step 3: Transcription progress and results."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {COLORS['bg_primary']};")
        
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setAlignment(Qt.AlignCenter)
        
        # Title
        title = QLabel("Transcribing")
        title_font = QFont("Segoe UI", 14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {COLORS['text_primary']};")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # File info
        self.file_info = QLabel()
        self.file_info.setFont(QFont("Segoe UI", 10))
        self.file_info.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self.file_info.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.file_info)
        
        layout.addSpacing(20)
        
        # Progress bar with gradient styling
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLORS['bg_tertiary']};
                border-radius: 8px;
                border: none;
                height: 24px;
            }}
            QProgressBar::chunk {{
                background: linear-gradient(90deg, {COLORS['accent']} 0%, {COLORS['accent_secondary']} 100%);
                border-radius: 8px;
            }}
        """)
        self.progress_bar.setMinimumHeight(28)
        layout.addWidget(self.progress_bar)
        
        # Status and times
        self.status_label = QLabel("Initializing...")
        self.status_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.status_label.setStyleSheet(f"color: {COLORS['text_primary']};")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        # Time info
        self.time_label = QLabel()
        self.time_label.setFont(QFont("Segoe UI", 10))
        self.time_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self.time_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.time_label)
        
        layout.addSpacing(10)
        
        # Result display (hidden until done)
        self.result_widget = QFrame()
        self.result_widget.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_tertiary']};
                border-radius: 10px;
                padding: 16px;
            }}
        """)
        result_layout = QVBoxLayout(self.result_widget)
        result_layout.setSpacing(8)
        
        # Checkmark icon
        result_icon = QLabel()
        result_pixmap = svg_to_pixmap(ICONS["check"], 48, COLORS['success'])
        result_icon.setPixmap(result_pixmap)
        result_icon.setAlignment(Qt.AlignCenter)
        result_layout.addWidget(result_icon)
        
        # Success message
        success_msg = QLabel("Transcription Complete!")
        success_msg.setFont(QFont("Segoe UI", 12, QFont.Bold))
        success_msg.setStyleSheet(f"color: {COLORS['success']};")
        success_msg.setAlignment(Qt.AlignCenter)
        result_layout.addWidget(success_msg)
        
        # File path
        self.result_path = QLabel()
        self.result_path.setFont(QFont("Segoe UI", 10))
        self.result_path.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self.result_path.setAlignment(Qt.AlignCenter)
        self.result_path.setWordWrap(True)
        result_layout.addWidget(self.result_path)
        
        self.result_widget.hide()
        layout.addWidget(self.result_widget)
        
        layout.addStretch()
        
        self.start_time = None
    
    def set_file_info(self, filename: str, model: str):
        """Set file and model info for display."""
        self.file_info.setText(f"{filename} • Model: {model.title()}")
    
    def update_progress(self, status: str, percentage: int):
        """Update progress bar and status."""
        self.progress_bar.setValue(percentage)
        self.status_label.setText(status)
    
    def show_result(self, file_path: str):
        """Show completion result."""
        self.result_widget.show()
        filename = os.path.basename(file_path)
        self.result_path.setText(f"Saved to:\n{filename}")


class MainWindow(QMainWindow):
    """Main application window - lightweight tool interface."""
    
    def __init__(self):
        super().__init__()
        logger.info("Initializing MainWindow...")
        
        self.setWindowTitle(config.APP_NAME)
        self.setGeometry(100, 50, config.GUI_WINDOW_WIDTH, config.GUI_WINDOW_HEIGHT)
        self.setMinimumSize(config.GUI_WINDOW_MIN_WIDTH, config.GUI_WINDOW_MIN_HEIGHT)
        self.setStyleSheet(f"QMainWindow {{ background-color: {COLORS['bg_primary']}; }}")
        
        self.hardware = HardwareDetector()
        self.current_step = Step.FILE_SELECT
        self.transcription_thread: Optional[QThread] = None
        self.selected_file: Optional[str] = None
        self.selected_model: Optional[str] = None
        self.audio_duration: int = 0
        
        # Build UI
        self._init_ui()
        
        # Center on screen
        self.center_on_screen()
        
        logger.info("✓ MainWindow ready")
    
    def center_on_screen(self):
        """Center window on screen."""
        screen = QDesktopWidget().screenGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        logger.debug(f"Window centered at ({x}, {y})")
    
    def _init_ui(self):
        """Initialize UI."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header
        header = QFrame()
        header.setStyleSheet(f"""
            QFrame {{
                background: linear-gradient(135deg, {COLORS['accent']} 0%, {COLORS['accent_secondary']} 100%);
                border: none;
                padding: 0px;
            }}
        """)
        header.setFixedHeight(50)
        
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_layout.setSpacing(10)
        
        # Microphone icon
        mic_icon = QLabel()
        mic_pixmap = svg_to_pixmap(ICONS["microphone"], 24, "white")
        mic_icon.setPixmap(mic_pixmap)
        mic_icon.setFixedSize(24, 24)
        header_layout.addWidget(mic_icon)
        
        # Title
        title = QLabel("Transcriber")
        title_font = QFont("Segoe UI", 12)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: white;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        main_layout.addWidget(header)
        
        # Content area
        content_widget = QWidget()
        content_widget.setStyleSheet(f"background-color: {COLORS['bg_primary']};")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # Stacked widget for steps
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setStyleSheet(f"background-color: {COLORS['bg_primary']};")
        
        # Create steps
        self.file_step = FileSelectStep()
        self.file_step.file_selected.connect(self._on_file_selected)
        
        self.model_step = ModelSelectStep(self.hardware, 0)
        self.model_step.model_selected.connect(self._on_model_selected)
        
        self.transcription_step = TranscriptionStep()
        
        self.stacked_widget.addWidget(self.file_step)
        self.stacked_widget.addWidget(self.model_step)
        self.stacked_widget.addWidget(self.transcription_step)
        
        content_layout.addWidget(self.stacked_widget)
        main_layout.addWidget(content_widget)
        
        # Navigation bar
        nav_widget = QFrame()
        nav_widget.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_secondary']};
                border-top: 1px solid {COLORS['border']};
                padding: 12px 16px;
            }}
        """)
        nav_layout = QHBoxLayout(nav_widget)
        nav_layout.setSpacing(8)
        
        # Back button
        self.back_btn = QPushButton()
        back_pixmap = svg_to_pixmap(ICONS["arrow_left"], 16, COLORS['text_primary'])
        self.back_btn.setIcon(QIcon(back_pixmap))
        self.back_btn.setText("  Back")
        self.back_btn.setMinimumHeight(36)
        self.back_btn.setMinimumWidth(80)
        self.back_btn.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.back_btn.setStyleSheet(ModernStyleSheet.button_secondary())
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.setEnabled(False)
        nav_layout.addWidget(self.back_btn)
        
        nav_layout.addStretch()
        
        # Next button
        self.next_btn = QPushButton("Next  →")
        self.next_btn.setMinimumHeight(36)
        self.next_btn.setMinimumWidth(80)
        self.next_btn.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.next_btn.setStyleSheet(ModernStyleSheet.button_primary())
        self.next_btn.clicked.connect(self._go_next)
        self.next_btn.setEnabled(False)
        nav_layout.addWidget(self.next_btn)
        
        # Cancel button
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(36)
        self.cancel_btn.setMinimumWidth(80)
        self.cancel_btn.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.cancel_btn.setStyleSheet(ModernStyleSheet.button_secondary())
        self.cancel_btn.clicked.connect(self._cancel)
        nav_layout.addWidget(self.cancel_btn)
        
        main_layout.addWidget(nav_widget)
    
    def _on_file_selected(self, file_path: str, duration: int):
        """Handle file selection."""
        self.selected_file = file_path
        self.audio_duration = duration
        self.next_btn.setEnabled(True)
        logger.debug(f"File selected: {file_path} ({duration}s)")
    
    def _on_model_selected(self, model: str):
        """Handle model selection."""
        self.selected_model = model
        self.next_btn.setEnabled(True)
        logger.debug(f"Model selected: {model}")
    
    def _go_back(self):
        """Go to previous step."""
        if self.current_step == Step.MODEL_SELECT:
            self.current_step = Step.FILE_SELECT
            self.stacked_widget.setCurrentIndex(0)
            self.back_btn.setEnabled(False)
            self.next_btn.setEnabled(self.selected_file is not None)
        logger.debug(f"Navigated to: {self.current_step}")
    
    def _go_next(self):
        """Go to next step."""
        if self.current_step == Step.FILE_SELECT:
            # Rebuild the model selection step with updated audio duration.
            # This ensures time estimates reflect the latest selected file.
            self.model_step = ModelSelectStep(self.hardware, self.audio_duration)
            self.model_step.model_selected.connect(self._on_model_selected)
            self.stacked_widget.removeWidget(self.stacked_widget.widget(1))
            self.stacked_widget.insertWidget(1, self.model_step)
            
            self.current_step = Step.MODEL_SELECT
            self.stacked_widget.setCurrentIndex(1)
            self.back_btn.setEnabled(True)
            self.next_btn.setEnabled(False)
        
        elif self.current_step == Step.MODEL_SELECT:
            if not self.selected_model:
                QMessageBox.warning(self, "No Model", "Please select a model")
                return
            
            # Proceed to transcription once the model is selected.
            self._start_transcription()
        
        logger.debug(f"Navigated to: {self.current_step}")
    
    def _start_transcription(self):
        """Start transcription thread."""
        self.current_step = Step.TRANSCRIPTION
        self.stacked_widget.setCurrentIndex(2)
        self.back_btn.setEnabled(False)
        self.next_btn.hide()
        self.cancel_btn.hide()
        
        filename = os.path.basename(self.selected_file)
        self.transcription_step.set_file_info(filename, self.selected_model)
        
        logger.info(f"Starting transcription: {filename} with {self.selected_model} model")
        
        self.transcription_thread = TranscriptionThread(
            self.selected_file,
            self.selected_model,
            "cpu"  # Auto-detect would go here
        )
        self.transcription_thread.progress.connect(self.transcription_step.update_progress)
        self.transcription_thread.finished.connect(self._on_transcription_complete)
        self.transcription_thread.error.connect(self._on_transcription_error)
        self.transcription_thread.start()
    
    def _on_transcription_complete(self, output_file: str):
        """Handle transcription completion."""
        logger.info(f"Transcription complete: {output_file}")
        self.transcription_step.show_result(output_file)
        
        # Show completion options
        self.next_btn.setText("New File")
        self.next_btn.show()
        self.cancel_btn.setText("Exit")
        self.cancel_btn.show()
        self.next_btn.clicked.disconnect()
        self.next_btn.clicked.connect(self._reset)
    
    def _on_transcription_error(self, error_msg: str):
        """Handle transcription error."""
        logger.error(f"Transcription error: {error_msg}")
        QMessageBox.critical(self, "Transcription Error", error_msg)
        self._reset()
    
    def _reset(self):
        """Reset to file selection."""
        self.current_step = Step.FILE_SELECT
        self.stacked_widget.setCurrentIndex(0)
        self.selected_file = None
        self.selected_model = None
        self.audio_duration = 0
        self.back_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.next_btn.setText("Next  →")
        self.next_btn.show()
        self.cancel_btn.setText("Cancel")
        self.cancel_btn.show()
        self.next_btn.clicked.disconnect()
        self.next_btn.clicked.connect(self._go_next)
        self.file_step.file_label.setText("No file selected")
        self.file_step.file_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self.file_step.selected_file = None
        self.file_step.selected_duration = 0
        logger.debug("Reset to file selection step")
    
    def _cancel(self):
        """Cancel operation or exit."""
        if self.current_step == Step.TRANSCRIPTION and self.transcription_thread:
            self.transcription_thread.stop()
            self.transcription_thread.wait()
        self.close()
        logger.info("Application closed by user")


def main():
    """Entry point for GUI."""
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
