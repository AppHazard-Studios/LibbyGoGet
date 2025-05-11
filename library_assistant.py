"""
Library Assistant - Elegant, minimal interface for academic resource search and download.
Maintains consistent design language with existing GUI application.
"""
import sys
import os
import logging
import json
import traceback
from pathlib import Path
import re
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

# Import PyQt components first
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QFrame, QScrollArea, QLineEdit, QSplitter,
    QComboBox, QCheckBox, QTextEdit, QDialog,
    QDialogButtonBox, QProgressBar, QStackedWidget
)
from PyQt6.QtGui import (
    QFont, QFontMetrics, QDragEnterEvent, QDropEvent,
    QCursor, QPainter, QColor, QPixmap, QIcon
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QObject, QSize, QPoint,
    QPropertyAnimation, QEasingCurve, QVariantAnimation,
    pyqtProperty, QTimer, QUrl
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

# Import keyring for credential storage
import keyring

# Import our custom modules
from settings import Settings
from utils import setup_logging, generate_book_id, clean_filename, parse_book_list
from library_manager import EbookCentralPortal

# Worker classes embedded directly to avoid import issues
class SearchWorker(QObject):
    """Worker thread to search for books in the background."""
    searchStarted = pyqtSignal(str)  # book_id
    searchResult = pyqtSignal(str, dict)  # book_id, results
    searchError = pyqtSignal(str, str)  # book_id, error message
    loginRequired = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, books, portal, username="", password=""):
        super().__init__()
        self.books = books  # List of dicts with 'id', 'title', 'author'
        self.portal = portal
        self.username = username
        self.password = password
        self.logger = logging.getLogger(__name__)
        self.cancel_flag = False

    def cancel(self):
        """Set cancel flag to stop processing."""
        self.cancel_flag = True

    def search(self):
        """Search for books on the library portal."""
        try:
            # Update portal credentials
            self.portal.username = self.username
            self.portal.password = self.password

            # First try logging in if credentials provided
            if self.username and self.password and not self.portal.is_logged_in:
                success = self.portal.login()
                if not success:
                    self.loginRequired.emit()
                    self.finished.emit()
                    return

            # Process each book
            for book in self.books:
                if self.cancel_flag:
                    break

                book_id = book["id"]
                self.searchStarted.emit(book_id)

                try:
                    # Search for this book using the portal
                    result = self.portal.search_book(book["title"], book["author"])

                    # Add book_id to result for reference
                    result["book_id"] = book_id

                    self.searchResult.emit(book_id, result)

                except Exception as e:
                    self.logger.exception(f"Error searching for book {book_id}: {str(e)}")
                    self.searchError.emit(book_id, str(e))

        except Exception as e:
            self.logger.exception(f"Error in search worker: {str(e)}")
        finally:
            self.finished.emit()


class DownloadWorker(QObject):
    """Worker thread to download books in the background."""
    downloadStarted = pyqtSignal(str)  # book_id
    downloadProgress = pyqtSignal(str, int)  # book_id, progress percentage
    downloadComplete = pyqtSignal(str, str)  # book_id, local file path
    downloadError = pyqtSignal(str, str)  # book_id, error message
    loginRequired = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, books, portal, output_folder, username="", password=""):
        super().__init__()
        self.books = books  # Dict of book_id: {download_url, title, etc}
        self.portal = portal
        self.output_folder = output_folder
        self.username = username
        self.password = password
        self.logger = logging.getLogger(__name__)
        self.cancel_flag = False

    def cancel(self):
        """Set cancel flag to stop processing."""
        self.cancel_flag = True

    def download(self):
        """Download books to the output folder."""
        try:
            # Update portal credentials
            self.portal.username = self.username
            self.portal.password = self.password

            # First try logging in if credentials provided
            if self.username and self.password and not self.portal.is_logged_in:
                success = self.portal.login()
                if not success:
                    self.loginRequired.emit()
                    self.finished.emit()
                    return

            # Ensure output folder exists
            os.makedirs(self.output_folder, exist_ok=True)

            # Process each book
            for book_id, book_info in self.books.items():
                if self.cancel_flag:
                    break

                self.downloadStarted.emit(book_id)

                try:
                    # Get required info from book_info
                    download_url = book_info.get("download_url", "")
                    title = book_info.get("title", "Unknown")
                    author = book_info.get("author", "Unknown")
                    ebook_id = book_info.get("ebook_id", "")

                    if not download_url:
                        raise ValueError("No download URL available")

                    # Create a clean filename
                    if author:
                        filename = f"{author} - {title}"
                    else:
                        filename = title

                    filename = self._clean_filename(filename)
                    output_path = os.path.join(self.output_folder, filename)

                    # Download the book
                    result = self.portal.download_book(
                        download_url,
                        ebook_id,
                        output_path,
                        callback=lambda received, total: self._handle_progress(book_id, received, total)
                    )

                    if result["success"]:
                        # Emit completion signal
                        self.downloadComplete.emit(book_id, result["file_path"])
                    else:
                        # Emit error signal
                        self.downloadError.emit(book_id, result.get("message", "Download failed"))

                except Exception as e:
                    self.logger.exception(f"Error downloading book {book_id}: {str(e)}")
                    self.downloadError.emit(book_id, str(e))

        except Exception as e:
            self.logger.exception(f"Error in download worker: {str(e)}")
        finally:
            self.finished.emit()

    def _handle_progress(self, book_id, received, total):
        """Handle download progress updates."""
        if total > 0 and not self.cancel_flag:
            progress = int((received / total) * 100)
            self.downloadProgress.emit(book_id, progress)

    def _clean_filename(self, filename):
        """Clean a filename to make it safe for all filesystems."""
        # Replace invalid chars with underscores
        invalid_chars = r'<>:"/\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')

        # Limit length (255 is safe for most filesystems)
        if len(filename) > 200:
            base, ext = os.path.splitext(filename)
            filename = base[:200 - len(ext)] + ext

        # Remove leading/trailing whitespace and periods
        filename = filename.strip().strip('.')

        # If empty after cleaning, provide a default
        if not filename:
            filename = "ebook"

        return filename


