#!/usr/bin/env python3
"""
main.py - Central Orchestrator for Zed Voice Agent

XRX Architecture Pipeline:
    👂 Ear (INPUT)  →  🧠 Brain (PROCESS)  →  👄 Mouth (OUTPUT)

Usage:
    python -m app.main
    
Environment Variables Required:
    GROQ_API_KEY      - For Whisper STT and LLM
    ELEVEN_API_KEY    - For ElevenLabs TTS
"""

import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# ============================================================
# LOGGING SETUP (Before any imports that might log)
# ============================================================

def setup_logging() -> logging.Logger:
    """Configure logging with timestamps for debugging."""
    log_format = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Reduce noise from libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    
    return logging.getLogger("zed.main")


logger = setup_logging()


# ============================================================
# COLORAMA SETUP (For colored terminal output)
# ============================================================

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    HAS_COLORAMA = True
except ImportError:
    HAS_COLORAMA = False
    # Fallback: empty color codes
    class Fore:
        RED = GREEN = YELLOW = CYAN = MAGENTA = WHITE = ""
    class Style:
        BRIGHT = RESET_ALL = ""


def print_error(msg: str) -> None:
    """Print error message in red."""
    print(f"{Fore.RED}{Style.BRIGHT}❌ ERROR: {msg}{Style.RESET_ALL}")


def print_success(msg: str) -> None:
    """Print success message in green."""
    print(f"{Fore.GREEN}{Style.BRIGHT}✅ {msg}{Style.RESET_ALL}")


def print_warning(msg: str) -> None:
    """Print warning message in yellow."""
    print(f"{Fore.YELLOW}⚠️  {msg}{Style.RESET_ALL}")


def print_info(msg: str) -> None:
    """Print info message in cyan."""
    print(f"{Fore.CYAN}ℹ️  {msg}{Style.RESET_ALL}")


# ============================================================
# ENVIRONMENT VALIDATION
# ============================================================

def validate_environment() -> bool:
    """
    Validate that all required environment variables are set.
    
    Returns:
        True if all required vars are present, False otherwise.
    """
    from dotenv import load_dotenv
    load_dotenv()
    
    required_vars = {
        "GROQ_API_KEY": "Groq API (Whisper STT + LLM)",
        "ELEVEN_API_KEY": "ElevenLabs TTS",
    }
    
    optional_vars = {
        "CANVAS_API_KEY": "Canvas LMS integration",
        "PORCUPINE_ACCESS_KEY": "Wake word detection",
    }
    
    missing = []
    
    for var, description in required_vars.items():
        if not os.environ.get(var):
            missing.append(f"  • {var} ({description})")
    
    if missing:
        print_error("Missing required environment variables:")
        for m in missing:
            print(f"{Fore.RED}{m}")
        print(f"\n{Fore.YELLOW}Please add them to your .env file.")
        return False
    
    # Check optional vars and warn
    for var, description in optional_vars.items():
        if not os.environ.get(var):
            print_warning(f"Optional: {var} not set ({description})")
    
    return True


# ============================================================
# MODULE INITIALIZATION
# ============================================================

def initialize_modules():
    """
    Safely import and initialize Ear, Brain, and Mouth.
    
    Returns:
        Tuple of (ear, brain, mouth, conversation) or raises SystemExit
    """
    print_info("Initializing Zed modules...")
    
    # Import modules (may fail if dependencies missing)
    try:
        from app.services.ears import Ear
        from app.services.brain import Brain, ConversationContext, HANGUP_TOKEN, is_hangup
        from app.services.mouth import Mouth
    except ImportError as e:
        print_error(f"Failed to import modules: {e}")
        print(f"{Fore.YELLOW}Run: pip install -r requirements.txt")
        sys.exit(1)
    
    # Initialize Ear (Whisper STT)
    try:
        logger.info("Initializing Ear (Speech-to-Text)...")
        ear = Ear()
        print_success("Ear initialized (Groq Whisper)")
    except Exception as e:
        print_error(f"Failed to initialize Ear: {e}")
        sys.exit(1)
    
    # Initialize Brain (LLM + RAG)
    try:
        logger.info("Initializing Brain (LLM + RAG)...")
        brain = Brain()
        print_success("Brain initialized (Groq LLM + ChromaDB)")
    except Exception as e:
        print_error(f"Failed to initialize Brain: {e}")
        sys.exit(1)
    
    # Initialize Mouth (TTS)
    try:
        logger.info("Initializing Mouth (Text-to-Speech)...")
        mouth = Mouth()
        print_success("Mouth initialized (ElevenLabs TTS)")
    except Exception as e:
        print_error(f"Failed to initialize Mouth: {e}")
        sys.exit(1)
    
    # Create conversation context for memory
    conversation = ConversationContext()
    
    return ear, brain, mouth, conversation, HANGUP_TOKEN, is_hangup


# ============================================================
# MAIN EVENT LOOP
# ============================================================

