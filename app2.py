import os
import fal_client
import yt_dlp
import unicodedata
import re
import json
import time
import streamlit as st
from datetime import datetime, timedelta

# -------------------- Provided Backend Components --------------------
# (These functions are taken from your provided code and are unchanged.)

def setup_fal_api():
    # FAL API key is now loaded automatically from st.secrets.
    try:
        fal_key = st.secrets["FAL_KEY"]
        os.environ["FAL_KEY"] = fal_key
        return fal_key
    except Exception as e:
        st.error("FAL_KEY not found in st.secrets. Please add it to your secrets file.")
        raise e

def sanitize_filename(filename):
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
        print(f"Error extracting episode name: {str(e)}")
        return 'transcript'

def download_audio(url):
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
                print(f"Error: Expected output file {final_filename} not found")
                return None
    except Exception as e:
        print(f"Download error: {str(e)}")
        return None

def transcribe_audio(file_path: str):
    try:
        if not os.path.exists(file_path):
            print(f"Error: Input file {file_path} does not exist")
            return None
        file_path = os.path.abspath(file_path)
        audio_url = fal_client.upload_file(file_path)
        print(f"Uploaded file URL: {audio_url}")
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
            on_queue_update=lambda update: print(update),
        )
        return result
    except Exception as e:
        print(f"Transcription error: {str(e)}")
        return None

def transcribe_in_batches(file_path, max_size_mb=30):
    try:
        batch_start_time = time.time()
        if not os.path.exists(file_path):
            print(f"Error: Input file {file_path} does not exist")
            return None
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb <= max_size_mb:
            return transcribe_audio(file_path)
        import subprocess
        def get_audio_duration():
            escaped_path = file_path.replace('"', '\\"')
            cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{escaped_path}"'
            duration = subprocess.check_output(cmd, shell=True)
            return float(duration)
        total_duration = get_audio_duration()
        batch_duration = 30 * 60  # 30 minutes per batch
        full_transcription = {"text": "", "chunks": []}
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        total_batches = (int(total_duration) + int(batch_duration) - 1) // int(batch_duration)
        print(f"\nProcessing {total_batches} batches...")
        for batch_num, start in enumerate(range(0, int(total_duration), int(batch_duration)), 1):
            batch_process_start = time.time()
            batch_output = f"batch_{start}_{sanitize_filename(base_name)}.mp3"
            print(f"\nProcessing batch {batch_num}/{total_batches}")
            escaped_input = file_path.replace('"', '\\"')
            escaped_output = batch_output.replace('"', '\\"')
            cut_cmd = f'ffmpeg -i "{escaped_input}" -ss {start} -t {batch_duration} -acodec copy "{escaped_output}"'
            subprocess.call(cut_cmd, shell=True)
            if os.path.exists(batch_output):
                try:
                    batch_result = transcribe_audio(batch_output)
                    if batch_result:
                        full_transcription["text"] += batch_result["text"] + " "
                        if "chunks" in batch_result:
                            for chunk in batch_result["chunks"]:
                                chunk['start'] += start
                                chunk['end'] += start
                                full_transcription["chunks"].append(chunk)
                    if os.path.exists(batch_output):
                        os.remove(batch_output)
                    batch_process_end = time.time()
                    print(f"Batch {batch_num} completed in {batch_process_end - batch_process_start:.2f} seconds")
                except Exception as e:
                    print(f"Error processing batch {batch_num}: {str(e)}")
            else:
                print(f"Error: Batch file {batch_output} was not created")
        total_batch_time = time.time() - batch_start_time
        print(f"\nTotal batch processing time: {total_batch_time:.2f} seconds")
        print(f"Average time per batch: {total_batch_time/total_batches:.2f} seconds")
        return full_transcription
    except Exception as e:
        print(f"Batch processing error: {str(e)}")
        return None

def save_transcript(result, url=None, title=None):
    if result and 'text' in result:
        try:
            episode_name = get_episode_name(url, title)
            transcript_filename = f"{episode_name}.txt"
            json_filename = f"{episode_name}_full.json"
            with open(transcript_filename, 'w', encoding='utf-8') as f:
                f.write(result['text'])
            print(f"Transcript saved successfully to {transcript_filename}")
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"Full transcript data saved to {json_filename}")
        except Exception as e:
            print(f"Error saving transcript: {str(e)}")
    else:
        print("Error: No valid transcription result to save")

# -------------------- UI Helpers and Session State --------------------

