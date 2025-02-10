import json
import streamlit as st
import yt_dlp
import os
import requests
import time
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
        'transcription_completed': False,
        'network_speed': None,
        'estimated_download_time': None
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def test_network_speed():
    """Test network download speed using a small file download."""
    test_file_url = "https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"
    try:
        start_time = time.time()
        response = requests.get(test_file_url, stream=True)
        file_size = int(response.headers.get('content-length', 0))
        
        # Download the file
        downloaded = 0
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                downloaded += len(chunk)
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Calculate speed in MB/s
        speed_mbps = (downloaded / 1024 / 1024) / duration
        return speed_mbps
    except Exception as e:
        append_log(f"Network speed test error: {str(e)}")
        return None

def estimate_download_time(file_size_bytes, speed_mbps):
    """Estimate download time based on file size and network speed."""
    if not speed_mbps or speed_mbps <= 0:
        return None
    
    # Convert file size to MB and calculate time in seconds
    file_size_mb = file_size_bytes / (1024 * 1024)
    estimated_seconds = file_size_mb / speed_mbps
    
    return estimated_seconds

def format_download_time(seconds):
    """Format download time in a human-readable format."""
    if seconds is None:
        return "Unknown"
    
    if seconds < 60:
        return f"{seconds:.1f} seconds"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f} minutes"
    else:
        hours = seconds / 3600
        return f"{hours:.1f} hours"

[... previous functions remain the same ...]

def handle_download(url: str) -> bool:
    """Download audio from the provided URL and update session state."""
    st.session_state.download_error = None
    st.session_state.transcription_completed = False
    if not url:
        st.session_state.download_error = "Please enter a valid URL."
        return False

    try:
        # Test network speed
        append_log("Testing network speed...")
        speed_mbps = test_network_speed()
        st.session_state.network_speed = speed_mbps
        append_log(f"Network speed: {speed_mbps:.2f} MB/s")

        with st.spinner("Fetching metadata..."):
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                st.session_state.metadata = get_metadata(info_dict)
                st.session_state.audio_duration = get_duration_from_metadata(info_dict)
                
                # Get file size from metadata if available
                filesize = info_dict.get('filesize') or info_dict.get('filesize_approx')
                if filesize:
                    st.session_state.file_size = filesize
                    if speed_mbps:
                        est_time = estimate_download_time(filesize, speed_mbps)
                        st.session_state.estimated_download_time = est_time
                        append_log(f"Estimated download time: {format_download_time(est_time)}")

        with st.spinner("Downloading audio..."):
            append_log("Starting download...")
            download_start_time = time.time()
            audio_file = download_audio(url)
            download_duration = time.time() - download_start_time
            
            if audio_file and os.path.exists(audio_file):
                st.session_state.audio_file = audio_file
                st.session_state.url = url
                actual_size = os.path.getsize(audio_file)
                st.session_state.file_size = actual_size
                
                # Calculate actual download speed
                actual_speed_mbps = (actual_size / 1024 / 1024) / download_duration
                append_log(f"Actual download speed: {actual_speed_mbps:.2f} MB/s")
                append_log(f"Downloaded audio: {audio_file} ({format_file_size(actual_size)})")
                return True
            else:
                st.session_state.download_error = "Failed to download audio file."
                append_log(st.session_state.download_error)
                return False
                
    except Exception as e:
        st.session_state.download_error = f"Error during download: {str(e)}"
        append_log(st.session_state.download_error)
        return False

[... previous functions remain the same ...]

def main():
    st.set_page_config(
        page_title="Podcast Transcription App",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    initialize_session_state()

    st.title("🎙️ Podcast Transcription App")
    
    [... previous sidebar code remains the same ...]

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

        [... rest of the button handling code remains the same ...]

    with col_status:
        st.subheader("Status")
        if st.session_state.network_speed:
            st.info(f"🌐 Network Speed: {st.session_state.network_speed:.2f} MB/s")
        
        if st.session_state.file_size and st.session_state.estimated_download_time:
            st.info(f"⏱️ Estimated Download Time: {format_download_time(st.session_state.estimated_download_time)}")
        
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