# Custom UI components
class ElegantFrame(QFrame):
    """A beautifully styled frame with subtle shadows and rounded corners."""

    def __init__(self, parent=None, radius=12, bg_color="#1a1a1a", shadow=True, border=False, border_color=None, border_style="solid"):
        super().__init__(parent)
        self.radius = radius
        self.bg_color = bg_color
        self.has_shadow = shadow
        self.has_border = border
        self.border_color = border_color or "#333333"
        self.border_style = border_style
        self.setStyleSheet(f"""
            background-color: transparent;
            border: none;
        """)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event):
        """Custom paint event to draw rounded corners and shadows."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw shadow if enabled
        if self.has_shadow:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 20))
            painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), self.radius, self.radius)

        # Draw main background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.bg_color))
        painter.drawRoundedRect(self.rect(), self.radius, self.radius)

        # Draw border if enabled
        if self.has_border:
            if self.border_style == "dashed":
                pen = painter.pen()
                pen.setColor(QColor(self.border_color))
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidth(1)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), self.radius, self.radius)
            else:
                painter.setPen(QColor(self.border_color))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), self.radius, self.radius)


class AnimatedButton(QPushButton):
    """Base class for buttons with smooth macOS-like animation."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # Animation properties
        self._animation_progress = 0.0
        self._animation = QVariantAnimation()
        self._animation.setDuration(75)  # 75ms animation
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)  # macOS-like easing
        self._animation.valueChanged.connect(self._update_animation)

        # Keep track of mouse state
        self._is_pressed = False
        self._is_hovered = False

        # Set transparent background so we can paint our own
        self.setStyleSheet("""
            QPushButton {
                color: #ffffff;
                background-color: transparent;
                border: none;
                padding: 6px 12px;
                font-size: 13px;
                text-align: center;
            }
        """)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _get_animation_progress(self):
        return self._animation_progress

    def _set_animation_progress(self, progress):
        self._animation_progress = progress
        self.update()  # Trigger repaint

    # Define animation property
    animation_progress = pyqtProperty(float, _get_animation_progress, _set_animation_progress)

    def _update_animation(self, value):
        """Update animation state."""
        self.animation_progress = value

    def enterEvent(self, event):
        """Handle mouse enter event."""
        self._is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Handle mouse leave event."""
        self._is_hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        """Handle mouse press with animation start."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_pressed = True

            # Start animation from 0 to 1
            self._animation.stop()
            self._animation.setStartValue(0.0)
            self._animation.setEndValue(1.0)
            self._animation.start()

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release with animation back."""
        if event.button() == Qt.MouseButton.LeftButton and self._is_pressed:
            self._is_pressed = False

            # Start animation from current value back to 0
            self._animation.stop()
            self._animation.setStartValue(self._animation_progress)
            self._animation.setEndValue(0.0)
            self._animation.start()

        super().mouseReleaseEvent(event)


class ElegantButton(AnimatedButton):
    """Beautifully styled button with smooth animations."""

    def __init__(self, text, parent=None, primary=False, icon=None):
        super().__init__(text, parent)
        self.is_primary = primary
        self.icon_path = icon

        # Set button styles based on primary status
        if primary:
            self.normal_color = "#0078d4"
            self.hover_color = "#0086f0"
            self.pressed_color = "#005a9e"  # Darker for press animation
        else:
            self.normal_color = "#1e1e1e"
            self.hover_color = "#2a2a2a"
            self.pressed_color = "#101010"  # Darker for press animation

        # Set font weight
        if primary:
            self.setStyleSheet("""
                QPushButton {
                    color: #ffffff;
                    background-color: transparent;
                    border: none;
                    padding: 6px 12px;
                    font-size: 13px;
                    font-weight: 600;
                    text-align: center;
                }
            """)

    def paintEvent(self, event):
        """Custom paint event to draw animated rounded button."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Determine background color based on state and animation
        if self._is_pressed or self._animation_progress > 0:
            # Animate between normal/hover color and pressed color based on animation progress
            if self._is_hovered and not self._is_pressed:
                base_color = self.hover_color
            else:
                base_color = self.normal_color

            # Mix colors based on animation progress
            color = self._mix_colors(base_color, self.pressed_color, self._animation_progress)
            painter.setBrush(QColor(color))
        elif self._is_hovered:
            painter.setBrush(QColor(self.hover_color))
        else:
            painter.setBrush(QColor(self.normal_color))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 8, 8)

        # Pass to standard button painting for text/icon
        super(AnimatedButton, self).paintEvent(event)

    def _mix_colors(self, color1, color2, factor):
        """Mix two hex colors based on factor (0-1)."""
        r1, g1, b1 = int(color1[1:3], 16), int(color1[3:5], 16), int(color1[5:7], 16)
        r2, g2, b2 = int(color2[1:3], 16), int(color2[3:5], 16), int(color2[5:7], 16)

        r = int(r1 + factor * (r2 - r1))
        g = int(g1 + factor * (g2 - g1))
        b = int(b1 + factor * (b2 - b1))

        return f"#{r:02x}{g:02x}{b:02x}"


