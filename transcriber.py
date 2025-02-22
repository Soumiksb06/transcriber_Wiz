# transcriber.py
import os
import subprocess
import time
import yt_dlp
import fal_client
from utils import sanitize_filename
from logger import Logger

log = Logger()

def download_audio(url: str) -> str:
    """
    Download audio from the given URL using yt-dlp.
    Returns the filename of the downloaded audio.
    """
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
            # Optionally, add 'ffmpeg_location': '/usr/bin' if needed.
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        final_filename = f"{safe_title}.mp3"
        if os.path.exists(final_filename):
            return final_filename
        else:
            log.log(f"Error: Expected output file {final_filename} not found")
            return None
    except Exception as e:
        log.log(f"Download error: {str(e)}")
        return None

def transcribe_audio(file_path: str) -> dict:
    """
    Transcribe the audio file using Fal.ai.
    
    The function uploads the file using fal_client.upload_file() and then
    calls fal_client.subscribe() with the following documented arguments:
      - audio_url: URL of the uploaded file
      - task: "transcribe"
      - language: "en"
      - chunk_level: "segment"
      - version: "3"
    
    The on_queue_update callback logs each message from the API.
    """
    try:
        if not os.path.exists(file_path):
            log.log(f"Error: Input file {file_path} does not exist")
            return None
        file_path = os.path.abspath(file_path)
        audio_url = fal_client.upload_file(file_path)
        log.log(f"Uploaded file URL: {audio_url}")
        
        # Define a callback that logs update messages from the API
        def on_queue_update(update):
            if hasattr(update, "logs") and update.logs:
                for item in update.logs:
                    log.log(item.get("message", "No message"))
            else:
                log.log("Queue update received.")
        
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
            on_queue_update=on_queue_update
        )
        return result
    except Exception as e:
        log.log(f"Transcription error: {str(e)}")
        return None

def transcribe_in_batches(file_path, max_size_mb=8):
    """Transcribe audio file in batches if larger than specified size"""
    try:
        batch_start_time = time.time()
        if not os.path.exists(file_path):
            print(f"Error: Input file {file_path} does not exist")
            return None

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        # For files smaller than or equal to 8 MB, process as a whole
        if file_size_mb <= max_size_mb:
            return transcribe_audio(file_path)

        import subprocess
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def get_audio_duration():
            escaped_path = file_path.replace('"', '\\"')
            cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{escaped_path}"'
            duration = subprocess.check_output(cmd, shell=True)
            return float(duration)

        total_duration = get_audio_duration()
        batch_duration = 8 * 60  # 8 minutes per batch
        full_transcription = {"text": "", "chunks": []}
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        
        total_batches = (int(total_duration) + int(batch_duration) - 1) // int(batch_duration)
        print(f"\nProcessing {total_batches} batches concurrently...")

        def process_batch(start):
            batch_process_start = time.time()
            batch_output = f"batch_{start}_{sanitize_filename(base_name)}.mp3"
            print(f"Processing batch starting at {start} sec")
            
            escaped_input = file_path.replace('"', '\\"')
            escaped_output = batch_output.replace('"', '\\"')
            cut_cmd = f'ffmpeg -i "{escaped_input}" -ss {start} -t {batch_duration} -acodec copy "{escaped_output}"'
            subprocess.call(cut_cmd, shell=True)
            
            result = None
            if os.path.exists(batch_output):
                try:
                    result = transcribe_audio(batch_output)
                    # Clean up batch file
                    os.remove(batch_output)
                    
                    batch_process_end = time.time()
                    print(f"Batch starting at {start} sec completed in {batch_process_end - batch_process_start:.2f} seconds")
                except Exception as e:
                    print(f"Error processing batch starting at {start} sec: {str(e)}")
            else:
                print(f"Error: Batch file {batch_output} was not created")
            
            return start, result

        # Process batches concurrently
        starts = list(range(0, int(total_duration), int(batch_duration)))
        results = []
        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(process_batch, start): start for start in starts}
            for future in as_completed(futures):
                start, batch_result = future.result()
                if batch_result:
                    results.append((start, batch_result))
        
        # Sort results by start time and compile full transcription
        results.sort(key=lambda x: x[0])
        for start, batch_result in results:
            if batch_result:
                full_transcription["text"] += batch_result["text"] + " "
                if "chunks" in batch_result:
                    for chunk in batch_result["chunks"]:
                        chunk['start'] += start
                        chunk['end'] += start
                        full_transcription["chunks"].append(chunk)
        
        total_batch_time = time.time() - batch_start_time
        print(f"\nTotal batch processing time: {total_batch_time:.2f} seconds")
        print(f"Average time per batch: {total_batch_time/total_batches:.2f} seconds")
        
        return full_transcription
    except Exception as e:
        print(f"Batch processing error: {str(e)}")
        return None
