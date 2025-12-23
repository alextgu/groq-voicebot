#!/usr/bin/env python3
"""
server.py - WebSocket Server for Zed Voice Agent

Implements an "Always-Listening" Smart Speaker Pattern with Wake Word Detection:
- ASLEEP: Ignores all audio until "Hey ZED" is detected
- AWAKE: Processes audio and responds until session ends or times out

WebSocket Protocol:
- Binary: Audio blob (WAV/WebM) → Transcription
- JSON: Text commands and responses

Session Management:
- "Hey ZED" → Wake up, start listening
- "Thank you ZED" or termination phrases → Go back to sleep
- [HANGUP] token from Brain → Session ended

Usage:
    python server.py
    # Server runs on ws://localhost:8000/ws
"""

import os
import io
import json
import wave
import asyncio
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from groq import Groq
from elevenlabs.client import ElevenLabs

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("zed.server")

# Reduce noise
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Groq client for transcription
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ElevenLabs client for TTS
eleven_api_key = os.environ.get("ELEVEN_API_KEY")
eleven_client = ElevenLabs(api_key=eleven_api_key) if eleven_api_key else None
ELEVEN_VOICE_ID = os.environ.get("ELEVEN_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel
ELEVEN_MODEL_ID = "eleven_turbo_v2_5"  # Fastest model

# Server config
HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
PORT = int(os.environ.get("SERVER_PORT", "8000"))
SKIP_RAG = os.environ.get("SKIP_RAG", "false").lower() == "true"  # For fast testing

# Wake Word Configuration
WAKE_PHRASE = "hey zed"
WAKE_GREETING = "I am ready."

# ============================================================
# BRAIN SINGLETON
# ============================================================

# Pre-load Brain at startup to avoid cold start latency
_brain = None
_brain_loaded = False


def get_cached_brain():
    """Get or initialize the Brain singleton (lazy but cached)."""
    global _brain, _brain_loaded
    if not _brain_loaded:
        try:
            from app.services.brain import get_brain
            logger.info("🧠 Pre-loading Brain and Knowledge Base...")
            _brain = get_brain()
            _brain_loaded = True
            logger.info("✅ Brain ready!")
        except Exception as e:
            logger.error(f"Failed to load Brain: {e}")
            _brain = None
            _brain_loaded = True
    return _brain


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Zed Voice Server",
    description="WebSocket server for Zed voice agent with Wake Word detection",
    version="2.0.0"
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Pre-load Brain and Knowledge Base on server startup."""
    logger.info("🚀 Starting Zed server...")
    # Pre-load in background to not block startup
    import threading
    threading.Thread(target=get_cached_brain, daemon=True).start()


# ============================================================
# AUDIO TRANSCRIPTION
# ============================================================

async def transcribe_audio(audio_bytes: bytes, format_hint: str = "webm") -> Optional[str]:
    """
    Transcribe audio bytes using Groq Whisper.
    
    Args:
        audio_bytes: Raw audio data (WAV or WebM)
        format_hint: Audio format hint ("wav" or "webm")
    
    Returns:
        Transcribed text or None on error
    """
    if not audio_bytes or len(audio_bytes) < 1000:
        logger.warning("Audio too short, skipping transcription")
        return None
    
    try:
        # Create a temporary file with the appropriate extension
        suffix = f".{format_hint}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        
        logger.info(f"Transcribing {len(audio_bytes)} bytes of {format_hint} audio...")
        
        # Open and transcribe
        with open(tmp_path, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3-turbo",
                response_format="json",
                language="en",
                temperature=0.0
            )
        
        # Cleanup temp file
        os.unlink(tmp_path)
        
        text = transcription.text.strip()
        logger.info(f"Transcribed: '{text[:50]}...' ({len(text)} chars)")
        return text
    
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return None


# ============================================================
# WAKE WORD DETECTION
# ============================================================

def contains_wake_phrase(text: str) -> bool:
    """
    Check if text contains the wake phrase "Hey ZED".
    
    Args:
        text: Transcribed text
    
    Returns:
        True if wake phrase detected
    """
    if not text:
        return False
    text_lower = text.lower().strip()
    # Check for various spellings/variations
    wake_variations = [
        "hey zed", "hey, zed", "hey zedd", "hey zad",
        "hey zet", "hey said", "hey set", "heyzed",
        "hey z", "hey z.", "a zed", "hey fed"  # Common misrecognitions
    ]
    for variation in wake_variations:
        if variation in text_lower:
            return True
    return False


# ============================================================
# BRAIN INTEGRATION
# ============================================================

def get_brain_response(text: str, conversation_id: str = "default"):
    """
    Get response from Brain (streaming generator).
    
    Args:
        text: User's transcribed text
        conversation_id: Session ID for conversation memory
    
    Yields:
        Response tokens
    """
    # Fast mode: Skip Brain entirely for testing latency
    if SKIP_RAG:
        logger.info("⚡ SKIP_RAG mode: Direct LLM response")
        try:
            stream = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",  # Fastest model
                messages=[
                    {"role": "system", "content": "You are ZED, a helpful study assistant. Be brief."},
                    {"role": "user", "content": text}
                ],
                stream=True,
                max_tokens=200
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            return
        except Exception as e:
            yield f"[Error: {e}]"
            return
    
    try:
        brain = get_cached_brain()
        
        if brain is None:
            yield "Brain not available. Check server logs."
            return
        
        # For now, single-turn (no memory across WebSocket reconnects)
        # In production, you'd store ConversationContext per session
        for token in brain.process(text):
            yield token
    
    except Exception as e:
        logger.error(f"Brain error: {e}")
        yield f"[Error: {str(e)}]"


# ============================================================
# TEXT-TO-SPEECH
# ============================================================

async def generate_tts_audio(text: str) -> bytes:
    """
    Generate TTS audio using ElevenLabs.
    
    Args:
        text: Text to convert to speech
    
    Returns:
        Audio bytes (MP3 format)
    """
    if not eleven_client:
        logger.warning("ElevenLabs not configured, skipping TTS")
        return b""
    
    if not text or len(text.strip()) < 2:
        return b""
    
    # Don't TTS the [HANGUP] token or error messages
    if "[HANGUP]" in text or text.startswith("[Error"):
        return b""
    
    try:
        logger.info(f"🔊 Generating TTS for: '{text[:50]}...'")
        
        # Generate audio (returns generator of bytes)
        audio_generator = eleven_client.text_to_speech.convert(
            text=text,
            voice_id=ELEVEN_VOICE_ID,
            model_id=ELEVEN_MODEL_ID,
            output_format="mp3_44100_128",  # Good quality MP3
        )
        
        # Collect all chunks
        audio_bytes = b"".join(audio_generator)
        logger.info(f"✅ TTS generated: {len(audio_bytes)} bytes")
        
        return audio_bytes
    
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return b""


# ============================================================
# WEBSOCKET HANDLER WITH WAKE WORD SESSION MANAGEMENT
# ============================================================

# Store active connections and their state
active_connections: dict[str, dict] = {}

# HANGUP token from Brain
HANGUP_TOKEN = "[HANGUP]"


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket endpoint for voice communication.
    
    Implements ASLEEP/AWAKE State Machine:
    - ASLEEP: Ignores all audio until "Hey ZED" is detected
    - AWAKE: Processes audio and responds until session ends
    
    Protocol:
    - Client sends binary (audio blob) → Server transcribes
    - Server checks wake word state before processing
    - Server sends JSON {type: "status", mode: "asleep"|"awake", text: "..."}
    - Server sends JSON {type: "response", text: "...", done: bool}
    """
    await websocket.accept()
    
    # Generate session ID
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    # ═══════════════════════════════════════════════════════════
    # TASK 1: Initialize State - Start ASLEEP
    # ═══════════════════════════════════════════════════════════
    is_awake = False
    
    active_connections[session_id] = {
        "websocket": websocket,
        "is_awake": is_awake,
        "connected_at": datetime.now()
    }
    
    logger.info(f"🔌 Client connected: {session_id} | State: ASLEEP")
    
    # Send initial status
    await websocket.send_json({
        "type": "status",
        "mode": "asleep",
        "text": "🔴 Waiting for 'Hey ZED'..."
    })
    
    try:
        while True:
            # Receive message (can be binary or text)
            message = await websocket.receive()
            text = None  # Will hold transcribed or direct text
            
            # ─────────────────────────────────────────────────
            # BINARY: Audio blob from browser
            # ─────────────────────────────────────────────────
            if "bytes" in message:
                audio_bytes = message["bytes"]
                logger.info(f"📥 Received audio: {len(audio_bytes)} bytes | Awake: {is_awake}")
                
                # Detect format from magic bytes
                format_hint = "webm"
                if audio_bytes[:4] == b'RIFF':
                    format_hint = "wav"
                elif audio_bytes[:4] == b'\x1aE\xdf\xa3':
                    format_hint = "webm"
                
                # Transcribe
                text = await transcribe_audio(audio_bytes, format_hint)
                
                if not text:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Could not transcribe audio"
                    })
                    continue
                
                # Send transcription back for UI feedback
                await websocket.send_json({
                    "type": "transcription",
                    "text": text
                })
            
            # ─────────────────────────────────────────────────
            # TEXT: JSON command from browser
            # ─────────────────────────────────────────────────
            elif "text" in message:
                try:
                    data = json.loads(message["text"])
                    msg_type = data.get("type", "text")
                    
                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong"})
                        continue
                    
                    if msg_type == "config":
                        logger.info(f"⚙️ Client config: {data}")
                        await websocket.send_json({
                            "type": "config_ack",
                            "status": "ok",
                            "is_awake": is_awake
                        })
                        continue
                    
                    if msg_type == "text":
                        text = data.get("text", "").strip()
                        if text:
                            # Send back as transcription for UI consistency
                            await websocket.send_json({
                                "type": "transcription",
                                "text": text
                            })
                
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON received")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid JSON"
                    })
                    continue
            
            # ═══════════════════════════════════════════════════════════
            # TASK 2: GATEKEEPER LOGIC - ASLEEP vs AWAKE
            # ═══════════════════════════════════════════════════════════
            
            if not text:
                continue  # No text to process
            
            # ─────────────────────────────────────────────────
            # A. IF ASLEEP: Check for wake word
            # ─────────────────────────────────────────────────
            if not is_awake:
                if not contains_wake_phrase(text):
                    # Ignore - still asleep
                    logger.info(f"💤 Ignored (Asleep): '{text[:50]}...'")
                    await websocket.send_json({
                        "type": "status",
                        "mode": "asleep",
                        "text": f"💤 Ignored (Asleep): {text[:30]}..."
                    })
                    continue  # ← Do NOT call Brain, go to next iteration
                
                # ═══════════════════════════════════════════════
                # WAKE WORD DETECTED! Transition to AWAKE
                # ═══════════════════════════════════════════════
                is_awake = True
                active_connections[session_id]["is_awake"] = True
                
                logger.info(f"🌅 Wake Word Detected! Session {session_id} is now AWAKE")
                
                # Notify frontend of state change
                await websocket.send_json({
                    "type": "status",
                    "mode": "awake",
                    "text": "🟢 Listening..."
                })
                
                # Send audio cue command (frontend can play a beep)
                await websocket.send_json({
                    "type": "audio_cue",
                    "name": "wake_beep"
                })
                
                # Generate and send greeting TTS
                greeting_audio = await generate_tts_audio(WAKE_GREETING)
                
                await websocket.send_json({
                    "type": "response",
                    "text": WAKE_GREETING,
                    "done": True,
                    "full_text": WAKE_GREETING,
                    "has_audio": len(greeting_audio) > 0
                })
                
                if greeting_audio:
                    await websocket.send_bytes(greeting_audio)
                
                # Done processing wake word - wait for next input
                continue
            
            # ─────────────────────────────────────────────────
            # B. IF AWAKE: Process with Brain
            # ─────────────────────────────────────────────────
            logger.info(f"🧠 Processing (Awake): '{text[:50]}...'")
            
            # Get Brain response (streaming)
            full_response = ""
            hangup_detected = False
            
            for token in get_brain_response(text, session_id):
                # ═══════════════════════════════════════════════
                # Monitor for [HANGUP] token
                # ═══════════════════════════════════════════════
                if HANGUP_TOKEN in token:
                    hangup_detected = True
                    # Extract any text before the hangup token
                    clean_token = token.replace(HANGUP_TOKEN, "")
                    if clean_token:
                        full_response += clean_token
                        await websocket.send_json({
                            "type": "response",
                            "text": clean_token,
                            "done": False
                        })
                    break  # Stop streaming
                
                full_response += token
                await websocket.send_json({
                    "type": "response",
                    "text": token,
                    "done": False
                })
            
            # ═══════════════════════════════════════════════
            # Handle session termination (HANGUP detected)
            # ═══════════════════════════════════════════════
            if hangup_detected:
                is_awake = False
                active_connections[session_id]["is_awake"] = False
                
                logger.info(f"🌙 Session Ended by User: {session_id} → ASLEEP")
                
                # Generate TTS for the farewell message (before hangup)
                if full_response:
                    tts_audio = await generate_tts_audio(full_response)
                else:
                    tts_audio = b""
                
                # Signal completion
                await websocket.send_json({
                    "type": "response",
                    "text": "",
                    "done": True,
                    "full_text": full_response,
                    "has_audio": len(tts_audio) > 0
                })
                
                if tts_audio:
                    await websocket.send_bytes(tts_audio)
                
                # Notify frontend of state change to ASLEEP
                await websocket.send_json({
                    "type": "status",
                    "mode": "asleep",
                    "text": "🔴 Asleep - Say 'Hey ZED' to wake me up"
                })
                
                continue  # Keep connection open, but now asleep
            
            # Normal response (no hangup) - generate TTS
            tts_audio = await generate_tts_audio(full_response)
            
            # Signal completion with audio
            await websocket.send_json({
                "type": "response",
                "text": "",
                "done": True,
                "full_text": full_response,
                "has_audio": len(tts_audio) > 0
            })
            
            # Send audio as binary if available
            if tts_audio:
                await websocket.send_bytes(tts_audio)
    
    except WebSocketDisconnect:
        logger.info(f"🔌 Client disconnected: {session_id}")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
    finally:
        active_connections.pop(session_id, None)