class BookCard(QWidget):
    """An elegantly designed book card displaying search results."""

    openLinkClicked = pyqtSignal(str)  # Signal for opening link
    downloadClicked = pyqtSignal(str)  # Signal for downloading

    def __init__(self, book_info, parent=None):
        super().__init__(parent)
        self.book_info = book_info
        self.title = book_info.get("title", "Unknown Title")
        self.author = book_info.get("author", "Unknown Author")
        self.status = "Waiting"  # Initial status
        self.download_url = book_info.get("download_url", "")
        self.view_url = book_info.get("view_url", "")
        self.format = book_info.get("format", "")

        self.setup_ui()

    def setup_ui(self):
        """Set up the book card UI."""
        # Main layout with larger margins for cleaner look
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # Base widget is transparent
        self.setStyleSheet("""
            background-color: transparent;
            color: #ffffff;
        """)

        # Create background frame
        self.bg_frame = ElegantFrame(self, radius=8, bg_color="#1a1a1a")
        self.bg_frame.setGeometry(self.rect())

        # Format indicator
        format_container = QWidget()
        format_container.setFixedSize(34, 34)
        format_container.setStyleSheet("""
            background-color: #2a2a2a;
            border-radius: 17px;
        """)

        format_layout = QVBoxLayout(format_container)
        format_layout.setContentsMargins(0, 0, 0, 0)

        self.format_label = QLabel(self.format[:3] if self.format else "?")  # Limit to 3 chars
        self.format_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.format_label.setStyleSheet("""
            color: #ffffff;
            font-size: 11px;
            font-weight: 600;
            background-color: transparent;
        """)
        format_layout.addWidget(self.format_label)

        layout.addWidget(format_container)

        # Book details container
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(2)

        # Title
        self.title_label = QLabel(self._truncate_text(self.title, 250))
        self.title_label.setStyleSheet("""
            color: #ffffff;
            font-size: 13px;
            font-weight: 500;
            background-color: transparent;
        """)
        self.title_label.setToolTip(self.title)
        details_layout.addWidget(self.title_label)

        # Author line
        self.author_label = QLabel(self.author)
        self.author_label.setStyleSheet("""
            color: #aaaaaa;
            font-size: 12px;
            background-color: transparent;
        """)
        details_layout.addWidget(self.author_label)

        # Status line
        self.status_label = QLabel("Waiting")
        self.status_label.setStyleSheet("""
            color: #888888;
            font-size: 12px;
            background-color: transparent;
        """)
        details_layout.addWidget(self.status_label)

        layout.addWidget(details_widget, 1)  # Stretch

        # Action buttons container
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)

        # View button
        self.view_btn = ElegantButton("View", self)
        self.view_btn.setFixedWidth(60)
        self.view_btn.clicked.connect(lambda: self.openLinkClicked.emit(self.view_url))
        self.view_btn.setEnabled(bool(self.view_url))
        actions_layout.addWidget(self.view_btn)

        # Download button
        self.download_btn = ElegantButton("Download", self, primary=True)
        self.download_btn.setFixedWidth(80)
        self.download_btn.clicked.connect(lambda: self.downloadClicked.emit(self.download_url))
        self.download_btn.setEnabled(bool(self.download_url))
        actions_layout.addWidget(self.download_btn)

        layout.addWidget(actions_widget)

        # Update on resize
        self.resizeEvent = self._on_resize

    def _on_resize(self, event):
        """Handle resize events."""
        # Update frame size
        self.bg_frame.setGeometry(self.rect())

    def _truncate_text(self, text, max_width):
        """Truncate text to fit in the available width."""
        metrics = QFontMetrics(self.font())
        if metrics.horizontalAdvance(text) <= max_width:
            return text

        # Truncate the middle
        while metrics.horizontalAdvance(text[:-3] + "...") > max_width and len(text) > 10:
            text = text[:-1]

        return text[:-3] + "..."

    def update_status(self, status, message=""):
        """Update status with optional message."""
        self.status = status

        # Update status label and styling based on status
        if status == "Searching":
            self.status_label.setText("Searching...")
            self.status_label.setStyleSheet("""
                color: #0078d4;
                font-size: 12px;
                background-color: transparent;
            """)
            self.bg_frame.bg_color = "#1a2a3a"

        elif status == "Found":
            self.status_label.setText("Found")
            self.status_label.setStyleSheet("""
                color: #2fcc71;
                font-size: 12px;
                background-color: transparent;
            """)
            self.bg_frame.bg_color = "#1a291f"

            # Enable buttons if URLs are available
            self.view_btn.setEnabled(bool(self.view_url))
            self.download_btn.setEnabled(bool(self.download_url))

        elif status == "Not Found":
            self.status_label.setText("Not Found")
            self.status_label.setStyleSheet("""
                color: #e74c3c;
                font-size: 12px;
                background-color: transparent;
            """)
            self.bg_frame.bg_color = "#2a1a1a"

        elif status == "Error":
            self.status_label.setText("Error")
            self.status_label.setStyleSheet("""
                color: #e74c3c;
                font-size: 12px;
                background-color: transparent;
            """)
            self.bg_frame.bg_color = "#2a1a1a"
            self.status_label.setToolTip(message)

        elif status == "Downloaded":
            self.status_label.setText("Downloaded")
            self.status_label.setStyleSheet("""
                color: #2fcc71;
                font-size: 12px;
                font-weight: 600;
                background-color: transparent;
            """)
            self.bg_frame.bg_color = "#1a3a1f"

        self.bg_frame.update()

    def update_details(self, details):
        """Update book details with new information."""
        # Update book info
        self.book_info.update(details)

        # Update display elements
        if "title" in details:
            self.title = details["title"]
            self.title_label.setText(self._truncate_text(self.title, 250))
            self.title_label.setToolTip(self.title)

        if "author" in details:
            self.author = details["author"]
            self.author_label.setText(self.author)

        if "format" in details:
            self.format = details["format"]
            self.format_label.setText(self.format[:3] if self.format else "?")

        if "download_url" in details:
            self.download_url = details["download_url"]
            self.download_btn.setEnabled(bool(self.download_url))

        if "view_url" in details:
            self.view_url = details["view_url"]
            self.view_btn.setEnabled(bool(self.view_url))


