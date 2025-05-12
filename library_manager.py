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
        elif level == "warning":
            self.logger.warning(message)

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
        """Search for a book using a hybrid approach - session for login and Selenium for dynamic content."""
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

            # Clean up the search query
            search_query = title.strip()
            if author:
                # Include author in search if provided
                author = author.strip()
                search_query = f"{search_query} {author}"

            self._debug(f"Searching for: '{search_query}'", "info")

            # First, try the existing API search method
            # Get home page to establish proper cookies
            home_url = f"{self.base_url}/lib/{self.lib_id}/home.action"
            self._debug(f"Getting home page to establish cookies: {home_url}", "info")
            home_response = self.session.get(home_url, timeout=30)

            # Try a different API endpoint that might return the results directly
            api_url = f"{self.base_url}/lib/{self.lib_id}/search.action"

            # Pass the search query as a parameter
            params = {
                "query": search_query,
                "pageSize": 10,
                "page": 1,
                "sortBy": "score"
            }

            self._debug(f"Making direct search request: GET {api_url}", "info")
            search_response = self.session.get(api_url, params=params, timeout=30)

            # Analyze the response
            if search_response.status_code == 200:
                self._debug(f"Direct search response received (status 200)", "info")

                # Check if we have results by parsing the HTML
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(search_response.text, 'html.parser')

                # Extract all hyperlinks that might contain book data
                links = soup.find_all('a')
                book_links = [link for link in links if 'docID=' in link.get('href', '')]

                if book_links:
                    # We found at least one book
                    first_book = book_links[0]

                    # Extract book ID from the link
                    href = first_book.get('href', '')
                    book_id_match = re.search(r'docID=([^&]+)', href)
                    book_id = book_id_match.group(1) if book_id_match else ''

                    # Extract title - might be in the link text or nearby element
                    title_text = first_book.get_text().strip()
                    if not title_text:
                        title_element = first_book.find('h3') or first_book.find_next('h3')
                        if title_element:
                            title_text = title_element.get_text().strip()

                    # Extract author if possible
                    author_element = soup.find('a', class_='auth-meta-link')
                    author_text = author_element.get_text().strip() if author_element else author

                    # Construct URLs
                    view_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={book_id}" if book_id else ""
                    download_url = f"{view_url}&download=true" if book_id else ""

                    result = {
                        "status": "Found",
                        "title": title_text or title,
                        "author": author_text,
                        "format": "PDF/EPUB",  # Default format
                        "view_url": view_url,
                        "download_url": download_url,
                        "book_id": book_id,
                        "ebook_id": book_id
                    }

                    self._debug(f"Found book via direct search: {title_text}", "info", result)
                    return result
                else:
                    self._debug("No book links found in direct search response", "info")
                    # Continue to next approach

            # If we didn't find results via direct search, try scraping the search results page
            search_url = f"{self.base_url}/ebc/lib/{self.lib_id}/?query={search_query}"
            self._debug(f"Getting search results page: {search_url}", "info")

            # Use our authenticated session to get the search page
            page_response = self.session.get(search_url, timeout=30)

            if page_response.status_code != 200:
                self._debug(f"Error getting search page: {page_response.status_code}", "error")
                return {
                    "status": "Error",
                    "message": f"Failed to get search page: {page_response.status_code}"
                }

            # Save the HTML for inspection
            with open("search_page.html", "w", encoding="utf-8") as f:
                f.write(page_response.text)
            self._debug("Saved search page HTML for inspection", "info")

            # Try to extract any book IDs using regex
            book_id_matches = re.findall(r'book_results_item_(\d+)', page_response.text)
            detail_matches = re.findall(r'docID=([^&"\']+)', page_response.text)

            if book_id_matches or detail_matches:
                # We found potential book IDs
                book_id = book_id_matches[0] if book_id_matches else (detail_matches[0] if detail_matches else "")
                self._debug(f"Found potential book IDs via regex: {book_id_matches or detail_matches}", "info")

                # Now parse the HTML to extract details
                soup = BeautifulSoup(page_response.text, 'html.parser')

                # Look for book title in various elements
                title_elem = soup.find('h3', class_='title') or soup.find('h3')
                title_text = title_elem.get_text().strip() if title_elem else title

                # Look for author
                author_elem = soup.find('a', class_='auth-meta-link')
                author_text = author_elem.get_text().strip() if author_elem else author

                # Construct URLs
                view_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={book_id}" if book_id else ""
                download_url = f"{view_url}&download=true" if book_id else ""

                result = {
                    "status": "Found",
                    "title": title_text,
                    "author": author_text,
                    "format": "PDF/EPUB",  # Default format
                    "view_url": view_url,
                    "download_url": download_url,
                    "book_id": book_id,
                    "ebook_id": book_id
                }

                self._debug(f"Found book via HTML parsing: {title_text}", "info", result)
                return result

            # If we still haven't found results, try one more approach - checking if the search is
            # returning results but they're hidden in JavaScript data
            script_data_matches = re.findall(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', page_response.text, re.DOTALL)
            if script_data_matches:
                self._debug("Found potential JavaScript data in the page", "info")

                # This would require parsing the JavaScript data, which is complex
                # You might want to use a JavaScript execution environment like Selenium just for this part

                # For now, return that we need further analysis
                return {
                    "status": "Error",
                    "title": title,
                    "author": author,
                    "message": "Search results may be in JavaScript data - needs further analysis"
                }

            # If we've exhausted all options, return not found
            self._debug(f"No results found for: {search_query}", "info")
            return {
                "status": "Not Found",
                "title": title,
                "author": author,
                "message": "No results found after trying multiple approaches"
            }

        except Exception as e:
            error_msg = f"Search error for '{title}': {str(e)}"
            self._debug(error_msg, "error")
            return {
                "status": "Error",
                "title": title,
                "author": author,
                "message": str(e)
            }

    def _parse_api_search_results(self, json_data: Dict, search_title: str, search_author: str) -> Dict:
        """Parse search results from the API JSON response.

        Args:
            json_data: JSON data from API response
            search_title: Original search title
            search_author: Original search author

        Returns:
            Dict with search results
        """
        try:
            # Debug the complete structure of the response
            self._debug("Examining API response structure", "debug",
                    {"keys": list(json_data.keys() if json_data else [])})

            # First check if we have any results
            total_count = json_data.get('totalCount', 0)
            titles = json_data.get('titles', [])

            self._debug(f"API returned {total_count} results, with {len(titles)} titles", "info")

            if not titles or total_count == 0:
                self._debug(f"No results found for: {search_title}", "info")
                return {
                    "status": "Not Found",
                    "title": search_title,
                    "author": search_author,
                    "message": "No results returned from API"
                }

            # Get the first (best) result
            first_result = titles[0]

            # Log sample of the data
            self._debug("First result from API:", "debug", first_result)

            # Extract book details
            book_id = str(first_result.get('id', ''))
            title = first_result.get('title', search_title)

            # Handle authors - might be a list or formatted differently
            authors = first_result.get('authors', [])
            if isinstance(authors, list):
                author = '; '.join(authors) if authors else search_author
            else:
                author = authors or search_author

            publisher = first_result.get('publisher', '')
            year = str(first_result.get('publicationYear', ''))

            # Check if download is available
            download_available = first_result.get('downloadAvailable', False)

            # Extract additional details if present
            isbn = first_result.get('isbn', '')
            eisbn = first_result.get('eisbn', '')

            # Construct URLs
            view_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={book_id}"
            download_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={book_id}&download=true" if download_available else ""

            result = {
                "status": "Found",
                "title": title,
                "author": author,
                "format": "PDF/EPUB",  # Default format for Ebook Central
                "view_url": view_url,
                "download_url": download_url,
                "publisher": publisher,
                "year": year,
                "book_id": book_id,
                "ebook_id": book_id,  # Used for download
                "isbn": isbn,
                "eisbn": eisbn
            }

            self._debug(f"Found book via API: {title} by {author}", "info", result)
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

    def _parse_angular_search_results(self, html_content: str, search_title: str, search_author: str) -> Dict:
        """Parse search results from the Angular UI HTML.

        Args:
            html_content: HTML content of search results page
            search_title: Original search title
            search_author: Original search author

        Returns:
            Dict with search results
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # Look for book containers with the exact class
            result_containers = soup.select('div.pub-list-item-container')

            # If no results found with main selector, try alternative selectors
            if not result_containers:
                # Angular sometimes loads content dynamically, so the content might not be in the initial HTML
                self._debug("No book containers found with primary selector", "info")

                # Look for Angular app elements that might contain book data
                angular_app = soup.select_one('app-search-book-result-item')
                if angular_app:
                    self._debug("Found Angular app components but no book containers", "info")
                    # Angular might load content dynamically after initial HTML load

                # Check if we can find book IDs with regex
                book_id_matches = re.findall(r'book_results_item_(\d+)', html_content)
                if book_id_matches:
                    self._debug(f"Found book IDs via regex: {book_id_matches}", "info")
                    # We found book IDs but couldn't parse containers - might be due to Angular loading

                # Check for Angular data binding attributes that might contain book info
                angular_data = re.search(r'\[books\]="([^"]+)"', html_content)
                if angular_data:
                    self._debug("Found Angular data binding that might contain book data", "info")

                # Check if page is still loading by looking for loading indicators
                loading = soup.select_one('.loading') or 'loading' in html_content.lower()
                if loading:
                    self._debug("Page appears to be still loading", "info")

                # Return not found since we can't properly parse the dynamic content
                return {
                    "status": "Not Found",
                    "title": search_title,
                    "author": search_author,
                    "message": "The search results might be loading dynamically and cannot be parsed from the initial HTML"
                }

            # Process the first result
            first_container = result_containers[0]
            self._debug(f"Found {len(result_containers)} result container(s)", "info")

            # Get the book ID from the container ID attribute
            container_id = first_container.get('id', '')
            book_id_match = re.search(r'book_results_item_(\d+)', container_id)
            book_id = book_id_match.group(1) if book_id_match else ''

            if not book_id:
                self._debug("Could not extract book ID from container", "error")
                return {
                    "status": "Error",
                    "message": "Could not extract book ID",
                    "title": search_title,
                    "author": search_author
                }

            # Get the title from the h3 tag inside the title link
            title_link = first_container.select_one('a.pub-list-item-title-link')
            title_elem = title_link.select_one('h3') if title_link else None
            title = title_elem.get_text().strip() if title_elem else search_title

            # Get author from the auth-meta-link class
            author_links = first_container.select('a.auth-meta-link')
            authors = [link.get_text().strip() for link in author_links if link]
            author = '; '.join(authors) if authors else search_author

            # Get publisher and year
            publisher_link = first_container.select_one('a.meta-publisher-link')
            publisher = publisher_link.get_text().strip() if publisher_link else ""

            year_span = first_container.select_one('span.meta-pub-year')
            year = year_span.get_text().strip() if year_span else ""

            # Check for download button with specific ID
            download_btn_id = f"book_download_link_{book_id}"
            download_btn = first_container.select_one(f'#{download_btn_id}')
            has_download = download_btn is not None

            # Extract view URL from the title link
            view_url = ""
            if title_link and title_link.has_attr('href'):
                href = title_link['href']
                if href.startswith('/'):
                    view_url = f"{self.base_url}{href}"
                elif href.startswith('http'):
                    view_url = href
                else:
                    view_url = f"{self.base_url}/{href}"

            # Construct download URL if download button exists
            download_url = ""
            if has_download:
                doc_id_match = re.search(r'docID=([^&]+)', view_url)
                doc_id = doc_id_match.group(1) if doc_id_match else book_id
                download_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={doc_id}&download=true"

            result = {
                "status": "Found",
                "title": title,
                "author": author,
                "format": "PDF/EPUB",  # Default format for Ebook Central
                "view_url": view_url,
                "download_url": download_url if has_download else "",
                "publisher": publisher,
                "year": year,
                "book_id": book_id,
                "ebook_id": book_id  # Used for download
            }

            self._debug(f"Found book: {title} by {author}", "info", result)
            return result

        except Exception as e:
            error_msg = f"Error parsing Angular search results: {str(e)}"
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