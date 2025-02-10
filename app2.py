# app/state.py
from dataclasses import dataclass
from typing import Optional, Dict, List
import time
from datetime import datetime

@dataclass
class AudioMetadata:
    title: str
    duration: float
    file_size: int
    url: str
    upload_date: Optional[str] = None
    channel: Optional[str] = None
    description: Optional[str] = None

@dataclass
class ProcessingState:
    is_downloading: bool = False
    is_transcribing: bool = False
    is_complete: bool = False
    current_stage: str = ""
    error: Optional[str] = None

@dataclass
class LogEntry:
    timestamp: float
    message: str
    level: str

class AppState:
    def __init__(self):
        self.logs: List[LogEntry] = []
        self.metadata: Optional[AudioMetadata] = None
        self.processing: ProcessingState = ProcessingState()
        self.audio_path: Optional[str] = None
        self.transcript_text: Optional[str] = None
        self.transcript_json: Optional[Dict] = None
    
    def add_log(self, message: str, level: str = "info"):
        log_entry = LogEntry(
            timestamp=time.time(),
            message=message,
            level=level
        )
        self.logs.append(log_entry)
        return log_entry

# app/utils.py
import humanize
from urllib.parse import urlparse
import re

def format_duration(seconds: float) -> str:
    """Convert seconds to human-readable duration"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining_seconds = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes}:{remaining_seconds:02d}"

def format_file_size(size_in_bytes: int) -> str:
    """Convert bytes to human-readable size"""
    return humanize.naturalsize(size_in_bytes)

def validate_url(url: str) -> bool:
    """Validate URL format and supported platforms"""
    try:
        parsed = urlparse(url)
        if not all([parsed.scheme, parsed.netloc]):
            return False
            
        # Add supported platforms
        supported_domains = [
            'youtube.com', 'youtu.be',
            'podcasts.apple.com',
            'spotify.com',
            'soundcloud.com'
        ]
        
        return any(domain in parsed.netloc for domain in supported_domains)
    except:
        return False

def estimate_processing_time(duration_seconds: float) -> float:
    """Estimate transcription processing time based on audio duration"""
    # Heuristic: 1 hour of audio ≈ 5 minutes processing
    return (duration_seconds / 3600) * 300  # 300 seconds = 5 minutes

# app/downloader.py
from typing import Optional, Tuple
import yt_dlp
import os
from pathlib import Path
import streamlit as st
from .state import AppState, AudioMetadata

class AudioDownloader:
    def __init__(self, output_dir: str = "downloads"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    def get_metadata(self, url: str) -> Optional[AudioMetadata]:
        """Fetch metadata without downloading"""
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                
                return AudioMetadata(
                    title=info.get('title', 'Untitled'),
                    duration=float(info.get('duration', 0)),
                    file_size=info.get('filesize', 0),
                    url=url,
                    upload_date=info.get('upload_date'),
                    channel=info.get('channel', info.get('uploader')),
                    description=info.get('description')
                )
        except Exception as e:
            st.error(f"Error fetching metadata: {str(e)}")
            return None
    
    def download(self, url: str, state: AppState) -> Optional[str]:
        """Download audio file and update state"""
        try:
            metadata = self.get_metadata(url)
            if not metadata:
                return None
                
            state.metadata = metadata
            state.add_log(f"Starting download of: {metadata.title}")
            
            output_path = self.output_dir / f"{self._sanitize_filename(metadata.title)}.mp3"
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': str(output_path.with_suffix('')),
                'progress_hooks': [lambda d: self._progress_hook(d, state)],
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
            if output_path.exists():
                state.audio_path = str(output_path)
                state.add_log("Download completed successfully")
                return str(output_path)
            
            state.add_log("Download failed - file not found", "error")
            return None
            
        except Exception as e:
            state.add_log(f"Download error: {str(e)}", "error")
            return None
    
    def _progress_hook(self, d, state: AppState):
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', 'N/A')
            speed = d.get('_speed_str', 'N/A')
            state.add_log(f"Downloading: {percent} at {speed}")

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        # Implementation from before...
        pass

# app/transcriber.py
from typing import Optional, Dict
import fal_client
import streamlit as st
from .state import AppState
import time
import json
from pathlib import Path

class Transcriber:
    def __init__(self, api_key: str, output_dir: str = "transcripts"):
        self.api_key = api_key
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
    def transcribe(self, audio_path: str, state: AppState) -> Optional[Dict]:
        """Transcribe audio and update state"""
        try:
            state.processing.is_transcribing = True
            state.add_log("Starting transcription")
            
            audio_url = fal_client.upload_file(audio_path)
            state.add_log("Audio file uploaded to FAL service")
            
            result = fal_client.subscribe(
                "fal-ai/wizper",
                arguments={
                    "audio_url": audio_url,
                    "task": "transcribe",
                    "chunk_level": "segment",
                    "version": "3",
                    "language": "en"
                },
                with_logs=True,
                on_queue_update=lambda u: self._handle_update(u, state),
            )
            
            if result and 'text' in result:
                self._save_transcripts(result, state)
                state.processing.is_complete = True
                state.add_log("Transcription completed successfully")
                return result
            
            state.add_log("Transcription failed - empty result", "error")
            return None
            
        except Exception as e:
            state.add_log(f"Transcription error: {str(e)}", "error")
            return None
        finally:
            state.processing.is_transcribing = False
    
    def _handle_update(self, update, state: AppState):
        if isinstance(update, fal_client.InProgress):
            for log in update.logs:
                state.add_log(log["message"])
    
    def _save_transcripts(self, result: Dict, state: AppState):
        """Save transcripts in both TXT and JSON formats"""
        try:
            base_name = Path(state.audio_path).stem
            
            # Save TXT version
            txt_path = self.output_dir / f"{base_name}.txt"
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(f"Transcription Date: {datetime.now()}\n\n")
                f.write(result['text'])
            
            # Save JSON version with metadata
            json_path = self.output_dir / f"{base_name}.json"
            json_data = {
                "api": {
                    "name": "Wizper",
                    "version": "3"
                },
                "metadata": {
                    "title": state.metadata.title,
                    "channel": state.metadata.channel,
                    "url": state.metadata.url,
                    "transcription_date": datetime.now().isoformat(),
                    "audio_duration": state.metadata.duration,
                },
                "transcript": result['text'],
                "chunks": result.get('chunks', [])
            }
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)
            
            state.transcript_text = result['text']
            state.transcript_json = json_data
            
        except Exception as e:
            state.add_log(f"Error saving transcripts: {str(e)}", "error")

# app/ui.py
import streamlit as st
from .state import AppState
from .utils import format_duration, format_file_size, validate_url, estimate_processing_time
import base64

def create_download_link(content: str, filename: str) -> str:
    """Create a download link for file content"""
    b64 = base64.b64encode(content.encode()).decode()
    return f'<a href="data:text/plain;base64,{b64}" download="{filename}">Download {filename}</a>'

def render_sidebar():
    """Render sidebar with instructions"""
    st.sidebar.title("Instructions")
    st.sidebar.markdown("""
    1. Enter your FAL API key
    2. Paste a URL from a supported platform:
       - YouTube
       - Apple Podcasts
       - Spotify
       - SoundCloud
    3. Click 'Download Audio' to fetch the file
    4. Start transcription
    5. Download results in TXT or JSON format
    """)

def render_main(state: AppState):
    """Render main interface"""
    st.title("Audio Transcription App")
    
    col1, col2 = st.columns([3, 2])
    
    with col1:
        api_key = st.text_input("FAL API Key:", type="password")
        url = st.text_input("Audio URL:")
        
        if url and not validate_url(url):
            st.error("Please enter a valid URL from a supported platform")
        
        if st.button("Download Audio", disabled=not (api_key and validate_url(url))):
            state.processing.is_downloading = True
            # Download logic here...
        
        if state.audio_path and not state.processing.is_complete:
            if st.button("Start Transcription"):
                state.processing.is_transcribing = True
                # Transcription logic here...
    
    with col2:
        if state.metadata:
            st.subheader("File Information")
            st.write(f"Title: {state.metadata.title}")
            st.write(f"Duration: {format_duration(state.metadata.duration)}")
            st.write(f"File Size: {format_file_size(state.metadata.file_size)}")
            
            if not state.processing.is_complete:
                est_time = estimate_processing_time(state.metadata.duration)
                st.info(f"Estimated processing time: {format_duration(est_time)}")
    
    # Logs section
    if state.logs:
        with st.expander("Process Logs", expanded=True):
            for log in state.logs[-10:]:  # Show last 10 logs
                timestamp = datetime.fromtimestamp(log.timestamp).strftime('%H:%M:%S')
                if log.level == "error":
                    st.error(f"{timestamp}: {log.message}")
                else:
                    st.text(f"{timestamp}: {log.message}")
    
    # Download section
    if state.processing.is_complete:
        st.success("Transcription completed!")
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(create_download_link(
                state.transcript_text,
                f"{Path(state.audio_path).stem}.txt"
            ), unsafe_allow_html=True)
        
        with col2:
            st.markdown(create_download_link(
                json.dumps(state.transcript_json, indent=2),
                f"{Path(state.audio_path).stem}.json"
            ), unsafe_allow_html=True)

# app/main.py
import streamlit as st
from .state import AppState
from .ui import render_sidebar, render_main
from .downloader import AudioDownloader
from .transcriber import Transcriber

def main():
    # Initialize session state
    if 'app_state' not in st.session_state:
        st.session_state.app_state = AppState()
    
    # Render UI
    render_sidebar()
    render_main(st.session_state.app_state)

if __name__ == "__main__":
    main()
