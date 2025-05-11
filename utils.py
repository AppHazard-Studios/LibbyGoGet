"""
Utility functions for Library Assistant.
"""
import os
import re
import logging
import hashlib
from pathlib import Path
from datetime import datetime


def setup_logging(log_level=logging.INFO):
    """Set up logging configuration.

    Args:
        log_level: Logging level (default: INFO)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)

    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)

    # Add console handler to logger
    logger.addHandler(console_handler)

    # Create file handler in logs directory
    try:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # Use date in log filename
        date_str = datetime.now().strftime("%Y%m%d")
        log_file = log_dir / f"library_assistant_{date_str}.log"

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)

        # Add file handler to logger
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not set up file logging: {str(e)}")

    return logger


def generate_book_id(title, author):
    """Generate a unique ID for a book based on title and author.

    Args:
        title: Book title
        author: Book author

    Returns:
        Unique identifier string
    """
    # Create a hash from the title and author
    text = f"{title.lower().strip()}|{author.lower().strip()}"
    hash_obj = hashlib.md5(text.encode())
    hash_str = hash_obj.hexdigest()[:10]

    # Return a prefixed ID
    return f"book_{hash_str}"


def clean_filename(filename):
    """Clean a filename to make it safe for all filesystems.

    Args:
        filename: Original filename

    Returns:
        Cleaned filename
    """
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
        filename = "untitled"

    return filename


def parse_book_list(text):
    """Parse a list of books from text input.

    Handles formats like:
    - "Title by Author"
    - "Author - Title"
    - One book per line

    Args:
        text: Text containing book list

    Returns:
        List of dicts with 'title' and 'author' keys
    """
    books = []

    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Try "Title by Author" format
        by_match = re.search(r'(.*?)\s+by\s+(.*)', line, re.IGNORECASE)
        if by_match:
            title = by_match.group(1).strip()
            author = by_match.group(2).strip()
            books.append({
                'title': title,
                'author': author,
                'id': generate_book_id(title, author)
            })
            continue

        # Try "Author - Title" format
        dash_match = re.search(r'(.*?)\s+-\s+(.*)', line)
        if dash_match:
            # Check if first part looks like a name (shorter, has fewer words)
            part1 = dash_match.group(1).strip()
            part2 = dash_match.group(2).strip()

            if len(part1.split()) <= 3 and len(part1) < len(part2):
                # First part is probably the author
                author = part1
                title = part2
            else:
                # Default to first part as title
                title = part1
                author = part2

            books.append({
                'title': title,
                'author': author,
                'id': generate_book_id(title, author)
            })
            continue

        # Default to whole line as title
        title = line
        author = ""
        books.append({
            'title': title,
            'author': author,
            'id': generate_book_id(title, author)
        })

    return books