def initialize_session_state():
    defaults = {
        "audio_file": None,
        "transcription_result": None,
        "download_error": "",
        "transcription_error": "",
        "logs": "",
        "processing": False,
        "transcription_completed": False,
        "url": ""
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def append_log(message: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs += f"{timestamp} - {message}\n"

def display_logs():
    with st.expander("Process Logs", expanded=False):
        st.text_area("", st.session_state.logs, height=200)

def create_download_buttons():
    if st.session_state.transcription_result and st.session_state.transcription_result.get("text"):
        transcript_text = st.session_state.transcription_result.get("text", "")
        episode_name = get_episode_name(st.session_state.url)
        transcript_filename = f"{episode_name}.txt"
        json_filename = f"{episode_name}_full.json"
        json_data = json.dumps(st.session_state.transcription_result, indent=2)
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                label="📄 Download TXT",
                data=transcript_text,
                file_name=transcript_filename,
                mime="text/plain"
            )
        with col2:
            st.download_button(
                label="📥 Download JSON",
                data=json_data,
                file_name=json_filename,
                mime="application/json"
            )

def handle_download(url):
    st.session_state.download_error = ""
    audio_file = download_audio(url)
    if audio_file and os.path.exists(audio_file):
        st.session_state.audio_file = audio_file
        st.session_state.logs += f"Downloaded audio: {audio_file}\n"
        return True
    else:
        st.session_state.download_error = "Failed to download audio file."
        st.session_state.logs += st.session_state.download_error + "\n"
        return False

def handle_transcription():
    if st.session_state.transcription_completed:
        st.session_state.logs += "Transcription already completed.\n"
        return
    st.session_state.transcription_error = ""
    if not st.session_state.audio_file or not os.path.exists(st.session_state.audio_file):
        st.session_state.transcription_error = "No audio file available for transcription."
        st.session_state.logs += st.session_state.transcription_error + "\n"
        return
    st.session_state.processing = True
    st.session_state.logs += "Starting transcription...\n"
    result = transcribe_in_batches(st.session_state.audio_file)
    if result and result.get("text"):
        st.session_state.transcription_result = result
        st.session_state.transcription_completed = True
        st.session_state.logs += "Transcription completed successfully.\n"
    else:
        st.session_state.transcription_error = "Transcription failed or returned empty result."
        st.session_state.logs += st.session_state.transcription_error + "\n"
    st.session_state.processing = False

# -------------------- Main Streamlit App --------------------

def main():
    st.set_page_config(page_title="Podcast Transcription App", layout="wide")
    st.title("🎙️ Podcast Transcription App")
    
    # Load FAL API key from st.secrets
    if "FAL_KEY" in st.secrets:
        fal_key = st.secrets["FAL_KEY"]
        os.environ["FAL_KEY"] = fal_key
    else:
        st.sidebar.error("FAL API key not found in secrets. Please add it to your secrets file.")
        st.stop()
    
    st.sidebar.header("How to Use")
    st.sidebar.markdown("""
    1. **Enter Podcast URL:** Paste the URL of your podcast episode.
    2. **Download Audio:** Click to download the audio file.
    3. **Start Transcription:** Click to transcribe the downloaded audio.
    4. **Download Results:** After transcription, download the transcript as TXT or JSON.
    """)
    
    initialize_session_state()
    
    col_input, col_status = st.columns([2, 1])
    
    with col_input:
        st.subheader("Input")
        url = st.text_input("Enter Podcast URL:", key="url_input", placeholder="https://example.com/your-podcast-episode")
        btn_cols = st.columns(2)
        if btn_cols[0].button("📥 Download Audio", disabled=st.session_state.processing):
            if url:
                st.session_state.url = url
                with st.spinner("Downloading audio..."):
                    if handle_download(url):
                        st.success("Download completed!")
                    else:
                        st.error(st.session_state.download_error)
            else:
                st.error("Please enter a valid URL.")
        if btn_cols[1].button("🎯 Start Transcription", disabled=(not st.session_state.audio_file or st.session_state.processing)):
            with st.spinner("Transcribing audio..."):
                handle_transcription()
            if st.session_state.transcription_completed:
                st.success("Transcription completed!")
                st.subheader("Transcript Preview")
                st.text_area("", st.session_state.transcription_result.get("text", ""), height=300)
            elif st.session_state.transcription_error:
                st.error(st.session_state.transcription_error)
                
    with col_status:
        st.subheader("Status")
        if st.session_state.audio_file:
            st.info(f"File: {os.path.basename(st.session_state.audio_file)}")
            try:
                file_size = os.path.getsize(st.session_state.audio_file)
                st.info(f"Size: {file_size} bytes")
            except Exception:
                pass
        if st.session_state.transcription_completed:
            create_download_buttons()
    
    display_logs()

if __name__ == '__main__':
    main()
