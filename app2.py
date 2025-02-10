import os
import sys
import fal_client
import yt_dlp
import unicodedata
import re
import shutil
import json
from dotenv import load_dotenv
import time
import streamlit as st
import io
import contextlib
import concurrent.futures
from datetime import datetime, timedelta

# -------------------- Utility Functions --------------------

def append_log(message: str):
    """Append a timestamped message to process logs."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs += f"{timestamp} - {message}\n"

def format_time(seconds):
    return str(timedelta(seconds=int(seconds))).split('.')[0]

# -------------------- Provided Components --------------------

def setup_fal_api():
    """Set up FAL API key from st.secrets."""
    try:
        fal_key = st.secrets["FAL_KEY"]
        os.environ['FAL_KEY'] = fal_key
        return fal_key
    except Exception as e:
        st.error("FAL_KEY not found in st.secrets. Please add it to your secrets file.")
        raise e

def sanitize_filename(filename):
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

def get_episode_name(url, fallback_title=None):
    """
    Extract episode name from URL or use fallback title.
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
        append_log(f"Error extracting episode name: {str(e)}")
        return 'transcript'

def save_transcript(result, url=None, title=None):
    """Save transcription result to episode-named file."""
    if result and 'text' in result:
        try:
            episode_name = get_episode_name(url, title)
            transcript_filename = f"{episode_name}.txt"
            json_filename = f"{episode_name}_full.json"
            with open(transcript_filename, 'w', encoding='utf-8') as f:
                f.write(result['text'])
            append_log(f"Transcript saved successfully to {transcript_filename}")
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            append_log(f"Full transcript data saved to {json_filename}")
        except Exception as e:
            append_log(f"Error saving transcript: {str(e)}")
    else:
        append_log("Error: No valid transcription result to save")

def download_audio(url):
    """Download audio from URL using yt-dlp with encoding handling."""
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            title = info_dict.get('title', 'video')
        safe_title = sanitize_filename(title)
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': f'{safe_title}.%(ext)s',
            'restrict_filenames': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            final_filename = f"{safe_title}.mp3"
            if os.path.exists(final_filename):
                return final_filename
            else:
                append_log(f"Error: Expected output file {final_filename} not found")
                return None
    except Exception as e:
        append_log(f"Download error: {str(e)}")
        return None

def on_queue_update(update):
    """Handle transcription queue updates."""
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            try:
                append_log(log["message"])
            except Exception as e:
                append_log(f"Log encoding error: {str(e)}")

def transcribe_audio(file_path: str):
    """Transcribe audio file using Fal.ai."""
    try:
        if not os.path.exists(file_path):
            append_log(f"Error: Input file {file_path} does not exist")
            return None
        file_path = os.path.abspath(file_path)
        audio_url = fal_client.upload_file(file_path)
        append_log(f"Uploaded file URL: {audio_url}")
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
            on_queue_update=on_queue_update,
        )
        return result
    except Exception as e:
        append_log(f"Transcription error: {str(e)}")
        return None

def transcribe_in_batches(file_path, max_size_mb=30):
    """Transcribe audio file in batches if larger than specified size."""
    try:
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb <= max_size_mb:
            return transcribe_audio(file_path)
        # For simplicity, we call transcribe_audio even for larger files.
        return transcribe_audio(file_path)
    except Exception as e:
        append_log(f"Batch processing error: {str(e)}")
        return None

# -------------------- Session State Initialization --------------------

