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

    def __init__(self, username: str = "", password: str = ""):
        # Hardcoded values for Ridley College
        self.base_url = "https://ebookcentral.proquest.com"
        self.lib_id = "ridley"  # Institution ID in the URL
        self.ezproxy_url = "https://ezproxy.ridley.edu.au/login"
        self.auth_path = "https://ridley.eblib.com/patron/Authentication.aspx?ebcid=966d562a9fb34b42a8930a460c883505&echo=1"

        self.username = username
        self.password = password
        self.session = requests.Session()
        self.logger = logging.getLogger(__name__)
        self.is_logged_in = False

    def login(self) -> bool:
        """Log in to EZproxy and Ebook Central.

        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            # Construct full login URL with encoded redirect to Ebook Central
            login_url = f"{self.ezproxy_url}?url={urllib.parse.quote(self.auth_path)}"

            if self.username:
                login_url += f"&userid={self.username}"

            # First hit the login page to get cookies and any CSRF tokens
            login_page = self.session.get(login_url)

            if login_page.status_code != 200:
                self.logger.error(f"Failed to access login page: {login_page.status_code}")
                return False

            # Parse the login form
            soup = BeautifulSoup(login_page.text, 'html.parser')
            login_form = soup.find('form')

            if not login_form:
                self.logger.error("Could not find login form")
                return False

            # Get the form action URL and any hidden fields
            action_url = login_form.get('action', '')
            if not action_url:
                action_url = login_url  # Default to original URL if no action found
            elif not action_url.startswith('http'):
                # Handle relative URLs
                action_url = urllib.parse.urljoin(login_url, action_url)

            # Build login data from form fields
            login_data = {}

            # Find input fields (including hidden fields)
            for input_field in login_form.find_all('input'):
                name = input_field.get('name')
                value = input_field.get('value', '')
                if name:
                    login_data[name] = value

            # Set username and password in correct fields
            # Note: Field names might need adjustment based on actual form
            username_field = None
            password_field = None

            for input_field in login_form.find_all('input'):
                input_type = input_field.get('type', '').lower()
                name = input_field.get('name')

                if input_type == 'text' or 'user' in (name or '').lower():
                    username_field = name
                elif input_type == 'password' or 'pass' in (name or '').lower():
                    password_field = name

            if username_field:
                login_data[username_field] = self.username
            if password_field:
                login_data[password_field] = self.password

            # Submit login form
            response = self.session.post(action_url, data=login_data, allow_redirects=True)

            # Check if login was successful
            # For ProQuest Ebook Central, check if we reached the library home
            success = any([
                "ebookcentral.proquest.com/lib/ridley/home.action" in response.url,
                "Authentication successful" in response.text,
                "My Bookshelf" in response.text
            ])

            if success:
                self.logger.info("Login successful")
                self.is_logged_in = True
                return True
            else:
                self.logger.error(f"Login failed. Redirected to: {response.url}")
                return False

        except Exception as e:
            self.logger.exception(f"Login error: {str(e)}")
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
                if not self.login():
                    return {
                        "status": "Error",
                        "message": "Login required"
                    }

            # Prepare search query
            query = f"{title}"
            if author:
                query += f" {author}"

            # Format search URL exactly as provided
            search_url = f"{self.base_url}/ebc/lib/{self.lib_id}/#/search"
            params = {
                "query": query,
                "toChapter": "false",
                "sortBy": "score",
                "pageNo": "1",
                "pageSize": "10",
                "facetPublishedPageSize": "3",
                "facetCategoryPageSize": "5",
                "facetBisacSubjectPageSize": "5",
                "facetLanguagePageSize": "5",
                "facetAuthorPageSize": "5"
            }

            # Construct full search URL
            search_page_url = f"{search_url}?{urllib.parse.urlencode(params)}"
            self.logger.info(f"Searching at URL: {search_page_url}")

            # Load search page
            response = self.session.get(search_page_url)

            if response.status_code != 200:
                return {
                    "status": "Error",
                    "message": f"Search failed with status code: {response.status_code}"
                }

            # Since Ebook Central uses JavaScript to load results, we need to find
            # and call their API directly

            # Try direct API approach first - based on observed behavior
            api_url = f"{self.base_url}/ebc/api/search"

            # Make API request for search results
            api_params = {
                "query": query,
                "libraryId": self.lib_id,
                "pageNo": 1,
                "pageSize": 10,
                "sortBy": "score"
            }

            # Use headers to mimic browser for API request
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Referer": search_page_url,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            # Make the API call
            api_response = self.session.get(api_url, params=api_params, headers=headers)

            if api_response.status_code == 200:
                try:
                    search_data = api_response.json()
                    return self._parse_search_results_from_api(search_data, title, author)
                except json.JSONDecodeError:
                    self.logger.warning("Failed to parse JSON response from API")

            # Fallback: Try to extract results directly from HTML
            return self._parse_search_results_from_html(response.text, title, author)

        except Exception as e:
            self.logger.exception(f"Search error for '{title}': {str(e)}")
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
                return {
                    "status": "Not Found",
                    "title": search_title,
                    "author": search_author
                }

            # Get the first (best) result
            first_result = data['titles'][0]

            book_id = first_result.get('id', '')
            title = first_result.get('title', search_title)
            authors = first_result.get('authors', [])
            author = '; '.join(authors) if authors else search_author
            publisher = first_result.get('publisher', '')
            pub_year = first_result.get('publicationYear', '')

            # Construct view URL
            view_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={book_id}"

            # Determine download URL if available
            # Note: ProQuest often requires multiple steps for download, so this might need adjustment
            download_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={book_id}&download=true"

            # Check if full download is available (based on API response flags)
            full_download_available = first_result.get('downloadAvailable', False)
            if not full_download_available:
                download_url = ""

            return {
                "status": "Found",
                "title": title,
                "author": author,
                "format": "PDF/EPUB",  # ProQuest typically offers PDF and/or EPUB
                "view_url": view_url,
                "download_url": download_url,
                "publisher": publisher,
                "year": pub_year,
                "book_id": book_id
            }

        except Exception as e:
            self.logger.exception(f"Error parsing API results: {str(e)}")
            return {
                "status": "Error",
                "message": f"Error parsing results: {str(e)}",
                "title": search_title,
                "author": search_author
            }

    def _parse_search_results_from_html(self, html_content: str, search_title: str, search_author: str) -> Dict:
        """Parse search results by extracting data from the HTML.

        Args:
            html_content: HTML content to parse
            search_title: Original search title
            search_author: Original search author

        Returns:
            Dict with search results
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # Look for book data in the HTML
            # This is challenging since the data is loaded via JavaScript in Ebook Central
            # We'll look for data embedded in script tags

            # Try to find embedded JSON data in script tags
            script_tags = soup.find_all('script')
            book_data = None

            for script in script_tags:
                script_text = script.string
                if not script_text:
                    continue

                # Look for data structure that might contain book info
                if 'searchResultsJSON' in script_text:
                    json_match = re.search(r'searchResultsJSON\s*=\s*({.*?});', script_text, re.DOTALL)
                    if json_match:
                        try:
                            json_data = json.loads(json_match.group(1))
                            if 'titles' in json_data and json_data['titles']:
                                book_data = json_data
                                break
                        except:
                            pass

            # If we found embedded JSON data, use it
            if book_data and 'titles' in book_data and book_data['titles']:
                return self._parse_search_results_from_api(book_data, search_title, search_author)

            # Fallback: Try to extract info from HTML structure
            # This is challenging due to Ebook Central's dynamic loading

            # Look for book results container
            results_container = soup.find('div', {'class': 'book-results-container'})
            if not results_container:
                # If we can't find a results container, try to check if there's a "no results" message
                no_results = soup.find('div', {'class': 'no-results'})
                if no_results:
                    return {
                        "status": "Not Found",
                        "title": search_title,
                        "author": search_author
                    }

                # If we get here, we'll just have to return an error since we can't reliably extract data
                return {
                    "status": "Error",
                    "message": "Unable to extract search results from page",
                    "title": search_title,
                    "author": search_author
                }

            # Try to extract the first result
            book_item = results_container.find('div', {'class': ['book-item', 'search-result-item']})
            if not book_item:
                return {
                    "status": "Not Found",
                    "title": search_title,
                    "author": search_author
                }

            # Extract details from the book item
            book_id = book_item.get('data-id', '')
            title_elem = book_item.find('h2', {'class': 'title'}) or book_item.find('div', {'class': 'title'})
            title = title_elem.text.strip() if title_elem else search_title

            author_elem = book_item.find('div', {'class': 'authors'}) or book_item.find('span', {'class': 'authors'})
            author = author_elem.text.strip() if author_elem else search_author

            # Construct view URL
            view_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={book_id}"

            # Determine download URL if available
            download_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={book_id}&download=true"

            # Check if download button is present
            download_btn = book_item.find('button', {'class': 'download-button'}) or book_item.find('a', {'class': 'download-button'})
            if not download_btn or 'disabled' in download_btn.get('class', []):
                download_url = ""

            return {
                "status": "Found",
                "title": title,
                "author": author,
                "format": "PDF/EPUB",  # ProQuest typically offers PDF and/or EPUB
                "view_url": view_url,
                "download_url": download_url,
                "book_id": book_id
            }

        except Exception as e:
            self.logger.exception(f"Error parsing HTML results: {str(e)}")
            return {
                "status": "Error",
                "message": f"Error parsing results: {str(e)}",
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
                if not self.login():
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
            self.logger.info(f"Visiting download page: {download_url}")
            download_page = self.session.get(download_url)

            if download_page.status_code != 200:
                return {
                    "success": False,
                    "message": f"Download page access failed: {download_page.status_code}"
                }

            # Step 2: Find and select format
            soup = BeautifulSoup(download_page.text, 'html.parser')

            # Look for download options form
            download_form = soup.find('form', {'id': 'downloadForm'}) or soup.find('form', {'name': 'downloadForm'})
            if not download_form:
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

            # Step 3: Submit form to confirm download
            if form_method == 'post':
                confirm_response = self.session.post(form_action, data=form_data)
            else:
                confirm_response = self.session.get(form_action, params=form_data)

            if confirm_response.status_code != 200:
                return {
                    "success": False,
                    "message": f"Download confirmation failed: {confirm_response.status_code}"
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

                        # Submit form to get download
                        form_method = download_form.get('method', 'post').lower()
                        if form_method == 'post':
                            download_response = self.session.post(form_action, data=final_form_data, stream=True)
                        else:
                            download_response = self.session.get(form_action, params=final_form_data, stream=True)
                    else:
                        return {
                            "success": False,
                            "message": "Could not find download action"
                        }
                else:
                    return {
                        "success": False,
                        "message": "Could not find download link or form"
                    }
            else:
                # Use the direct download link
                download_response = self.session.get(download_link, stream=True)

            # Check if download succeeded
            if download_response.status_code != 200:
                return {
                    "success": False,
                    "message": f"File download failed: {download_response.status_code}"
                }

            # Determine file extension from content-type
            content_type = download_response.headers.get('content-type', '').lower()
            ext = '.pdf' if 'pdf' in content_type else '.epub' if 'epub' in content_type else '.bin'

            # If output_path doesn't have the right extension, add it
            if not output_path.lower().endswith(ext):
                output_path = f"{os.path.splitext(output_path)[0]}{ext}"

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Save the file
            total_length = int(download_response.headers.get('content-length', 0))
            downloaded = 0

            with open(output_path, 'wb') as f:
                for chunk in download_response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Update progress if callback provided
                        if callback and total_length:
                            callback(downloaded, total_length)

            return {
                "success": True,
                "file_path": output_path,
                "format": ext[1:].upper()  # Remove leading dot
            }

        except Exception as e:
            self.logger.exception(f"Download error: {str(e)}")
            return {
                "success": False,
                "message": str(e)
            }

    def get_book_details(self, book_id: str) -> Dict:
        """Get detailed information about a book.

        Args:
            book_id: Book ID

        Returns:
            Dict with detailed book information
        """
        try:
            # Ensure we're logged in if credentials are provided
            if self.username and self.password and not self.is_logged_in:
                if not self.login():
                    return {
                        "success": False,
                        "message": "Login required"
                    }

            # Construct detail URL
            detail_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={book_id}"

            # Get book detail page
            response = self.session.get(detail_url)

            if response.status_code != 200:
                return {
                    "success": False,
                    "message": f"Detail page access failed: {response.status_code}"
                }

            # Parse details from the page
            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract basic info
            title_elem = soup.find('h1', {'id': 'bookTitle'}) or soup.find('h1', {'class': 'title'})
            title = title_elem.text.strip() if title_elem else ""

            author_elem = soup.find('div', {'class': 'authors'}) or soup.find('span', {'class': 'authors'})
            author = author_elem.text.strip() if author_elem else ""

            # Extract metadata
            metadata = {}
            metadata_table = soup.find('table', {'class': 'bookMetadata'})
            if metadata_table:
                rows = metadata_table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        key = cells[0].text.strip().rstrip(':')
                        value = cells[1].text.strip()
                        metadata[key] = value

            # Check if download is available
            download_available = False
            download_btn = soup.find('button', {'id': 'downloadButton'}) or soup.find('a', {'id': 'downloadButton'})
            if download_btn and 'disabled' not in download_btn.get('class', []):
                download_available = True

            # Create download URL if available
            download_url = f"{self.base_url}/lib/{self.lib_id}/detail.action?docID={book_id}&download=true" if download_available else ""

            return {
                "success": True,
                "title": title,
                "author": author,
                "metadata": metadata,
                "download_available": download_available,
                "download_url": download_url,
                "view_url": detail_url,
                "book_id": book_id
            }

        except Exception as e:
            self.logger.exception(f"Error getting book details: {str(e)}")
            return {
                "success": False,
                "message": str(e)
            }