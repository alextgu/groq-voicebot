import { useState, useEffect, useCallback } from "react";
import { AnimatePresence, motion } from "framer-motion";
import LoginScene from "./components/LoginScene";
import MainScene from "./components/MainScene";

// Logo component - replace src with your actual logo
const Logo = ({ size = 40, className = "" }: { size?: number; className?: string }) => (
  <img
    src="/logo.png"
    alt="ZED Logo"
    width={size}
    height={size}
    className={`object-contain ${className}`}
    onError={(e) => {
      // Fallback to text if image doesn't load
      e.currentTarget.style.display = "none";
      e.currentTarget.nextElementSibling?.classList.remove("hidden");
    }}
  />
);

// Fallback logo (shown if image fails to load)
const LogoFallback = ({ size = 40 }: { size?: number }) => (
  <div
    className="hidden rounded-xl bg-gradient-to-br from-[#ff6b6b] to-[#ff9a9e] flex items-center justify-center"
    style={{ width: size, height: size }}
  >
    <span className="text-white font-bold" style={{ fontSize: size * 0.45 }}>Z</span>
  </div>
);

type Phase = "intro" | "login" | "welcome" | "main";

export default function App() {
  const [phase, setPhase] = useState<Phase>("intro");
  const [introText, setIntroText] = useState("");
  const [welcomeText, setWelcomeText] = useState("");
  const [rotation, setRotation] = useState({ x: 0, y: 0 });
  const [showHelp, setShowHelp] = useState(false);

  // Skip to next phase on click
  const skipToNext = useCallback(() => {
    if (phase === "intro") setPhase("login");
    else if (phase === "welcome") setPhase("main");
  }, [phase]);

  // Mouse parallax effect
  const handleMouseMove = (e: React.MouseEvent) => {
    const x = (window.innerHeight / 2 - e.clientY) / 200;
    const y = (e.clientX - window.innerWidth / 2) / 200;
    setRotation({ x, y });
  };

  const handleMouseLeave = () => setRotation({ x: 0, y: 0 });

  // Intro typing animation
  useEffect(() => {
    if (phase !== "intro") return;
    let i = 0;
    const text = "Meet ZED, your personalized study buddy.";
    const timer = setInterval(() => {
      setIntroText(text.slice(0, i + 1));
      i++;
      if (i === text.length) {
        clearInterval(timer);
        setTimeout(() => setPhase("login"), 1400);
      }
    }, 70);
    return () => clearInterval(timer);
  }, [phase]);

  // Welcome typing animation
  useEffect(() => {
    if (phase !== "welcome") return;
    let i = 0;
    const message = "Welcome back 👋 Good luck studying.";
    const timer = setInterval(() => {
      setWelcomeText(message.slice(0, i + 1));
      i++;
      if (i === message.length) {
        clearInterval(timer);
        setTimeout(() => setPhase("main"), 1800);
      }
    }, 55);
    return () => clearInterval(timer);
  }, [phase]);

  return (
    // Persistent background wrapper to prevent white flash
    <div className="fixed inset-0 bg-[#0a0a0f]">
      {/* Animated liquid background */}
      <div className="animated-bg">
        <div className="bg-orb bg-orb-1"></div>
        <div className="bg-orb bg-orb-2"></div>
        <div className="bg-orb bg-orb-3"></div>
      </div>
      
      <AnimatePresence mode="wait">
      {/* INTRO PHASE */}
      {phase === "intro" && (
        <motion.div
          key="intro"
          className="absolute inset-0 flex flex-col items-center justify-center text-white font-sans cursor-pointer"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.5 }}
          onClick={skipToNext}
        >
          <div className="text-3xl sm:text-5xl px-8 text-center">
            {introText}
            <span className="animate-pulse">|</span>
          </div>
          <motion.p
            className="absolute bottom-8 text-gray-500 text-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 1 }}
          >
            Click anywhere to skip
          </motion.p>
        </motion.div>
      )}

      {/* LOGIN PHASE */}
      {phase === "login" && (
        <motion.div
          key="login"
          className="absolute inset-0"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.5 }}
        >
          <LoginScene onLoginSuccess={() => setPhase("welcome")} />
        </motion.div>
      )}

      {/* WELCOME PHASE */}
      {phase === "welcome" && (
        <motion.div
          key="welcome"
          className="absolute inset-0 flex flex-col items-center justify-center text-white font-sans cursor-pointer"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.5 }}
          onClick={skipToNext}
        >
          <div className="text-3xl sm:text-5xl px-8 text-center">
            {welcomeText}
          </div>
          <motion.p
            className="absolute bottom-8 text-gray-500 text-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5 }}
          >
            Click anywhere to skip
          </motion.p>
        </motion.div>
      )}

      {/* MAIN PHASE */}
      {phase === "main" && (
        <motion.div
          key="main"
          className="absolute inset-0"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.5 }}
        >
          <MainScene
            rotation={rotation}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
          />
        </motion.div>
      )}

      {/* Bottom Instructions Panel */}
      {phase === "main" && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, duration: 0.6 }}
          className="fixed bottom-0 left-0 right-0 z-40 py-5 sm:py-6 px-4 sm:px-6 backdrop-blur-md border-t border-white/10"
          style={{
            background:
              "linear-gradient(to top, rgba(10,10,15,0.6), rgba(10,10,15,0.4))",
          }}
        >
          <div className="max-w-4xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 sm:gap-5">
            {/* Logo & Title */}
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl overflow-hidden flex items-center justify-center bg-gradient-to-br from-[#ff6b6b] to-[#ff9a9e]">
                <Logo size={40} />
                <LogoFallback size={40} />
              </div>
              <div>
                <h3 className="text-white font-semibold">ZED.AI</h3>
                <p className="text-gray-500 text-xs">Your AI Study Assistant</p>
              </div>
            </div>

            {/* Instructions */}
            <div className="flex flex-wrap items-center justify-center gap-4 sm:gap-6 text-xs sm:text-sm">
              <div className="flex items-center gap-2 text-gray-400">
                <span className="px-2 py-1 bg-white/10 rounded text-[10px] sm:text-xs font-mono text-[#ff6b6b]">
                  "Hey ZED"
                </span>
                <span>Wake word</span>
              </div>
              <div className="flex items-center gap-2 text-gray-400">
                <span className="px-2 py-1 bg-white/10 rounded text-[10px] sm:text-xs font-mono">
                  🎤 Click
                </span>
                <span>Voice</span>
              </div>
              <div className="flex items-center gap-2 text-gray-400">
                <span className="px-2 py-1 bg-white/10 rounded text-[10px] sm:text-xs font-mono">
                  ⌨️ Type
                </span>
                <span>Question</span>
              </div>
            </div>

            {/* Status */}
            <div className="flex items-center gap-2 text-gray-500 text-[10px] sm:text-xs">
              <div className="w-1.5 sm:w-2 h-1.5 sm:h-2 rounded-full bg-green-500 animate-pulse"></div>
              <span>Connected</span>
            </div>
          </div>
        </motion.div>
      )}

      {/* Floating About Button & Panel */}
      {phase === "main" && (
        <>
          {/* About Icon Button */}
          <motion.button
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.6, duration: 0.3 }}
            onClick={() => setShowHelp(!showHelp)}
            className="fixed bottom-16 sm:bottom-24 right-3 sm:right-6 z-50 w-9 h-9 sm:w-10 sm:h-10 rounded-full backdrop-blur-xl border border-white/20 flex items-center justify-center hover:scale-110 active:scale-95 transition-transform cursor-pointer"
            style={{
              background:
                "linear-gradient(135deg, rgba(255,255,255,0.15), rgba(255,255,255,0.05))",
              boxShadow:
                "0 8px 25px rgba(0,0,0,0.3), inset 0 0 25px rgba(255,255,255,0.05)",
            }}
          >
            {showHelp ? (
              <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            )}
          </motion.button>

          {/* About Panel - Full screen on mobile, positioned on desktop */}
          <AnimatePresence>
            {showHelp && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 20 }}
                transition={{ duration: 0.2 }}
                className="fixed inset-x-3 bottom-28 sm:bottom-36 sm:right-6 sm:left-auto sm:inset-x-auto z-50 w-auto sm:w-96 max-h-[60vh] overflow-y-auto p-4 sm:p-6 rounded-2xl backdrop-blur-xl border border-white/20"
                style={{
                  background:
                    "linear-gradient(135deg, rgba(20,20,30,0.95), rgba(10,10,15,0.9))",
                  boxShadow:
                    "0 15px 40px rgba(0,0,0,0.5), inset 0 0 25px rgba(255,255,255,0.03)",
                }}
              >
                {/* Header */}
                <div className="flex items-center gap-2 mb-3 sm:mb-4">
                  <span className="text-xl sm:text-2xl">🧠</span>
                  <h3 className="text-white font-bold text-base sm:text-lg">Why ZED?</h3>
                </div>

                {/* Content */}
                <div className="space-y-3 sm:space-y-4 text-xs sm:text-sm leading-relaxed">
                  <p className="text-gray-300">
                    <span className="text-[#ff6b6b] font-semibold">AI is killing critical thinking.</span>{" "}
                    Studies show a significant decline in student performance and independent problem-solving 
                    as AI tools become more prevalent in education.
                  </p>
                  
                  <p className="text-gray-400 hidden sm:block">
                    Universities worldwide are reporting decreased marks and a growing inability 
                    among students to think through problems without AI assistance.
                  </p>

                  <div className="h-px bg-white/10"></div>
                  
                  <p className="text-gray-300">
                    <span className="text-[#ff6b6b] font-semibold">ZED is different.</span>{" "}
                    Instead of giving you answers, ZED promotes{" "}
                    <span className="text-white font-medium">critical thinking</span> by:
                  </p>

                  <ul className="space-y-1.5 sm:space-y-2 text-gray-400">
                    <li className="flex items-start gap-2">
                      <span className="text-[#ff6b6b] mt-0.5">→</span>
                      <span>Quizzing you on your actual course material</span>
                    </li>
                    <li className="flex items-start gap-2">
                      <span className="text-[#ff6b6b] mt-0.5">→</span>
                      <span>Guiding you to answers, not handing them over</span>
                    </li>
                    <li className="flex items-start gap-2">
                      <span className="text-[#ff6b6b] mt-0.5">→</span>
                      <span>Building real understanding that sticks</span>
                    </li>
                  </ul>
                </div>

                {/* Footer */}
                <div className="mt-4 sm:mt-5 pt-3 sm:pt-4 border-t border-white/10">
                  <p className="text-gray-500 text-[10px] sm:text-xs text-center">
                    Built for students who want to actually learn.
                  </p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}
      </AnimatePresence>
    </div>
  );
}