def initialize_session_state():
    defaults = {
        "audio_file": None,
        "transcription_result": None,
        "metadata": None,
        "download_error": "",
        "transcription_error": "",
        "logs": "",
        "processing": False,
        "transcription_completed": False,
        "url": "",
        "audio_duration": None  # in seconds
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# -------------------- New Transcription Handler with Overall Progress Bar --------------------

def handle_transcribe(url):
    # Reset previous state
    st.session_state.logs = ""
    st.session_state.transcription_result = None
    st.session_state.transcription_completed = False
    st.session_state.download_error = ""
    st.session_state.transcription_error = ""
    
    setup_fal_api()
    append_log("Starting process...")
    
    # Create an overall progress bar (0 to 100)
    overall_progress = st.progress(0)
    overall_progress_text = st.empty()
    
    # --- Stage 1: Extract Metadata & Podcast Duration (0-10%) ---
    overall_progress_text.text("Extracting metadata...")
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info_dict = ydl.extract_info(url, download=False)
        podcast_duration = info_dict.get('duration')
        st.session_state.audio_duration = podcast_duration
        if podcast_duration:
            append_log(f"Podcast Duration: {format_time(podcast_duration)}")
        else:
            append_log("Podcast duration not found.")
        title = info_dict.get('title', None)
        # Store metadata (adjust as needed)
        st.session_state.metadata = {
            "podcast": {
                "title": title or "Podcast Transcript",
                "show": "",
                "date_posted": ""
            }
        }
    except Exception as e:
        append_log(f"Metadata extraction error: {str(e)}")
        st.session_state.audio_duration = None
        title = None
    overall_progress.progress(10)
    
    # --- Stage 2: Download Audio (10-30%) ---
    overall_progress_text.text("Downloading audio...")
    append_log("Downloading audio...")
    audio_file = download_audio(url)
    if audio_file and os.path.exists(audio_file):
        st.session_state.audio_file = audio_file
        append_log(f"Downloaded audio: {audio_file}")
    else:
        st.session_state.download_error = "Failed to download audio file."
        append_log(st.session_state.download_error)
        overall_progress_text.text(st.session_state.download_error)
        return None
    overall_progress.progress(30)
    
    # --- Stage 3: Transcription (30-90%) ---
    if st.session_state.audio_duration:
        estimated_time = (st.session_state.audio_duration / 3600) * 5 * 60  # in seconds
    else:
        estimated_time = 120  # fallback 2 minutes
    append_log(f"Estimated transcription time: {format_time(estimated_time)}")
    overall_progress_text.text("Transcribing audio...")
    
    transcription_start = time.time()
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(transcribe_in_batches, st.session_state.audio_file)
        while not future.done():
            elapsed = time.time() - transcription_start
            transcription_progress = min(elapsed / estimated_time, 1.0)
            overall_progress.progress(30 + int(transcription_progress * 60))  # 30 to 90%
            remaining = max(estimated_time - elapsed, 0)
            overall_progress_text.text(f"Transcribing... Estimated time remaining: {int(remaining)} seconds")
            time.sleep(1)
        result = future.result()
    overall_progress.progress(90)
    overall_progress_text.text("Transcription complete!")
    
    # --- Stage 4: Save Transcript (90-100%) ---
    if result and result.get("text"):
        st.session_state.transcription_result = result
        st.session_state.transcription_completed = True
        append_log("Transcription completed successfully.")
        save_transcript(result, url=url, title=title)
        overall_progress.progress(100)
        overall_progress_text.text("Process complete!")
    else:
        st.session_state.transcription_error = "Transcription failed or returned empty result."
        append_log(st.session_state.transcription_error)
        overall_progress_text.text(st.session_state.transcription_error)
    return result

# -------------------- Custom Download Buttons Using Provided Format --------------------

def create_download_buttons_custom():
    """Create download buttons for JSON and TXT versions of the transcript using safe_title and include metadata in both outputs."""
    if st.session_state.transcription_result:
        transcript_text = st.session_state.transcription_result.get("text", "")
        # Ensure metadata exists; if not, provide defaults.
        if not st.session_state.metadata:
            st.session_state.metadata = {
                "podcast": {
                    "title": "Podcast Transcript",
                    "show": "",
                    "date_posted": ""
                }
            }
        # Compute safe_title using get_episode_name (which returns a sanitized title)
        safe_title = get_episode_name(
            st.session_state.url, 
            st.session_state.metadata.get('podcast', {}).get('title', 'Podcast Transcript')
        )
        # Build JSON structure including metadata
        json_data = {
            "api": {
                "name": "Wizper"
            },
            "podcast": {
                "title": st.session_state.metadata.get('podcast', {}).get('title', 'Podcast Transcript'),
                "Podcast Show": st.session_state.metadata.get('podcast', {}).get('show', ''),
                "url": st.session_state.url,
                "Date posted": st.session_state.metadata.get('podcast', {}).get('date_posted', ''),
                "Date transcribed": datetime.now().strftime('%Y-%m-%d')
            },
            "transcript": transcript_text,
            "chunks": st.session_state.transcription_result.get("chunks", [])
        }
        
        # Build TXT content including metadata
        txt_content = f"""Transcribed by Wizper API
Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Podcast Metadata:
Title: {st.session_state.metadata.get('podcast', {}).get('title', 'Podcast Transcript')}
Podcast Show: {st.session_state.metadata.get('podcast', {}).get('show', '')}
URL: {st.session_state.url}
Date posted: {st.session_state.metadata.get('podcast', {}).get('date_posted', '')}
Date transcribed: {datetime.now().strftime('%Y-%m-%d')}

Transcript:
{transcript_text}
"""
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "📥 Download JSON",
                data=json.dumps(json_data, indent=2),
                file_name=f"{safe_title}_full.json",
                mime="application/json",
                use_container_width=True,
                key="download_json_custom"
            )
        with col2:
            st.download_button(
                "📄 Download TXT",
                data=txt_content,
                file_name=f"{safe_title}.txt",
                mime="text/plain",
                use_container_width=True,
                key="download_txt_custom"
            )



