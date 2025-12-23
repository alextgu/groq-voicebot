# ZED — Socratic AI Study Coach

> *"The AI that teaches you to think."*

ZED is a voice-first AI study assistant that uses the **Socratic method** to build critical thinking skills. Instead of giving answers, ZED asks guiding questions, challenges your understanding, and pushes you to master concepts through active reasoning.

---

## 🏗️ Architecture: xRx (Input → Reasoning → Output)

ZED follows the **xRx Architecture** pattern, a clean separation of concerns for voice AI agents:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           ZED ARCHITECTURE                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌─────────────┐    ┌─────────────────────┐    ┌─────────────┐         │
│   │             │    │                     │    │             │         │
│   │    INPUT    │───▶│     REASONING       │───▶│   OUTPUT    │         │
│   │   (Ears)    │    │     (Brain)         │    │   (Mouth)   │         │
│   │             │    │                     │    │             │         │
│   └─────────────┘    └─────────────────────┘    └─────────────┘         │
│         │                     │                        │                │
│         ▼                     ▼                        ▼                │
│   ┌───────────┐        ┌───────────┐            ┌───────────┐          │
│   │  Whisper  │        │   Llama   │            │ ElevenLabs│          │
│   │   (STT)   │        │   (LLM)   │            │   (TTS)   │          │
│   │   Groq    │        │   Groq    │            │           │          │
│   └───────────┘        └───────────┘            └───────────┘          │
│                              │                                          │
│                              ▼                                          │
│                     ┌─────────────────┐                                 │
│                     │    MEMORY       │                                 │
│                     │  (Knowledge)    │                                 │
│                     │                 │                                 │
│                     │  ┌───────────┐  │                                 │
│                     │  │ ChromaDB  │  │                                 │
│                     │  │  (RAG)    │  │                                 │
│                     │  └───────────┘  │                                 │
│                     │                 │                                 │
│                     │  ┌───────────┐  │                                 │
│                     │  │  Canvas   │  │                                 │
│                     │  │  (ETL)    │  │                                 │
│                     │  └───────────┘  │                                 │
│                     └─────────────────┘                                 │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### xRx Components

| Layer | File | Responsibility |
|-------|------|----------------|
| **INPUT** | `ears.py` | Captures audio, transcribes speech → text (Groq Whisper) |
| **REASONING** | `brain.py` | Socratic State Machine, RAG retrieval, LLM streaming (Groq Llama) |
| **OUTPUT** | `mouth.py` | Converts text → speech, plays audio (ElevenLabs) |
| **MEMORY** | `knowledge.py` | Vector embeddings, ChromaDB, semantic search |
| **ETL** | `canvas_sync.py` | Downloads PDFs from Canvas LMS, organizes by course |

---

## 🧠 Socratic State Machine

ZED implements a **3-State Socratic Tutor** that adapts to the user's understanding:

