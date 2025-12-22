"""
brain.py - Reasoning Layer for Zed

XRX Architecture Role: PROCESS
- Retrieves context from Knowledge Base (Memory)
- Generates Socratic responses using Groq LLM
- Streams tokens for instant voice output

Usage:
    from app.services.brain import Brain
    
    brain = Brain()
    for token in brain.process("What is a random variable?"):
        print(token, end="", flush=True)
"""

import os
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

# Model configuration
DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
DEFAULT_TEMPERATURE = float(os.environ.get("GROQ_TEMPERATURE", "0.5"))
DEFAULT_MAX_TOKENS = int(os.environ.get("GROQ_MAX_TOKENS", "400"))

# RAG configuration
RELEVANCE_THRESHOLD = float(os.environ.get("RAG_THRESHOLD", "0.35"))
MAX_CONTEXT_RESULTS = int(os.environ.get("RAG_MAX_RESULTS", "3"))

# Special tokens
HANGUP_TOKEN = "[HANGUP]"

# Termination phrases (user wants to end the session)
TERMINATION_PHRASES = [
    "no", "stop", "i'm done", "im done", "that's enough", "thats enough",
    "enough", "bye", "goodbye", "end", "quit", "exit", "i give up",
    "no more", "stop it", "leave me alone", "shut up"
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


# ============================================================
# BRAIN - THE REASONING ENGINE
# ============================================================

class Brain:
    """
    Zed's reasoning engine.
    
    Follows XRX Architecture:
    1. INPUT: User text (from Ears)
    2. PROCESS: RAG retrieval + LLM reasoning
    3. OUTPUT: Streamed tokens (to Mouth)
    
    Socratic Method (3 Phases):
    - GYM PHASE: Challenge with questions
    - COOL-DOWN PHASE: Validate understanding
    - CHALLENGE PHASE: Push with edge cases (The Bonus Round!)
    
    Termination:
    - If user says "No", "Stop", "I'm done" → yields [HANGUP] token
    """
    
    # The Socratic System Prompt with 3 Phases
    SYSTEM_PROMPT = """You are ZED, a Socratic study coach.

YOUR MISSION: Build critical thinking, not dependency.

PHASE DETECTION (3 PHASES):

1. GYM PHASE (User is learning/confused):
   - Ask guiding questions
   - Reference specific slides/materials
   - NEVER give the full answer
   - Example: "Slide 14 mentions X. How does that connect to your question?"

2. COOL-DOWN PHASE (User understands the basics):
   - Detect closure signals: "Oh I get it", "Thanks", "Makes sense"
   - Briefly confirm their logic
   - BUT DON'T END HERE - transition to Challenge Phase
   - Example: "Exactly. You connected X to Y correctly."

3. CHALLENGE PHASE - THE BONUS ROUND (User got it right):
   - After validating, IMMEDIATELY pose an edge case or tricky variation
   - Push them further - "But what if...?", "Can you handle this edge case?"
   - Make them prove they REALLY understand, not just memorized
   - Examples:
     * "Good. But what happens if the variance is zero?"
     * "Correct. Now, what if the sample size approaches infinity?"
     * "Right. But can you explain why this breaks for non-normal distributions?"
   - Keep challenging until they say they're done

TERMINATION SIGNALS:
- If user says "No", "Stop", "I'm done", "That's enough", "Quit" → END the session
- Respond with a brief farewell: "Alright, good session. Keep thinking critically."

TONE:
- Brief, sharp, academic
- No fluff ("I'm glad you asked...")
- Relentless but fair - like a good coach

RULES:
- If context is provided, USE IT to guide questions
- If no context, rely on general knowledge
- Never let them off easy - always push for deeper understanding
- The goal is MASTERY, not just "getting it right once\""""

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
            temperature: Response randomness (0-1)
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
        
        logger.info(f"Brain initialized with model: {model}")
    
    def _retrieve_context(self, query: str) -> str:
        """
        Retrieve relevant context from the knowledge base.
        
        Args:
            query: User's question
        
        Returns:
            Formatted context string or empty string if nothing relevant
        """
        results = self.kb.search(query, n_results=MAX_CONTEXT_RESULTS)
        
        # Filter by relevance threshold
        relevant = [r for r in results if r['score'] > RELEVANCE_THRESHOLD]
        
        if not relevant:
            logger.debug(f"No relevant context for: {query[:50]}...")
            return ""
        
        # Format context block
        context_lines = []
        for r in relevant:
            source_info = f"{r['source']}"
            if r.get('page'):
                source_info += f", Page {r['page']}"
            context_lines.append(f"[{source_info}]: {r['text']}")
        
        logger.info(f"Found {len(relevant)} relevant chunks (scores: {[r['score'] for r in relevant]})")
        
        return "\n\n".join(context_lines)
    
    def _build_system_prompt(self, context: str) -> str:
        """
        Build the full system prompt with optional context.
        
        Args:
            context: Retrieved course material (may be empty)
        
        Returns:
            Complete system prompt
        """
        if context:
            return f"""{self.SYSTEM_PROMPT}

=== RELEVANT COURSE MATERIAL ===
{context}

INSTRUCTION: Use this material to guide your Socratic questions."""
        
        return f"""{self.SYSTEM_PROMPT}

NOTE: No specific course material found. Use general knowledge."""
    
    def _is_termination_request(self, text: str) -> bool:
        """
        Check if user wants to end the session.
        
        Args:
            text: User's message
        
        Returns:
            True if user wants to stop
        """
        text_lower = text.lower().strip()
        
        # Check exact matches and partial matches
        for phrase in TERMINATION_PHRASES:
            if text_lower == phrase or text_lower.startswith(phrase + " "):
                return True
        
        return False
    
    def process(
        self, 
        user_text: str,
        conversation: Optional[ConversationContext] = None
    ) -> Generator[str, None, None]:
        """
        🎯 MAIN PROCESSING FUNCTION
        
        Takes user input, retrieves context, and streams response.
        
        Args:
            user_text: The user's question/statement
            conversation: Optional conversation context for memory
        
        Yields:
            Response tokens (strings) for immediate TTS
            Special token [HANGUP] if user wants to end session
        
        Example:
            brain = Brain()
            for token in brain.process("What is variance?"):
                if token == "[HANGUP]":
                    print("Session ended by user")
                    break
                print(token, end="", flush=True)
        """
        # 0. Check for termination request
        if self._is_termination_request(user_text):
            logger.info("Termination request detected")
            yield "Alright, good session. Keep thinking critically. "
            yield HANGUP_TOKEN
            return
        
        # 1. Retrieve Context (RAG)
        context = self._retrieve_context(user_text)
        
        # 2. Build System Prompt
        system_prompt = self._build_system_prompt(context)
        
        # 3. Prepare Messages
        messages = [{"role": "system", "content": system_prompt}]
        
        if conversation:
            # Add conversation history
            messages.extend(conversation.to_messages())
        else:
            # Single turn - just the user message
            messages.append({"role": "user", "content": user_text})
        
        # 4. Stream from Groq
        try:
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
            logger.error(f"Groq API error: {e}")
            yield f"[Error: {str(e)}]"
    
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
        
        # Add assistant response to history
        conversation.add_assistant(full_response)


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
    return token == HANGUP_TOKEN


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys
    
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("🧠 ZED BRAIN - CLI (with Bonus Round!)")
    print("=" * 60)
    print("Commands: 'reset' to clear memory")
    print("Say 'no', 'stop', or 'I'm done' to end the session\n")
    
    brain = Brain()
    conversation = ConversationContext()
    
    # Single query mode
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"Query: {query}\n")
        print("Zed: ", end="")
        for token in brain.process(query):
            if token == HANGUP_TOKEN:
                print("\n\n🔌 [Session terminated by user]")
                sys.exit(0)
            print(token, end="", flush=True)
        print()
        sys.exit(0)
    
    # Interactive mode
    while True:
        try:
            user_input = input("\nYou: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ["reset", "clear"]:
                conversation.clear()
                print("🧹 Memory cleared.")
                continue
            
            print("Zed: ", end="")
            should_hangup = False
            
            for token in brain.chat(user_input, conversation):
                if token == HANGUP_TOKEN:
                    should_hangup = True
                    continue  # Don't print the token itself
                print(token, end="", flush=True)
            
            print()
            
            # Handle hangup after response completes
            if should_hangup:
                print("\n🔌 [Session ended - User requested termination]")
                print("👋 Goodbye! Keep thinking critically.")
                break
        
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break

