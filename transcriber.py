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
