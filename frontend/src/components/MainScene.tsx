import { useState, useRef, useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useVoiceInput } from "../hooks/useVoiceInput";

interface MainSceneProps {
  rotation: { x: number; y: number };
  onMouseMove: (e: React.MouseEvent) => void;
  onMouseLeave: () => void;
}

// Rotating taglines
const TAGLINES = [
  "The AI that teaches you to think.",
  "Questions, not answers.",
  "Built to challenge, not to cheat.",
  "Your mind's sparring partner.",
  "Learn to solve, not to copy.",
  "Think harder. Learn deeper.",
];

export default function MainScene({ rotation, onMouseMove, onMouseLeave }: MainSceneProps) {
  const [showInput, setShowInput] = useState(false);
  const [query, setQuery] = useState("");
  const [isPanelOpen, setIsPanelOpen] = useState(true);
  const [taglineIndex, setTaglineIndex] = useState(0);
  const chatEndRef = useRef<HTMLDivElement>(null);
  
  // Voice input hook
  const [voiceState, voiceActions] = useVoiceInput({
    wsUrl: "ws://localhost:8000/ws",
    vadThreshold: 0.08,
    silenceDuration: 1500,
  });
  
  const { status, isConnected, response, error, volume, chatHistory } = voiceState;
  const { sendText, clear } = voiceActions;

  // Auto-scroll chat to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, response]);

  // Rotate taglines every 5 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      setTaglineIndex((prev) => (prev + 1) % TAGLINES.length);
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  // Handle text form submission
  const handleTextSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    sendText(query);
    setQuery("");
  };

  const hasMessages = chatHistory.length > 0;

  return (
    <div
      className="relative h-full w-full flex text-white font-sans overflow-hidden pb-16 sm:pb-24"
      onMouseMove={onMouseMove}
      onMouseLeave={onMouseLeave}
    >
      {/* Left Panel - Chat/Output Panel (Collapsible) */}
      <motion.div
        initial={false}
        animate={{ 
          width: isPanelOpen ? 400 : 0,
          opacity: isPanelOpen ? 1 : 0
        }}
        transition={{ duration: 0.3, ease: "easeInOut" }}
        className="hidden md:flex flex-col h-full border-r border-white/10 backdrop-blur-xl overflow-hidden flex-shrink-0"
        style={{
          background: "linear-gradient(180deg, rgba(15,15,25,0.95), rgba(10,10,20,0.98))",
        }}
      >
        <div className="w-[400px] h-full flex flex-col">
        {/* Chat Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
          <div className="flex items-center gap-3">
            <span className="text-[#ff6b6b] text-xl">💬</span>
            <div>
              <span className="text-base font-semibold text-white">Conversation</span>
              <p className="text-xs text-gray-500">Voice & text responses</p>
            </div>
          </div>
          {hasMessages && (
            <button
              onClick={clear}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors px-2 py-1 rounded hover:bg-white/5"
            >
              Clear all
            </button>
          )}
        </div>

        {/* Chat Messages */}
        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5 scrollbar-thin scrollbar-thumb-white/10">
          {/* Empty state */}
          {!hasMessages && !response && (
            <div className="h-full flex flex-col items-center justify-center text-gray-500">
              <span className="text-4xl mb-3">🎙️</span>
              <p className="text-sm text-center">Start speaking to ZED</p>
              <p className="text-xs text-gray-600 mt-1">Responses will appear here</p>
            </div>
          )}

          {chatHistory.map((msg) => (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}
            >
              {/* Role Label */}
              <span className={`text-xs mb-1.5 font-medium ${
                msg.role === "user" ? "text-blue-400" : "text-[#ff6b6b]"
              }`}>
                {msg.role === "user" ? "You" : "🧠 ZED"}
              </span>
              
              {/* Message Bubble */}
              <div
                className={`max-w-[95%] px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                  msg.role === "user"
                    ? "bg-blue-500/20 border border-blue-500/30 text-blue-100"
                    : "bg-[#ff6b6b]/10 border border-[#ff6b6b]/20 text-gray-100"
                }`}
              >
                {msg.content}
              </div>
              
              {/* Timestamp */}
              <span className="text-[10px] text-gray-600 mt-1.5">
                {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </motion.div>
          ))}

          {/* Current streaming response */}
          {response && (status === "speaking" || status === "processing") && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-start"
            >
              <span className="text-xs mb-1.5 font-medium text-[#ff6b6b]">🧠 ZED</span>
              <div className="max-w-[95%] px-4 py-3 rounded-2xl text-sm leading-relaxed bg-[#ff6b6b]/10 border border-[#ff6b6b]/20 text-gray-100 whitespace-pre-wrap">
                {response || "Thinking..."}
                <motion.span
                  animate={{ opacity: [1, 0, 1] }}
                  transition={{ duration: 0.8, repeat: Infinity }}
                  className="ml-1 text-[#ff6b6b]"
                >
                  ▊
                </motion.span>
              </div>
            </motion.div>
          )}

          <div ref={chatEndRef} />
        </div>

        {/* Status Bar */}
        <div className="px-5 py-4 border-t border-white/10 bg-black/20">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm">
              {status === "recording" && (
                <>
                  <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse"></span>
                  <span className="text-red-400">Recording...</span>
                </>
              )}
              {status === "processing" && (
                <>
                  <span className="w-2.5 h-2.5 rounded-full bg-yellow-500 animate-pulse"></span>
                  <span className="text-yellow-400">Processing...</span>
                </>
              )}
              {status === "speaking" && (
                <>
                  <span className="w-2.5 h-2.5 rounded-full bg-[#ff6b6b] animate-pulse"></span>
                  <span className="text-[#ff6b6b]">🔊 Speaking...</span>
                </>
              )}
              {(status === "idle" || status === "listening") && (
                <>
                  <span className="w-2.5 h-2.5 rounded-full bg-green-500"></span>
                  <span className="text-gray-400">Ready</span>
                </>
              )}
            </div>
            <span className="text-xs text-gray-600">
              {chatHistory.length} message{chatHistory.length !== 1 ? "s" : ""}
            </span>
          </div>
        </div>
        </div>
      </motion.div>

      {/* Panel Toggle Arrow Button */}
      <motion.button
        onClick={() => setIsPanelOpen(!isPanelOpen)}
        className="hidden md:flex fixed top-1/2 -translate-y-1/2 z-30 items-center justify-center w-6 h-16 rounded-r-lg border border-l-0 border-white/20 backdrop-blur-xl hover:bg-white/10 transition-colors group"
        initial={false}
        animate={{
          left: isPanelOpen ? 400 : 0, // Match panel width
        }}
        transition={{ duration: 0.3, ease: "easeInOut" }}
        style={{
          background: "linear-gradient(90deg, rgba(15,15,25,0.95), rgba(20,20,30,0.9))",
        }}
      >
        <motion.svg
          animate={{ rotate: isPanelOpen ? 0 : 180 }}
          transition={{ duration: 0.3 }}
          className="w-4 h-4 text-gray-400 group-hover:text-white transition-colors"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </motion.svg>
      </motion.button>

      {/* Right Panel - Main ZED Interface */}
      <div className="flex-1 flex items-center justify-center px-4">
        {/* Connection Status (Small, top right) */}
        <div className="absolute top-4 sm:top-6 right-4 sm:right-6 flex items-center gap-2 text-xs text-gray-500 z-20">
          <div className={`w-2 h-2 rounded-full ${isConnected ? "bg-green-500" : "bg-red-500"}`} />
          <span>{isConnected ? "Connected" : "Offline"}</span>
        </div>

        {/* Volume Visualizer (Small, subtle) */}
        {volume > 0.01 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="absolute top-4 sm:top-6 left-4 z-20 md:hidden"
          >
            <div className="flex items-end gap-0.5 h-4">
              {[0.2, 0.4, 0.6, 0.8, 1].map((threshold, i) => (
                <div
                  key={i}
                  className={`w-1 rounded-full transition-all duration-75 ${
                    volume > threshold * 0.3 ? "bg-[#ff6b6b]" : "bg-white/20"
                  }`}
                  style={{ height: `${(i + 1) * 20}%` }}
                />
              ))}
            </div>
          </motion.div>
        )}

        {/* Main Glass Card */}
        <div
          className="relative z-10 w-full max-w-2xl p-8 sm:p-12 md:p-16 rounded-2xl sm:rounded-3xl border border-white/30 backdrop-blur-2xl text-center space-y-8 sm:space-y-12 transition-transform duration-300 ease-out"
          style={{
            transform: `perspective(1000px) rotateX(${rotation.x}deg) rotateY(${rotation.y}deg) scale(1.01)`,
            background:
              "linear-gradient(135deg, rgba(30,30,45,0.85), rgba(20,20,35,0.75))",
            boxShadow:
              "0 20px 60px rgba(0,0,0,0.5), inset 0 0 30px rgba(255,255,255,0.08)",
          }}
        >
          {/* Title with Pulsing Effect when Recording */}
          <motion.h1 
            className="text-5xl sm:text-[6rem] md:text-[7rem] font-extrabold tracking-[0.1em] sm:tracking-[0.18em] text-white/95 drop-shadow-[0_0_15px_rgba(255,255,255,0.25)] -mt-2 sm:-mt-6"
            animate={status === "recording" ? { 
              textShadow: [
                "0 0 15px rgba(255,107,107,0.5)",
                "0 0 30px rgba(255,107,107,0.8)",
                "0 0 15px rgba(255,107,107,0.5)"
              ]
            } : {}}
            transition={{ duration: 1, repeat: Infinity }}
          >
            <span className="text-[#ff6b6b]">ZED</span>
            <span className="text-white/90">.AI</span>
          </motion.h1>

          {/* Rotating Tagline */}
          <div className="h-8 sm:h-10 flex items-center justify-center">
            <AnimatePresence mode="wait">
              <motion.p
                key={taglineIndex}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.5, ease: "easeInOut" }}
                className="text-sm sm:text-base md:text-lg text-gray-300 leading-relaxed max-w-md mx-auto"
              >
                {TAGLINES[taglineIndex]}
              </motion.p>
            </AnimatePresence>
          </div>

          {/* Voice Status - Primary Focus */}
          <div className="flex flex-col items-center gap-4">
            {/* Main Voice Indicator */}
            <motion.div 
              className={`relative px-8 sm:px-12 py-4 sm:py-5 rounded-2xl text-base sm:text-lg font-medium border-2 backdrop-blur-md transition-all ${
                status === "recording"
                  ? "bg-red-500/20 border-red-500/60 text-white"
                  : status === "listening"
                  ? "bg-blue-500/20 border-blue-500/40 text-blue-200"
                  : status === "processing"
                  ? "bg-yellow-500/20 border-yellow-500/40 text-yellow-200"
                  : status === "speaking"
                  ? "bg-[#ff6b6b]/20 border-[#ff6b6b]/40 text-[#ff6b6b]"
                  : "bg-white/5 border-white/20 text-gray-300"
              }`}
              animate={status === "recording" ? { scale: [1, 1.02, 1] } : {}}
              transition={{ duration: 1.5, repeat: Infinity }}
            >
              {status === "recording" && (
                <motion.div
                  className="absolute inset-0 rounded-2xl bg-red-500/10"
                  animate={{ opacity: [0.3, 0.6, 0.3] }}
                  transition={{ duration: 1, repeat: Infinity }}
                />
              )}
              <span className="relative z-10 flex items-center gap-3">
                {status === "recording" && (
                  <>
                    <span className="w-3 h-3 rounded-full bg-red-500 animate-pulse"></span>
                    Recording...
                  </>
                )}
                {status === "listening" && (
                  <>
                    <span className="w-3 h-3 rounded-full bg-blue-400 animate-pulse"></span>
                    Listening...
                  </>
                )}
                {status === "processing" && (
                  <>
                    <span className="w-3 h-3 rounded-full bg-yellow-400 animate-spin"></span>
                    Thinking...
                  </>
                )}
                {status === "speaking" && (
                  <>
                    <span className="w-3 h-3 rounded-full bg-[#ff6b6b] animate-pulse"></span>
                    🔊 Speaking...
                  </>
                )}
                {status === "idle" && (
                  <>
                    <span className="w-3 h-3 rounded-full bg-gray-400"></span>
                    🎤 Speak anytime
                  </>
                )}
                {status === "error" && (
                  <>
                    <span className="w-3 h-3 rounded-full bg-red-400"></span>
                    Reconnecting...
                  </>
                )}
              </span>
            </motion.div>

            {/* Secondary: Type option */}
            <button
              onClick={() => setShowInput(!showInput)}
              className="text-gray-500 text-sm hover:text-gray-300 transition-colors flex items-center gap-2"
            >
              <span>⌨️</span>
              <span>{showInput ? "Hide keyboard" : "Or type instead"}</span>
            </button>

            {/* Text Input Form */}
            <AnimatePresence>
              {showInput && (
                <motion.form
                  initial={{ opacity: 0, y: -10, height: 0 }}
                  animate={{ opacity: 1, y: 0, height: "auto" }}
                  exit={{ opacity: 0, y: -10, height: 0 }}
                  transition={{ duration: 0.3, ease: "easeOut" }}
                  onSubmit={handleTextSubmit}
                  className="flex items-center justify-center gap-2 sm:gap-3 w-full"
                >
                  <input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Ask ZED anything..."
                    className="flex-1 sm:flex-none w-full sm:w-72 md:w-96 px-4 sm:px-5 py-2.5 sm:py-3 bg-white/10 border border-white/20 rounded-xl text-white text-sm sm:text-base placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-red-500/50 backdrop-blur-lg transition"
                  />
                  <button
                    type="submit"
                    className="px-4 sm:px-5 py-2.5 sm:py-3 bg-gradient-to-r from-[#ff6b6b] to-[#ff9a9e] rounded-xl font-semibold text-white hover:scale-105 active:scale-95 transition-transform"
                  >
                    →
                  </button>
                </motion.form>
              )}
            </AnimatePresence>
          </div>

          {/* Error Display - Small and subtle */}
          {error && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-red-400/80 text-xs flex items-center justify-center gap-1"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-red-400"></span>
              {error}
            </motion.div>
          )}

          {/* Mobile: Show last exchange inline */}
          {hasMessages && (
            <div className="md:hidden space-y-3">
              <div className="h-px bg-white/10"></div>
              <div className="text-left space-y-2">
                {chatHistory.slice(-2).map((msg) => (
                  <div
                    key={msg.id}
                    className={`text-xs ${
                      msg.role === "user" ? "text-blue-300" : "text-gray-300"
                    }`}
                  >
                    <span className={`font-semibold ${
                      msg.role === "user" ? "text-blue-400" : "text-[#ff6b6b]"
                    }`}>
                      {msg.role === "user" ? "You: " : "ZED: "}
                    </span>
                    {msg.content.length > 100 ? msg.content.slice(0, 100) + "..." : msg.content}
                  </div>
                ))}
              </div>
              <button
                onClick={clear}
                className="text-gray-500 text-xs hover:text-white transition-colors"
              >
                Clear conversation
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Large Visual Indicator (Recording State) */}
      <AnimatePresence>
        {status === "recording" && (
          <motion.div
            initial={{ opacity: 0, scale: 0.5 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.5 }}
            className="fixed inset-0 pointer-events-none z-30 flex items-center justify-center"
          >
            {/* Pulsing ring effect */}
            <motion.div
              className="absolute w-[200px] h-[200px] sm:w-[300px] sm:h-[300px] rounded-full border-4 border-red-500/30"
              animate={{ 
                scale: [1, 1.5, 1],
                opacity: [0.5, 0, 0.5]
              }}
              transition={{ duration: 2, repeat: Infinity }}
            />
            <motion.div
              className="absolute w-[150px] h-[150px] sm:w-[200px] sm:h-[200px] rounded-full border-4 border-red-500/50"
              animate={{ 
                scale: [1, 1.3, 1],
                opacity: [0.7, 0.2, 0.7]
              }}
              transition={{ duration: 1.5, repeat: Infinity }}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
