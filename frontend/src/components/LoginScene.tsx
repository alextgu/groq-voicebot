import { useState } from "react";

interface LoginSceneProps {
  onLoginSuccess: () => void;
}

export default function LoginScene({ onLoginSuccess }: LoginSceneProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    
    // Simulate login - replace with actual auth later
    await new Promise((resolve) => setTimeout(resolve, 1200));
    
    setIsLoading(false);
    onLoginSuccess();
  };

  return (
    <div className="h-full w-full flex items-center justify-center font-sans px-4">
      <div
        className="relative z-10 w-full max-w-md p-6 sm:p-10 rounded-2xl sm:rounded-3xl border border-white/20 backdrop-blur-2xl"
        style={{
          background:
            "linear-gradient(135deg, rgba(30,30,45,0.85), rgba(20,20,35,0.75))",
          boxShadow:
            "0 15px 45px rgba(0,0,0,0.45), inset 0 0 25px rgba(255,255,255,0.05)",
        }}
      >
        {/* Logo */}
        <div className="text-center mb-6 sm:mb-8">
          <h1 className="text-4xl sm:text-5xl font-extrabold tracking-wider">
            <span className="text-[#ff6b6b]">ZED</span>
            <span className="text-white/90">.AI</span>
          </h1>
          <p className="text-gray-400 mt-2 text-sm sm:text-base">Sign in to continue</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 sm:space-y-5">
          <div>
            <label className="block text-sm text-gray-300 mb-1.5 sm:mb-2">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@university.edu"
              className="w-full px-4 sm:px-5 py-2.5 sm:py-3 bg-white/10 border border-white/20 rounded-xl text-white text-sm sm:text-base placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-[#ff6b6b]/50 backdrop-blur-lg transition"
              required
            />
          </div>

          <div>
            <label className="block text-sm text-gray-300 mb-1.5 sm:mb-2">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full px-4 sm:px-5 py-2.5 sm:py-3 bg-white/10 border border-white/20 rounded-xl text-white text-sm sm:text-base placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-[#ff6b6b]/50 backdrop-blur-lg transition"
              required
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-2.5 sm:py-3 mt-2 sm:mt-4 bg-gradient-to-r from-[#ff6b6b] to-[#ff9a9e] rounded-xl font-semibold text-white text-sm sm:text-base hover:scale-[1.02] active:scale-[0.98] transition-transform disabled:opacity-70 disabled:cursor-not-allowed"
          >
            {isLoading ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="animate-spin h-4 w-4 sm:h-5 sm:w-5" viewBox="0 0 24 24">
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                    fill="none"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                Signing in...
              </span>
            ) : (
              "Sign In"
            )}
          </button>
        </form>

        <div className="mt-4 sm:mt-6 text-center">
          <p className="text-gray-500 text-xs sm:text-sm">
            Don't have an account?{" "}
            <button className="text-[#ff6b6b] hover:underline">Sign up</button>
          </p>
        </div>

        {/* Divider */}
        <div className="flex items-center gap-4 my-4 sm:my-6">
          <div className="flex-1 h-px bg-white/10"></div>
          <span className="text-gray-500 text-xs sm:text-sm">or</span>
          <div className="flex-1 h-px bg-white/10"></div>
        </div>

        {/* Canvas/Quercus Login */}
        <button
          onClick={onLoginSuccess}
          className="w-full py-2.5 sm:py-3 bg-white/10 border border-white/20 rounded-xl text-white text-sm sm:text-base font-medium hover:bg-white/20 active:scale-[0.98] transition-all backdrop-blur-md flex items-center justify-center gap-2 sm:gap-3"
        >
          <svg className="w-4 h-4 sm:w-5 sm:h-5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
          </svg>
          Continue with Canvas
        </button>
      </div>
    </div>
  );
}

