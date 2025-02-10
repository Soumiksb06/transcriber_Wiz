import json
import streamlit as st
import yt_dlp
import os
from datetime import datetime, timedelta
from transcriber import download_audio, transcribe_in_batches
from utils import get_metadata, sanitize_filename
from file_manager import save_transcript

def initialize_session_state():
    """Initialize required session state variables."""
    defaults = {
        'audio_file': None,
        'transcription_result': None,
        'metadata': {},
        'url': "",
        'file_size': None,
        'download_error': None,
        'transcription_error': None,
        'logs': "",
        'audio_duration': None,
        'processing': False,
        'transcription_completed': False  # Add new state variable
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def append_log(message: str):
    """Append a timestamped message to the log."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs += f"{timestamp} - {message}\n"

def display_logs():
    """Display the process logs in a collapsible section."""
    with st.expander("Process Logs", expanded=False):
        st.text_area("", st.session_state.logs, height=200)

def get_duration_from_metadata(info_dict):
    """Extract duration from yt-dlp metadata."""
    duration = info_dict.get('duration')
    if duration:
        return int(duration)
    return None

def format_time(seconds):
    """Convert seconds to human-readable time format."""
    return str(timedelta(seconds=seconds)).split('.')[0]

def calculate_estimated_time(duration):
    """Calculate estimated transcription time (1 hour audio = 5 min processing)."""
    if duration:
        return (duration / 3600) * 5  # Convert to minutes (1 hour = 5 minutes)
    return None

def format_file_size(size_in_bytes):
    """Convert bytes to human readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.1f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.1f} TB"

def handle_download(url: str) -> bool:
    """Download audio from the provided URL and update session state."""
    st.session_state.download_error = None
    st.session_state.transcription_completed = False  # Reset transcription state
    if not url:
        st.session_state.download_error = "Please enter a valid URL."
        return False

    try:
        with st.spinner("Fetching metadata..."):
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                st.session_state.metadata = get_metadata(info_dict)
                st.session_state.audio_duration = get_duration_from_metadata(info_dict)

        with st.spinner("Downloading audio..."):
            append_log("Starting download...")
            audio_file = download_audio(url)
            
            if audio_file and os.path.exists(audio_file):
                st.session_state.audio_file = audio_file
                st.session_state.url = url
                st.session_state.file_size = os.path.getsize(audio_file)
                append_log(f"Downloaded audio: {audio_file} ({st.session_state.file_size} bytes)")
                return True
            else:
                st.session_state.download_error = "Failed to download audio file."
                append_log(st.session_state.download_error)
                return False
                
    except Exception as e:
        st.session_state.download_error = f"Error during download: {str(e)}"
        append_log(st.session_state.download_error)
        return False

def handle_transcription():
    """Transcribe the downloaded audio and update session state."""
    if st.session_state.transcription_completed:
        append_log("Transcription already completed.")
        return

    st.session_state.transcription_error = None
    if not st.session_state.audio_file or not os.path.exists(st.session_state.audio_file):
        st.session_state.transcription_error = "No audio file available for transcription."
        append_log(st.session_state.transcription_error)
        return

    try:
        st.session_state.processing = True
        append_log("Starting transcription...")
        
        with st.spinner("Transcribing audio... This may take a few minutes."):
            result = transcribe_in_batches(st.session_state.audio_file)
            if result and result.get("text"):
                st.session_state.transcription_result = result
                title = st.session_state.metadata.get('podcast', {}).get('title', 'Podcast Transcript')
                save_transcript(result, st.session_state.url, title, st.session_state.metadata)
                st.session_state.transcription_completed = True
                append_log("Transcription completed successfully.")
            else:
                st.session_state.transcription_error = "Transcription failed or returned empty result."
                append_log(st.session_state.transcription_error)
    except Exception as e:
        st.session_state.transcription_error = f"Transcription error: {str(e)}"
        append_log(st.session_state.transcription_error)
    finally:
        st.session_state.processing = False

def create_download_buttons():
    """Create download buttons for JSON and TXT versions of the transcript."""
    if st.session_state.transcription_result and st.session_state.metadata:
        st.subheader("Download Results")
        
        api_info = {
            "api": {
                "name": "Wizper",
                "timestamp": datetime.now().isoformat()
            }
        }
        
        full_data = {
            **api_info,
            **st.session_state.metadata,
            "transcript": st.session_state.transcription_result.get("text", ""),
            "chunks": st.session_state.transcription_result.get("chunks", []),
            "raw_response": st.session_state.transcription_result
        }
        
        txt_content = f"""Transcribed by Wizper API
Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Transcript:
{st.session_state.transcription_result.get('text', '')}\n"""
        
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "📥 Download JSON",
                data=json.dumps(full_data, indent=2),
                file_name="transcript.json",
                mime="application/json",
                use_container_width=True
            )
        with col2:
            st.download_button(
                "📄 Download TXT",
                data=txt_content,
                file_name="transcript.txt",
                mime="text/plain",
                use_container_width=True
            )

def main():
    st.set_page_config(
        page_title="Podcast Transcription App",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    initialize_session_state()

    st.title("🎙️ Podcast Transcription App")
    
    with st.sidebar:
        st.header("📖 How to Use")
        st.markdown("""
        1. **Enter URL**: Paste the URL of your podcast episode
        2. **Download**: Click 'Download Audio' to fetch the file
        3. **Transcribe**: Click 'Start Transcription' to convert audio to text
        4. **Download Results**: Get your transcript in JSON or TXT format
        
        **Supported Platforms:**
        - YouTube
        - Apple Podcasts
        """)

    col_input, col_status = st.columns([2, 1])
    
    with col_input:
        st.subheader("Input")
        url = st.text_input(
            "Enter Podcast URL",
            key="url_input",
            placeholder="https://example.com/your-podcast-episode",
            help="Paste the URL of your podcast episode here"
        )
        
        btn_cols = st.columns(2)
        
        # Handle download button
        if btn_cols[0].button(
            "📥 Download Audio",
            disabled=st.session_state.processing,
            use_container_width=True,
            key="download_button"
        ):
            if handle_download(url):
                st.success("✅ Download completed successfully!")
                if st.session_state.audio_duration:
                    est_time = calculate_estimated_time(st.session_state.audio_duration)
                    st.info(f"ℹ️ Estimated transcription time: {format_time(est_time * 60)}")
            else:
                st.error(f"❌ {st.session_state.download_error}")

        # Handle transcription button
        if btn_cols[1].button(
            "🎯 Start Transcription",
            disabled=not st.session_state.audio_file or st.session_state.processing,
            use_container_width=True,
            key="transcribe_button"
        ):
            handle_transcription()
            if st.session_state.transcription_completed:
                st.success("✅ Transcription completed successfully!")
                st.subheader("Transcript Preview")
                st.text_area(
                    "",
                    st.session_state.transcription_result.get("text", ""),
                    height=300
                )
            elif st.session_state.transcription_error:
                st.error(f"❌ {st.session_state.transcription_error}")

    with col_status:
        st.subheader("Status")
        if st.session_state.audio_file:
            st.info(f"📁 File: {os.path.basename(st.session_state.audio_file)}")
            if st.session_state.file_size:
                st.info(f"💾 Size: {format_file_size(st.session_state.file_size)}")
            if st.session_state.audio_duration:
                st.info(f"⏱️ Duration: {format_time(st.session_state.audio_duration)}")
        
        if st.session_state.transcription_completed:
            create_download_buttons()
        
        display_logs()

if __name__ == "__main__":
    main()
