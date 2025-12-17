import os
from elevenlabs import stream as play_stream
from elevenlabs.client import ElevenLabs

class Mouth:
    def __init__(self):
        # 1. Initialize Client
        api_key = os.environ.get("ELEVEN_API_KEY")
        if not api_key:
            print("⚠️ ELEVEN_API_KEY not found in .env")
        
        self.client = ElevenLabs(api_key=api_key)

        # 2. Configuration
        # You can grab other IDs from https://api.elevenlabs.io/v1/voices
        self.voice_id = "21m00Tcm4TlvDq8ikWAM" 
        
        self.model_id = "eleven_turbo_v2_5"

    def speak(self, text: str):
        """
        Generates audio and plays it instantly (streaming).
        This function blocks until the audio finishes playing.
        """
        if not text or len(text.strip()) == 0:
            return

        print(f"👄 Mouth speaking: '{text[:30]}...'")
        
        try:
            # 1. Generate the Stream using the new SDK API
            audio_stream = self.client.text_to_speech.stream(
                text=text,
                voice_id=self.voice_id,
                model_id=self.model_id,
            )
            
            # 2. Play the Stream
            play_stream(audio_stream)
            
        except Exception as e:
            print(f"❌ Mouth Error: {e}")

if __name__ == "__main__":
    # Quick Test
    from dotenv import load_dotenv
    load_dotenv()
    
    mouth = Mouth()
    mouth.speak("System initialized. I am ready to speak.")