```
┌─────────────────────────────────────────────────────────────────┐
│                    SOCRATIC STATE MACHINE                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────────┐                                           │
│   │                 │                                           │
│   │   STATE 1: GYM  │◀─────────────────────────────────┐        │
│   │   (Learning)    │                                  │        │
│   │                 │                                  │        │
│   └────────┬────────┘                                  │        │
│            │                                           │        │
│            │ User gets it right                        │        │
│            ▼                                           │        │
│   ┌─────────────────┐                                  │        │
│   │                 │                                  │        │
│   │ STATE 2: COOL-  │                                  │        │
│   │ DOWN (Validate) │                                  │        │
│   │                 │                                  │        │
│   └────────┬────────┘                                  │        │
│            │                                           │        │
│            │ Immediately pivot                         │        │
│            ▼                                           │        │
│   ┌─────────────────┐                                  │        │
│   │                 │     User struggles               │        │
│   │ STATE 3:        │──────────────────────────────────┘        │
│   │ CHALLENGE       │                                           │
│   │ (Edge Cases)    │                                           │
│   │                 │                                           │
│   └────────┬────────┘                                           │
│            │                                                     │
│            │ "Thank you ZED" / "I'm done"                       │
│            ▼                                                     │
│   ┌─────────────────┐                                           │
│   │   [HANGUP]      │                                           │
│   │   Session End   │                                           │
│   └─────────────────┘                                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### State Behaviors

| State | Trigger | ZED's Action |
|-------|---------|--------------|
| **GYM** | User is wrong/learning | Ask scaffolding questions, reference slides |
| **COOL-DOWN** | User answers correctly | Validate briefly ("Exactly."), then immediately pivot |
| **CHALLENGE** | User shows understanding | Push with edge cases ("What if variance is 0?") |
| **Exception: Confused** | "I don't understand" | Brief explanation (2-3 sentences), then check understanding |
| **Exception: Tired** | "I'm done", "Thank you ZED" | Acknowledge, validate session, yield `[HANGUP]` |

---

## 🎙️ Wake Word Session Management

ZED operates like a smart speaker with **ASLEEP/AWAKE** states:

```
┌────────────────────────────────────────────────────────────┐
│                  WAKE WORD STATE MACHINE                    │
├────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────┐          "Hey ZED"         ┌───────────┐ │
│   │             │ ─────────────────────────▶ │           │ │
│   │   ASLEEP    │                            │   AWAKE   │ │
│   │  🔴 Ignore  │ ◀───────────────────────── │  🟢 Listen│ │
│   │             │     [HANGUP] / Timeout     │           │ │
│   └─────────────┘                            └───────────┘ │
│                                                             │
│   • WebSocket stays open                                    │
│   • Only state changes, not connection                      │
│   • Frontend receives status updates                        │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

### Backend (Python)

| Technology | Purpose | Why |
|------------|---------|-----|
| **FastAPI** | WebSocket server | Async, fast, modern Python |
| **Groq** | LLM & STT inference | Fastest inference (Llama 3.3 70B, Whisper) |
| **ElevenLabs** | Text-to-Speech | Natural, low-latency voice |
| **ChromaDB** | Vector database | Local, lightweight, persistent |
| **Sentence-Transformers** | Embeddings | `all-MiniLM-L6-v2` for semantic search |
| **PyMuPDF** | PDF parsing | Fast, accurate text extraction |
| **canvasapi** | Canvas LMS integration | Download course materials automatically |

### Frontend (TypeScript)

| Technology | Purpose | Why |
|------------|---------|-----|
| **React 18** | UI framework | Component-based, hooks |
| **Vite** | Build tool | Fast HMR, modern bundling |
| **TypeScript** | Type safety | Catch errors at compile time |
| **Tailwind CSS** | Styling | Utility-first, rapid prototyping |
| **Framer Motion** | Animations | Declarative, performant |
| **Web Audio API** | Voice Activity Detection | Browser-native VAD |
| **MediaRecorder API** | Audio capture | Browser-native recording |

### Infrastructure

| Component | Technology |
|-----------|------------|
| **Protocol** | WebSocket (real-time bidirectional) |
| **Audio Format** | WebM/WAV → MP3 |
| **Vector Store** | ChromaDB (SQLite backend) |
| **Session State** | In-memory (per WebSocket) |

---

## 📁 Project Structure

