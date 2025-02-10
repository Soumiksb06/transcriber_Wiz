import os
import sys
import fal_client
import yt_dlp
import unicodedata
import re
import shutil
import json
from dotenv import load_dotenv
import time
import streamlit as st
import io
import contextlib

# -------------------- Provided Components --------------------

def setup_fal_api():
    """Set up FAL API key from st.secrets."""
    try:
        fal_key = st.secrets["FAL_KEY"]
        os.environ['FAL_KEY'] = fal_key
        return fal_key
    except Exception as e:
        st.error("FAL_KEY not found in st.secrets. Please add it to your secrets file.")
        raise e

def sanitize_filename(filename):
    """
    Sanitize filename to handle special characters and encoding issues
    """
    # Remove common podcast URL elements
    filename = re.sub(r'\/podcast\/', '', filename)
    # Remove any ID patterns like 'id1469759170'
    filename = re.sub(r'id\d+', '', filename)
    # Remove URL parameters
    filename = filename.split('?')[0]
    # Get the last part of the path
    filename = filename.split('/')[-1]
    
    # Convert to ASCII and clean up
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
        # Handle podcast URLs
        if 'podcast' in url:
            # Extract the episode name from the URL path
            path = url.split('/')
            for segment in path:
                if len(segment) > 10:  # Assume longer segments might be title
                    cleaned = segment.replace('-', ' ')
                    if not cleaned.startswith('id') and not cleaned.isdigit():
                        return sanitize_filename(segment)
        
        # If we can't extract from URL or it's not a podcast URL,
        # use the fallback title
        if fallback_title:
            return sanitize_filename(fallback_title)
            
        return 'transcript'
    except Exception as e:
        print(f"Error extracting episode name: {str(e)}")
        return 'transcript'

def save_transcript(result, url=None, title=None):
    """Save transcription result to episode-named file"""
    if result and 'text' in result:
        try:
            # Get episode name from URL or title
            episode_name = get_episode_name(url, title)
            transcript_filename = f"{episode_name}.txt"
            json_filename = f"{episode_name}_full.json"
            
            # Save text version
            with open(transcript_filename, 'w', encoding='utf-8') as f:
                f.write(result['text'])
            print(f"Transcript saved successfully to {transcript_filename}")

            # Save full result including chunks
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"Full transcript data saved to {json_filename}")

        except Exception as e:
            print(f"Error saving transcript: {str(e)}")
    else:
        print("Error: No valid transcription result to save")

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
                print(f"Error: Expected output file {final_filename} not found")
                return None

    except Exception as e:
        print(f"Download error: {str(e)}")
        return None

def on_queue_update(update):
    """Handle transcription queue updates"""
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            try:
                print(log["message"].encode('utf-8', errors='replace').decode('utf-8'))
            except Exception as e:
                print(f"Log encoding error: {str(e)}")

def transcribe_audio(file_path: str):
    """Transcribe audio file using Fal.ai"""
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
            on_queue_update=on_queue_update,
        )
        return result
    except Exception as e:
        print(f"Transcription error: {str(e)}")
        return None

def transcribe_in_batches(file_path, max_size_mb=30):
    """Transcribe audio file in batches if larger than specified size"""
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

def download_and_transcribe(url):
    """Download audio from URL and transcribe"""
    try:
        # Setup FAL API key first from secrets
        setup_fal_api()
        
        start_time = time.time()
        print("Starting download and transcription...")
        
        # Get video info first to extract title
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            title = info_dict.get('title', None)
        
        audio_file = download_audio(url)
        download_time = time.time()
        print(f"Download completed in {download_time - start_time:.2f} seconds")
        
        if audio_file and os.path.exists(audio_file):
            result = transcribe_in_batches(audio_file)
            if result:
                save_transcript(result, url=url, title=title)
                end_time = time.time()
                print(f"\nTotal processing time: {end_time - start_time:.2f} seconds")
                print(f"- Download time: {download_time - start_time:.2f} seconds")
                print(f"- Transcription time: {end_time - download_time:.2f} seconds")
            return result
        return None
    except Exception as e:
        print(f"Download and transcribe error: {str(e)}")
        return None

# -------------------- Streamlit Application --------------------

def main():
    st.set_page_config(page_title="Podcast Transcription App", layout="wide")
    st.title("🎙️ Podcast Transcription App")
    
    # Load FAL API key from st.secrets automatically
    if "FAL_KEY" in st.secrets:
        fal_key = st.secrets["FAL_KEY"]
        os.environ["FAL_KEY"] = fal_key
    else:
        st.sidebar.error("FAL API key not found in secrets. Please add it to your secrets file.")
        st.stop()
    
    st.sidebar.header("Instructions")
    st.sidebar.markdown("""
    1. **Enter Podcast URL:** Paste the URL of your podcast episode.
    2. **Download & Transcribe:** Click the button below to start the process.
    3. **View & Download:** After processing, preview the transcript and download the results.
    """)
    
    url = st.text_input("Enter Podcast URL:", placeholder="https://example.com/your-podcast-episode")
    
    if st.button("Download & Transcribe"):
        if not url:
            st.error("Please enter a valid URL.")
            return
        
        # Capture print() output for logs
        log_output = io.StringIO()
        with st.spinner("Processing... This may take a few minutes."):
            with contextlib.redirect_stdout(log_output):
                result = download_and_transcribe(url)
        logs = log_output.getvalue()
        st.text_area("Process Logs", logs, height=300)
        
        if result and result.get('text'):
            st.success("Transcription completed successfully!")
            st.subheader("Transcript Preview")
            st.text_area("", result.get('text', ""), height=300)
            
            # Extract title again to generate file names
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
                    title = info_dict.get('title', None)
            except Exception as e:
                title = None
            
            episode_name = get_episode_name(url, title)
            transcript_filename = f"{episode_name}.txt"
            json_filename = f"{episode_name}_full.json"
            
            # Read saved transcript files for download
            transcript_text = ""
            transcript_json = ""
            if os.path.exists(transcript_filename):
                with open(transcript_filename, 'r', encoding='utf-8') as f:
                    transcript_text = f.read()
            if os.path.exists(json_filename):
                with open(json_filename, 'r', encoding='utf-8') as f:
                    transcript_json = f.read()
            
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
                    data=transcript_json,
                    file_name=json_filename,
                    mime="application/json"
                )
        else:
            st.error("Transcription failed or returned an empty result.")

if __name__ == '__main__':
    main()
