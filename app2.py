# app/main.py
import streamlit as st
import time
from datetime import datetime
import json
from pathlib import Path
import humanize
from typing import Optional, Dict, List
import yt_dlp
import fal_client
import base64
from dataclasses import dataclass
import os

# Data Models
@dataclass
class TranscriptionMetadata:
    title: str
    channel: Optional[str]
    upload_date: Optional[str]
    description: Optional[str]
    duration: float
    file_size: int
    url: str
    download_path: Optional[str] = None

class TranscriptionState:
    def __init__(self):
        self.initialize_state()
    
    def initialize_state(self):
        """Initialize or reset all state variables"""
        if 'metadata' not in st.session_state:
            st.session_state.metadata = None
        if 'audio_file' not in st.session_state:
            st.session_state.audio_file = None
        if 'transcript' not in st.session_state:
            st.session_state.transcript = None
        if 'logs' not in st.session_state:
            st.session_state.logs = []
        if 'processing_status' not in st.session_state:
            st.session_state.processing_status = None
        if 'is_complete' not in st.session_state:
            st.session_state.is_complete = False
    
    def add_log(self, message: str, level: str = "info"):
        """Add timestamped log entry"""
        log_entry = {
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'message': message,
            'level': level
        }
        st.session_state.logs.append(log_entry)
        return log_entry

class AudioProcessor:
    def __init__(self, state: TranscriptionState):
        self.state = state
        self.output_dir = Path("downloads")
        self.output_dir.mkdir(exist_ok=True)
        self.transcript_dir = Path("transcripts")
        self.transcript_dir.mkdir(exist_ok=True)
    
    def extract_metadata(self, url: str) -> Optional[TranscriptionMetadata]:
        """Extract metadata from URL without downloading"""
        try:
            self.state.add_log(f"Fetching metadata for URL: {url}")
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                
                metadata = TranscriptionMetadata(
                    title=info.get('title', 'Untitled'),
                    channel=info.get('channel', info.get('uploader')),
                    upload_date=info.get('upload_date'),
                    description=info.get('description'),
                    duration=float(info.get('duration', 0)),
                    file_size=info.get('filesize', 0),
                    url=url
                )
                
                self.state.add_log(f"Found content: {metadata.title}")
                return metadata
                
        except Exception as e:
            self.state.add_log(f"Metadata extraction failed: {str(e)}", "error")
            return None
    
    def download_audio(self, url: str) -> Optional[str]:
        """Download audio file with progress tracking"""
        try:
            metadata = self.extract_metadata(url)
            if not metadata:
                return None
            
            st.session_state.metadata = metadata
            output_path = self.output_dir / f"{self.sanitize_filename(metadata.title)}.mp3"
            
            def progress_hook(d):
                if d['status'] == 'downloading':
                    progress = d.get('_percent_str', 'unknown')
                    speed = d.get('_speed_str', 'unknown')
                    self.state.add_log(f"Downloading: {progress} at {speed}")
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': str(output_path.with_suffix('')),
                'progress_hooks': [progress_hook],
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.state.add_log("Starting download...")
                ydl.download([url])
            
            if output_path.exists():
                metadata.download_path = str(output_path)
                self.state.add_log("Download completed successfully")
                return str(output_path)
                
            self.state.add_log("Download failed - file not found", "error")
            return None
            
        except Exception as e:
            self.state.add_log(f"Download failed: {str(e)}", "error")
            return None

    def transcribe_in_batches(self, file_path: str, api_key: str) -> Optional[Dict]:
        """Transcribe audio file in batches with progress tracking"""
        try:
            self.state.add_log("Starting transcription process")
            os.environ['FAL_KEY'] = api_key
            
            # Get file size and duration
            duration = self.get_audio_duration(file_path)
            if not duration:
                return None
            
            # Estimate processing time
            est_time = self.estimate_processing_time(duration)
            self.state.add_log(
                f"Estimated processing time: {self.format_duration(est_time)}"
            )
            
            # Process in 30-minute batches
            batch_duration = 30 * 60
            total_batches = (int(duration) + batch_duration - 1) // batch_duration
            
            full_transcript = {
                "text": "",
                "chunks": [],
                "metadata": {
                    "title": st.session_state.metadata.title,
                    "channel": st.session_state.metadata.channel,
                    "url": st.session_state.metadata.url,
                    "transcription_date": datetime.now().isoformat()
                }
            }
            
            for batch_num in range(total_batches):
                start_time = batch_num * batch_duration
                self.state.add_log(f"Processing batch {batch_num + 1}/{total_batches}")
                
                # Create batch file
                batch_file = self.create_batch_file(
                    file_path, start_time, batch_duration
                )
                if not batch_file:
                    continue
                
                # Transcribe batch
                try:
                    batch_result = self.transcribe_batch(batch_file)
                    if batch_result:
                        full_transcript["text"] += batch_result["text"] + " "
                        if "chunks" in batch_result:
                            for chunk in batch_result["chunks"]:
                                chunk["start"] += start_time
                                chunk["end"] += start_time
                                full_transcript["chunks"].append(chunk)
                finally:
                    if os.path.exists(batch_file):
                        os.remove(batch_file)
            
            if full_transcript["text"]:
                self.save_transcripts(full_transcript)
                self.state.add_log("Transcription completed successfully")
                return full_transcript
                
            return None
            
        except Exception as e:
            self.state.add_log(f"Transcription failed: {str(e)}", "error")
            return None

    def save_transcripts(self, result: Dict):
        """Save transcripts in both TXT and JSON formats"""
        try:
            base_name = Path(st.session_state.metadata.download_path).stem
            
            # Save TXT version
            txt_path = self.transcript_dir / f"{base_name}.txt"
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(f"Transcription Date: {datetime.now()}\n")
                f.write(f"Title: {st.session_state.metadata.title}\n")
                if st.session_state.metadata.channel:
                    f.write(f"Channel: {st.session_state.metadata.channel}\n")
                f.write(f"URL: {st.session_state.metadata.url}\n\n")
                f.write(result['text'])
            
            # Save JSON version
            json_path = self.transcript_dir / f"{base_name}.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            self.state.add_log("Transcript files saved successfully")
            st.session_state.transcript = result
            
        except Exception as e:
            self.state.add_log(f"Error saving transcripts: {str(e)}", "error")

    @staticmethod
    def get_audio_duration(file_path: str) -> Optional[float]:
        """Get audio duration using ffprobe"""
        try:
            import subprocess
            cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{file_path}"'
            output = subprocess.check_output(cmd, shell=True)
            return float(output)
        except Exception:
            return None

    @staticmethod
    def estimate_processing_time(duration: float) -> float:
        """Estimate processing time based on audio duration"""
        # Heuristic: 1 hour audio ≈ 5 minutes processing
        return (duration / 3600) * 300

    @staticmethod
    def format_duration(seconds: float) -> str:
        """Format duration in HH:MM:SS"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    @staticmethod
    def format_file_size(size_in_bytes: int) -> str:
        """Format file size in human readable format"""
        return humanize.naturalsize(size_in_bytes)

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename for safe saving"""
        import unicodedata
        import re
        filename = unicodedata.normalize('NFKD', filename)
        filename = filename.encode('ASCII', 'ignore').decode('ASCII')
        filename = re.sub(r'[^\w\s-]', '', filename)
        return re.sub(r'\s+', '_', filename.strip())