class LoginDialog(QDialog):
    """Elegant login dialog for library portal."""

    def __init__(self, parent=None, first_run=False):
        super().__init__(parent)
        self.setWindowTitle("Login to Ridley Library")
        self.resize(400, 320)

        # Set dialog style - darker theme
        self.setStyleSheet("""
            QDialog, QWidget {
                background-color: #121212;
                color: #ffffff;
                font-family: Arial, sans-serif;
            }
        """)

        self.setup_ui(first_run)

    def setup_ui(self, first_run):
        """Set up the login dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Title with welcome message for first run
        if first_run:
            title_label = QLabel("Welcome to Ridley Library Assistant")
            title_label.setStyleSheet("""
                color: #ffffff;
                font-size: 18px;
                font-weight: 600;
            """)
            layout.addWidget(title_label)

            intro_text = QLabel("Please enter your Ridley College login credentials to access the library resources.")
            intro_text.setWordWrap(True)
            intro_text.setStyleSheet("color: #aaaaaa; font-size: 13px;")
            layout.addWidget(intro_text)
        else:
            title_label = QLabel("Ridley Library Login")
            title_label.setStyleSheet("""
                color: #ffffff;
                font-size: 18px;
                font-weight: 600;
            """)
            layout.addWidget(title_label)

        # Content frame
        content_frame = ElegantFrame(self, radius=12, bg_color="#171717")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(16)

        # Username field
        username_layout = QVBoxLayout()
        username_layout.setSpacing(4)

        username_label = QLabel("Username")
        username_label.setStyleSheet("color: #aaaaaa; font-size: 13px;")
        username_layout.addWidget(username_label)

        self.username_input = QLineEdit()
        self.username_input.setStyleSheet("""
            background-color: #1e1e1e;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 8px;
            font-size: 14px;
        """)
        username_layout.addWidget(self.username_input)

        content_layout.addLayout(username_layout)

        # Password field
        password_layout = QVBoxLayout()
        password_layout.setSpacing(4)

        password_label = QLabel("Password")
        password_label.setStyleSheet("color: #aaaaaa; font-size: 13px;")
        password_layout.addWidget(password_label)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setStyleSheet("""
            background-color: #1e1e1e;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 8px;
            font-size: 14px;
        """)
        password_layout.addWidget(self.password_input)

        content_layout.addLayout(password_layout)

        # Remember me checkbox
        self.remember_checkbox = QCheckBox("Remember credentials")
        self.remember_checkbox.setStyleSheet("""
            color: #aaaaaa;
            font-size: 13px;
        """)
        self.remember_checkbox.setChecked(True)
        content_layout.addWidget(self.remember_checkbox)

        layout.addWidget(content_frame)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 8, 0, 0)
        button_layout.setSpacing(12)

        button_layout.addStretch(1)

        if not first_run:
            # Only show cancel button if not first run
            self.cancel_btn = ElegantButton("Cancel", self)
            self.cancel_btn.clicked.connect(self.reject)
            button_layout.addWidget(self.cancel_btn)

        self.login_btn = ElegantButton("Login", self, primary=True)
        self.login_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.login_btn)

        layout.addLayout(button_layout)


class SettingsDialog(QDialog):
    """Settings dialog for Library Assistant."""

    def __init__(self, parent=None, username="", remember_credentials=True):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(400, 350)

        # Set dialog style - darker theme
        self.setStyleSheet("""
            QDialog, QWidget {
                background-color: #121212;
                color: #ffffff;
                font-family: Arial, sans-serif;
            }
        """)

        self.username = username
        self.remember_credentials = remember_credentials

        # Try to load password from keyring
        self.password = ""
        if username:
            try:
                self.password = keyring.get_password("LibraryAssistant", username) or ""
            except:
                pass

        self.setup_ui()

    def setup_ui(self):
        """Set up the settings dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Title
        title_label = QLabel("Settings")
        title_label.setStyleSheet("""
            color: #ffffff;
            font-size: 18px;
            font-weight: 600;
        """)
        layout.addWidget(title_label)

        # Account settings frame
        account_frame = ElegantFrame(self, radius=12, bg_color="#171717")
        account_layout = QVBoxLayout(account_frame)
        account_layout.setContentsMargins(16, 16, 16, 16)
        account_layout.setSpacing(16)

        # Account section header
        account_header = QLabel("Ridley Library Account")
        account_header.setStyleSheet("""
            color: #ffffff;
            font-size: 15px;
            font-weight: 600;
        """)
        account_layout.addWidget(account_header)

        # Username field
        username_layout = QVBoxLayout()
        username_layout.setSpacing(4)

        username_label = QLabel("Username")
        username_label.setStyleSheet("color: #aaaaaa; font-size: 13px;")
        username_layout.addWidget(username_label)

        self.username_input = QLineEdit()
        self.username_input.setText(self.username)
        self.username_input.setStyleSheet("""
            background-color: #1e1e1e;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 8px;
            font-size: 14px;
        """)
        username_layout.addWidget(self.username_input)

        account_layout.addLayout(username_layout)

        # Password field
        password_layout = QVBoxLayout()
        password_layout.setSpacing(4)

        password_label = QLabel("Password")
        password_label.setStyleSheet("color: #aaaaaa; font-size: 13px;")
        password_layout.addWidget(password_label)

        self.password_input = QLineEdit()
        self.password_input.setText(self.password)
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setStyleSheet("""
            background-color: #1e1e1e;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 8px;
            font-size: 14px;
        """)
        password_layout.addWidget(self.password_input)

        account_layout.addLayout(password_layout)

        # Remember me checkbox
        self.remember_checkbox = QCheckBox("Remember credentials")
        self.remember_checkbox.setStyleSheet("""
            color: #aaaaaa;
            font-size: 13px;
        """)
        self.remember_checkbox.setChecked(self.remember_credentials)
        account_layout.addWidget(self.remember_checkbox)

        layout.addWidget(account_frame)

        # About section
        about_label = QLabel("Ridley Library Assistant v1.0")
        about_label.setStyleSheet("""
            color: #888888;
            font-size: 12px;
            margin-top: 8px;
        """)
        layout.addWidget(about_label)

        layout.addStretch(1)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 8, 0, 0)
        button_layout.setSpacing(12)

        button_layout.addStretch(1)

        self.cancel_btn = ElegantButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        self.save_btn = ElegantButton("Save", self, primary=True)
        self.save_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.save_btn)

        layout.addLayout(button_layout)


