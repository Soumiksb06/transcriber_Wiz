import os
import sys
import re
import json
import time
import subprocess
import unicodedata
from datetime import datetime

import streamlit as st
import yt_dlp
from dotenv import load_dotenv
import fal_client  # Ensure you have the fal_client package installed

# -------------------------------------------------------------------
# Global logger function; by default it prints to console.
# In the Streamlit app we override this with a function that writes to a text area.
logger = print

# -------------------------------------------------------------------
# Utility functions (same as your original code but with logger instead of print)
def get_metadata(info_dict):
    """Extract metadata from yt-dlp info dictionary"""
    return {
        "api": "Wizper",
        "podcast": {
            "title": info_dict.get('title', ''),
            "Podcast Show": info_dict.get('channel', '') or info_dict.get('uploader', ''),
            "url": info_dict.get('original_url', ''),
            "Date posted": datetime.fromtimestamp(info_dict.get('timestamp') or info_dict.get('release_timestamp', 0)).strftime('%Y-%m-%d') if info_dict.get('timestamp') or info_dict.get('release_timestamp') else None,
            "Date transcribed": datetime.now().strftime('%Y-%m-%d'),
            "Transcript": ""
        }
    }

def sanitize_filename(filename):
    """
    Sanitize filename to handle special characters and encoding issues
    """
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
    """
    Extract episode name from URL or use fallback title
    """
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
        logger(f"Error extracting episode name: {str(e)}")
        return 'transcript'

def save_transcript(result, url=None, title=None, metadata=None):
    """Save transcription result to episode-named file with metadata"""
    if result and 'text' in result:
        try:
            episode_name = get_episode_name(url, title)
            transcript_filename = f"{episode_name}.txt"
            json_filename = f"{episode_name}_full.json"
            
            if metadata:
                metadata['podcast']['Transcript'] = result['text']
                full_result = {
                    **metadata,
                    'chunks': result.get('chunks', []),
                    'raw_response': result
                }
            else:
                full_result = result

            with open(transcript_filename, 'w', encoding='utf-8') as f:
                if metadata:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)
                else:
                    f.write(result['text'])
            logger(f"Transcript saved successfully to {transcript_filename}")

            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(full_result, f, ensure_ascii=False, indent=2)
            logger(f"Full transcript data saved to {json_filename}")

        except Exception as e:
            logger(f"Error saving transcript: {str(e)}")
    else:
        logger("Error: No valid transcription result to save")

def download_audio(url):
    """Download audio from URL using yt-dlp with encoding handling"""
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
                logger(f"Error: Expected output file {final_filename} not found")
                return None

    except Exception as e:
        logger(f"Download error: {str(e)}")
        return None

def on_queue_update(update):
    """Handle transcription queue updates"""
    if isinstance(update, fal_client.InProgress):
        for log_item in update.logs:
            try:
                msg = log_item["message"].encode('utf-8', errors='replace').decode('utf-8')
                logger(msg)
            except Exception as e:
                logger(f"Log encoding error: {str(e)}")

def transcribe_audio(file_path: str):
    """Transcribe audio file using Fal.ai"""
    try:
        if not os.path.exists(file_path):
            logger(f"Error: Input file {file_path} does not exist")
            return None

        file_path = os.path.abspath(file_path)
        audio_url = fal_client.upload_file(file_path)
        logger(f"Uploaded file URL: {audio_url}")

        result = fal_client.subscribe(
            "fal-ai/wizper",
            arguments={
                "audio_url": audio_url,
                "task": "transcribe",
                "chunk_level": "segment",
                "version": "3",
                "language": "en",
                "diarize": True,
                "num_speakers": 2
            },
            with_logs=True,
            on_queue_update=on_queue_update,
        )
        return result
    except Exception as e:
        logger(f"Transcription error: {str(e)}")
        return None

