"""
Library Assistant - Main entry point.
Elegant, minimal interface for academic resource search and download.
"""
import sys
import traceback

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from library_assistant import LibraryAssistantApp
from settings import Settings
from utils import setup_logging
from library_manager import EbookCentralPortal


def main():
    """Application entry point."""
    # Set up logging
    logger = setup_logging()
    logger.info("Starting Library Assistant")

    # Start application
    app = QApplication(sys.argv)

    # Use modern font
    font = QFont("Arial", 10)
    app.setFont(font)

    # Add exception hook to log uncaught exceptions
    def exception_hook(exctype, value, tb):
        logger.critical(f"Uncaught exception: {value}")
        logger.critical("".join(traceback.format_tb(tb)))
        sys.__excepthook__(exctype, value, tb)

    sys.excepthook = exception_hook

    try:
        # Create settings
        settings = Settings()

        # Create and show main window
        window = LibraryAssistantApp()
        window.show()

        # Run application
        sys.exit(app.exec())

    except Exception as e:
        logger.exception(f"Unhandled exception: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()