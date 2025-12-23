"""
brain.py - Reasoning Layer for Zed

XRX Architecture Role: PROCESS
- Retrieves context from Knowledge Base (Memory)
- Generates Socratic responses using Groq LLM
- Streams tokens for instant voice output

Socratic State Machine (3 States):
- STATE 1 (GYM): User is wrong/learning → Ask scaffolding questions
- STATE 2 (COOL-DOWN): User is correct → Validate FIRST, then pivot to new challenge
- STATE 3 (CHALLENGE): Push with edge cases → "What if variance is 0?"

Exceptions:
- Confusion ("I don't understand") → Brief explanation, then check understanding
- Fatigue ("I'm done") → Acknowledge and validate gracefully

Usage:
    from app.services.brain import Brain, HANGUP_TOKEN
    
    brain = Brain()
    for token in brain.process("What is a random variable?"):
        if token == HANGUP_TOKEN:
            break
        print(token, end="", flush=True)
"""

import os
import re
import logging
from typing import Generator, Optional
from dataclasses import dataclass, field

from groq import Groq
from dotenv import load_dotenv

from app.services.knowledge import get_knowledge_base

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Model configuration - LOWERED temperature to 0.4 for less rambling
DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
DEFAULT_TEMPERATURE = float(os.environ.get("GROQ_TEMPERATURE", "0.4"))  # Reduced from 0.5
DEFAULT_MAX_TOKENS = int(os.environ.get("GROQ_MAX_TOKENS", "350"))  # Slightly reduced for conciseness

# RAG configuration
RELEVANCE_THRESHOLD = float(os.environ.get("RAG_THRESHOLD", "0.35"))
MAX_CONTEXT_RESULTS = int(os.environ.get("RAG_MAX_RESULTS", "3"))

# Special tokens
HANGUP_TOKEN = "[HANGUP]"

# ============================================================
# TERMINATION PHRASES - STRICT LIST ONLY
# ============================================================
# FIX 2: These are the ONLY phrases that should end the session.
# Do NOT include positive phrases like "correct", "I got it", "thank you" (without 'zed').
# The user must explicitly want to leave.
TERMINATION_PHRASES = [
    # Explicit session-ending phrases
    "thank you zed",
    "thanks zed", 
    "goodbye zed",
    "bye zed",
    "goodbye",
    "i'm done",
    "im done",
    "stop session",
    "end session",
    "quit",
    "exit",
]

# Phrases that should NOT trigger termination (for reference/logging)
# These are commonly confused with termination:
# - "correct" / "that's correct" → User is validating, not leaving
# - "I got it" / "I understand" → User learned, keep pushing
# - "thank you" (without 'zed') → Generic thanks, not a goodbye
# - "that makes sense" → Comprehension signal, pivot to challenge
# - "yes" / "no" → Answers to questions, not session control

# Confusion phrases (user needs brief explanation before continuing)
CONFUSION_PHRASES = [
    "i don't understand", "i dont understand", "what do you mean",
    "huh", "confused", "i'm confused", "im confused", "what?",
    "explain", "can you explain", "i don't get it", "i dont get it",
    "lost", "i'm lost", "help", "clarify", "unclear"
]

logger = logging.getLogger(__name__)


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class Message:
    """A conversation message."""
    role: str  # "user", "assistant", or "system"
    content: str


@dataclass
class ConversationContext:
    """Tracks conversation state."""
    history: list[Message] = field(default_factory=list)
    
    def add_user(self, content: str) -> None:
        """Add a user message."""
        self.history.append(Message(role="user", content=content))
    
    def add_assistant(self, content: str) -> None:
        """Add an assistant message."""
        self.history.append(Message(role="assistant", content=content))
    
    def to_messages(self) -> list[dict]:
        """Convert to Groq message format."""
        return [{"role": m.role, "content": m.content} for m in self.history]
    
    def clear(self) -> None:
        """Clear conversation history."""
        self.history = []
    
    @property
    def last_user_message(self) -> Optional[str]:
        """Get the last user message."""
        for msg in reversed(self.history):
            if msg.role == "user":
                return msg.content
        return None
    
    @property
    def turn_count(self) -> int:
        """Count the number of conversation turns."""
        return len([m for m in self.history if m.role == "user"])