def transcribe_in_batches(file_path, max_size_mb=30):
    """Transcribe audio file in batches if larger than specified size"""
    try:
        batch_start_time = time.time()
        if not os.path.exists(file_path):
            logger(f"Error: Input file {file_path} does not exist")
            return None

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb <= max_size_mb:
            return transcribe_audio(file_path)

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
        logger(f"\nProcessing {total_batches} batches...")

        for batch_num, start in enumerate(range(0, int(total_duration), int(batch_duration)), 1):
            batch_process_start = time.time()
            batch_output = f"batch_{start}_{sanitize_filename(base_name)}.mp3"
            
            logger(f"\nProcessing batch {batch_num}/{total_batches}")
            
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
                    logger(f"Batch {batch_num} completed in {batch_process_end - batch_process_start:.2f} seconds")
                    
                except Exception as e:
                    logger(f"Error processing batch {batch_num}: {str(e)}")
            else:
                logger(f"Error: Batch file {batch_output} was not created")

        total_batch_time = time.time() - batch_start_time
        logger(f"\nTotal batch processing time: {total_batch_time:.2f} seconds")
        logger(f"Average time per batch: {total_batch_time/total_batches:.2f} seconds")
        
        return full_transcription
    except Exception as e:
        logger(f"Batch processing error: {str(e)}")
        return None

def download_and_transcribe(url):
    """Download audio from URL and transcribe with metadata"""
    try:
        # Setup FAL API key first (see function below)
        setup_fal_api()
        
        start_time = time.time()
        logger("Starting download and transcription...")
        
        # Get video info first to extract metadata
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            metadata = get_metadata(info_dict)
            title = info_dict.get('title', None)
        
        audio_file = download_audio(url)
        download_time = time.time()
        logger(f"Download completed in {download_time - start_time:.2f} seconds")
        
        if audio_file and os.path.exists(audio_file):
            result = transcribe_in_batches(audio_file)
            if result:
                save_transcript(result, url=url, title=title, metadata=metadata)
                end_time = time.time()
                logger(f"\nTotal processing time: {end_time - start_time:.2f} seconds")
                logger(f"- Download time: {download_time - start_time:.2f} seconds")
                logger(f"- Transcription time: {end_time - download_time:.2f} seconds")
            return result
        return None
    except Exception as e:
        logger(f"Download and transcribe error: {str(e)}")
        return None

# -------------------------------------------------------------------
# API Key Setup for Streamlit using st.secrets (or a text input if not set)
def setup_fal_api():
    """
    Set up FAL API key from Streamlit secrets if available, otherwise prompt user.
    """
    # Check if the key is in Streamlit secrets
    if 'FAL_KEY' in st.secrets and st.secrets['FAL_KEY']:
        fal_key = st.secrets['FAL_KEY']
        os.environ['FAL_KEY'] = fal_key
    else:
        fal_key = st.text_input("Enter your FAL API key:", type="password")
        if fal_key:
            os.environ['FAL_KEY'] = fal_key
        else:
            st.error("FAL API key is required to proceed.")
            st.stop()
    return fal_key

# -------------------------------------------------------------------
# Main Streamlit App
def main():
    st.title("Podcast Transcription App")
    st.write("This app downloads and transcribes podcast episodes from a given URL using Fal.ai and yt-dlp.")

    # Initialize session state for logs if not present
    if 'log_text' not in st.session_state:
        st.session_state.log_text = ""

    # Create an empty container for log output
    log_area = st.empty()

    # Override the global logger to write to the Streamlit log area
    def app_log(msg):
        st.session_state.log_text += msg + "\n"
        log_area.text_area("Logs", st.session_state.log_text, height=300)
    global logger
    logger = app_log

    # Ensure the FAL API key is set (from st.secrets or user input)
    setup_fal_api()

    # Form for URL input and submission
    with st.form("transcription_form"):
        url = st.text_input("Enter the URL to transcribe")
        submit_button = st.form_submit_button("Transcribe")

    if submit_button:
        if not url:
            st.error("Please enter a valid URL.")
        else:
            st.write("Processing... This might take a few minutes.")
            # Run the transcription process and display a spinner during processing
            with st.spinner("Downloading and transcribing..."):
                result = download_and_transcribe(url)
            if result and result.get('text'):
                st.success("Transcription completed!")
                st.text_area("Transcript", result.get('text'), height=300)
            else:
                st.error("Transcription failed or returned empty result.")

if __name__ == "__main__":
    main()
