/**
 * useVoiceInput.ts - Voice Input Hook for Zed
 * 
 * Supports two modes:
 * 1. Push-to-Talk (Button) - Click to record, click to stop
 * 2. Voice Activation (Hands-Free) - Automatic speech detection via VAD
 * 
 * Uses Web Audio API for volume monitoring and MediaRecorder for capture.
 */

import { useState, useRef, useCallback, useEffect } from "react";

// ============================================================
// TYPES
// ============================================================

export type VoiceMode = "push-to-talk" | "hands-free";
export type VoiceStatus = "idle" | "listening" | "recording" | "processing" | "speaking" | "error";
export type ConversationState = "waiting" | "active"; // waiting for wake word, or in active conversation

export interface VoiceInputConfig {
  /** WebSocket URL for the server */
  wsUrl?: string;
  /** Voice activation threshold (0-1, default 0.1) */
  vadThreshold?: number;
  /** Silence duration before stopping (ms, default 1500) */
  silenceDuration?: number;
  /** Minimum speech duration before recording starts (ms, default 100) */
  speechMinDuration?: number;
  /** Audio sample rate */
  sampleRate?: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

export interface VoiceInputState {
  status: VoiceStatus;
  mode: VoiceMode;
  conversationState: ConversationState; // waiting for wake word or in active conversation
  isConnected: boolean;
  transcription: string;
  response: string;
  error: string | null;
  volume: number; // Current mic volume (0-1)
  chatHistory: ChatMessage[]; // Full conversation history
}

export interface VoiceInputActions {
  /** Start recording (Push-to-Talk mode) */
  startRecording: () => void;
  /** Stop recording (Push-to-Talk mode) */
  stopRecording: () => void;
  /** Toggle recording (Push-to-Talk mode) */
  toggleRecording: () => void;
  /** Set voice mode */
  setMode: (mode: VoiceMode) => void;
  /** Send text directly (bypass voice) */
  sendText: (text: string) => void;
  /** Clear transcription and response */
  clear: () => void;
  /** Reconnect WebSocket */
  reconnect: () => void;
}

// ============================================================
// CONSTANTS
// ============================================================

const DEFAULT_CONFIG: Required<VoiceInputConfig> = {
  wsUrl: "ws://localhost:8000/ws",
  vadThreshold: 0.08,
  silenceDuration: 1500,
  speechMinDuration: 150,
  sampleRate: 16000,
};

// Wake word and end phrase detection
const WAKE_PHRASES = ["hey zed", "hey said", "hey set", "hey zedd", "hey zet", "a zed", "heyze"];
const END_PHRASES = ["thank you zed", "thanks zed", "thank you said", "thanks said", "thankyou zed"];

function containsWakeWord(text: string): boolean {
  const lower = text.toLowerCase().trim();
  return WAKE_PHRASES.some(phrase => lower.includes(phrase));
}

function containsEndPhrase(text: string): boolean {
  const lower = text.toLowerCase().trim();
  return END_PHRASES.some(phrase => lower.includes(phrase));
}

function extractAfterWakeWord(text: string): string {
  const lower = text.toLowerCase();
  for (const phrase of WAKE_PHRASES) {
    const idx = lower.indexOf(phrase);
    if (idx !== -1) {
      return text.slice(idx + phrase.length).trim();
    }
  }
  return text;
}

// ============================================================
// HOOK
// ============================================================

export function useVoiceInput(config: VoiceInputConfig = {}): [VoiceInputState, VoiceInputActions] {
  const cfg = { ...DEFAULT_CONFIG, ...config };
  
  // Refs (declared first since setStatus uses statusRef)
  const wsRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const volumeIntervalRef = useRef<number | null>(null);
  const currentResponseRef = useRef("");
  
  // VAD state refs
  const isSpeakingRef = useRef(false);
  const silenceStartRef = useRef<number | null>(null);
  const speechStartRef = useRef<number | null>(null);
  const vadEnabledRef = useRef(false);
  const isRecordingRef = useRef(false);
  const statusRef = useRef<VoiceStatus>("idle"); // Track status for VAD logic
  const cooldownUntilRef = useRef<number>(0); // Prevent recording right after ZED speaks
  
  // State - Default to hands-free mode
  const [status, setStatusState] = useState<VoiceStatus>("idle");
  const [mode, setModeState] = useState<VoiceMode>("hands-free");
  const [conversationState, setConversationState] = useState<ConversationState>("waiting");
  const [isConnected, setIsConnected] = useState(false);
  const [transcription, setTranscription] = useState("");
  const [response, setResponse] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [volume, setVolume] = useState(0);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  
  // Ref for conversation state (for use in callbacks)
  const conversationStateRef = useRef<ConversationState>("waiting");
  
  // Wrapper to keep statusRef in sync with state
  const setStatus = useCallback((newStatus: VoiceStatus) => {
    statusRef.current = newStatus;
    setStatusState(newStatus);
  }, []);
  
  // ─────────────────────────────────────────────────────
  // WEBSOCKET CONNECTION
  // ─────────────────────────────────────────────────────
  
  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    
    console.log("🔌 Connecting to WebSocket:", cfg.wsUrl);
    const ws = new WebSocket(cfg.wsUrl);
    
    ws.onopen = () => {
      console.log("✅ WebSocket connected");
      setIsConnected(true);
      setError(null);
      
      // Send config to server
      ws.send(JSON.stringify({
        type: "config",
        sampleRate: cfg.sampleRate
      }));
    };
    
    ws.onclose = () => {
      console.log("❌ WebSocket disconnected");
      setIsConnected(false);
    };
    
    ws.onerror = (e) => {
      console.error("WebSocket error:", e);
      setError("Connection failed");
      setIsConnected(false);
    };
    
    ws.onmessage = async (event) => {
      // Check if it's binary data (audio)
      if (event.data instanceof Blob) {
        console.log("🔊 Received audio:", event.data.size, "bytes");
        try {
          // Play the audio
          const audioUrl = URL.createObjectURL(event.data);
          const audio = new Audio(audioUrl);
          
          // Set status to speaking while audio plays
          setStatus("speaking");
          
          audio.onended = () => {
            console.log("🔊 Audio playback finished");
            URL.revokeObjectURL(audioUrl);
            
            // Set cooldown after audio finishes
            cooldownUntilRef.current = Date.now() + 2000;
            console.log("⏸️ Cooldown started (2s before listening again)");
            setStatus("idle");
          };
          
          audio.onerror = (e) => {
            console.error("Audio playback error:", e);
            URL.revokeObjectURL(audioUrl);
            setStatus("idle");
          };
          
          await audio.play();
        } catch (e) {
          console.error("Failed to play audio:", e);
          setStatus("idle");
        }
        return;
      }
      
      // Handle JSON messages
      try {
        const data = JSON.parse(event.data);
        console.log("📨 Received:", data.type);
        
        switch (data.type) {
          case "transcription": {
            const text = data.text;
            console.log("🎤 Transcription:", text, "| State:", conversationStateRef.current);
            
            // Check for end phrase first (takes priority)
            if (containsEndPhrase(text)) {
              console.log("👋 End phrase detected - ending conversation");
              setConversationState("waiting");
              conversationStateRef.current = "waiting";
              setTranscription("");
              setResponse("Goodbye! Say 'Hey ZED' when you need me.");
              
              // Send end signal to server
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: "end_conversation" }));
              }
              
              setStatus("idle");
              return;
            }
            
            // Check for wake word
            if (conversationStateRef.current === "waiting") {
              if (containsWakeWord(text)) {
                console.log("👂 Wake word detected - activating!");
                setConversationState("active");
                conversationStateRef.current = "active";
                
                // Extract anything said after the wake word
                const afterWake = extractAfterWakeWord(text);
                if (afterWake && afterWake.length > 2) {
                  // User said something after "Hey ZED", process it
                  setTranscription(afterWake);
                  setStatus("processing");
                  setChatHistory(prev => [...prev, {
                    id: `user-${Date.now()}`,
                    role: "user",
                    content: afterWake,
                    timestamp: new Date()
                  }]);
                  currentResponseRef.current = "";
                  
                  // Send the actual query to backend
                  if (wsRef.current?.readyState === WebSocket.OPEN) {
                    wsRef.current.send(JSON.stringify({ type: "text", text: afterWake }));
                  }
                } else {
                  // Just wake word, acknowledge and wait for question
                  setTranscription("");
                  setResponse("I'm listening...");
                  setStatus("idle");
                }
              } else {
                // Not a wake word, ignore
                console.log("💤 Ignoring (waiting for wake word):", text);
                setStatus("idle");
              }
              return;
            }
            
            // Active conversation - process normally
            setTranscription(text);
            setStatus("processing");
            setChatHistory(prev => [...prev, {
              id: `user-${Date.now()}`,
              role: "user",
              content: text,
              timestamp: new Date()
            }]);
            currentResponseRef.current = "";
            break;
          }
          
