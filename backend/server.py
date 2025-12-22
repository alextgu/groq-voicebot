#!/usr/bin/env python3
"""
server.py - WebSocket Server for Zed Voice Agent

Supports two input modes:
1. Push-to-Talk (Button) - User clicks, speaks, releases
2. Voice Activation (Hands-Free) - Browser detects speech automatically

WebSocket Protocol:
- Binary: Audio blob (WAV/WebM) → Transcription
- JSON: Text commands and responses

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

# Server config
HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
PORT = int(os.environ.get("SERVER_PORT", "8000"))


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Zed Voice Server",
    description="WebSocket server for Zed voice agent",
    version="1.0.0"
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    try:
        from app.services.brain import get_brain, ConversationContext, HANGUP_TOKEN
        
        brain = get_brain()
        
        # For now, single-turn (no memory across WebSocket reconnects)
        # In production, you'd store ConversationContext per session
        for token in brain.process(text):
            yield token
    
    except ImportError:
        logger.warning("Brain module not available, using echo mode")
        yield f"Echo: {text}"
    except Exception as e:
        logger.error(f"Brain error: {e}")
        yield f"[Error: {str(e)}]"


# ============================================================
# WEBSOCKET HANDLER
# ============================================================

# Store active connections
active_connections: dict[str, WebSocket] = {}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket endpoint for voice communication.
    
    Protocol:
    - Client sends binary (audio blob) → Server responds with JSON {type: "transcription", text: "..."}
    - Client sends JSON {type: "text", text: "..."} → Server responds with streamed tokens
    - Server sends JSON {type: "response", text: "...", done: bool}
    - Server sends JSON {type: "error", message: "..."}
    """
    await websocket.accept()
    
    # Generate session ID
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    active_connections[session_id] = websocket
    logger.info(f"Client connected: {session_id}")
    
    try:
        while True:
            # Receive message (can be binary or text)
            message = await websocket.receive()
            
            # ─────────────────────────────────────────────────
            # BINARY: Audio blob from browser
            # ─────────────────────────────────────────────────
            if "bytes" in message:
                audio_bytes = message["bytes"]
                logger.info(f"Received audio: {len(audio_bytes)} bytes")
                
                # Detect format from magic bytes
                format_hint = "webm"
                if audio_bytes[:4] == b'RIFF':
                    format_hint = "wav"
                elif audio_bytes[:4] == b'\x1aE\xdf\xa3':
                    format_hint = "webm"
                
                # Transcribe
                text = await transcribe_audio(audio_bytes, format_hint)
                
                if text:
                    # Send transcription back
                    await websocket.send_json({
                        "type": "transcription",
                        "text": text
                    })
                    
                    # Get Brain response (streaming)
                    full_response = ""
                    for token in get_brain_response(text, session_id):
                        full_response += token
                        await websocket.send_json({
                            "type": "response",
                            "text": token,
                            "done": False
                        })
                    
                    # Signal completion
                    await websocket.send_json({
                        "type": "response",
                        "text": "",
                        "done": True,
                        "full_text": full_response
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Could not transcribe audio"
                    })
            
            # ─────────────────────────────────────────────────
            # TEXT: JSON command from browser
            # ─────────────────────────────────────────────────
            elif "text" in message:
                try:
                    data = json.loads(message["text"])
                    msg_type = data.get("type", "text")
                    
                    if msg_type == "text":
                        # Direct text input
                        text = data.get("text", "").strip()
                        if text:
                            # Get Brain response
                            full_response = ""
                            for token in get_brain_response(text, session_id):
                                full_response += token
                                await websocket.send_json({
                                    "type": "response",
                                    "text": token,
                                    "done": False
                                })
                            
                            await websocket.send_json({
                                "type": "response",
                                "text": "",
                                "done": True,
                                "full_text": full_response
                            })
                    
                    elif msg_type == "ping":
                        # Health check
                        await websocket.send_json({"type": "pong"})
                    
                    elif msg_type == "config":
                        # Client configuration (e.g., sample rate)
                        logger.info(f"Client config: {data}")
                        await websocket.send_json({
                            "type": "config_ack",
                            "status": "ok"
                        })
                
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid JSON"
                    })
    
    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        active_connections.pop(session_id, None)


# ============================================================
# REST ENDPOINTS
# ============================================================

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "Zed Voice Server",
        "status": "running",
        "websocket": "/ws",
        "connections": len(active_connections)
    }


@app.get("/health")
async def health():
    """Detailed health check."""
    return {
        "status": "healthy",
        "groq_configured": bool(os.environ.get("GROQ_API_KEY")),
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
║     ███████╗███████╗██████╗    Server                     ║
║     ╚══███╔╝██╔════╝██╔══██╗                              ║
║       ███╔╝ █████╗  ██║  ██║   WebSocket: ws://{HOST}:{PORT}/ws
║      ███╔╝  ██╔══╝  ██║  ██║   REST:      http://{HOST}:{PORT}
║     ███████╗███████╗██████╔╝                              ║
║     ╚══════╝╚══════╝╚═════╝                               ║
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

