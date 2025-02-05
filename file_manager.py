# file_manager.py
import json
from utils import get_episode_name

def save_transcript(result: dict, url: str, title: str, metadata: dict) -> None:
    """
    Save the transcription result in both TXT and JSON formats.
    The TXT file includes human-readable metadata.
    """
    if result and 'text' in result:
        episode_name = get_episode_name(url, title)
        transcript_filename = f"{episode_name}.txt"
        json_filename = f"{episode_name}_full.json"
        
        # Insert transcript into metadata.
        if metadata:
            metadata['Transcript'] = result['text']
            full_result = {**metadata, 'chunks': result.get('chunks', []), 'raw_response': result}
        else:
            full_result = result

        with open(transcript_filename, 'w', encoding='utf-8') as f:
            # Save a human-readable version.
            if metadata:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            else:
                f.write(result['text'])
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(full_result, f, ensure_ascii=False, indent=2)
