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
