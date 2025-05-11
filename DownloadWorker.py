"""
Worker thread for downloading books in the background.
"""
import os
import time
import logging
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal


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
        self.logger.info("Download cancellation requested")

    def download(self):
        """Download books to the output folder."""
        try:
            # Update portal credentials
            self.portal.username = self.username
            self.portal.password = self.password

            # First try logging in if credentials provided
            if self.username and self.password and not self.portal.is_logged_in:
                self.logger.info(f"Attempting login with username: {self.username}")
                start_time = time.time()
                success = self.portal.login()
                elapsed = time.time() - start_time

                if not success:
                    self.logger.error(f"Login failed in download worker (took {elapsed:.2f}s)")
                    self.loginRequired.emit()
                    self.finished.emit()
                    return
                else:
                    self.logger.info(f"Login successful in download worker (took {elapsed:.2f}s)")
            elif not self.username or not self.password:
                self.logger.warning("Missing credentials for login")
                self.loginRequired.emit()
                self.finished.emit()
                return
            elif self.portal.is_logged_in:
                self.logger.info("Already logged in, proceeding with download")

            # Ensure output folder exists
            os.makedirs(self.output_folder, exist_ok=True)
            self.logger.info(f"Output folder: {self.output_folder}")

            # Process each book
            for book_id, book_info in self.books.items():
                if self.cancel_flag:
                    self.logger.info("Download cancelled")
                    break

                self.logger.info(f"Starting download for book ID: {book_id}")
                self.downloadStarted.emit(book_id)

                try:
                    # Get required info from book_info
                    download_url = book_info.get("download_url", "")
                    title = book_info.get("title", "Unknown")
                    author = book_info.get("author", "Unknown")
                    ebook_id = book_info.get("ebook_id", "")

                    # Log book details
                    self.logger.info(f"Book details - Title: {title}, Author: {author}")
                    self.logger.info(f"Download URL: {download_url}")

                    if not download_url:
                        self.logger.error(f"No download URL available for book: {title}")
                        raise ValueError("No download URL available")

                    # Create a clean filename
                    if author:
                        filename = f"{author} - {title}"
                    else:
                        filename = title

                    filename = self._clean_filename(filename)
                    output_path = os.path.join(self.output_folder, filename)

                    self.logger.info(f"Downloading book to: {output_path}")

                    # Download the book
                    start_time = time.time()
                    result = self.portal.download_book(
                        download_url,
                        ebook_id,
                        output_path,
                        callback=lambda received, total: self._handle_progress(book_id, received, total)
                    )
                    elapsed = time.time() - start_time

                    if result["success"]:
                        # Emit completion signal
                        self.logger.info(f"Download complete: {result['file_path']} (took {elapsed:.2f}s)")
                        self.downloadComplete.emit(book_id, result["file_path"])
                    else:
                        # Emit error signal
                        self.logger.error(f"Download failed: {result.get('message', 'Unknown error')} (took {elapsed:.2f}s)")
                        self.downloadError.emit(book_id, result.get("message", "Download failed"))

                except Exception as e:
                    self.logger.exception(f"Error downloading book {book_id}: {str(e)}")
                    self.downloadError.emit(book_id, str(e))

        except Exception as e:
            self.logger.exception(f"Error in download worker: {str(e)}")
        finally:
            self.logger.info("Download worker finished")
            self.finished.emit()

    def _handle_progress(self, book_id, received, total):
        """Handle download progress updates."""
        if total > 0 and not self.cancel_flag:
            progress = int((received / total) * 100)

            # Only emit progress updates on significant changes to reduce overhead
            if progress % 5 == 0:  # Every 5%
                self.downloadProgress.emit(book_id, progress)
                self.logger.debug(f"Download progress for {book_id}: {progress}% ({received}/{total} bytes)")

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

        # Add .pdf extension if no extension present
        if not os.path.splitext(filename)[1]:
            filename += ".pdf"

        return filename