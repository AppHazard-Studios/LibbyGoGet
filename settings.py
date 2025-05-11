"""
Settings handler for Library Assistant application.
"""
import os
import json
import logging
from pathlib import Path


class Settings:
    """Class to manage application settings."""
    
    def __init__(self, filename="library_settings.json"):
        self.filename = filename
        self.settings = self._load()
        
    def _load(self):
        """Load settings from file."""
        try:
            if os.path.exists(self.filename):
                with open(self.filename, 'r') as f:
                    return json.load(f)
            else:
                return self._default_settings()
        except Exception as e:
            logging.error(f"Error loading settings: {str(e)}")
            return self._default_settings()
    
    def _default_settings(self):
        """Return default settings."""
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads", "Library Assistant")
        
        return {
            "portal_url": "",
            "output_folder": downloads_dir,
            "remember_credentials": True,
            "last_file_path": os.path.expanduser("~"),
            "download_format_preference": "pdf"  # Default format preference
        }
    
    def save(self):
        """Save settings to file."""
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving settings: {str(e)}")
    
    def get(self, key, default=None):
        """Get a setting value."""
        return self.settings.get(key, default)
    
    def set(self, key, value):
        """Set a setting value."""
        self.settings[key] = value