def run_event_loop(ear, brain, mouth, conversation, HANGUP_TOKEN, is_hangup):
    """
    Main event loop: Listen → Think → Speak
    
    Pipeline:
        1. Ear listens for user speech
        2. Brain processes and streams response
        3. Mouth speaks the response
        4. Check for hangup signal
    """
    print("\n" + "=" * 60)
    print(f"{Fore.MAGENTA}{Style.BRIGHT}🎙️  ZED VOICE AGENT - READY{Style.RESET_ALL}")
    print("=" * 60)
    print(f"{Fore.WHITE}Speak to interact. Say 'stop' or 'I'm done' to end.")
    print(f"Press Ctrl+C to quit.\n")
    
    session_start = datetime.now()
    turn_count = 0
    
    while True:
        try:
            # ─────────────────────────────────────────────────────
            # STEP 1: LISTEN (Ear)
            # ─────────────────────────────────────────────────────
            logger.info("Waiting for user input...")
            user_input = ear.listen()
            
            # Skip if nothing detected
            if not user_input or not user_input.strip():
                logger.debug("No speech detected, continuing...")
                continue
            
            turn_count += 1
            logger.info(f"Turn {turn_count}: '{user_input[:50]}...'")
            
            # ─────────────────────────────────────────────────────
            # STEP 2: THINK (Brain) - Streaming
            # ─────────────────────────────────────────────────────
            logger.info("Processing with Brain...")
            
            # Add user message to conversation history
            conversation.add_user(user_input)
            
            # Collect streamed response
            full_response = ""
            should_hangup = False
            
            print(f"\n{Fore.CYAN}🧠 Zed: {Style.RESET_ALL}", end="", flush=True)
            
            for token in brain.process(user_input, conversation):
                if is_hangup(token):
                    should_hangup = True
                    continue
                
                # Print token to console
                print(token, end="", flush=True)
                full_response += token
            
            print()  # Newline after response
            
            # Add assistant response to history
            if full_response:
                conversation.add_assistant(full_response)
            
            # ─────────────────────────────────────────────────────
            # STEP 3: SPEAK (Mouth)
            # ─────────────────────────────────────────────────────
            if full_response:
                logger.info("Speaking response...")
                mouth.speak(full_response)
            
            # ─────────────────────────────────────────────────────
            # STEP 4: CHECK FOR HANGUP
            # ─────────────────────────────────────────────────────
            if should_hangup:
                logger.info("Hangup signal received")
                print(f"\n{Fore.YELLOW}🔌 Session ended by user request.{Style.RESET_ALL}")
                break
        
        except KeyboardInterrupt:
            # User pressed Ctrl+C
            raise
        
        except Exception as e:
            # Log error but try to continue
            logger.exception(f"Error in event loop: {e}")
            print_error(f"Something went wrong: {e}")
            print_info("Attempting to continue...")
            time.sleep(1)  # Brief pause before retrying
            continue
    
    # Session summary
    session_duration = datetime.now() - session_start
    print(f"\n{Fore.GREEN}📊 Session Stats:")
    print(f"   Duration: {session_duration}")
    print(f"   Turns: {turn_count}")


# ============================================================
# CLEANUP
# ============================================================

def cleanup(ear=None, brain=None, mouth=None):
    """
    Clean up resources on exit.
    
    Args:
        ear: Ear instance (has PyAudio to terminate)
        brain: Brain instance
        mouth: Mouth instance (has PyAudio to terminate)
    """
    logger.info("Cleaning up resources...")
    
    try:
        if ear and hasattr(ear, 'p'):
            ear.p.terminate()
            logger.debug("Ear PyAudio terminated")
    except Exception as e:
        logger.warning(f"Error cleaning up Ear: {e}")
    
    try:
        if mouth and hasattr(mouth, '_audio') and mouth._audio:
            mouth._audio.terminate()
            logger.debug("Mouth PyAudio terminated")
    except Exception as e:
        logger.warning(f"Error cleaning up Mouth: {e}")
    
    print_success("Cleanup complete")


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def main():
    """Main entry point for Zed voice agent."""
    ear = brain = mouth = conversation = None
    
    print(f"\n{Fore.MAGENTA}{Style.BRIGHT}")
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║                                                           ║")
    print("║     ███████╗███████╗██████╗                               ║")
    print("║     ╚══███╔╝██╔════╝██╔══██╗                              ║")
    print("║       ███╔╝ █████╗  ██║  ██║                              ║")
    print("║      ███╔╝  ██╔══╝  ██║  ██║                              ║")
    print("║     ███████╗███████╗██████╔╝                              ║")
    print("║     ╚══════╝╚══════╝╚═════╝                               ║")
    print("║                                                           ║")
    print("║     Your Socratic Study Coach                             ║")
    print("║     Powered by Groq + ElevenLabs                          ║")
    print("║                                                           ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print(f"{Style.RESET_ALL}")
    
    try:
        # Phase 1: Validate environment
        if not validate_environment():
            sys.exit(1)
        
        # Phase 2: Initialize modules
        ear, brain, mouth, conversation, HANGUP_TOKEN, is_hangup = initialize_modules()
        
        # Phase 3: Run event loop
        run_event_loop(ear, brain, mouth, conversation, HANGUP_TOKEN, is_hangup)
    
    except KeyboardInterrupt:
        print(f"\n\n{Fore.YELLOW}👋 Goodbye! Keep thinking critically.{Style.RESET_ALL}")
    
    except SystemExit:
        raise
    
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        print_error(f"Fatal error: {e}")
        sys.exit(1)
    
    finally:
        # Phase 4: Cleanup
        cleanup(ear, brain, mouth)


# ============================================================
# SCRIPT ENTRY
# ============================================================

if __name__ == "__main__":
    main()

