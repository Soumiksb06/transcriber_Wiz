# utils.py
import re
import unicodedata
from datetime import datetime

def get_metadata(info_dict: dict) -> dict:
    """Extract metadata from yt-dlp info dictionary."""
    return {
        "podcast": {
            "title": info_dict.get('title', ''),
            "Podcast Show": info_dict.get('channel', '') or info_dict.get('uploader', ''),
            "url": info_dict.get('original_url', ''),
            "Date posted": (
                datetime.fromtimestamp(info_dict.get('timestamp') or info_dict.get('release_timestamp', 0))
                .strftime('%Y-%m-%d')
                if (info_dict.get('timestamp') or info_dict.get('release_timestamp'))
                else None
            ),
            "Date transcribed": datetime.now().strftime('%Y-%m-%d')
        }
    }

def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to handle special characters and encoding issues.
    """
    filename = re.sub(r'\/podcast\/', '', filename)
    filename = re.sub(r'id\d+', '', filename)
    filename = filename.split('?')[0]
    filename = filename.split('/')[-1]
    filename = unicodedata.normalize('NFKD', filename)
    filename = filename.encode('ASCII', 'ignore').decode('ASCII')
    filename = re.sub(r'[^\w\s-]', '', filename)
    filename = re.sub(r'\s+', '_', filename.strip())
    return filename

def get_episode_name(url: str, fallback_title: str = None) -> str:
    """
    Extract episode name from URL or use the fallback title.
    """
    try:
        if 'podcast' in url:
            path = url.split('/')
            for segment in path:
                if len(segment) > 10:
                    cleaned = segment.replace('-', ' ')
                    if not cleaned.startswith('id') and not cleaned.isdigit():
                        return sanitize_filename(segment)
        if fallback_title:
            return sanitize_filename(fallback_title)
        return 'transcript'
    except Exception as e:
        raise e
