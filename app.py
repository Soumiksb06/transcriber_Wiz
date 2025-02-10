import json
import streamlit as st
import yt_dlp
import os
from datetime import datetime, timedelta
from config import setup_fal_api  # Assuming this sets up FAL_KEY if needed
from utils import get_metadata, sanitize_filename
from transcriber import download_audio, transcribe_in_batches, estimate_transcription_time
from file_manager import save_transcript

def initialize_session_state():
    """Initialize session state variables."""
    initial_states = {
        'audio_file': None,
        'transcription_result': None,
        'metadata': None,
        'url': "",
        'log_text': "",
        'download_complete': False,
        'file_size': None,
        'transcription_start_time': None,
        'estimated_completion_time': None,
        'download_error': None,
        'transcription_error': None,
        'estimated_transcription_duration': None  # in seconds
    }
    
    for key, value in initial_states.items():
        if key not in st.session_state:
            st.session_state[key] = value

def format_file_size(size_bytes):
    """Convert file size to human readable format."""
    mb = size_bytes / (1024 * 1024)
    return f"{mb:.2f} MB"

def check_existing_audio(url):
    """Check if audio file already exists for the URL."""
    try:
        if st.session_state.audio_file and os.path.exists(st.session_state.audio_file):
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                # Get the expected filename using the title from the metadata
                title = info_dict.get('title', 'video')
                expected_filename = f"{sanitize_filename(title)}.mp3"
                if expected_filename == st.session_state.audio_file:
                    st.session_state.metadata = get_metadata(info_dict)
                    st.session_state.file_size = os.path.getsize(st.session_state.audio_file)
                    st.session_state.download_complete = True
                    return True
    except Exception as e:
        st.session_state.download_error = f"Error checking existing audio: {str(e)}"
    return False

def handle_download(url: str):
    """Handle the audio download process."""
    st.session_state.download_error = None
    st.session_state.download_complete = False
    
    if not url:
        st.session_state.download_error = "Please enter a valid URL."
        return False
    
    # Check for existing download
    if check_existing_audio(url):
        st.info("Using previously downloaded audio file.")
        return True
    
    try:
        with st.spinner("Downloading audio..."):
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                st.session_state.metadata = get_metadata(info_dict)
                audio_file = download_audio(url)
                if audio_file and os.path.exists(audio_file):
                    st.session_state.audio_file = audio_file
                    st.session_state.url = url
                    st.session_state.file_size = os.path.getsize(audio_file)
                    st.session_state.download_complete = True
                    # Calculate expected transcription duration (in seconds)
                    st.session_state.estimated_transcription_duration = estimate_transcription_time(audio_file)
                    return True
                else:
                    st.session_state.download_error = "Failed to download audio file."
                    return False
    except Exception as e:
        st.session_state.download_error = f"Error downloading audio: {str(e)}"
        return False

def handle_transcription():
    """Handle the transcription process."""
    st.session_state.transcription_error = None
    
    if not st.session_state.audio_file or not os.path.exists(st.session_state.audio_file):
        st.session_state.transcription_error = "No audio file available for transcription."
        return
    
    try:
        # Calculate estimated completion time based on when transcription starts
        file_duration = estimate_transcription_time(st.session_state.audio_file)
        st.session_state.transcription_start_time = datetime.now()
        st.session_state.estimated_completion_time = datetime.now() + timedelta(seconds=file_duration)
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        with st.spinner("Transcribing audio..."):
            result = transcribe_in_batches(st.session_state.audio_file)
            if result:
                st.session_state.transcription_result = result
                # The podcast title is assumed to be part of the metadata structure
                podcast_title = st.session_state.metadata.get('podcast', {}).get('title', 'Podcast Transcript')
                save_transcript(result, st.session_state.url, podcast_title, st.session_state.metadata)
                progress_bar.progress(100)
                status_text.success("Transcription completed!")
            else:
                st.session_state.transcription_error = "Transcription failed."
                
    except Exception as e:
        st.session_state.transcription_error = f"Error during transcription: {str(e)}"

def create_download_buttons():
    """Create download buttons for transcription results."""
    if st.session_state.transcription_result and st.session_state.metadata:
        col1, col2 = st.columns(2)
        
        # Prepare download data
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
            st.download_button(
                "📥 Download as JSON",
                data=json.dumps(full_data, indent=2),
                file_name="transcript_full.json",
                mime="application/json",
                key="json_download",
                use_container_width=True
            )
        
        with col2:
            st.download_button(
                "📄 Download as TXT",
                data=txt_content,
                file_name="transcript.txt",
                mime="text/plain",
                key="txt_download",
                use_container_width=True
            )

def show_guide():
    """Display the user guide in an expander."""
    with st.expander("📖 How to Use This App"):
        st.markdown("""
        ### Quick Start Guide
        
        1. **Find a Podcast URL** 📎
           - Copy the URL of any podcast episode you want to transcribe.
        
        2. **Download the Audio** ⬇️
           - Paste the URL in the input field.
           - Click 'Download Audio' and wait for the download to complete.
        
        3. **Generate Transcript** 🎯
           - Click 'Transcribe' after the download is complete.
           - The app will show estimated time remaining.
        
        4. **Get Your Results** 📄
           - View the transcript in the app.
           - Download as TXT or JSON for further use.
        """)

def main():
    st.set_page_config(page_title="Podcast Transcription App", layout="wide")
    st.title("🎙️ Podcast Transcription App")
    st.write("Transform your favorite podcasts into text with our easy-to-use transcription tool.")
    
    show_guide()
    initialize_session_state()
    
    # Set up API key if needed (from config)
    setup_fal_api()
    
    input_col, status_col = st.columns([2, 1])
    
    with input_col:
        url = st.text_input(
            "Enter podcast URL",
            key="url_input",
            placeholder="https://example.com/podcast/episode",
            help="Paste the URL of the podcast episode you want to transcribe"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📥 Download Audio", key="download_button", use_container_width=True):
                handle_download(url)
        with col2:
            if st.button(
                "🎯 Transcribe",
                key="transcribe_button",
                disabled=not st.session_state.download_complete,
                use_container_width=True
            ):
                handle_transcription()
    
    with status_col:
        st.subheader("Status")
        if st.session_state.download_complete:
            st.success(f"✅ Download complete - {format_file_size(st.session_state.file_size)}")
            if st.session_state.estimated_transcription_duration:
                # Show expected transcription time in minutes (rounded)
                expected_minutes = st.session_state.estimated_transcription_duration / 60
                st.info(f"⏳ Expected transcription time: {expected_minutes:.2f} minutes")
        elif st.session_state.download_error:
            st.error(f"❌ {st.session_state.download_error}")
        
        if st.session_state.transcription_error:
            st.error(f"❌ {st.session_state.transcription_error}")
        elif st.session_state.transcription_start_time and st.session_state.estimated_completion_time:
            remaining_time = st.session_state.estimated_completion_time - datetime.now()
            if remaining_time.total_seconds() > 0:
                st.info(f"⏳ Estimated time remaining: {remaining_time.seconds // 60} minutes")
    
    if st.session_state.transcription_result:
        st.subheader("📝 Transcript")
        st.text_area(
            "Full Transcript",
            st.session_state.transcription_result.get("text", ""),
            height=400,
            key="transcript_area"
        )
        create_download_buttons()

if __name__ == "__main__":
    main()
