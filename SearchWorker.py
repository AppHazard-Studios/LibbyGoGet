"""
Worker thread for searching books in the background.
"""
import time
import logging
from PyQt6.QtCore import QObject, pyqtSignal


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
