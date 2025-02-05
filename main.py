# main.py
import json
import streamlit as st
import yt_dlp  # used directly for extracting video info
from config import setup_fal_api
from utils import get_metadata
from transcriber import download_audio, transcribe_in_batches
from file_manager import save_transcript

def download_and_transcribe(url: str) -> dict:
    """
    Downloads audio from a URL and transcribes it.
    Returns a dictionary combining metadata and the transcript.
    """
    # Set up API key
    setup_fal_api()
    st.write("Starting download and transcription...")
    
    # Extract video info and metadata.
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        info_dict = ydl.extract_info(url, download=False)
        metadata = get_metadata(info_dict)
        title = info_dict.get('title', None)
    
    # Download audio.
    audio_file = download_audio(url)
    if audio_file:
        result = transcribe_in_batches(audio_file)
        if result:
            # Save transcript files locally.
            save_transcript(result, url, title, metadata)
            # Combine metadata and transcript for download.
            full_data = {**metadata, 'transcript': result["text"], 'chunks': result.get("chunks", []), 'raw_response': result}
            return full_data
    return None

def main():
    st.title("Podcast Transcription App")
    st.write("This app downloads and transcribes podcast episodes from a given URL using Fal.ai and yt-dlp.")
    
    # Log area for process updates.
    if 'log_text' not in st.session_state:
        st.session_state.log_text = ""
    log_area = st.empty()
    
    def app_log(msg: str):
        st.session_state.log_text += msg + "\n"
        log_area.text_area("Logs", st.session_state.log_text, height=300)
    
    with st.form("transcription_form"):
        url = st.text_input("Enter the URL to transcribe")
        submit_button = st.form_submit_button("Transcribe")
    
    if submit_button:
        if not url:
            st.error("Please enter a valid URL.")
        else:
            st.write("Processing... This might take a few minutes.")
            with st.spinner("Downloading and transcribing..."):
                full_data = download_and_transcribe(url)
            if full_data and full_data.get('transcript'):
                st.success("Transcription completed!")
                st.text_area("Transcript", full_data.get('transcript'), height=300)
                
                # Prepare JSON download.
                json_data = json.dumps(full_data, indent=2)
                st.download_button("Download as JSON", data=json_data,
                                   file_name="transcript_full.json", mime="application/json")
                
                # Prepare TXT download (including metadata).
                podcast = full_data.get('podcast', {})
                txt_content = (
                    f"Title: {podcast.get('title', '')}\n"
                    f"Podcast Show: {podcast.get('Podcast Show', '')}\n"
                    f"URL: {podcast.get('url', '')}\n"
                    f"Date posted: {podcast.get('Date posted', '')}\n"
                    f"Date transcribed: {podcast.get('Date transcribed', '')}\n\n"
                    f"Transcript:\n{full_data.get('transcript')}\n"
                )
                st.download_button("Download as TXT", data=txt_content,
                                   file_name="transcript.txt", mime="text/plain")
            else:
                st.error("Transcription failed or returned empty result.")

if __name__ == "__main__":
    main()
