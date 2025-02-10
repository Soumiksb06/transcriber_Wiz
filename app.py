import json
import streamlit as st
import yt_dlp
import os
from datetime import datetime, timedelta
from config import setup_fal_api
from utils import get_metadata, sanitize_filename
from transcriber import download_audio, transcribe_in_batches, estimate_transcription_time
from file_manager import save_transcript

def initialize_session_state():
    """Initialize all necessary session state variables."""
    defaults = {
        'audio_file': None,
        'transcription_result': None,
        'metadata': None,
        'url': "",
        'download_complete': False,
        'file_size': None,
        'estimated_transcription_duration': None,  # in seconds
        'download_error': None,
        'transcription_error': None,
        'logs': ""
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def append_log(message: str):
    """Append a timestamped message to the logs."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs += f"{timestamp} - {message}\n"

def display_logs():
    """Display the log area for debugging."""
    st.text_area("Logs", st.session_state.logs, height=200)

def format_file_size(size_bytes):
    """Convert a byte count to a human‐readable MB string."""
    mb = size_bytes / (1024 * 1024)
    return f"{mb:.2f} MB"

def check_existing_audio(url: str):
    """If an audio file already exists for the given URL, reuse it."""
    try:
        if st.session_state.audio_file and os.path.exists(st.session_state.audio_file):
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                expected_filename = f"{sanitize_filename(info_dict.get('title', 'video'))}.mp3"
                if expected_filename == st.session_state.audio_file:
                    st.session_state.metadata = get_metadata(info_dict)
                    st.session_state.file_size = os.path.getsize(st.session_state.audio_file)
                    st.session_state.download_complete = True
                    append_log("Found existing downloaded audio.")
                    return True
    except Exception as e:
        st.session_state.download_error = f"Error checking existing audio: {str(e)}"
        append_log(st.session_state.download_error)
    return False

def handle_download(url: str):
    """Download the audio from the provided URL and update session state."""
    st.session_state.download_error = None
    st.session_state.download_complete = False
    if not url:
        st.session_state.download_error = "Please enter a valid URL."
        return False

    if check_existing_audio(url):
        st.info("Using previously downloaded audio file.")
        return True

    with st.spinner("Downloading audio..."):
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                st.session_state.metadata = get_metadata(info_dict)
            audio_file = download_audio(url)
            if audio_file and os.path.exists(audio_file):
                st.session_state.audio_file = audio_file
                st.session_state.url = url
                st.session_state.file_size = os.path.getsize(audio_file)
                st.session_state.download_complete = True
                st.session_state.estimated_transcription_duration = estimate_transcription_time(audio_file)
                append_log(f"Downloaded audio: {audio_file} ({format_file_size(st.session_state.file_size)})")
                return True
            else:
                st.session_state.download_error = "Failed to download audio file."
                append_log(st.session_state.download_error)
                return False
        except Exception as e:
            st.session_state.download_error = f"Error downloading audio: {str(e)}"
            append_log(st.session_state.download_error)
            return False

def handle_transcription():
    """Transcribe the downloaded audio file and update session state."""
    st.session_state.transcription_error = None
    if not st.session_state.audio_file or not os.path.exists(st.session_state.audio_file):
        st.session_state.transcription_error = "No audio file available for transcription."
        append_log(st.session_state.transcription_error)
        return

    with st.spinner("Transcribing audio..."):
        try:
            result = transcribe_in_batches(st.session_state.audio_file)
            if result and result.get("text"):
                st.session_state.transcription_result = result
                title = st.session_state.metadata.get('podcast', {}).get('title', 'Podcast Transcript')
                save_transcript(result, st.session_state.url, title, st.session_state.metadata)
                append_log("Transcription completed successfully.")
            else:
                st.session_state.transcription_error = "Transcription failed or returned empty result."
                append_log(st.session_state.transcription_error)
        except Exception as e:
            st.session_state.transcription_error = f"Error during transcription: {str(e)}"
            append_log(st.session_state.transcription_error)

def create_download_buttons():
    """Display download buttons for the transcription result."""
    if st.session_state.transcription_result and st.session_state.metadata:
        col1, col2 = st.columns(2)
        full_data = {
            **st.session_state.metadata,
            'transcript': st.session_state.transcription_result.get("text", ""),
            'chunks': st.session_state.transcription_result.get("chunks", []),
            'raw_response': st.session_state.transcription_result
        }
        podcast = st.session_state.metadata.get('podcast', {})
        txt_content = (
            f"Title: {podcast.get('title', '')}\n"
            f"Podcast Show: {podcast.get('Podcast Show', '')}\n"
            f"URL: {podcast.get('url', '')}\n"
            f"Date posted: {podcast.get('Date posted', '')}\n"
            f"Date transcribed: {podcast.get('Date transcribed', '')}\n\n"
            f"Transcript:\n{st.session_state.transcription_result.get('text', '')}\n"
        )
        with col1:
            st.download_button("Download as JSON", data=json.dumps(full_data, indent=2),
                               file_name="transcript_full.json", mime="application/json")
        with col2:
            st.download_button("Download as TXT", data=txt_content,
                               file_name="transcript.txt", mime="text/plain")

def main():
    st.set_page_config(page_title="Podcast Transcription App", layout="wide")
    st.title("🎙️ Podcast Transcription App")
    st.write("Transform your favorite podcasts into text with our transcription tool.")
    initialize_session_state()
    setup_fal_api()

    # Layout: two columns (input on left, status and logs on right)
    input_col, status_col = st.columns([2, 1])
    
    with input_col:
        url = st.text_input("Enter podcast URL", key="url_input",
                            placeholder="https://example.com/podcast/episode",
                            help="Paste the URL of the podcast episode you want to transcribe.")
        btn_cols = st.columns(2)
        if btn_cols[0].button("📥 Download Audio"):
            if handle_download(url):
                st.success(f"Download complete - {format_file_size(st.session_state.file_size)}")
                if st.session_state.estimated_transcription_duration:
                    expected_minutes = st.session_state.estimated_transcription_duration / 60
                    st.info(f"Expected transcription time: {expected_minutes:.2f} minutes")
            else:
                st.error(st.session_state.download_error)
        if btn_cols[1].button("🎯 Transcribe", disabled=not st.session_state.download_complete):
            handle_transcription()
            if st.session_state.transcription_result:
                st.success("Transcription completed!")
            else:
                st.error(st.session_state.transcription_error)
                
    with status_col:
        st.subheader("Status")
        if st.session_state.download_complete:
            st.write(f"✅ Download complete - {format_file_size(st.session_state.file_size)}")
            if st.session_state.estimated_transcription_duration:
                expected_minutes = st.session_state.estimated_transcription_duration / 60
                st.write(f"⏳ Expected transcription time: {expected_minutes:.2f} minutes")
        if st.session_state.transcription_error:
            st.error(f"❌ {st.session_state.transcription_error}")
        elif st.session_state.transcription_result:
            st.write("Transcription finished successfully.")
        st.subheader("Process Logs")
        display_logs()

    if st.session_state.transcription_result:
        st.subheader("📝 Transcript")
        st.text_area("Full Transcript", st.session_state.transcription_result.get("text", ""), height=400)
        create_download_buttons()

if __name__ == "__main__":
    main()