# ============================================================
# REST ENDPOINTS
# ============================================================

@app.get("/")
async def root():
    """Health check endpoint."""
    awake_count = sum(1 for c in active_connections.values() if c.get("is_awake", False))
    return {
        "service": "Zed Voice Server",
        "status": "running",
        "websocket": "/ws",
        "connections": {
            "total": len(active_connections),
            "awake": awake_count,
            "asleep": len(active_connections) - awake_count
        }
    }


@app.get("/health")
async def health():
    """Detailed health check."""
    return {
        "status": "healthy",
        "groq_configured": bool(os.environ.get("GROQ_API_KEY")),
        "elevenlabs_configured": bool(eleven_api_key),
        "brain_loaded": _brain_loaded,
        "active_connections": len(active_connections)
    }


@app.post("/transcribe")
async def transcribe_endpoint(audio: bytes):
    """
    REST endpoint for transcription (alternative to WebSocket).
    """
    text = await transcribe_audio(audio)
    if text:
        return {"text": text}
    raise HTTPException(status_code=400, detail="Transcription failed")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn
    
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║     ███████╗███████╗██████╗    Server v2.0                ║
║     ╚══███╔╝██╔════╝██╔══██╗                              ║
║       ███╔╝ █████╗  ██║  ██║   WebSocket: ws://{HOST}:{PORT}/ws
║      ███╔╝  ██╔══╝  ██║  ██║   REST:      http://{HOST}:{PORT}
║     ███████╗███████╗██████╔╝                              ║
║     ╚══════╝╚══════╝╚═════╝                               ║
║                                                           ║
║  Wake Word: "Hey ZED"                                     ║
║  End Session: "Thank you ZED" or "I'm done"               ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "server:app",
        host=HOST,
        port=PORT,
        reload=True,
        log_level="info"
    )
