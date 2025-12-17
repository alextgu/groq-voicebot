from fastapi import FastAPI, HTTPException
from ears import Ear
from groq import Groq
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Ear → Groq LLM Service")

# Singleton instances for efficiency
ear = Ear()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def call_llm(text: str) -> str:
    """
    Optional: send the transcribed text to a Groq LLM model.
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": text}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        # Bubble up LLM errors
        raise RuntimeError(f"Groq LLM error: {e}")

@app.post("/listen")
def listen_and_respond():
    """
    1️⃣ Record audio from mic (Ear listens)
    2️⃣ Transcribe via Groq Whisper (inside Ear)
    3️⃣ Send text to Groq LLM (optional)
    4️⃣ Return JSON with both transcript and LLM response
    """

    # 1. Record & transcribe audio
    text = ear.listen()
    if not text:
        raise HTTPException(status_code=400, detail="No speech detected")

    # 2. Optional: LLM processing
    try:
        response = call_llm(text)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 3. Return JSON
    return {
        "transcript": text,
        "response": response
    }
