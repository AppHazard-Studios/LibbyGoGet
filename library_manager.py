"""
ProQuest Ebook Central integration module.
Handles searching and downloading from Ridley library's Ebook Central platform.
"""
import os
import re
import time
import logging
import requests
import urllib.parse
import json
from typing import Dict, List, Tuple, Optional
from bs4 import BeautifulSoup


class EbookCentralPortal:
    """Class to interact with ProQuest Ebook Central via EZproxy."""

    def __init__(self, username: str = "", password: str = "", debug_callback=None):
        # Hardcoded values for Ridley College
        self.base_url = "https://ebookcentral.proquest.com"
        self.lib_id = "ridley"  # Institution ID in the URL
        self.ezproxy_url = "https://ezproxy.ridley.edu.au/login"
        self.auth_path = "https://ridley.eblib.com/patron/Authentication.aspx?ebcid=966d562a9fb34b42a8930a460c883505&echo=1"

        # Store debug callback function for UI feedback
        self.debug_callback = debug_callback

        # Authentication state
        self.username = username
        self.password = password
        self.is_logged_in = False

        # Set up session with headers that mimic a browser
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })

        # Configure logging
        self.logger = logging.getLogger(__name__)

    def _debug(self, message, level="info", data=None):
        """Send debug info to both logger and UI callback if available."""
        if level == "info":
            self.logger.info(message)
        elif level == "error":
            self.logger.error(message)
        elif level == "debug":
            self.logger.debug(message)

        # Also send to UI callback if available
        if self.debug_callback:
            self.debug_callback(message, level, data)

    def test_connection(self) -> Dict:
        """Test connection to ProQuest Ebook Central with current credentials.

        Returns:
            Dict with status and detailed information about the connection
        """
        self._debug("Testing connection to ProQuest Ebook Central")
        result = {
            "success": False,
            "message": "",
            "url": "",
            "status_code": 0,
            "response_text": "",
            "is_logged_in": False
        }

        try:
            # Clear any existing cookies
            self.session.cookies.clear()
            self._debug("Cleared previous cookies")

            # Try to access the homepage without logging in
            self._debug(f"Testing direct access to: {self.base_url}/lib/{self.lib_id}/home.action")
            home_response = self.session.get(
                f"{self.base_url}/lib/{self.lib_id}/home.action",
                timeout=30,
                allow_redirects=True
            )

            result["status_code"] = home_response.status_code
            result["url"] = home_response.url

            # Check if already logged in directly
            if "Ebook Central" in home_response.text and "Bookshelf" in home_response.text:
                result["success"] = True
                result["message"] = "Already logged in (direct access)"
                result["is_logged_in"] = True
                self.is_logged_in = True
                self._debug("Already logged in (direct access)", "info", result)
                return result

            # Try standard login if needed
            self._debug(f"Direct access requires login. Attempting standard login with username: {self.username}")

            # Attempt EZproxy login
            login_url = self.ezproxy_url
            login_data = {
                'user': self.username,
                'pass': self.password,
                'url': self.auth_path
            }

            self._debug(f"Logging in via EZproxy: POST {login_url}")
            login_response = self.session.post(
                login_url,
                data=login_data,
                timeout=30,
                allow_redirects=True
            )

            result["status_code"] = login_response.status_code
            result["url"] = login_response.url

            # Save a snippet of the response text for debugging (first 500 chars)
            response_snippet = login_response.text[:500] + "..." if len(login_response.text) > 500 else login_response.text
            result["response_text"] = response_snippet

            # Check for successful login
            success_indicators = [
                "ebookcentral.proquest.com/lib/ridley/home.action" in login_response.url,
                "Authentication successful" in login_response.text,
                "My Bookshelf" in login_response.text,
                "/ebc/" in login_response.url,
                "ProQuest Ebook Central" in login_response.text and "Bookshelf" in login_response.text
            ]

            if any(success_indicators):
                result["success"] = True
                result["message"] = "Login successful"
                result["is_logged_in"] = True
                self.is_logged_in = True
                self._debug(f"Login successful! Redirected to: {login_response.url}", "info", result)
            else:
                result["success"] = False
                result["message"] = "Login failed. Check credentials."
                result["is_logged_in"] = False
                self.is_logged_in = False
                self._debug(f"Login failed. Redirected to: {login_response.url}", "error", result)

            return result

        except requests.Timeout:
            result["success"] = False
            result["message"] = "Connection timed out"
            self._debug("Connection timed out during test", "error")
            return result
        except requests.ConnectionError:
            result["success"] = False
            result["message"] = "Connection error (check network)"
            self._debug("Connection error during test", "error")
            return result
        except Exception as e:
            result["success"] = False
            result["message"] = f"Error: {str(e)}"
            self._debug(f"Error during connection test: {str(e)}", "error")
            return result

    def login(self) -> bool:
        """Log in to EZproxy and Ebook Central.

        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            # Test connection and login in one step
            result = self.test_connection()
            return result["success"]

        except Exception as e:
            self._debug(f"Login error: {str(e)}", "error")
            return False

    def search_book(self, title: str, author: str = "") -> Dict:
        """Search for a book in Ebook Central.

        Args:
            title: Book title
            author: Book author (optional)

        Returns:
            Dict containing search results
        """
        try:
            # Ensure we're logged in if credentials are provided
            if self.username and self.password and not self.is_logged_in:
                login_success = self.login()
                if not login_success:
                    self._debug("Login required for search", "error")
                    return {
                        "status": "Error",
                        "message": "Login required"
                    }

            # Prepare search query
            query = f"{title}"
            if author:
                query += f" {author}"

            self._debug(f"Searching for: '{query}'")

            # Use the API approach for searching
            api_url = f"{self.base_url}/ebc/api/search"

            # API parameters - keep it simple
            api_params = {
                "query": query.strip(),
                "libraryId": self.lib_id,
                "pageNo": 1,
                "pageSize": 20,
                "sortBy": "score"
            }

            # Use headers to mimic browser for API request
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Referer": f"{self.base_url}/lib/{self.lib_id}/home.action"
            }

            # Make the API call
            self._debug(f"API request to: {api_url} with params: {api_params}")

            api_response = self.session.get(
                api_url,
                params=api_params,
                headers=headers,
                timeout=30
            )

            self._debug(f"API response status: {api_response.status_code}")

            # Handle API response
            if api_response.status_code == 200:
                try:
                    # Parse JSON response
                    search_data = api_response.json()

                    # Log a sample of the data
                    self._debug("API returned data", "debug", {
                        "totalCount": search_data.get("totalCount", 0),
                        "titles_count": len(search_data.get("titles", [])),
                        "sample": search_data.get("titles", [])[:1]  # First result only
                    })

                    # Parse the results
                    return self._parse_search_results_from_api(search_data, title, author)

                except json.JSONDecodeError:
                    error_msg = "Failed to parse JSON response from API"
                    self._debug(error_msg, "error", {"response": api_response.text[:500]})
                    return {
                        "status": "Error",
                        "message": error_msg
                    }
            else:
                error_msg = f"API search failed with status code: {api_response.status_code}"
                self._debug(error_msg, "error")
                return {
                    "status": "Error",
                    "message": error_msg
                }

        except requests.Timeout:
            error_msg = "Search timed out"
            self._debug(error_msg, "error")
            return {
                "status": "Error",
                "message": error_msg
            }
        except Exception as e:
            error_msg = f"Search error for '{title}': {str(e)}"
            self._debug(error_msg, "error")
            return {
                "status": "Error",
                "message": str(e)
            }

    def _parse_search_results_from_api(self, data: Dict, search_title: str, search_author: str) -> Dict:
        """Parse search results from Ebook Central API response.

        Args:
            data: JSON data from API
            search_title: Original search title
            search_author: Original search author

        Returns:
            Dict with search results
        """
        try:
            # Check if we have results
            if 'titles' not in data or not data['titles'] or data.get('totalCount', 0) == 0:
                self._debug(f"No results found for: {search_title}", "info")
                return {
                    "status": "Not Found",
                    "title": search_title,
                    "author": search_author
                }

            # Get the first (best) result
            first_result = data['titles'][0]

            self._debug(f"Found result: {first_result.get('title')}", "info", first_result)

            book_id = first_result.get('id', '')
            title = first_result.get('title', search_title)
            authors = first_result.get('authors', [])
            author = '; '.join(authors) if authors else search_author
            publisher = first_result.get('publisher', '')
            pub_year = first_result.get('publicationYear', '')

            # Construct view URL
            view_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={book_id}"

            # Determine download URL if available
            download_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={book_id}&download=true"

            # Check if full download is available (based on API response flags)
            full_download_available = first_result.get('downloadAvailable', False)
            if not full_download_available:
                download_url = ""
                self._debug(f"Download not available for: {title}", "info")

            result = {
                "status": "Found",
                "title": title,
                "author": author,
                "format": "PDF/EPUB",  # ProQuest typically offers PDF and/or EPUB
                "view_url": view_url,
                "download_url": download_url,
                "publisher": publisher,
                "year": pub_year,
                "book_id": book_id,
                "ebook_id": book_id  # Used for download
            }

            self._debug(f"Parsed result: {title} by {author}", "info", result)
            return result

        except Exception as e:
            error_msg = f"Error parsing API results: {str(e)}"
            self._debug(error_msg, "error")
            return {
                "status": "Error",
                "message": error_msg,
                "title": search_title,
                "author": search_author
            }

    def download_book(self, download_url: str, book_id: str, output_path: str, callback=None) -> Dict:
        """Download a book from Ebook Central.

        Args:
            download_url: URL to download the resource
            book_id: Book ID for the resource
            output_path: Path to save the downloaded file
            callback: Optional callback function for progress updates

        Returns:
            Dict with results
        """
        try:
            # Ensure we're logged in if credentials are provided
            if self.username and self.password and not self.is_logged_in:
                login_success = self.login()
                if not login_success:
                    self._debug("Login required for download", "error")
                    return {
                        "success": False,
                        "message": "Login required"
                    }

            # ProQuest Ebook Central has a multi-step download process:
            # 1. Visit the download page
            # 2. Select format (usually PDF or EPUB)
            # 3. Confirm download
            # 4. Get actual download link

            # Step 1: Visit download page
            self._debug(f"Visiting download page: {download_url}")
            download_page = self.session.get(download_url, timeout=30)

            if download_page.status_code != 200:
                error_msg = f"Download page access failed: {download_page.status_code}"
                self._debug(error_msg, "error")
                return {
                    "success": False,
                    "message": error_msg
                }

            # Step 2: Find and select format
            soup = BeautifulSoup(download_page.text, 'html.parser')

            # Look for download options form
            download_form = soup.find('form', {'id': 'downloadForm'}) or soup.find('form', {'name': 'downloadForm'})
            if not download_form:
                self._debug("Could not find download form", "error",
                           {"page_snippet": download_page.text[:1000]})
                return {
                    "success": False,
                    "message": "Could not find download form"
                }

            # Extract form action and method
            form_action = download_form.get('action', '')
            form_method = download_form.get('method', 'post').lower()

            if not form_action:
                form_action = download_url
            elif not form_action.startswith('http'):
                form_action = urllib.parse.urljoin(download_url, form_action)

            self._debug(f"Download form action: {form_action}, method: {form_method}")

            # Prepare form data from all inputs
            form_data = {}
            for input_field in download_form.find_all(['input', 'select']):
                name = input_field.get('name')
                value = input_field.get('value', '')

                if name:
                    # If this is a format selection, prefer PDF
                    if name == 'format':
                        # Check if PDF is available
                        pdf_option = input_field.find('option', {'value': 'pdf'}) or input_field.find('option', text=re.compile('PDF', re.I))
                        if pdf_option:
                            value = pdf_option.get('value', 'pdf')
                        elif input_field.name == 'select':
                            # If no PDF, use first option
                            first_option = input_field.find('option')
                            if first_option:
                                value = first_option.get('value', '')

                    form_data[name] = value

            # If docID is missing, add it
            if 'docID' not in form_data and book_id:
                form_data['docID'] = book_id

            self._debug(f"Download form data: {form_data}")

            # Step 3: Submit form to confirm download
            self._debug(f"Submitting download form to: {form_action}")
            if form_method == 'post':
                confirm_response = self.session.post(form_action, data=form_data, timeout=30)
            else:
                confirm_response = self.session.get(form_action, params=form_data, timeout=30)

            if confirm_response.status_code != 200:
                error_msg = f"Download confirmation failed: {confirm_response.status_code}"
                self._debug(error_msg, "error")
                return {
                    "success": False,
                    "message": error_msg
                }

            # Step 4: Get actual download link from confirmation page
            confirm_soup = BeautifulSoup(confirm_response.text, 'html.parser')

            # Look for download link or form
            download_link = None

            # Try finding a direct download link
            link_elements = confirm_soup.find_all('a')
            for link in link_elements:
                if any(term in (link.text.lower() or '') for term in ['download', 'get book', 'get pdf', 'get epub']):
                    download_link = link.get('href')
                    if download_link and not download_link.startswith('http'):
                        download_link = urllib.parse.urljoin(confirm_response.url, download_link)
                    break

            if download_link:
                self._debug(f"Found direct download link: {download_link}")
            else:
                self._debug("No direct download link found, looking for form")

            # If no direct link, look for a form that submits the download
            if not download_link:
                download_form = confirm_soup.find('form', {'id': 'downloadForm'}) or confirm_soup.find('form', {'name': 'downloadForm'})
                if download_form:
                    form_action = download_form.get('action', '')
                    if form_action:
                        if not form_action.startswith('http'):
                            form_action = urllib.parse.urljoin(confirm_response.url, form_action)

                        # Prepare form data
                        final_form_data = {}
                        for input_field in download_form.find_all('input'):
                            name = input_field.get('name')
                            value = input_field.get('value', '')
                            if name:
                                final_form_data[name] = value

                        self._debug(f"Found download form with action: {form_action}")

                        # Submit form to get download
                        form_method = download_form.get('method', 'post').lower()
                        self._debug(f"Submitting final download form")
                        if form_method == 'post':
                            download_response = self.session.post(form_action, data=final_form_data, stream=True, timeout=30)
                        else:
                            download_response = self.session.get(form_action, params=final_form_data, stream=True, timeout=30)
                    else:
                        error_msg = "Could not find download action"
                        self._debug(error_msg, "error")
                        return {
                            "success": False,
                            "message": error_msg
                        }
                else:
                    error_msg = "Could not find download link or form"
                    self._debug(error_msg, "error",
                               {"page_snippet": confirm_response.text[:1000]})
                    return {
                        "success": False,
                        "message": error_msg
                    }
            else:
                # Use the direct download link
                self._debug(f"Starting download from direct link")
                download_response = self.session.get(download_link, stream=True, timeout=30)

            # Check if download succeeded
            if download_response.status_code != 200:
                error_msg = f"File download failed: {download_response.status_code}"
                self._debug(error_msg, "error")
                return {
                    "success": False,
                    "message": error_msg
                }

            # Determine file extension from content-type
            content_type = download_response.headers.get('content-type', '').lower()
            self._debug(f"Download content type: {content_type}")

            ext = '.pdf' if 'pdf' in content_type else '.epub' if 'epub' in content_type else '.bin'

            # If output_path doesn't have the right extension, add it
            if not output_path.lower().endswith(ext):
                output_path = f"{os.path.splitext(output_path)[0]}{ext}"

            self._debug(f"Saving download to: {output_path}")

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Save the file
            total_length = int(download_response.headers.get('content-length', 0))
            downloaded = 0

            self._debug(f"Total download size: {total_length} bytes")

            with open(output_path, 'wb') as f:
                for chunk in download_response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Update progress if callback provided
                        if callback and total_length:
                            callback(downloaded, total_length)

            self._debug(f"Download complete: {downloaded} bytes saved")

            return {
                "success": True,
                "file_path": output_path,
                "format": ext[1:].upper()  # Remove leading dot
            }

        except requests.Timeout:
            error_msg = "Download timed out"
            self._debug(error_msg, "error")
            return {
                "success": False,
                "message": error_msg
            }
        except Exception as e:
            error_msg = f"Download error: {str(e)}"
            self._debug(error_msg, "error")
            return {
                "success": False,
                "message": str(e)
            }