```
groq/
├── backend/
│   ├── server.py              # WebSocket server, wake word gatekeeper
│   ├── app/
│   │   ├── main.py            # CLI orchestrator (terminal mode)
│   │   └── services/
│   │       ├── brain.py       # Socratic State Machine, LLM
│   │       ├── knowledge.py   # RAG pipeline, ChromaDB
│   │       ├── ears.py        # Audio recording, Whisper STT
│   │       ├── mouth.py       # ElevenLabs TTS, audio playback
│   │       └── canvas_sync.py # Canvas LMS PDF downloader
│   ├── data/
│   │   ├── chroma_db/         # Vector embeddings (persistent)
│   │   ├── downloads/         # PDFs organized by course
│   │   └── wake_words/        # Porcupine wake word models
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx            # Main app, phase management
│   │   ├── components/
│   │   │   ├── MainScene.tsx  # Voice UI, conversation panel
│   │   │   └── LoginScene.tsx # Canvas login
│   │   └── hooks/
│   │       └── useVoiceInput.ts # VAD, WebSocket, audio handling
│   ├── index.html
│   └── package.json
│
└── README.md
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- API Keys: `GROQ_API_KEY`, `ELEVEN_API_KEY`, `CANVAS_API_KEY` (optional)

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
GROQ_API_KEY=your_groq_key
ELEVEN_API_KEY=your_elevenlabs_key
CANVAS_API_KEY=your_canvas_key  # Optional
CANVAS_API_URL=https://your-institution.instructure.com
EOF

# Run server
python server.py
```

### Frontend

```bash
cd frontend
npm install

# Create .env file
cat > .env << EOF
VITE_WS_URL=ws://localhost:8000/ws
VITE_API_URL=http://localhost:8000
EOF

# Run dev server
npm run dev
```

### Usage

1. Open `http://localhost:5173` in your browser
2. Allow microphone access
3. Say **"Hey ZED"** to wake up
4. Ask your question
5. Say **"Thank you ZED"** or **"I'm done"** to end

---

## 🔧 Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | ✅ | - | Groq API key for Whisper + Llama |
| `ELEVEN_API_KEY` | ✅ | - | ElevenLabs API key for TTS |
| `ELEVEN_VOICE_ID` | ❌ | `21m00Tcm4TlvDq8ikWAM` | ElevenLabs voice (Rachel) |
| `CANVAS_API_KEY` | ❌ | - | Canvas LMS API token |
| `CANVAS_API_URL` | ❌ | - | Canvas instance URL |
| `GROQ_MODEL` | ❌ | `llama-3.3-70b-versatile` | LLM model |
| `GROQ_TEMPERATURE` | ❌ | `0.4` | LLM temperature |
| `RAG_THRESHOLD` | ❌ | `0.35` | Minimum relevance score |
| `SKIP_RAG` | ❌ | `false` | Bypass RAG for testing |

### Frontend (`frontend/.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VITE_WS_URL` | ✅ | `ws://localhost:8000/ws` | WebSocket endpoint |
| `VITE_API_URL` | ❌ | `http://localhost:8000` | REST API endpoint |

---

## 📊 Data Flow

```
User speaks "What is variance?"
         │
         ▼
┌─────────────────┐
│  Browser        │
│  MediaRecorder  │──── WebM audio blob ────▶ WebSocket
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  server.py      │
│  (Gatekeeper)   │──── is_awake? ────▶ If FALSE, ignore
└─────────────────┘
         │ TRUE
         ▼
┌─────────────────┐
│  Groq Whisper   │
│  (STT)          │──── "What is variance?" ────▶
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  brain.py       │
│  (Reasoning)    │
│                 │
│  1. RAG search  │──── ChromaDB ────▶ [relevant chunks]
│  2. Build prompt│
│  3. Stream LLM  │──── Groq Llama ────▶ tokens
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  ElevenLabs     │
│  (TTS)          │──── MP3 audio ────▶ WebSocket
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  Browser        │
│  Audio.play()   │──── 🔊 ZED speaks
└─────────────────┘
```

---

## 🎯 Design Principles

1. **Socratic, not Spoon-feeding**: ZED asks questions, never gives direct answers
2. **Voice-first**: Optimized for spoken interaction, not typing
3. **Low Latency**: Streaming tokens + TTS for instant feedback
4. **Context-aware**: RAG pulls relevant course materials
5. **Relentless**: Keeps pushing until you truly understand
6. **Graceful**: Respects when you're done, validates your effort

---

## 📝 License

MIT

---

*Built with 🧠 and ☕ for students who want to think, not just memorize.*
