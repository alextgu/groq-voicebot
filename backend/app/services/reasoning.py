import os
from pathlib import Path
from groq import Groq
from dotenv import load_dotenv
from app.services.knowledge import retrieve_context

# 1. FIX THE WARNING LOGS
os.environ["TOKENIZERS_PARALLELISM"] = "false"

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# DEBUG FLAG
VERBOSE_DEBUG = True 

class Reasoner:
    # PART 1: THE PERSONA
    SYSTEM_DIRECTIVE = SYSTEM_DIRECTIVE = """
    You are ZED. You are a Socratic "Gym Coach" for the mind.
    
    CORE BEHAVIORS:
    1. THE GYM PHASE (User is confused/learning):
       - ANSWER WITH QUESTIONS. If the user is struggling, scaffold the next step.
       - NEVER explain the full answer. Make them work for it.
       - "Slide 14 mentions X. How does that fit here?"

    2. THE COOL-DOWN PHASE (User understands/agrees):
       - DETECT CLOSURE. If the user says "Oh I get it", "Thanks", or "Makes sense", DO NOT ASK A QUESTION.
       - VERIFY & DISMISS. Confirm their logic briefly, then end the turn.
       - Example: "Exactly. You connect the variable to the constant. Good work." (Stop there).

    3. TONE:
       - Brief, sharp, academic.
       - No fluff ("I'm glad you asked").
       - If they get it right, acknowledge it and shut up.

    INTERACTION FLOW:
    User: "Is it X?"
    Zed: "Why would it be X?" (Gym Phase)
    User: "Because Y?"
    Zed: "Correct. Good." (Cool-down Phase - NO NEW QUESTION)
    """

    @staticmethod
    def _construct_system_prompt(latest_query: str) -> str:
        """
        Builds the prompt using RAG based ONLY on the user's latest message.
        """
        results = retrieve_context(latest_query, n_results=3)
        
        # --- DEBUG PRINT ---
        if VERBOSE_DEBUG:
            print(f"\n[🔍 DEBUG] Analysis Query: '{latest_query}'")
            if results and results[0]['score'] > 0.35:
                print(f"[✅ DEBUG] Found relevant slide: {results[0]['source']} (Score: {results[0]['score']:.2f})")
            else:
                print(f"[❌ DEBUG] No relevant slides found.")
        # -------------------

        is_relevant = results and results[0]['score'] > 0.35
        context_block = ""
        
        if is_relevant:
            context_block = "\n=== RELEVANT COURSE MATERIAL ===\n"
            for r in results:
                if r['score'] > 0.3:
                    context_block += f"Source: {r['source']}\nContent: {r['text']}\n---\n"
            context_block += "INSTRUCTION: Challenge the user based on these slides."
        else:
            context_block = "\n=== SYSTEM NOTE ===\nNo specific course slides found for this topic. Rely on general knowledge."

        return f"{Reasoner.SYSTEM_DIRECTIVE}\n\n{context_block}"

    # PART 2: THE ENGINE (With Memory)
    @staticmethod
    def generate_response(conversation_history: list):
        """
        Takes a LIST of messages: 
        [
          {"role": "user", "content": "Hi"}, 
          {"role": "assistant", "content": "Hello"}, 
          {"role": "user", "content": "Help me"}
        ]
        """
        # 1. Get the very last thing the user said (for RAG search)
        # We don't want to search the database for "Hello", only the real question.
        latest_user_input = conversation_history[-1]['content']

        # 2. Build the System Prompt (Persona + New Context)
        system_prompt = Reasoner._construct_system_prompt(latest_user_input)
        
        # 3. Combine: [System Prompt] + [Conversation History]
        # This gives Groq the "Personality" AND the "Memory"
        messages_to_send = [
            {"role": "system", "content": system_prompt}
        ] + conversation_history
        
        try:
            stream = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages_to_send,
                temperature=0.6,
                max_tokens=300,
                stream=True
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
                    
        except Exception as e:
            yield f"[Error: {str(e)}]"

# PART 3: THE TERMINAL TESTER (Now with Memory Loop)
if __name__ == "__main__":
    print("🤖 Zed Memory Test (Type 'reset' to clear memory)")
    
    # Initialize Memory
    history = []
    
    while True:
        user_text = input("\nYou: ")
        
        # RESET COMMAND
        if user_text.lower() in ["reset", "clear"]:
            history = []
            print("🧹 Memory wiped.")
            continue
            
        if user_text.lower() in ["exit", "quit"]:
            break
        
        # 1. Add User to History
        history.append({"role": "user", "content": user_text})
        
        print("Zed: ", end="")
        full_response = ""
        
        # 2. Call Generator with FULL History
        for token in Reasoner.generate_response(history):
            print(token, end="", flush=True)
            full_response += token
            
        # 3. Add Zed's Response to History (So he remembers what he said)
        history.append({"role": "assistant", "content": full_response})
        print()