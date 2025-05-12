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
        self.logger.info("Search cancellation requested")

    def search(self):
        """Search for books on the library portal."""
        try:
            # Update portal credentials
            self.portal.username = self.username
            self.portal.password = self.password

            # If empty book list, just verify login and return
            if not self.books:
                self.logger.info("No books to search, just verifying login")
                # First try logging in if credentials provided
                if self.username and self.password and not self.portal.is_logged_in:
                    self.logger.info(f"Attempting login verification with username: {self.username}")
                    success = self.portal.login()
                    if not success:
                        self.logger.error("Login verification failed")
                        self.loginRequired.emit()
                    else:
                        self.logger.info("Login verification successful")

                self.finished.emit()
                return

            # First try logging in if credentials provided
            if self.username and self.password and not self.portal.is_logged_in:
                self.logger.info(f"Attempting login with username: {self.username}")
                start_time = time.time()
                success = self.portal.login()
                elapsed = time.time() - start_time

                if not success:
                    self.logger.error(f"Login failed in search worker (took {elapsed:.2f}s)")
                    self.loginRequired.emit()
                    self.finished.emit()
                    return
                else:
                    self.logger.info(f"Login successful in search worker (took {elapsed:.2f}s)")
            elif not self.username or not self.password:
                self.logger.warning("Missing credentials for login")
                self.loginRequired.emit()
                self.finished.emit()
                return
            elif self.portal.is_logged_in:
                self.logger.info("Already logged in, proceeding with search")

            # Process each book
            for book in self.books:
                if self.cancel_flag:
                    self.logger.info("Search cancelled")
                    break

                book_id = book["id"]
                self.logger.info(f"Searching for book: {book['title']} by {book['author']}")
                self.searchStarted.emit(book_id)

                try:
                    # Search for this book using the portal
                    start_time = time.time()
                    result = self.portal.search_book(book["title"], book["author"])
                    elapsed = time.time() - start_time

                    # Add book_id to result for reference
                    result["book_id"] = book_id

                    self.logger.info(f"Search result for {book_id}: {result.get('status', 'Unknown')} (took {elapsed:.2f}s)")
                    self.searchResult.emit(book_id, result)

                except Exception as e:
                    self.logger.exception(f"Error searching for book {book_id}: {str(e)}")
                    self.searchError.emit(book_id, str(e))

        except Exception as e:
            self.logger.exception(f"Error in search worker: {str(e)}")
        finally:
            self.logger.info("Search worker finished")
            self.finished.emit()