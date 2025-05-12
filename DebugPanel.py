"""
Debug panel to display real-time information about application operations.
"""

import json
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QPushButton, QLabel, 
    QCheckBox, QHBoxLayout, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSlot, QSize
from PyQt6.QtGui import QColor, QTextCursor, QFont


class DebugPanel(QWidget):
    """Debug panel that shows real-time logs and network operations."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Set up logger
        # Set up logger
        self.logger = logging.getLogger(__name__)
        
        # Create UI
        self.setup_ui()
        
        # Initialize counters
        self.message_count = 0
        self.max_messages = 1000  # Limit messages to avoid memory issues
        
    def setup_ui(self):
        """Set up the debug panel UI."""
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Title and controls
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 8, 8, 8)
        
        title = QLabel("Debug Console")
        title.setStyleSheet("""
            font-weight: bold;
            font-size: 14px;
            color: #cccccc;
        """)
        header_layout.addWidget(title)
        
        # Auto-scroll checkbox
        self.auto_scroll = QCheckBox("Auto-scroll")
        self.auto_scroll.setChecked(True)
        header_layout.addWidget(self.auto_scroll)
        
        header_layout.addStretch(1)
        
        # Clear button
        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet("""
            background-color: #333333;
            color: #ffffff;
            padding: 4px 8px;
            border: none;
            border-radius: 4px;
        """)
        clear_btn.clicked.connect(self.clear_log)
        header_layout.addWidget(clear_btn)
        
        layout.addWidget(header)
        
        # Splitter for log and details
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        
        # Log text area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            background-color: #1a1a1a;
            color: #cccccc;
            font-family: monospace;
            font-size: 12px;
            border: none;
        """)
        splitter.addWidget(self.log_text)
        
        # Details text area
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setStyleSheet("""
            background-color: #1a1a1a;
            color: #cccccc;
            font-family: monospace;
            font-size: 12px;
            border: none;
        """)
        self.details_text.setMaximumHeight(200)
        self.details_text.setVisible(False)  # Hidden initially
        splitter.addWidget(self.details_text)
        
        # Set initial splitter sizes
        splitter.setSizes([700, 300])
        
        layout.addWidget(splitter, 1)
        
        # Set the background color
        self.setStyleSheet("""
            background-color: #1a1a1a;
            color: #cccccc;
        """)
        
    def format_data(self, data):
        """Format data for display."""
        if not data:
            return ""
            
        if isinstance(data, dict) or isinstance(data, list):
            try:
                return json.dumps(data, indent=2)
            except:
                return str(data)
        return str(data)
        
    @pyqtSlot(str, str, object)
    def add_message(self, message, level="info", data=None):
        """Add a message to the debug log.
        
        Args:
            message: Message text
            level: Log level (info, error, debug)
            data: Optional data object to display in details
        """
        # Create formatted message
        timestamp = logging.Formatter().converter()
        time_str = logging.Formatter().formatTime(timestamp, "%H:%M:%S")
        
        # Color based on level
        if level == "error":
            color = QColor(239, 83, 80)  # Red
        elif level == "debug":
            color = QColor(156, 156, 156)  # Gray
        else:
            color = QColor(220, 220, 220)  # Light gray
            
        # Add message to log
        self.log_text.setTextColor(color)
        
        prefix = f"[{time_str}] "
        
        # Add level indicator for non-info messages
        if level != "info":
            prefix += f"[{level.upper()}] "
            
        # Add the message
        self.log_text.append(f"{prefix}{message}")
        
        # If data provided, add indication and store it
        if data:
            # Show a data indicator
            self.log_text.setTextColor(QColor(100, 181, 246))  # Light blue
            self.log_text.insertPlainText(" [+]")
            
            # Show data in details panel
            self.details_text.clear()
            self.details_text.setTextColor(QColor(200, 200, 200))
            
            formatted_data = self.format_data(data)
            self.details_text.setText(formatted_data)
            
            # Make details visible
            self.details_text.setVisible(True)
            
        # Auto-scroll if enabled
        if self.auto_scroll.isChecked():
            scrollbar = self.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            
        # Increment counter and check if we need to trim
        self.message_count += 1
        if self.message_count > self.max_messages:
            # Remove the oldest half of messages
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(
                QTextCursor.MoveOperation.Down, 
                QTextCursor.MoveMode.KeepAnchor, 
                self.max_messages // 2
            )
            cursor.removeSelectedText()
            self.message_count = self.max_messages // 2
            
    def clear_log(self):
        """Clear the debug log."""
        self.log_text.clear()
        self.details_text.clear()
        self.message_count = 0
        
    def set_font_size(self, size):
        """Change the font size."""
        self.log_text.setFont(QFont("monospace", size))
        self.details_text.setFont(QFont("monospace", size))