# -------------------- Main Streamlit App --------------------

def main():
    st.set_page_config(page_title="Podcast Transcription App", layout="wide")
    st.title("🎙️ Podcast Transcription App")
    
    # Load FAL API key from st.secrets automatically
    if "FAL_KEY" in st.secrets:
        os.environ["FAL_KEY"] = st.secrets["FAL_KEY"]
    else:
        st.sidebar.error("FAL API key not found in secrets. Please add it to your secrets file.")
        st.stop()
    
    st.sidebar.header("Instructions")
    st.sidebar.markdown("""
    1. **Enter Podcast URL:** Paste the URL of your podcast episode.
    2. **Transcribe:** Click the button below to download and transcribe.
    3. **View & Download:** After transcription, view the transcript and download the results.
    """)
    
    initialize_session_state()
    
    # Layout: Left column for Input & Transcript Preview; Right column for Status & Process Logs.
    col_input, col_status = st.columns([2, 1])
    
    with col_input:
        st.subheader("Input")
        url = st.text_input("Enter Podcast URL:", key="url_input", placeholder="https://example.com/your-podcast-episode")
        if st.button("Transcribe"):
            if not url:
                st.error("Please enter a valid URL.")
            else:
                st.session_state.url = url
                result = handle_transcribe(url)
                if result and result.get("text"):
                    st.success("Transcription completed successfully!")
                elif st.session_state.transcription_error:
                    st.error(st.session_state.transcription_error)
        # Transcript preview appears below the input and messages.
        if st.session_state.transcription_result and st.session_state.transcription_result.get("text"):
            st.subheader("Transcript Preview")
            st.text_area("", st.session_state.transcription_result.get("text", ""), height=300)
    
    with col_status:
        st.subheader("Status")
        if st.session_state.audio_file:
            st.info(f"File: {os.path.basename(st.session_state.audio_file)}")
            try:
                size = os.path.getsize(st.session_state.audio_file)
                size_mb = size / (1024 * 1024)
                st.info(f"Size: {size_mb:.2f} MB")
            except Exception:
                pass
        if st.session_state.audio_duration:
            st.info(f"Podcast Duration: {format_time(st.session_state.audio_duration)}")
        if st.session_state.transcription_completed:
            create_download_buttons_custom()
        st.subheader("Process Logs")
        st.text_area("", st.session_state.logs, height=200)

if __name__ == '__main__':
    main()