# ============================================================
# BRAIN - THE REASONING ENGINE (SOCRATIC STATE MACHINE)
# ============================================================

class Brain:
    """
    Zed's reasoning engine - High-Performance Socratic Tutor.
    
    Implements a strict 3-State Socratic State Machine:
    
    STATE 1 - GYM PHASE (User is wrong/learning):
        → Ask scaffolding questions
        → Reference specific slides if context present
        → NEVER give the full answer directly
    
    STATE 2 - COOL-DOWN PHASE (User is correct):
        → VALIDATE them first ("Exactly", "Right")
        → Then PIVOT to a new challenge immediately
    
    STATE 3 - CHALLENGE PHASE (Push deeper):
        → Pose edge cases ("What if variance is 0?")
        → Make them prove mastery, not memorization
    
    EXCEPTIONS:
        - Confusion: Brief explanation, then check understanding
        - Fatigue: Acknowledge, validate session, graceful exit
    
    TONE: Concise, Senior Engineer vibe, no fluff.
    """
    
    # ========================================================
    # THE SOCRATIC SYSTEM PROMPT - FULL STATE MACHINE LOGIC
    # ========================================================
    
    SYSTEM_PROMPT_BASE = """You are ZED, a high-performance Socratic tutor.

YOUR CORE MISSION: Build critical thinking and deep understanding. Never create dependency.

=== SOCRATIC STATE MACHINE (3 STATES) ===

STATE 1 — GYM PHASE (User is wrong, guessing, or learning):
- Detect: Incorrect answers, vague responses, "I think...", "Maybe..."
- Action: Ask scaffolding questions that guide them to the answer
- If course material is provided, reference specific slides/pages: "Slide 14 defines X. How does that apply here?"
- NEVER give the full answer directly
- Keep questions focused and build on their partial understanding
- Example: "You said X causes Y. But what happens to Y when X approaches zero?"

STATE 2 — COOL-DOWN PHASE (User got it right):
- Detect: Correct answer, proper reasoning, "So it's because...", demonstrates understanding
- Detect signals: "correct", "I got it", "that makes sense", "oh I see", "right, so..."
- Action: FIRST validate them briefly ("Exactly.", "Right.", "That's it.")
- Then IMMEDIATELY ask a follow-up Challenge Question in the SAME response
- DO NOT say goodbye. DO NOT ask "Do you want to continue?" or "Need help with anything else?"
- DO NOT end the conversation just because they got one answer right
- Just push to the next logical step — keep the momentum going
- Example: "Exactly. Now — what happens when variance equals zero? What does that mean for the distribution?"
- Example: "Right. But here's the edge case: what if your sample size is 1?"
- The conversation only ends when the user explicitly says "goodbye" or "I'm done"

STATE 3 — CHALLENGE PHASE (Push for mastery):
- Detect: User has answered correctly 2+ times or shows solid grasp
- Action: Throw edge cases, tricky variations, or real-world applications
- Make them prove they truly understand, not just memorized
- Examples:
  * "Good. But what if n approaches infinity?"
  * "Correct. Now, can you explain why this fails for heavy-tailed distributions?"
  * "Right. But in production, what happens when your sample is biased?"
- Continue challenging until they explicitly request to stop

=== EXCEPTION HANDLERS ===

EXCEPTION: USER IS CONFUSED ("I don't understand", "Huh?", "What?"):
- Action: Provide a BRIEF, clear explanation (2-3 sentences max)
- Then immediately check their understanding with a simple question
- Example: "The variance measures how spread out values are from the mean. Higher variance = more spread. Quick check: if all values are identical, what's the variance?"

EXCEPTION: USER IS TIRED ("I'm done", "That's enough", "Thanks, bye"):
- Action: Acknowledge respectfully and validate the session
- Keep it brief and encouraging
- Example: "Good session. You nailed the core concepts. Rest up — mastery takes reps."

=== TONE & STYLE ===

- Concise, sharp, academic — like a senior engineer or professor who respects your time
- NO fluff: Never say "I'm glad you asked", "Great question!", "Let me explain..."
- Be direct: Get to the point immediately
- Relentless but fair: Push hard, but acknowledge when they're right
- Brief responses: 1-3 sentences for questions, slightly more for explanations

=== STRICT RULES ===

1. If context is provided below, USE IT to craft specific questions referencing slides, pages, or concepts
2. If no context is provided, use your general knowledge
3. Always prefer questions over answers — make them work
4. The goal is MASTERY through struggle, not instant gratification
5. When they're right, say so clearly THEN pivot to the next challenge
6. Never let them off easy after one correct answer"""

    CONTEXT_INJECTION_TEMPLATE = """

=== RELEVANT COURSE MATERIAL ===
{context}

INSTRUCTION: Reference this material directly in your Socratic questions. Cite specific slides or pages when relevant."""

    NO_CONTEXT_TEMPLATE = """

NOTE: No specific course material retrieved for this query. Use your general knowledge to guide the Socratic dialogue."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS
    ):
        """
        Initialize the Brain.
        
        Args:
            model: Groq model to use
            temperature: Response randomness (0.4 recommended for focused responses)
            max_tokens: Maximum response length
        """
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable required")
        
        self.client = Groq(api_key=api_key)
        self.kb = get_knowledge_base()
        
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        logger.info(f"🧠 Brain initialized | Model: {model} | Temp: {temperature} | Max Tokens: {max_tokens}")
    
    def _retrieve_context(self, query: str) -> str:
        """
        Retrieve relevant context from the knowledge base.
        
        Args:
            query: User's question
        
        Returns:
            Formatted context string or empty string if nothing relevant
        """
        try:
            results = self.kb.search(query, n_results=MAX_CONTEXT_RESULTS)
        except Exception as e:
            logger.warning(f"Knowledge base search failed: {e}")
            return ""
        
        # Filter by relevance threshold
        relevant = [r for r in results if r.get('score', 0) > RELEVANCE_THRESHOLD]
        
        if not relevant:
            logger.debug(f"No relevant context for: {query[:50]}...")
            return ""
        
        # Format context block with clear source attribution
        context_lines = []
        for r in relevant:
            source_info = f"{r.get('source', 'Unknown')}"
            if r.get('page'):
                source_info += f", Page {r['page']}"
            context_lines.append(f"[{source_info}]:\n{r.get('text', '')}")
        
        logger.info(f"📚 RAG: Found {len(relevant)} chunks (scores: {[round(r['score'], 3) for r in relevant]})")
        
        return "\n\n---\n\n".join(context_lines)
    
    def _build_system_prompt(self, context: str) -> str:
        """
        Build the full system prompt with dynamically injected context.
        
        Args:
            context: Retrieved course material (may be empty)
        
        Returns:
            Complete system prompt with context injection
        """
        if context:
            return self.SYSTEM_PROMPT_BASE + self.CONTEXT_INJECTION_TEMPLATE.format(context=context)
        
        return self.SYSTEM_PROMPT_BASE + self.NO_CONTEXT_TEMPLATE
    
    def _is_termination_request(self, text: str) -> bool:
        """
        Check if user wants to end the session.
        
        FIX 2: STRICT termination detection.
        Only triggers on explicit goodbye phrases.
        Does NOT trigger on:
        - "correct", "I got it", "that makes sense" (validation)
        - "thank you" without "zed" (generic thanks)
        - "yes", "no" (answers to questions)
        
        Args:
            text: User's message
        
        Returns:
            True if user explicitly wants to stop
        """
        text_lower = text.lower().strip()
        
        # Remove punctuation for matching
        text_clean = re.sub(r'[^\w\s]', '', text_lower)
        
        # STRICT: Only match exact phrases or very close variations
        for phrase in TERMINATION_PHRASES:
            phrase_clean = re.sub(r'[^\w\s]', '', phrase)
            
            # Exact match
            if text_clean == phrase_clean:
                logger.info(f"🛑 Termination match (exact): '{phrase}'")
                return True
            
            # Phrase at the start (e.g., "goodbye, see you later")
            if text_clean.startswith(phrase_clean + " "):
                logger.info(f"🛑 Termination match (prefix): '{phrase}'")
                return True
            
            # For "thank you zed" / "thanks zed" - must contain both parts
            if "zed" in phrase_clean and phrase_clean in text_clean:
                logger.info(f"🛑 Termination match (contains zed): '{phrase}'")
                return True
        
        # NOT a termination - log for debugging
        logger.debug(f"✅ Not a termination request: '{text_clean[:30]}...'")
        return False
    
    def _is_confusion_signal(self, text: str) -> bool:
        """
        Check if user is expressing confusion.
        
        Args:
            text: User's message
        
        Returns:
            True if user seems confused
        """
        text_lower = text.lower().strip()
        
        for phrase in CONFUSION_PHRASES:
            if phrase in text_lower:
                return True
        
        return False
    
    def process(
        self, 
        user_text: str,
        conversation: Optional[ConversationContext] = None
    ) -> Generator[str, None, None]:
        """
        🎯 MAIN PROCESSING FUNCTION - SOCRATIC STATE MACHINE
        
        Takes user input, handles exceptions, retrieves context, and streams response.
        
        Flow:
        1. Check for TERMINATION signals → Yield closing message + [HANGUP]
        2. Retrieve RAG context
        3. Build system prompt with injected context
        4. Stream LLM response tokens
        
        Args:
            user_text: The user's question/statement
            conversation: Optional conversation context for memory
        
        Yields:
            Response tokens (strings) for immediate TTS
            Special token [HANGUP] if user wants to end session
        
        Example:
            brain = Brain()
            for token in brain.process("What is variance?"):
                if token == HANGUP_TOKEN:
                    print("\\n[Session ended]")
                    break
                print(token, end="", flush=True)
        """
        # =================================================
        # STEP 0: Handle Termination Signals BEFORE LLM call
        # =================================================
        if self._is_termination_request(user_text):
            logger.info("🛑 Termination signal detected")
            yield "Good session. You put in the work — keep that momentum. "
            yield HANGUP_TOKEN
            return
        
        # =================================================
        # STEP 1: Retrieve Context (RAG)
        # =================================================
        context = self._retrieve_context(user_text)
        
        # =================================================
        # STEP 2: Build System Prompt with Dynamic Context
        # =================================================
        system_prompt = self._build_system_prompt(context)
        
        # =================================================
        # STEP 3: Prepare Messages
        # =================================================
        messages = [{"role": "system", "content": system_prompt}]
        
        if conversation:
            # Add conversation history
            messages.extend(conversation.to_messages())
        else:
            # Single turn - just the user message
            messages.append({"role": "user", "content": user_text})
        
        # =================================================
        # STEP 4: Stream from Groq (Temperature 0.4)
        # =================================================
        try:
            logger.debug(f"🚀 Calling Groq | Model: {self.model} | Temp: {self.temperature}")
            
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True
            )
            
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        
        except Exception as e:
            logger.error(f"❌ Groq API error: {e}")
            yield f"[Error: Unable to process. Try again.]"
    
    def think(
        self,
        user_text: str,
        conversation: Optional[ConversationContext] = None
    ) -> str:
        """
        Non-streaming version - returns complete response.
        
        Args:
            user_text: The user's question/statement
            conversation: Optional conversation context
        
        Returns:
            Complete response string
        """
        return "".join(self.process(user_text, conversation))
    
    def chat(
        self,
        user_text: str,
        conversation: ConversationContext
    ) -> Generator[str, None, None]:
        """
        Process with automatic conversation tracking.
        
        Args:
            user_text: The user's message
            conversation: Conversation context (will be updated)
        
        Yields:
            Response tokens
        """
        # Add user message to history
        conversation.add_user(user_text)
        
        # Collect and yield response
        full_response = ""
        for token in self.process(user_text, conversation):
            full_response += token
            yield token
        
        # Add assistant response to history (excluding HANGUP token)
        clean_response = full_response.replace(HANGUP_TOKEN, "").strip()
        if clean_response:
            conversation.add_assistant(clean_response)


# ============================================================
# SINGLETON ACCESSOR
# ============================================================

_brain_instance: Optional[Brain] = None


def get_brain() -> Brain:
    """
    Get the global Brain singleton instance.
    
    Usage:
        from app.services.brain import get_brain, HANGUP_TOKEN
        
        brain = get_brain()
        for token in brain.process("What is entropy?"):
            if token == HANGUP_TOKEN:
                print("User ended session")
                break
            print(token, end="")
    """
    global _brain_instance
    
    if _brain_instance is None:
        _brain_instance = Brain()
    
    return _brain_instance


def is_hangup(token: str) -> bool:
    """Check if a token is the hangup signal."""
    return HANGUP_TOKEN in token


# ============================================================
# CLI - INTERACTIVE TESTING
# ============================================================

if __name__ == "__main__":
    import sys
    from colorama import init, Fore, Style
    
    init()  # Initialize colorama for cross-platform colors
    load_dotenv()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}🧠 ZED BRAIN - Socratic State Machine CLI{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"\n{Fore.YELLOW}Commands:{Style.RESET_ALL}")
    print(f"  • Type your question to start")
    print(f"  • 'reset' or 'clear' → Clear conversation memory")
    print(f"  • 'context [query]' → Test RAG retrieval only")
    print(f"  • 'thank you zed', 'stop', 'i'm done' → End session")
    print(f"  • Ctrl+C → Force quit\n")
    
    try:
        brain = Brain()
        print(f"{Fore.GREEN}✅ Brain initialized successfully{Style.RESET_ALL}\n")
    except Exception as e:
        print(f"{Fore.RED}❌ Failed to initialize Brain: {e}{Style.RESET_ALL}")
        sys.exit(1)
    
    conversation = ConversationContext()
    
    # Single query mode (command line argument)
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"{Fore.YELLOW}Query:{Style.RESET_ALL} {query}\n")
        print(f"{Fore.CYAN}Zed:{Style.RESET_ALL} ", end="")
        
        for token in brain.process(query):
            if token == HANGUP_TOKEN:
                print(f"\n\n{Fore.YELLOW}🔌 [Session terminated]{Style.RESET_ALL}")
                sys.exit(0)
            print(token, end="", flush=True)
        
        print()
        sys.exit(0)
    
    # Interactive mode
    while True:
        try:
            user_input = input(f"\n{Fore.GREEN}You:{Style.RESET_ALL} ").strip()
            
            if not user_input:
                continue
            
            # Command: Reset conversation
            if user_input.lower() in ["reset", "clear"]:
                conversation.clear()
                print(f"{Fore.YELLOW}🧹 Conversation memory cleared.{Style.RESET_ALL}")
                continue
            
            # Command: Test RAG context retrieval
            if user_input.lower().startswith("context "):
                query = user_input[8:].strip()
                if query:
                    print(f"\n{Fore.YELLOW}📚 Retrieving context for: '{query}'{Style.RESET_ALL}\n")
                    context = brain._retrieve_context(query)
                    if context:
                        print(f"{Fore.CYAN}{context}{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.RED}No relevant context found.{Style.RESET_ALL}")
                continue
            
            # Process with Brain
            print(f"{Fore.CYAN}Zed:{Style.RESET_ALL} ", end="")
            should_hangup = False
            
            for token in brain.chat(user_input, conversation):
                if token == HANGUP_TOKEN:
                    should_hangup = True
                    continue  # Don't print the token itself
                print(token, end="", flush=True)
            
            print()  # Newline after response
            
            # Handle hangup after response completes
            if should_hangup:
                print(f"\n{Fore.YELLOW}🔌 [Session ended - User requested termination]{Style.RESET_ALL}")
                print(f"{Fore.CYAN}👋 Keep thinking critically. See you next time.{Style.RESET_ALL}")
                break
        
        except KeyboardInterrupt:
            print(f"\n\n{Fore.YELLOW}👋 Interrupted. Goodbye!{Style.RESET_ALL}")
            break
        except Exception as e:
            print(f"\n{Fore.RED}❌ Error: {e}{Style.RESET_ALL}")
            logger.exception("CLI error")
            continue