class LibraryAssistantApp(QMainWindow):
    """Main application window for Library Assistant."""

    def __init__(self):
        super().__init__()
        self.settings = Settings()

        # Book data
        self.books = {}  # Dict of book_id: book_info
        self.next_book_id = 1

        # Login state
        self.username = ""
        self.password = ""
        self.is_logged_in = False

        # Worker threads
        self.search_worker = None
        self.search_thread = None
        self.download_worker = None
        self.download_thread = None

        # Create library portal instance
        self.portal = EbookCentralPortal()

        # Logger
        self.logger = logging.getLogger(__name__)

        # Set up the UI
        self.setWindowTitle("Ridley Library Assistant")
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)
        self.resize(1000, 700)  # Default size

        # Set app style - darker theme
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #121212;
                color: #ffffff;
                font-family: Arial, sans-serif;
            }
            QScrollBar:vertical {
                border: none;
                background: #1e1e1e;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #555555;
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0px;
            }
            QSplitter::handle {
                background-color: #2a2a2a;
                width: 1px;
            }
            QLineEdit, QTextEdit, QComboBox {
                background-color: #1e1e1e;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 6px;
            }
        """)

        # Check for first run and show login dialog if needed
        self.check_first_run()

        # Setup the main UI
        self.setup_ui()

        # Try to load credentials from keyring
        if self.settings.get("remember_credentials", True):
            try:
                self.username = keyring.get_password("LibraryAssistant", "username") or ""
                self.password = keyring.get_password("LibraryAssistant", "password") or ""
                if self.username and self.password:
                    self.is_logged_in = True
                    # Update the portal with credentials
                    self.portal.username = self.username
                    self.portal.password = self.password
            except Exception as e:
                self.logger.warning(f"Failed to load credentials: {str(e)}")

        # Enable drag and drop
        self.setAcceptDrops(True)

    def check_first_run(self):
        """Check if this is the first run and show setup dialog if needed."""
        if not self.settings.get("is_configured", False) or not self.settings.get("remember_credentials", False):
            # Show welcome and login dialog
            self.show_login_dialog(first_run=True)
            # Mark as configured
            self.settings.set("is_configured", True)
            self.settings.save()

    def setup_ui(self):
        """Set up the streamlined UI with horizontal layout."""
        # Main widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(0)

        # Create horizontal splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)

        # Left side - Input panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 12, 0)
        left_layout.setSpacing(10)

        # Input panel header with login status
        header_container = QWidget()
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        input_header = QLabel("Book Search")
        input_header.setStyleSheet("""
            color: #ffffff;
            font-size: 15px;
            font-weight: 600;
            margin-bottom: 4px;
        """)
        header_layout.addWidget(input_header)

        header_layout.addStretch(1)

        # Settings button
        self.settings_btn = ElegantButton("Settings")
        self.settings_btn.clicked.connect(self.show_settings)
        header_layout.addWidget(self.settings_btn)

        left_layout.addWidget(header_container)

        # Input options container with frame
        input_frame = ElegantFrame(radius=10, bg_color="#171717")
        input_frame_layout = QVBoxLayout(input_frame)
        input_frame_layout.setContentsMargins(16, 16, 16, 16)
        input_frame_layout.setSpacing(12)

        # Text input for books
        input_frame_layout.addWidget(QLabel("Enter books (one per line, format: Title by Author):"))

        self.books_input = QTextEdit()
        self.books_input.setStyleSheet("""
            background-color: #1e1e1e;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 8px;
            font-size: 13px;
        """)
        self.books_input.setAcceptRichText(False)
        self.books_input.setPlaceholderText("The Great Gatsby by F. Scott Fitzgerald\nTo Kill a Mockingbird by Harper Lee")
        self.books_input.setMinimumHeight(150)
        input_frame_layout.addWidget(self.books_input)

        # Or import from file
        import_container = QWidget()
        import_layout = QHBoxLayout(import_container)
        import_layout.setContentsMargins(0, 0, 0, 0)
        import_layout.setSpacing(8)

        import_label = QLabel("Or import from file:")
        import_label.setStyleSheet("""
            color: #aaaaaa;
            font-size: 13px;
        """)
        import_layout.addWidget(import_label)

        import_layout.addStretch(1)

        self.import_btn = ElegantButton("Browse File")
        self.import_btn.clicked.connect(self.import_from_file)
        import_layout.addWidget(self.import_btn)

        input_frame_layout.addWidget(import_container)

        # Action buttons
        buttons_container = QWidget()
        buttons_layout = QHBoxLayout(buttons_container)
        buttons_layout.setContentsMargins(0, 8, 0, 0)
        buttons_layout.setSpacing(8)

        self.clear_btn = ElegantButton("Clear")
        self.clear_btn.clicked.connect(self.clear_input)
        buttons_layout.addWidget(self.clear_btn)

        buttons_layout.addStretch(1)

        self.search_btn = ElegantButton("Search Books", primary=True)
        self.search_btn.clicked.connect(self.start_search)
        buttons_layout.addWidget(self.search_btn)

        input_frame_layout.addWidget(buttons_container)

        left_layout.addWidget(input_frame)

        # Output folder display
        output_container = QWidget()
        output_layout = QHBoxLayout(output_container)
        output_layout.setContentsMargins(0, 8, 0, 0)
        output_layout.setSpacing(8)

        output_label = QLabel("Downloads folder:")
        output_label.setStyleSheet("""
            color: #aaaaaa;
            font-size: 13px;
        """)
        output_layout.addWidget(output_label)

        self.output_folder_label = QLabel(self.settings.get("output_folder"))
        self.output_folder_label.setStyleSheet("""
            color: #ffffff;
            font-size: 13px;
            padding: 4px 8px;
            background-color: #1e1e1e;
            border-radius: 6px;
        """)
        self.output_folder_label.setMinimumWidth(100)
        self.output_folder_label.setToolTip(self.settings.get("output_folder"))
        output_layout.addWidget(self.output_folder_label, 1)

        self.browse_output_btn = ElegantButton("Browse")
        self.browse_output_btn.clicked.connect(self.browse_output_folder)
        output_layout.addWidget(self.browse_output_btn)

        left_layout.addWidget(output_container)

        # Right side - Results panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 0, 0, 0)
        right_layout.setSpacing(10)

        # Results header with action buttons
        results_header_container = QWidget()
        results_header_layout = QHBoxLayout(results_header_container)
        results_header_layout.setContentsMargins(0, 0, 0, 0)
        results_header_layout.setSpacing(8)

        results_header = QLabel("Results")
        results_header.setStyleSheet("""
            color: #ffffff;
            font-size: 15px;
            font-weight: 600;
            margin-bottom: 4px;
        """)
        results_header_layout.addWidget(results_header)

        results_header_layout.addStretch(1)

        self.download_all_btn = ElegantButton("Download All")
        self.download_all_btn.clicked.connect(self.download_all)
        self.download_all_btn.setEnabled(False)
        results_header_layout.addWidget(self.download_all_btn)

        right_layout.addWidget(results_header_container)

        # Results container with frame
        results_frame = ElegantFrame(radius=10, bg_color="#171717")
        results_frame_layout = QVBoxLayout(results_frame)
        results_frame_layout.setContentsMargins(10, 10, 10, 10)
        results_frame_layout.setSpacing(6)

        # Results list with scroll
        self.results_widget = QWidget()
        self.results_layout = QVBoxLayout(self.results_widget)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(4)
        self.results_layout.addStretch(1)  # Push content to top

        # Scroll area for results
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidget(self.results_widget)
        results_frame_layout.addWidget(scroll_area)

        # Empty state message
        self.empty_results_label = QLabel("No results yet. Enter books and click 'Search'.")
        self.empty_results_label.setStyleSheet("""
            color: #888888;
            font-size: 14px;
            padding: 20px;
            qproperty-alignment: AlignCenter;
        """)
        results_frame_layout.addWidget(self.empty_results_label)

        right_layout.addWidget(results_frame, 1)  # Stretch to fill

        # Add panels to splitter
        self.splitter.addWidget(left_panel)
        self.splitter.addWidget(right_panel)

        # Set initial sizes (left panel smaller than right)
        self.splitter.setSizes([350, 650])

        # Add splitter to main layout
        main_layout.addWidget(self.splitter)

    def show_login_dialog(self, first_run=False):
        """Show login dialog for library portal."""
        dialog = LoginDialog(self, first_run)

        # Pre-fill username if available
        if self.username:
            dialog.username_input.setText(self.username)
            dialog.password_input.setFocus()

        if dialog.exec():
            self.username = dialog.username_input.text().strip()
            self.password = dialog.password_input.text()
            remember = dialog.remember_checkbox.isChecked()

            # Save to settings
            self.settings.set("remember_credentials", remember)
            self.settings.save()

            # Save to keyring if remember is checked
            if remember:
                try:
                    keyring.set_password("LibraryAssistant", "username", self.username)
                    keyring.set_password("LibraryAssistant", "password", self.password)
                except Exception as e:
                    self.logger.warning(f"Failed to save credentials: {str(e)}")

            # Update login status
            if self.username and self.password:
                self.is_logged_in = True
                # Update the portal with credentials
                self.portal.username = self.username
                self.portal.password = self.password

    def show_settings(self):
        """Show settings dialog."""
        dialog = SettingsDialog(self, self.username, self.settings.get("remember_credentials", True))

        if dialog.exec():
            # Get updated settings
            self.username = dialog.username_input.text().strip()
            self.password = dialog.password_input.text()
            remember = dialog.remember_checkbox.isChecked()

            # Save to settings
            self.settings.set("remember_credentials", remember)
            self.settings.save()

            # Save to keyring if remember is checked
            if remember:
                try:
                    keyring.set_password("LibraryAssistant", "username", self.username)
                    keyring.set_password("LibraryAssistant", "password", self.password)
                except Exception as e:
                    self.logger.warning(f"Failed to save credentials: {str(e)}")

            # Update login status
            if self.username and self.password:
                self.is_logged_in = True
                # Update the portal with credentials
                self.portal.username = self.username
                self.portal.password = self.password

    def import_from_file(self):
        """Import book list from text file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Book List File",
            self.settings.get("last_file_path", os.path.expanduser("~")),
            "Text Files (*.txt);;All Files (*.*)"
        )

        if file_path:
            try:
                # Update last file path
                self.settings.set("last_file_path", os.path.dirname(file_path))
                self.settings.save()

                # Read file
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Update text input
                self.books_input.setText(content)

            except Exception as e:
                self.logger.error(f"Error importing file: {str(e)}")
                # Show error message - would use QMessageBox in a real implementation

    def clear_input(self):
        """Clear input fields."""
        self.books_input.clear()

    def browse_output_folder(self):
        """Browse for output folder."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Download Folder",
            self.settings.get("output_folder")
        )

        if folder:
            self.settings.set("output_folder", folder)
            self.settings.save()
            self.output_folder_label.setText(self._format_folder_path(folder))
            self.output_folder_label.setToolTip(folder)

    def _format_folder_path(self, path, max_length=30):
        """Format folder path for display."""
        if len(path) <= max_length:
            return path

        # Show the first and last parts
        head, tail = os.path.split(path)
        if len(tail) > max_length - 5:  # If filename itself is too long
            return "..." + tail[-(max_length-3):]

        # Shorten the middle
        remaining = max_length - len(tail) - 5
        return head[:remaining] + "..." + os.path.sep + tail

    def parse_books(self):
        """Parse book input into structured data."""
        text = self.books_input.toPlainText().strip()
        if not text:
            return []

        books = []
        lines = text.split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Try to parse "Title by Author" format
            match = re.search(r'(.*?)\s+by\s+(.*)', line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                author = match.group(2).strip()
            else:
                # If no "by" found, assume the whole line is the title
                title = line
                author = ""

            if title:
                book_id = f"book_{self.next_book_id}"
                self.next_book_id += 1

                book = {
                    "id": book_id,
                    "title": title,
                    "author": author,
                    "status": "Waiting"
                }

                books.append(book)
                self.books[book_id] = book

        return books

    def start_search(self):
        """Start search process for parsed books."""
        # Parse books
        books = self.parse_books()
        if not books:
            # Show message if no books to search
            return

        # Clear previous results
        self.clear_results()

        # Create result cards for each book
        for book in books:
            self.create_book_card(book)

        # Hide empty state label
        self.empty_results_label.hide()

        # Disable search button during search
        self.search_btn.setEnabled(False)

        # Start worker thread
        self.search_thread = QThread()
        self.search_worker = SearchWorker(books, self.portal, self.username, self.password)
        self.search_worker.moveToThread(self.search_thread)

        # Connect signals
        self.search_thread.started.connect(self.search_worker.search)
        self.search_worker.searchStarted.connect(self.on_search_started)
        self.search_worker.searchResult.connect(self.on_search_result)
        self.search_worker.searchError.connect(self.on_search_error)
        self.search_worker.loginRequired.connect(self.on_login_required)
        self.search_worker.finished.connect(self.on_search_finished)
        self.search_worker.finished.connect(self.search_thread.quit)
        self.search_thread.finished.connect(self.search_worker.deleteLater)
        self.search_thread.finished.connect(lambda: setattr(self, 'search_thread', None))

        # Start thread
        self.search_thread.start()

    def clear_results(self):
        """Clear all results."""
        # Remove all cards
        while self.results_layout.count() > 1:  # Keep the stretch item
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Show empty state label
        self.empty_results_label.show()

        # Disable download all button
        self.download_all_btn.setEnabled(False)

    def create_book_card(self, book):
        """Create and add a book card to results."""
        book_card = BookCard(book)
        book_card.openLinkClicked.connect(self.open_book_link)
        book_card.downloadClicked.connect(self.download_book)

        # Add to layout before the stretch
        self.results_layout.insertWidget(self.results_layout.count() - 1, book_card)

        return book_card

    def on_search_started(self, book_id):
        """Handle search started for a book."""
        if book_id in self.books:
            # Update book status
            self.books[book_id]["status"] = "Searching"

            # Find the card and update it
            for i in range(self.results_layout.count() - 1):  # Skip the stretch item
                widget = self.results_layout.itemAt(i).widget()
                if isinstance(widget, BookCard) and widget.book_info["id"] == book_id:
                    widget.update_status("Searching")
                    break

    def on_search_result(self, book_id, result):
        """Handle search result for a book."""
        if book_id in self.books:
            # Update book info
            self.books[book_id].update(result)

            # Find the card and update it
            for i in range(self.results_layout.count() - 1):  # Skip the stretch item
                widget = self.results_layout.itemAt(i).widget()
                if isinstance(widget, BookCard) and widget.book_info["id"] == book_id:
                    widget.update_details(result)
                    widget.update_status(result.get("status", "Found"))
                    break

            # Enable download all button if any books found
            if result.get("status") == "Found" and result.get("download_url"):
                self.download_all_btn.setEnabled(True)

    def on_search_error(self, book_id, error_message):
        """Handle search error for a book."""
        if book_id in self.books:
            # Update book status
            self.books[book_id]["status"] = "Error"

            # Find the card and update it
            for i in range(self.results_layout.count() - 1):  # Skip the stretch item
                widget = self.results_layout.itemAt(i).widget()
                if isinstance(widget, BookCard) and widget.book_info["id"] == book_id:
                    widget.update_status("Error", error_message)
                    break

    def on_login_required(self):
        """Handle login required notification."""
        # Stop current search
        if self.search_thread and self.search_thread.isRunning():
            self.search_worker.cancel()

        # Show settings dialog
        self.show_settings()

        # Re-enable search button
        self.search_btn.setEnabled(True)

    def on_search_finished(self):
        """Handle search process finished."""
        # Re-enable search button
        self.search_btn.setEnabled(True)

    def open_book_link(self, url):
        """Open book link in external browser."""
        if url:
            # This would use the platform-specific method to open URL
            # For example, on Windows: os.startfile(url)
            # On macOS/Linux: subprocess.call(['open', url]) or equivalent
            print(f"Opening URL: {url}")  # Replace with actual implementation

    def download_book(self, url):
        """Download a single book."""
        if not url:
            return

        # Find the book id from the URL
        book_id = None
        for bid, book in self.books.items():
            if book.get("download_url") == url:
                book_id = bid
                break

        if not book_id:
            return

        # Start download worker with just this book
        books_to_download = {book_id: self.books[book_id]}
        self.start_download(books_to_download)

    def download_all(self):
        """Download all available books."""
        # Create a dict of all downloadable books
        download_books = {}
        for book_id, book in self.books.items():
            if book.get("status") == "Found" and book.get("download_url"):
                download_books[book_id] = book

        if download_books:
            self.start_download(download_books)

    def start_download(self, books_to_download):
        """Start download worker with specified downloads."""
        # Disable download buttons during download
        self.download_all_btn.setEnabled(False)

        # Start worker thread
        self.download_thread = QThread()
        self.download_worker = DownloadWorker(
            books_to_download,
            self.portal,
            self.settings.get("output_folder"),
            self.username,
            self.password
        )
        self.download_worker.moveToThread(self.download_thread)

        # Connect signals
        self.download_thread.started.connect(self.download_worker.download)
        self.download_worker.downloadStarted.connect(self.on_download_started)
        self.download_worker.downloadProgress.connect(self.on_download_progress)
        self.download_worker.downloadComplete.connect(self.on_download_complete)
        self.download_worker.downloadError.connect(self.on_download_error)
        self.download_worker.loginRequired.connect(self.on_login_required)
        self.download_worker.finished.connect(self.on_download_finished)
        self.download_worker.finished.connect(self.download_thread.quit)
        self.download_thread.finished.connect(self.download_worker.deleteLater)
        self.download_thread.finished.connect(lambda: setattr(self, 'download_thread', None))

        # Start thread
        self.download_thread.start()

    def on_download_started(self, book_id):
        """Handle download started for a book."""
        if book_id in self.books:
            # Update book status
            self.books[book_id]["status"] = "Downloading"

            # Find the card and update status
            for i in range(self.results_layout.count() - 1):
                widget = self.results_layout.itemAt(i).widget()
                if isinstance(widget, BookCard) and widget.book_info["id"] == book_id:
                    widget.update_status("Downloading")
                    break

    def on_download_progress(self, book_id, progress):
        """Handle download progress for a book."""
        if book_id in self.books:
            # Find the card and update status with progress
            for i in range(self.results_layout.count() - 1):
                widget = self.results_layout.itemAt(i).widget()
                if isinstance(widget, BookCard) and widget.book_info["id"] == book_id:
                    widget.status_label.setText(f"Downloading: {progress}%")
                    break

    def on_download_complete(self, book_id, file_path):
        """Handle download completed for a book."""
        if book_id in self.books:
            # Update book info
            self.books[book_id]["status"] = "Downloaded"
            self.books[book_id]["local_path"] = file_path

            # Find the card and update status
            for i in range(self.results_layout.count() - 1):
                widget = self.results_layout.itemAt(i).widget()
                if isinstance(widget, BookCard) and widget.book_info["id"] == book_id:
                    widget.update_status("Downloaded")
                    break

    def on_download_error(self, book_id, error_message):
        """Handle download error for a book."""
        if book_id in self.books:
            # Update book status
            self.books[book_id]["status"] = "Error"

            # Find the card and update status
            for i in range(self.results_layout.count() - 1):
                widget = self.results_layout.itemAt(i).widget()
                if isinstance(widget, BookCard) and widget.book_info["id"] == book_id:
                    widget.update_status("Error", error_message)
                    break

    def on_download_finished(self):
        """Handle download process finished."""
        # Re-enable download button
        has_downloadable = any(
            book.get("status") == "Found" and book.get("download_url")
            for book in self.books.values()
        )
        self.download_all_btn.setEnabled(has_downloadable)

    def dragEnterEvent(self, event):
        """Handle drag enter events for files."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path.lower().endswith('.txt'):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event):
        """Handle drop events for files."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path.lower().endswith('.txt'):
                    try:
                        # Read file
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()

                        # Update text input
                        self.books_input.setText(content)

                    except Exception as e:
                        self.logger.error(f"Error importing dropped file: {str(e)}")

                    event.acceptProposedAction()
                    break