          case "response":
            if (data.done) {
              const finalText = data.full_text || currentResponseRef.current;
              if (finalText) {
                setResponse(finalText);
                // Add assistant message to history
                setChatHistory(prev => [...prev, {
                  id: `assistant-${Date.now()}`,
                  role: "assistant",
                  content: finalText,
                  timestamp: new Date()
                }]);
              }
              currentResponseRef.current = "";
              
              // If no audio coming, set idle immediately with cooldown
              if (!data.has_audio) {
                cooldownUntilRef.current = Date.now() + 2000;
                console.log("⏸️ Cooldown started (no audio, 2s before listening)");
                setStatus("idle");
              }
              // If audio is coming, keep status as "speaking" until audio finishes
            } else {
              currentResponseRef.current += data.text;
              setResponse(currentResponseRef.current);
              setStatus("speaking");
            }
            break;
          
          case "error":
            setError(data.message);
            setStatus("error");
            break;
          
          case "pong":
          case "config_ack":
            // Acknowledged
            break;
        }
      } catch (e) {
        console.error("Failed to parse message:", e);
      }
    };
    
    wsRef.current = ws;
  }, [cfg.wsUrl, cfg.sampleRate]);
  
  // Connect on mount
  useEffect(() => {
    connectWebSocket();
    return () => {
      wsRef.current?.close();
    };
  }, [connectWebSocket]);
  
  // Initialize hands-free mode on mount (request mic permission and start VAD)
  useEffect(() => {
    const initHandsFree = async () => {
      if (mode === "hands-free") {
        console.log("🎤 Initializing hands-free mode on mount...");
        try {
          await setupAudio();
          vadEnabledRef.current = true;
          startVolumeMonitoring();
          setStatus("listening");
          console.log("✅ Hands-free mode active");
        } catch (e) {
          console.error("Failed to initialize hands-free mode:", e);
          setError("Microphone access required");
        }
      }
    };
    
    // Small delay to let WebSocket connect first
    const timer = setTimeout(initHandsFree, 500);
    return () => clearTimeout(timer);
  }, []); // Only run once on mount
  
  // ─────────────────────────────────────────────────────
  // AUDIO SETUP
  // ─────────────────────────────────────────────────────
  
  const setupAudio = useCallback(async () => {
    if (streamRef.current) return streamRef.current;
    
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: cfg.sampleRate,
        }
      });
      
      streamRef.current = stream;
      
      // Setup Web Audio API for volume monitoring
      const audioContext = new AudioContext({ sampleRate: cfg.sampleRate });
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      source.connect(analyser);
      
      audioContextRef.current = audioContext;
      analyserRef.current = analyser;
      
      console.log("🎤 Audio setup complete");
      return stream;
    } catch (e) {
      console.error("Failed to get microphone:", e);
      setError("Microphone access denied");
      throw e;
    }
  }, [cfg.sampleRate]);
  
  // ─────────────────────────────────────────────────────
  // VOLUME MONITORING (for VAD)
  // ─────────────────────────────────────────────────────
  
  const getVolume = useCallback((): number => {
    if (!analyserRef.current) return 0;
    
    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
    analyserRef.current.getByteFrequencyData(dataArray);
    
    // Calculate RMS
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
      const normalized = dataArray[i] / 255;
      sum += normalized * normalized;
    }
    const rms = Math.sqrt(sum / dataArray.length);
    
    return rms;
  }, []);
  
  const startVolumeMonitoring = useCallback(() => {
    if (volumeIntervalRef.current) return;
    
    volumeIntervalRef.current = window.setInterval(() => {
      const vol = getVolume();
      setVolume(vol);
      
      // VAD Logic (only in hands-free mode, and NOT while processing/speaking/cooldown)
      const currentStatus = statusRef.current;
      const now = Date.now();
      const inCooldown = now < cooldownUntilRef.current;
      
      const canListen = vadEnabledRef.current && 
                        !isRecordingRef.current && 
                        !inCooldown &&
                        currentStatus !== "processing" && 
                        currentStatus !== "speaking";
      
      if (canListen) {
        if (vol > cfg.vadThreshold) {
          // Sound detected
          silenceStartRef.current = null;
          
          if (!speechStartRef.current) {
            speechStartRef.current = now;
          } else if (now - speechStartRef.current > cfg.speechMinDuration) {
            // Speech confirmed - start recording
            console.log("🎙️ VAD: Speech detected, starting recording");
            isSpeakingRef.current = true;
            startRecordingInternal();
          }
        } else {
          // Silence
          speechStartRef.current = null;
        }
      }
      
      // Check for silence during recording (VAD mode)
      if (vadEnabledRef.current && isRecordingRef.current && isSpeakingRef.current) {
        if (vol < cfg.vadThreshold) {
          if (!silenceStartRef.current) {
            silenceStartRef.current = Date.now();
          } else if (Date.now() - silenceStartRef.current > cfg.silenceDuration) {
            // Silence threshold reached - stop recording
            console.log("🔇 VAD: Silence detected, stopping recording");
            stopRecordingInternal();
            isSpeakingRef.current = false;
            silenceStartRef.current = null;
          }
        } else {
          silenceStartRef.current = null;
        }
      }
    }, 50); // 50ms = 20Hz monitoring
  }, [getVolume, cfg.vadThreshold, cfg.speechMinDuration, cfg.silenceDuration]);
  
  const stopVolumeMonitoring = useCallback(() => {
    if (volumeIntervalRef.current) {
      clearInterval(volumeIntervalRef.current);
      volumeIntervalRef.current = null;
    }
    setVolume(0);
  }, []);
  
  // ─────────────────────────────────────────────────────
  // RECORDING
  // ─────────────────────────────────────────────────────
  
  const startRecordingInternal = useCallback(async () => {
    if (isRecordingRef.current) return;
    
    try {
      const stream = await setupAudio();
      
      chunksRef.current = [];
      
      // Use webm for browser compatibility
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      
      const recorder = new MediaRecorder(stream, { mimeType });
      
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };
      
      recorder.onstop = async () => {
        console.log("📼 Recording stopped, processing...");
        isRecordingRef.current = false;
        setStatus("processing");
        
        const blob = new Blob(chunksRef.current, { type: mimeType });
        console.log(`📦 Audio blob: ${blob.size} bytes`);
        
        // Send to server
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          const arrayBuffer = await blob.arrayBuffer();
          wsRef.current.send(arrayBuffer);
          console.log("📤 Sent audio to server");
        } else {
          setError("Not connected to server");
          setStatus("error");
        }
        
        chunksRef.current = [];
      };
      
      recorder.start(100); // Collect data every 100ms
      mediaRecorderRef.current = recorder;
      isRecordingRef.current = true;
      setStatus("recording");
      setResponse(""); // Clear previous response
      
      console.log("🎙️ Recording started");
    } catch (e) {
      console.error("Failed to start recording:", e);
      setError("Failed to start recording");
      setStatus("error");
    }
  }, [setupAudio]);
  
  const stopRecordingInternal = useCallback(() => {
    if (!isRecordingRef.current || !mediaRecorderRef.current) return;
    
    if (mediaRecorderRef.current.state === "recording") {
      mediaRecorderRef.current.stop();
    }
  }, []);
  
  // ─────────────────────────────────────────────────────
  // PUBLIC ACTIONS
  // ─────────────────────────────────────────────────────
  
  const startRecording = useCallback(() => {
    if (mode === "push-to-talk") {
      startRecordingInternal();
    }
  }, [mode, startRecordingInternal]);
  
  const stopRecording = useCallback(() => {
    if (mode === "push-to-talk") {
      stopRecordingInternal();
    }
  }, [mode, stopRecordingInternal]);
  
  const toggleRecording = useCallback(() => {
    if (isRecordingRef.current) {
      stopRecording();
    } else {
      startRecording();
    }
  }, [startRecording, stopRecording]);
  
  const setMode = useCallback(async (newMode: VoiceMode) => {
    setModeState(newMode);
    
    if (newMode === "hands-free") {
      // Enable VAD
      console.log("🎤 Enabling hands-free mode");
      await setupAudio();
      vadEnabledRef.current = true;
      startVolumeMonitoring();
      setStatus("listening");
    } else {
      // Disable VAD
      console.log("🔘 Switching to push-to-talk mode");
      vadEnabledRef.current = false;
      isSpeakingRef.current = false;
      silenceStartRef.current = null;
      speechStartRef.current = null;
      
      // Stop recording if in progress
      if (isRecordingRef.current) {
        stopRecordingInternal();
      }
      
      stopVolumeMonitoring();
      setStatus("idle");
    }
  }, [setupAudio, startVolumeMonitoring, stopVolumeMonitoring, stopRecordingInternal]);
  
  const sendText = useCallback((text: string) => {
    if (!text.trim()) return;
    
    setTranscription(text);
    setResponse("");
    setStatus("processing");
    
    // Add user message to history
    setChatHistory(prev => [...prev, {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: new Date()
    }]);
    currentResponseRef.current = "";
    
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: "text",
        text: text
      }));
    } else {
      setError("Not connected to server");
      setStatus("error");
    }
  }, []);
  
  const clear = useCallback(() => {
    setTranscription("");
    setResponse("");
    setError(null);
    setChatHistory([]);
    currentResponseRef.current = "";
  }, []);
  
  const reconnect = useCallback(() => {
    wsRef.current?.close();
    connectWebSocket();
  }, [connectWebSocket]);
  
  // ─────────────────────────────────────────────────────
  // CLEANUP
  // ─────────────────────────────────────────────────────
  
  useEffect(() => {
    return () => {
      stopVolumeMonitoring();
      
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      }
      
      streamRef.current?.getTracks().forEach(track => track.stop());
      audioContextRef.current?.close();
      wsRef.current?.close();
    };
  }, [stopVolumeMonitoring]);
  
  // ─────────────────────────────────────────────────────
  // RETURN
  // ─────────────────────────────────────────────────────
  
  const state: VoiceInputState = {
    status,
    mode,
    conversationState,
    isConnected,
    transcription,
    response,
    error,
    volume,
    chatHistory,
  };
  
  const actions: VoiceInputActions = {
    startRecording,
    stopRecording,
    toggleRecording,
    setMode,
    sendText,
    clear,
    reconnect,
  };
  
  return [state, actions];
}

export default useVoiceInput;

