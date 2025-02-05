# main.py
import json
import streamlit as st
import yt_dlp
import os
from config import setup_fal_api
from utils import get_metadata
from transcriber import download_audio, transcribe_in_batches
from file_manager import save_transcript

def initialize_session_state():
    """Initialize session state variables."""
    if 'audio_file' not in st.session_state:
        st.session_state.audio_file = None
    if 'transcription_result' not in st.session_state:
        st.session_state.transcription_result = None
    if 'metadata' not in st.session_state:
        st.session_state.metadata = None
    if 'url' not in st.session_state:
        st.session_state.url = ""
    if 'log_text' not in st.session_state:
        st.session_state.log_text = ""

def handle_download(url: str):
    """Handle the audio download process."""
    if not url:
        st.error("Please enter a valid URL.")
        return False
    
    # Check if we already have this URL downloaded
    if st.session_state.audio_file and st.session_state.url == url:
        if os.path.exists(st.session_state.audio_file):
            st.info("Using previously downloaded audio file.")
            return True
    
    # Extract video info and metadata
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            st.session_state.metadata = get_metadata(info_dict)
            audio_file = download_audio(url)
            
            if audio_file and os.path.exists(audio_file):
                st.session_state.audio_file = audio_file
                st.session_state.url = url
                return True
            else:
                st.error("Failed to download audio file.")
                return False
    except Exception as e:
        st.error(f"Error downloading audio: {str(e)}")
        return False

def handle_transcription():
    """Handle the transcription process."""
    if not st.session_state.audio_file or not os.path.exists(st.session_state.audio_file):
        st.error("No audio file available for transcription.")
        return
    
    with st.spinner("Transcribing audio..."):
        result = transcribe_in_batches(st.session_state.audio_file)
        if result:
            st.session_state.transcription_result = result
            # Save transcript files locally
            save_transcript(result, st.session_state.url, 
                          st.session_state.metadata['podcast']['title'], 
                          st.session_state.metadata)
            st.success("Transcription completed!")
        else:
            st.error("Transcription failed.")

def create_download_buttons():
    """Create download buttons for transcription results."""
    if st.session_state.transcription_result and st.session_state.metadata:
        # Combine metadata and transcript for JSON download
        full_data = {
            **st.session_state.metadata,
            'transcript': st.session_state.transcription_result["text"],
            'chunks': st.session_state.transcription_result.get("chunks", []),
            'raw_response': st.session_state.transcription_result
        }
        
        # JSON download
        json_data = json.dumps(full_data, indent=2)
        st.download_button(
            "Download as JSON",
            data=json_data,
            file_name="transcript_full.json",
            mime="application/json",
            key="json_download"  # Unique key prevents reset
        )
        
        # TXT download
        podcast = st.session_state.metadata.get('podcast', {})
        txt_content = (
            f"Title: {podcast.get('title', '')}\n"
            f"Podcast Show: {podcast.get('Podcast Show', '')}\n"
            f"URL: {podcast.get('url', '')}\n"
            f"Date posted: {podcast.get('Date posted', '')}\n"
            f"Date transcribed: {podcast.get('Date transcribed', '')}\n\n"
            f"Transcript:\n{st.session_state.transcription_result.get('text', '')}\n"
        )
        st.download_button(
            "Download as TXT",
            data=txt_content,
            file_name="transcript.txt",
            mime="text/plain",
            key="txt_download"  # Unique key prevents reset
        )

def main():
    st.title("Podcast Transcription App")
    st.write("This app downloads and transcribes podcast episodes from a given URL using Fal.ai and yt-dlp.")
    
    # Initialize session state
    initialize_session_state()
    
    # Set up API key
    setup_fal_api()
    
    # URL input
    url = st.text_input("Enter the URL to transcribe", key="url_input")
    
    # Download and transcribe sections
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("Download Audio", key="download_button"):
            handle_download(url)
    
    with col2:
        if st.button("Transcribe", key="transcribe_button", 
                    disabled=not st.session_state.audio_file):
            handle_transcription()
    
    # Show current audio file
    if st.session_state.audio_file:
        st.info(f"Current audio file: {os.path.basename(st.session_state.audio_file)}")
    
    # Show transcript if available
    if st.session_state.transcription_result:
        st.text_area("Transcript", st.session_state.transcription_result.get("text", ""), 
                    height=300, key="transcript_area")
        
        # Add download buttons
        create_download_buttons()

if __name__ == "__main__":
    main()