def render_sidebar():
    """Render sidebar with instructions"""
    st.sidebar.title("Audio Transcription App")
    st.sidebar.markdown("""
    ### Instructions
    
    1. Enter your FAL API key in the settings
    2. Paste a URL from a supported platform:
       - YouTube
       - Apple Podcasts
       - Spotify
       - SoundCloud
    3. The app will:
       - Extract metadata
       - Download the audio
       - Transcribe in manageable chunks
       - Provide downloadable results
    
    ### Processing Time
    Transcription takes approximately 5 minutes
    for every hour of audio content.
    
    ### Output Formats
    - TXT: Plain text transcript
    - JSON: Structured data with metadata
    """)

def render_main():
    """Main app UI"""
    state = TranscriptionState()
    processor = AudioProcessor(state)
    
    # Load API key from secrets
    api_key = st.secrets.get("FAL_KEY")
    if not api_key:
        api_key = st.text_input("FAL API Key:", type="password")
        st.info("Consider adding your API key to .streamlit/secrets.toml")
    else:
        st.success("FAL API key loaded from secrets ✓")
    
    # Main layout
    col1, col2 = st.columns([3, 2])
    
    with col1:
        url = st.text_input("Enter URL:")
        
        if url:
            if not st.session_state.metadata:
                metadata = processor.extract_metadata(url)
                if metadata:
                    st.session_state.metadata = metadata
            
            if st.session_state.metadata and not st.session_state.audio_file:
                if st.button("Download Audio"):
                    with st.spinner("Downloading audio..."):
                        audio_path = processor.download_audio(url)
                        if audio_path:
                            st.session_state.audio_file = audio_path
            
            if st.session_state.audio_file and not st.session_state.is_complete:
                if st.button("Start Transcription"):
                    with st.spinner("Transcribing audio..."):
                        result = processor.transcribe_in_batches(
                            st.session_state.audio_file,
                            api_key
                        )
                        if result:
                            st.session_state.is_complete = True
    
    with col2:
        if st.session_state.metadata:
            st.subheader("File Information")
            metadata = st.session_state.metadata
            st.write(f"Title: {metadata.title}")
            st.write(f"Duration: {processor.format_duration(metadata.duration)}")
            st.write(f"File Size: {processor.format_file_size(metadata.file_size)}")
            if metadata.channel:
                st.write(f"Channel: {metadata.channel}")
    
    # Logs section
    if st.session_state.logs:
        with st.expander("Process Logs", expanded=True):
            for log in st.session_state.logs[-10:]:
                if log['level'] == "error":
                    st.error(f"{log['timestamp']}: {log['message']}")
                else:
                    st.text(f"{log['timestamp']}: {log['message']}")
    
    # Download section
    if st.session_state.is_complete and st.session_state.transcript:
        st.success("Transcription completed!")
        
        def get_download_link(content: str, filename: str) -> str:
            b64 = base64.b64encode(content.encode()).decode()
            return f'<a href="data:text/plain;base64,{b64}" download="{filename}">Download {filename}</a>'
        
        col1, col2 = st.columns(2)
        with col1:
            txt_content = st.session_state.transcript['text']
            st.markdown(
                get_download_link(txt_content, "transcript.txt"),
                unsafe_allow_html=True
            )
        
        with col2:
            json_content = json.dumps(st.session_state.transcript, indent=2)
            st.markdown(
                get_download_link(json_content, "transcript.json"),
                unsafe_allow_html=True
            )

def main():
    render_sidebar()
    render_main()

if __name__ == "__main__":
    main()
