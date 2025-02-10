# app.py
import streamlit as st
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod
import time
import fal_client
import yt_dlp
from pathlib import Path
import json

# Data Models
@dataclass
class TranscriptionResult:
    text: str
    chunks: list
    processing_time: float
    download_time: float

@dataclass
class AudioFile:
    path: str
    title: str
    url: Optional[str] = None

# Abstract base classes for SOLID principles
class AudioDownloader(ABC):
    @abstractmethod
    def download(self, url: str) -> Optional[AudioFile]:
        pass

class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, audio_file: AudioFile) -> Optional[TranscriptionResult]:
        pass

class TranscriptionSaver(ABC):
    @abstractmethod
    def save(self, result: TranscriptionResult, audio_file: AudioFile) -> None:
        pass

# Concrete implementations
class YTDLPDownloader(AudioDownloader):
    def __init__(self, output_dir: str = "downloads"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
    def download(self, url: str) -> Optional[AudioFile]:
        try:
            # Get video info first
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                title = info_dict.get('title', 'video')
                
            safe_title = self._sanitize_filename(title)
            output_path = self.output_dir / f"{safe_title}.mp3"

            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': str(output_path.with_suffix('')),
                'restrict_filenames': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
            if output_path.exists():
                return AudioFile(str(output_path), title, url)
            return None

        except Exception as e:
            st.error(f"Download error: {str(e)}")
            return None

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        # Implementation from original sanitize_filename function
        import unicodedata
        import re
        
        filename = re.sub(r'\/podcast\/', '', filename)
        filename = re.sub(r'id\d+', '', filename)
        filename = filename.split('?')[0]
        filename = filename.split('/')[-1]
        
        filename = unicodedata.normalize('NFKD', filename)
        filename = filename.encode('ASCII', 'ignore').decode('ASCII')
        filename = re.sub(r'[^\w\s-]', '', filename)
        filename = re.sub(r'\s+', '_', filename.strip())
        return filename

class FalTranscriber(Transcriber):
    def __init__(self, api_key: str):
        os.environ['FAL_KEY'] = api_key
        
    def transcribe(self, audio_file: AudioFile) -> Optional[TranscriptionResult]:
        try:
            start_time = time.time()
            file_path = Path(audio_file.path)
            
            if not file_path.exists():
                st.error(f"Error: Input file {file_path} does not exist")
                return None

            audio_url = fal_client.upload_file(str(file_path))
            st.info(f"File uploaded successfully")

            with st.spinner("Transcribing audio..."):
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
                    on_queue_update=self._on_queue_update,
                )
            
            end_time = time.time()
            
            if result and 'text' in result:
                return TranscriptionResult(
                    text=result['text'],
                    chunks=result.get('chunks', []),
                    processing_time=end_time - start_time,
                    download_time=0  # Set by the orchestrator
                )
            return None

        except Exception as e:
            st.error(f"Transcription error: {str(e)}")
            return None

    def _on_queue_update(self, update):
        if isinstance(update, fal_client.InProgress):
            for log in update.logs:
                try:
                    st.text(log["message"])
                except Exception as e:
                    st.error(f"Log error: {str(e)}")

class FileSystemTranscriptionSaver(TranscriptionSaver):
    def __init__(self, output_dir: str = "transcripts"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def save(self, result: TranscriptionResult, audio_file: AudioFile) -> None:
        try:
            base_name = Path(audio_file.path).stem
            
            # Save text version
            text_path = self.output_dir / f"{base_name}.txt"
            with open(text_path, 'w', encoding='utf-8') as f:
                f.write(result.text)
            st.success(f"Transcript saved to {text_path}")

            # Save full result including chunks
            json_path = self.output_dir / f"{base_name}_full.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'text': result.text,
                    'chunks': result.chunks,
                    'processing_time': result.processing_time,
                    'download_time': result.download_time,
                    'title': audio_file.title,
                    'url': audio_file.url
                }, f, ensure_ascii=False, indent=2)
            st.success(f"Full transcript data saved to {json_path}")

        except Exception as e:
            st.error(f"Error saving transcript: {str(e)}")

# Orchestrator class to coordinate the components
class TranscriptionOrchestrator:
    def __init__(
        self,
        downloader: AudioDownloader,
        transcriber: Transcriber,
        saver: TranscriptionSaver
    ):
        self.downloader = downloader
        self.transcriber = transcriber
        self.saver = saver

    def process_url(self, url: str) -> Optional[TranscriptionResult]:
        # Download
        download_start = time.time()
        audio_file = self.downloader.download(url)
        download_time = time.time() - download_start
        
        if not audio_file:
            return None
            
        # Transcribe
        result = self.transcriber.transcribe(audio_file)
        if not result:
            return None
            
        # Update download time
        result.download_time = download_time
        
        # Save
        self.saver.save(result, audio_file)
        
        return result

# Streamlit UI
def main():
    st.title("Audio Transcription App")
    st.write("Enter a URL to download and transcribe audio content")
    
    # API Key input
    api_key = st.text_input("Enter your FAL API key:", type="password")
    
    # URL input
    url = st.text_input("Enter URL:")
    
    if st.button("Transcribe") and url and api_key:
        try:
            # Initialize components
            downloader = YTDLPDownloader()
            transcriber = FalTranscriber(api_key)
            saver = FileSystemTranscriptionSaver()
            
            # Create orchestrator
            orchestrator = TranscriptionOrchestrator(downloader, transcriber, saver)
            
            # Process the URL
            with st.spinner("Processing..."):
                result = orchestrator.process_url(url)
                
            if result:
                st.success("Transcription completed!")
                st.write("### Transcript:")
                st.text_area("Full transcript:", result.text, height=300)
                
                st.write("### Processing Times:")
                st.write(f"Download time: {result.download_time:.2f} seconds")
                st.write(f"Transcription time: {result.processing_time:.2f} seconds")
                st.write(f"Total time: {result.download_time + result.processing_time:.2f} seconds")
                
        except Exception as e:
            st.error(f"Error: {str(e)}")

if __name__ == "__main__":
    main()
