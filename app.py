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
        'processing': False
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
    """Calculate estimated transcription time (1 min audio = 10 sec processing)."""
    if duration:
        return duration * 10 / 60  # Convert to minutes
    return None

def handle_download(url: str) -> bool:
    """Download audio from the provided URL and update session state."""
    st.session_state.download_error = None
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
    st.session_state.transcription_error = None
    if not st.session_state.audio_file or not os.path.exists(st.session_state.audio_file):
        st.session_state.transcription_error = "No audio file available for transcription."
        append_log(st.session_state.transcription_error)
        return

    st.session_state.processing = True
    append_log("Starting transcription...")
    
    try:
        with st.spinner("Transcribing audio... This may take a few minutes."):
            result = transcribe_in_batches(st.session_state.audio_file)
            if result and result.get("text"):
                st.session_state.transcription_result = result
                title = st.session_state.metadata.get('podcast', {}).get('title', 'Podcast Transcript')
                save_transcript(result, st.session_state.url, title, st.session_state.metadata)
                append_log("Transcription completed successfully.")
            else:
                st.session_state.transcription_error = "Transcription failed or returned empty result."
                append_log(st.session_state.transcription_error)
    finally:
        st.session_state.processing = False

def create_download_buttons():
    """Create download buttons for JSON and TXT versions of the transcript."""
    if st.session_state.transcription_result and st.session_state.metadata:
        st.subheader("Download Results")
        full_data = {
            **st.session_state.metadata,
            "transcript": st.session_state.transcription_result.get("text", ""),
            "chunks": st.session_state.transcription_result.get("chunks", []),
            "raw_response": st.session_state.transcription_result
        }
        txt_content = f"Transcript:\n{st.session_state.transcription_result.get('text', '')}\n"
        
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

    # Header section
    st.title("🎙️ Podcast Transcription App")
    
    # Help section in sidebar
    with st.sidebar:
        st.header("📖 How to Use")
        st.markdown("""
        1. **Enter URL**: Paste the URL of your podcast episode
        2. **Download**: Click 'Download Audio' to fetch the file
        3. **Transcribe**: Click 'Start Transcription' to convert audio to text
        4. **Download Results**: Get your transcript in JSON or TXT format
        
        **Supported Platforms:**
        - YouTube
        - Spotify
        - SoundCloud
        - Direct MP3/MP4 links
        
        **Note:** Processing time depends on audio length. 
        Typically 1 minute of audio takes about 10 seconds to process.
        """)

    # Main content area
    col_input, col_status = st.columns([2, 1])
    
    with col_input:
        st.subheader("Input")
        url = st.text_input(
            "Enter Podcast URL",
            key="url_input",
            placeholder="https://example.com/your-podcast-episode",
            help="Paste the URL of your podcast episode here"
        )
        
        # Action buttons
        btn_cols = st.columns(2)
        download_btn = btn_cols[0].button(
            "📥 Download Audio",
            disabled=st.session_state.processing,
            use_container_width=True
        )
        transcribe_btn = btn_cols[1].button(
            "🎯 Start Transcription",
            disabled=not st.session_state.audio_file or st.session_state.processing,
            use_container_width=True
        )

        if download_btn:
            if handle_download(url):
                st.success("✅ Download completed successfully!")
                if st.session_state.audio_duration:
                    est_time = calculate_estimated_time(st.session_state.audio_duration)
                    st.info(f"ℹ️ Estimated transcription time: {format_time(est_time * 60)}")
            else:
                st.error(f"❌ {st.session_state.download_error}")

        if transcribe_btn:
            handle_transcription()
            if st.session_state.transcription_result:
                st.success("✅ Transcription completed successfully!")
            else:
                st.error(f"❌ {st.session_state.transcription_error}")

    with col_status:
        st.subheader("Status")
        if st.session_state.audio_file:
            st.info(f"📁 File: {os.path.basename(st.session_state.audio_file)}")
            if st.session_state.audio_duration:
                st.info(f"⏱️ Duration: {format_time(st.session_state.audio_duration)}")
        
        if st.session_state.transcription_result:
            st.subheader("Transcript Preview")
            st.text_area(
                "",
                st.session_state.transcription_result.get("text", ""),
                height=300
            )
            create_download_buttons()
        
        display_logs()

if __name__ == "__main__":
    main()
