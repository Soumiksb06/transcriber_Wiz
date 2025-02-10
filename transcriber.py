# transcriber.py
import os
import subprocess
import time
import yt_dlp
import fal_client
from utils import sanitize_filename
from logger import Logger

log = Logger()

def setup_api() -> bool:
    """
    Ensure the FAL_KEY environment variable is set and configure the client.
    """
    api_key = os.getenv("FAL_KEY")
    if not api_key:
        log.log("Error: FAL_KEY environment variable is not set.")
        return False
    fal_client.set_api_key(api_key)
    return True

def download_audio(url: str) -> str:
    """
    Download audio from the given URL using yt-dlp.
    Returns the filename of the downloaded audio.
    """
    try:
        # Extract basic info (e.g. title) without downloading
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
            log.log(f"Error: Expected output file {final_filename} not found.")
            return None
    except Exception as e:
        log.log(f"Download error: {str(e)}")
        return None

def transcribe_audio(file_path: str) -> dict:
    """
    Transcribe the audio file using the Wizper API.
    
    This function uploads the file using fal_client.upload_file() and then
    calls fal_client.subscribe() with the following parameters (as documented):
      - audio_url: URL of the uploaded file
      - task: "transcribe" (default)
      - language: "en" (default)
      - chunk_level: "segment" (default)
      - version: "3" (default)
    
    The on_queue_update callback logs status updates from the API.
    """
    if not os.path.exists(file_path):
        log.log(f"Error: Input file {file_path} does not exist.")
        return None

    if not setup_api():
        return None

    # Upload the file so that the API can access it
    audio_url = fal_client.upload_file(file_path)
    if not audio_url:
        log.log("Error: File upload failed.")
        return None

    log.log(f"File uploaded successfully. URL: {audio_url}")

    # Define a callback to log progress updates
    def on_queue_update(update):
        if isinstance(update, fal_client.InProgress):
            for item in update.logs:
                log.log(item.get("message", "No message"))
        else:
            log.log("Queue update: " + str(update))

    # Submit the transcription request with the documented arguments
    result = fal_client.subscribe(
        "fal-ai/wizper",
        arguments={
            "audio_url": audio_url,
            "task": "transcribe",
            "language": "en",
            "chunk_level": "segment",
            "version": "3"
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    log.log("Transcription result received.")
    return result

def transcribe_in_batches(file_path: str, max_size_mb: int = 30) -> dict:
    """
    Transcribe the audio file in batches if it exceeds max_size_mb.
    
    If the file is smaller than max_size_mb, a single call to transcribe_audio()
    is made. Otherwise, the file is split into 30-minute batches using ffmpeg,
    each batch is transcribed, and the results are combined.
    """
    try:
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb <= max_size_mb:
            return transcribe_audio(file_path)

        # Obtain the total duration using ffprobe
        escaped_path = file_path.replace('"', '\\"')
        cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{escaped_path}"'
        total_duration = float(subprocess.check_output(cmd, shell=True))
        batch_duration = 30 * 60  # 30 minutes per batch

        full_transcription = {"text": "", "chunks": []}
        base_name = os.path.splitext(os.path.basename(file_path))[0]

        for start in range(0, int(total_duration), int(batch_duration)):
            batch_file = f"batch_{start}_{sanitize_filename(base_name)}.mp3"
            # Split the file using ffmpeg
            cut_cmd = f'ffmpeg -i "{file_path}" -ss {start} -t {batch_duration} -acodec copy "{batch_file}"'
            subprocess.call(cut_cmd, shell=True)

            if os.path.exists(batch_file):
                batch_result = transcribe_audio(batch_file)
                if batch_result and batch_result.get("text"):
                    full_transcription["text"] += batch_result["text"] + " "
                    if "chunks" in batch_result:
                        for chunk in batch_result["chunks"]:
                            # Adjust chunk timestamps based on batch start
                            if "start" in chunk and "end" in chunk:
                                chunk["start"] += start
                                chunk["end"] += start
                            full_transcription["chunks"].append(chunk)
                os.remove(batch_file)
                log.log(f"Batch starting at {start} seconds processed.")
            else:
                log.log(f"Error: Batch file {batch_file} was not created.")

        return full_transcription
    except Exception as e:
        log.log(f"Batch processing error: {str(e)}")
        return None

def estimate_transcription_time(audio_file: str) -> float:
    """
    Estimate transcription time based on file size.
    
    Rough estimation: 1 MB takes about 10 seconds to process.
    """
    file_size = os.path.getsize(audio_file)
    return (file_size / (1024 * 1024)) * 10
