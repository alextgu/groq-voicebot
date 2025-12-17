import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

interface MainSceneProps {
  rotation: { x: number; y: number };
  onMouseMove: (e: React.MouseEvent) => void;
  onMouseLeave: () => void;
}

type MicStatus = "initializing" | "active" | "error" | "loading_model" | "requesting_mic" | "inactive";

export default function MainScene({ rotation, onMouseMove, onMouseLeave }: MainSceneProps) {
  const [showInput, setShowInput] = useState(false);
  const [query, setQuery] = useState("");
  const [micStatus] = useState<MicStatus>("active");
  const [isListening, setIsListening] = useState(false);
  const [transcribedText, setTranscribedText] = useState("");

  const handleTextSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    console.log("📨 Sending user query:", query);
    setTranscribedText(query);
    setQuery("");
  };

  const handleVoiceClick = () => {
    setIsListening(!isListening);
    if (!isListening) {
      // Start listening simulation
      setTimeout(() => {
        setTranscribedText("What is a moment generating function?");
        setIsListening(false);
      }, 3000);
    }
  };

  return (
    <div
      className="relative h-full w-full flex items-center justify-center text-white font-sans overflow-hidden pb-16 sm:pb-24 px-4"
      onMouseMove={onMouseMove}
      onMouseLeave={onMouseLeave}
    >

      {/* Mic Status Indicator */}
      {micStatus !== "inactive" && (
        <div
          className="absolute top-4 sm:top-8 right-4 sm:right-8 flex items-center gap-2 sm:gap-3 px-3 sm:px-5 py-1.5 sm:py-2.5 rounded-xl sm:rounded-2xl border border-white/20 backdrop-blur-xl z-20"
          style={{
            background:
              "linear-gradient(135deg, rgba(255,255,255,0.15), rgba(255,255,255,0.05))",
            boxShadow:
              "0 8px 25px rgba(0,0,0,0.4), inset 0 0 25px rgba(255,255,255,0.08)",
          }}
        >
          <div
            className={`w-2.5 sm:w-3.5 h-2.5 sm:h-3.5 rounded-full transition-all duration-500 ${
              micStatus === "active"
                ? "bg-green-500 shadow-[0_0_8px_2px_rgba(34,197,94,0.7)] animate-pulse"
                : micStatus === "error"
                ? "bg-red-500"
                : micStatus === "loading_model"
                ? "bg-purple-500"
                : micStatus === "requesting_mic"
                ? "bg-orange-400"
                : "bg-yellow-500"
            }`}
          ></div>
          <span className="text-xs sm:text-sm font-semibold bg-gradient-to-r from-[#8cffb1] via-[#4ee6ff] to-[#ff7ce0] bg-[length:200%_200%] text-transparent bg-clip-text animate-gradientFlow">
            {micStatus === "active"
              ? "Listening"
              : micStatus === "error"
              ? "Error"
              : micStatus === "loading_model"
              ? "Loading..."
              : micStatus === "requesting_mic"
              ? "Requesting..."
              : "Init..."}
          </span>
        </div>
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
        {/* Title */}
        <h1 className="text-5xl sm:text-[6rem] md:text-[7rem] font-extrabold tracking-[0.1em] sm:tracking-[0.18em] text-white/95 drop-shadow-[0_0_15px_rgba(255,255,255,0.25)] -mt-2 sm:-mt-6">
          <span className="text-[#ff6b6b]">ZED</span>
          <span className="text-white/90">.AI</span>
        </h1>

        {/* Description */}
        <p className="text-sm sm:text-base md:text-lg text-gray-200 leading-relaxed max-w-lg mx-auto">
          <span className="hidden sm:inline">Meet your personal AI assistant — designed to streamline your
          workflow, deliver precise insights, and anticipate your needs.</span>
          <span className="sm:hidden">Your personal AI study assistant.</span>
          <br />
          <span className="text-gray-200">
            Say{" "}
            <span className="text-[#ff6b6b] font-semibold">"Hey ZED"</span>{" "}
            to start.
          </span>
        </p>

        {/* Action Buttons */}
        <div className="flex flex-col items-center gap-4 sm:gap-6">
          <div className="flex flex-col sm:flex-row justify-center gap-3 sm:gap-6 w-full sm:w-auto">
            <button
              onClick={() => setShowInput(!showInput)}
              className="px-6 sm:px-8 py-2.5 sm:py-3 bg-white/10 border border-white/20 rounded-xl text-white text-sm sm:text-base font-medium hover:bg-white/20 active:scale-95 transition-all backdrop-blur-md"
            >
              Click to Type
            </button>

            <button
              onClick={handleVoiceClick}
              className={`px-6 sm:px-8 py-2.5 sm:py-3 rounded-xl text-sm sm:text-base font-medium border border-white/20 backdrop-blur-md active:scale-95 transition-all ${
                isListening
                  ? "bg-[#ff6b6b]/30 border-[#ff6b6b]/50 text-white"
                  : "bg-white/10 text-white hover:bg-white/20"
              }`}
            >
              {isListening ? "🎤 Listening..." : "Press to Talk"}
            </button>
          </div>

          {/* Text Input Form */}
          <AnimatePresence>
            {showInput && (
              <motion.form
                initial={{ opacity: 0, y: -10, height: 0 }}
                animate={{ opacity: 1, y: 0, height: "auto" }}
                exit={{ opacity: 0, y: -10, height: 0 }}
                transition={{ duration: 0.4, ease: "easeOut" }}
                onSubmit={handleTextSubmit}
                className="flex items-center justify-center gap-2 sm:gap-3 mt-2 w-full"
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

        {/* Transcription Display */}
        {transcribedText && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-4 sm:mt-6 p-3 sm:p-4 bg-green-500/20 border border-green-400/30 rounded-xl backdrop-blur-md"
          >
            <p className="text-green-300 font-semibold mb-1 text-sm sm:text-base">✅ You asked:</p>
            <p className="text-white text-sm sm:text-lg">"{transcribedText}"</p>
          </motion.div>
        )}
      </div>
    </div>
  );
}

