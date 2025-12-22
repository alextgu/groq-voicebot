import os
import threading
import pyaudio
from elevenlabs.client import ElevenLabs

class Mouth:
    def __init__(self):
        # 1. Initialize Client
        api_key = os.environ.get("ELEVEN_API_KEY")
        if not api_key:
            print("⚠️ Mouth Warning: ELEVEN_API_KEY not found in .env")
        
        self.client = ElevenLabs(api_key=api_key)

        # 2. Configuration
        # "Turbo" models have the lowest latency (critical for Groq demo)
        self.model_id = "eleven_turbo_v2_5"
        self.voice_id = "21m00Tcm4TlvDq8ikWAM"
        
        # 3. Interruption state
        self._interrupt_event = threading.Event()
        self._is_speaking = False
        self._audio = None

    def speak(self, text: str, interrupt_event: threading.Event = None):
        """
        Generates audio and plays it with interruption support.
        
        Args:
            text: The response to speak.
            interrupt_event: Optional external threading event to signal interruption.
        """
        if not text or len(text.strip()) == 0:
            return

        # Use external event if provided, otherwise use internal
        stop_event = interrupt_event or self._interrupt_event
        stop_event.clear()
        self._is_speaking = True

        print(f"👄 Mouth speaking: '{text[:50]}...'")
        
        try:
            # 1. Generate the audio stream from ElevenLabs (use stream method)
            audio_stream = self.client.text_to_speech.stream(
                text=text,
                voice_id=self.voice_id,
                model_id=self.model_id,
                output_format="pcm_22050",  # Raw PCM for PyAudio
            )
            
            # 2. Initialize PyAudio for playback
            self._audio = pyaudio.PyAudio()
            stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=22050,
                output=True
            )
            
            # 3. Play chunks with interruption check
            try:
                for chunk in audio_stream:
                    # Check for interruption before playing each chunk
                    if stop_event.is_set():
                        print("🛑 Mouth: Interrupted mid-speech!")
                        break
                    stream.write(chunk)
            finally:
                stream.stop_stream()
                stream.close()
                self._audio.terminate()
                self._audio = None
            
        except Exception as e:
            print(f"❌ Mouth Error: {e}")
        finally:
            self._is_speaking = False

    def stop(self):
        """
        Immediately stops audio playback.
        """
        print("🛑 Mouth: Stop signal received.")
        self._interrupt_event.set()
    
    @property
    def is_speaking(self) -> bool:
        """Check if currently speaking."""
        return self._is_speaking

if __name__ == "__main__":
    # Quick Test with interruption demo
    import time
    from dotenv import load_dotenv
    load_dotenv()
    
    mouth = Mouth()
    
    # Test 1: Normal speech
    print("\n=== Test 1: Normal Speech ===")
    mouth.speak("Hello! This is a short test.")
    
    # Test 2: Interrupted speech
    print("\n=== Test 2: Interrupted Speech (stops after 2 seconds) ===")
    
    def delayed_stop():
        time.sleep(2)
        mouth.stop()
    
    # Start the stopper in background
    stopper = threading.Thread(target=delayed_stop)
    stopper.start()
    
    # This long text will be interrupted
    mouth.speak("This is a much longer sentence that will be interrupted after two seconds. "
                "I am going to keep talking and talking until someone tells me to stop. "
                "The interruption logic should kick in any moment now.")
    
    stopper.join()
    print("\n✅ Interruption test complete!")