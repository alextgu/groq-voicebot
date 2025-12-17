import os
import time
import wave
import io
import math
import struct
import pyaudio
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

# ----------------------
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 2.0  # Float is fine here

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

class Ear:
    def __init__(self):
        self.p = pyaudio.PyAudio()

    def _is_silent(self, data_chunk):
        """Returns True if the chunk is quieter than the threshold."""
        # FIX 1: Ensure count is an integer
        count = int(len(data_chunk) / 2)
        format = "%dh" % (count)
        
        try:
            shorts = struct.unpack(format, data_chunk)
        except struct.error:
            # Fallback if chunk size is weird (rare, but safety first)
            return True

        sum_squares = 0.0
        for sample in shorts:
            n = sample * (1.0 / 32768.0)
            sum_squares += n * n
        
        # Avoid division by zero
        if count == 0:
            return True
            
        rms = math.sqrt(sum_squares / count) * 32768.0
        return rms < SILENCE_THRESHOLD

    def listen(self):
        """Records until silence is detected, then returns the transcription."""
        print("Listening... (Speak now)")
        
        try:
            stream = self.p.open(format=FORMAT,
                                channels=CHANNELS,
                                rate=RATE,
                                input=True,
                                frames_per_buffer=CHUNK)
        except IOError as e:
            print(f"Microphone error: {e}")
            return None

        frames = []
        silent_chunks = 0
        chunks_per_second = RATE / CHUNK
        
        while True:
            try:
                # Handle potential overflow if computer is slow
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)
            except IOError:
                continue

            if self._is_silent(data):
                silent_chunks += 1
            else:
                silent_chunks = 0

            if silent_chunks > (chunks_per_second * SILENCE_DURATION):
                print("Silence detected. Transcribing...")
                break

        stream.stop_stream()
        stream.close()
        
        # Optimization: Don't transcribe if recording is just silence (too short)
        # 1.5s of silence is the stop trigger, so we check total length
        total_duration = len(frames) * CHUNK / RATE
        if total_duration < (SILENCE_DURATION + 0.5): 
             print("Too short/silent, skipping.")
             return None

        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(self.p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))
        
        buffer.name = "audio.wav"
        buffer.seek(0)

        start_time = time.time()
        
        try:
            transcription = client.audio.transcriptions.create(
                file=buffer,
                model="whisper-large-v3-turbo",
                response_format="json",
                language="en",
                temperature=0.0
            )
            text = transcription.text
            
            end_time = time.time()
            print(f"👂 Heard: '{text}' (took {end_time - start_time:.2f}s)")
            return text
            
        except Exception as e:
            print(f"Error calling Groq: {e}")
            return None

    # Clean up PyAudio when the class dies
    def __del__(self):
        try:
            self.p.terminate()
        except:
            pass

if __name__ == "__main__":
    ear = Ear()
    # Loop to test continuous listening
    while True:
        try:
            text = ear.listen()
        except KeyboardInterrupt:
            break