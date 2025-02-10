import json
import streamlit as st
import yt_dlp
import os
import requests
from datetime import datetime, timedelta
import time
from transcriber import transcribe_in_batches
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
        'download_progress': 0,
        'download_speed': 0,
        'estimated_time': "calculating..."
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def append_log(message: str):
    """Append a timestamped message to the log."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs += f"{timestamp} - {message}\n"

def format_size(size):
    """Format size in bytes to human readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

def format_speed(speed):
    """Format speed in bytes/sec to human readable format."""
    return f"{format_size(speed)}/s"

def format_time(seconds):
    """Format seconds into human readable time."""
    if seconds < 60:
        return f"{seconds:.0f} seconds"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f} minutes"
    else:
        hours = seconds / 3600
        return f"{hours:.1f} hours"

def download_with_progress(url, output_path):
    """Download file with progress tracking."""
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    block_size = 1024  # 1 KB
    
    if total_size == 0:
        append_log("Warning: Content length not available")
        return None
    
    # Create progress bar
    progress_bar = st.progress(0)
    progress_text = st.empty()
    speed_text = st.empty()
    time_text = st.empty()
    
    # Initialize tracking variables
    downloaded = 0
    start_time = time.time()
    speeds = []  # Keep track of recent speeds
    
    try:
        with open(output_path, 'wb') as file:
            for data in response.iter_content(block_size):
                file.write(data)
                downloaded += len(data)
                
                # Calculate progress
                progress = (downloaded / total_size)
                progress_bar.progress(progress)
                
                # Calculate speed
                elapsed_time = time.time() - start_time
                if elapsed_time > 0:
                    speed = downloaded / elapsed_time
                    speeds.append(speed)
                    if len(speeds) > 50:  # Keep last 50 speed measurements
                        speeds.pop(0)
                    current_speed = sum(speeds) / len(speeds)
                    
                    # Calculate estimated time remaining
                    remaining_bytes = total_size - downloaded
                    estimated_time = remaining_bytes / current_speed if current_speed > 0 else 0
                    
                    # Update status
                    progress_text.text(f"Downloaded: {format_size(downloaded)} of {format_size(total_size)} ({progress:.1%})")
                    speed_text.text(f"Speed: {format_speed(current_speed)}")
                    time_text.text(f"Estimated time remaining: {format_time(estimated_time)}")
                    
                    # Update session state
                    st.session_state.download_progress = progress
                    st.session_state.download_speed = current_speed
                    st.session_state.estimated_time = format_time(estimated_time)
        
        # Clean up progress displays
        progress_bar.empty()
        progress_text.empty()
        speed_text.empty()
        time_text.empty()
        
        return output_path
        
    except Exception as e:
        append_log(f"Download error: {str(e)}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return None

def download_audio(url):
    """Download audio using yt-dlp with custom progress tracking."""
    try:
        # First get video info and best audio format
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_url = info['url']
            title = sanitize_filename(info['title'])
            
            # Create output path
            output_path = os.path.join('downloads', f"{title}.mp3")
            os.makedirs('downloads', exist_ok=True)
            
            # Download with progress
            append_log(f"Starting download of {title}")
            result = download_with_progress(audio_url, output_path)
            
            if result:
                append_log(f"Download completed: {title}")
                return output_path
            else:
                append_log("Download failed")
                return None
                
    except Exception as e:
        append_log(f"Error in download_audio: {str(e)}")
        return None

def create_download_buttons():
    """Create download buttons for JSON and TXT versions of the transcript."""
    if st.session_state.transcription_result and st.session_state.metadata:
        st.subheader("Download Results")
        
        # Get the transcript text
        transcript_text = st.session_state.transcription_result.get("text", "")
        
        # Create standardized JSON structure
        json_data = {
            "api": {
                "name": "Wizper",
                "timestamp": datetime.now().isoformat()
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
        
        txt_content = f"""Transcribed by Wizper API
Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Transcript:
{transcript_text}\n"""
        
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "📥 Download JSON",
                data=json.dumps(json_data, indent=2),
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

def handle_transcription():
    """Transcribe the downloaded audio and update session state."""
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
            audio_file = download_audio(url)
            if audio_file:
                st.session_state.audio_file = audio_file
                st.session_state.url = url
                st.success("✅ Download completed successfully!")
            else:
                st.error("❌ Download failed!")

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
        if st.session_state.download_speed:
            st.info(f"⚡ Download Speed: {format_speed(st.session_state.download_speed)}")
        if st.session_state.download_progress:
            st.info(f"📊 Progress: {st.session_state.download_progress:.1%}")
        if st.session_state.estimated_time:
            st.info(f"⏱️ Estimated Time: {st.session_state.estimated_time}")
        
        if st.session_state.transcription_completed:
            create_download_buttons()
        
        display_logs()

if __name__ == "__main__":
    main()
