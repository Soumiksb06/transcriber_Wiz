import json
import streamlit as st
import yt_dlp
import os
from datetime import datetime
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
        'logs': ""
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def append_log(message: str):
    """Append a timestamped message to the log."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs += f"{timestamp} - {message}\n"

def display_logs():
    """Display the process logs."""
    st.text_area("Logs", st.session_state.logs, height=200)

def handle_download(url: str) -> bool:
    """Download audio from the provided URL and update session state."""
    st.session_state.download_error = None
    if not url:
        st.session_state.download_error = "Please enter a valid URL."
        return False

    append_log("Starting download...")
    audio_file = download_audio(url)
    if audio_file and os.path.exists(audio_file):
        st.session_state.audio_file = audio_file
        st.session_state.url = url
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info_dict = ydl.extract_info(url, download=False)
            st.session_state.metadata = get_metadata(info_dict)
        except Exception as e:
            st.session_state.metadata = {}
            append_log(f"Metadata extraction error: {str(e)}")
        st.session_state.file_size = os.path.getsize(audio_file)
        append_log(f"Downloaded audio: {audio_file} ({st.session_state.file_size} bytes)")
        return True
    else:
        st.session_state.download_error = "Failed to download audio file."
        append_log(st.session_state.download_error)
        return False

def handle_transcription():
    """Transcribe the downloaded audio and update session state."""
    st.session_state.transcription_error = None
    if not st.session_state.audio_file or not os.path.exists(st.session_state.audio_file):
        st.session_state.transcription_error = "No audio file available for transcription."
        append_log(st.session_state.transcription_error)
        return

    append_log("Starting transcription...")
    result = transcribe_in_batches(st.session_state.audio_file)
    if result and result.get("text"):
        st.session_state.transcription_result = result
        title = st.session_state.metadata.get('podcast', {}).get('title', 'Podcast Transcript')
        save_transcript(result, st.session_state.url, title, st.session_state.metadata)
        append_log("Transcription completed successfully.")
    else:
        st.session_state.transcription_error = "Transcription failed or returned empty result."
        append_log(st.session_state.transcription_error)

def create_download_buttons():
    """Create download buttons for JSON and TXT versions of the transcript."""
    if st.session_state.transcription_result and st.session_state.metadata:
        col1, col2 = st.columns(2)
        full_data = {**st.session_state.metadata,
                     "transcript": st.session_state.transcription_result.get("text", ""),
                     "chunks": st.session_state.transcription_result.get("chunks", []),
                     "raw_response": st.session_state.transcription_result}
        txt_content = f"Transcript:\n{st.session_state.transcription_result.get('text', '')}\n"
        with col1:
            st.download_button("Download JSON",
                               data=json.dumps(full_data, indent=2),
                               file_name="transcript.json",
                               mime="application/json")
        with col2:
            st.download_button("Download TXT",
                               data=txt_content,
                               file_name="transcript.txt",
                               mime="text/plain")

def main():
    st.set_page_config(page_title="Podcast Transcription App", layout="wide")
    st.title("Podcast Transcription App")
    st.write("Enter a podcast URL to download and transcribe the audio using the Wizper API.")

    initialize_session_state()

    # Layout: input area on the left, status and logs on the right.
    col_input, col_status = st.columns([2, 1])
    
    with col_input:
        url = st.text_input("Podcast URL",
                            key="url_input",
                            placeholder="https://example.com/your-podcast-episode")
        btn_cols = st.columns(2)
        if btn_cols[0].button("Download Audio"):
            if handle_download(url):
                st.success("Download completed.")
            else:
                st.error(st.session_state.download_error)
        if btn_cols[1].button("Transcribe"):
            handle_transcription()
            if st.session_state.transcription_result:
                st.success("Transcription completed.")
            else:
                st.error(st.session_state.transcription_error)
    
    with col_status:
        if st.session_state.audio_file:
            st.write(f"Downloaded file: {st.session_state.audio_file} ({st.session_state.file_size} bytes)")
        if st.session_state.transcription_result:
            st.subheader("Transcription Result")
            st.text_area("Transcript", st.session_state.transcription_result.get("text", ""), height=300)
        display_logs()
        create_download_buttons()

if __name__ == "__main__":
    main()
