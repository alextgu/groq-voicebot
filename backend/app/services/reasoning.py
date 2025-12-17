import os
from pathlib import Path
from groq import Groq
from dotenv import load_dotenv
from app.services.knowledge import retrieve_context

# Load environment variables
load_dotenv()

# Initialize Groq
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

class Reasoner:
    # ---------------------------------------------------------
    # PART 1: THE PROMPT ENGINEER (Logic & Persona)
    # ---------------------------------------------------------
    
    # This is where you define Zed's personality
    SYSTEM_DIRECTIVE = """
    IDENTIFIED AS: ZED (Encouraging Socratic Tutor).
    OBJECTIVE: Guide the student toward the answer using "Scaffolding." Build their confidence.

    OPERATIONAL PROTOCOLS:
    1. THE 80/20 RULE: The student must do 80 percent of the thinking. Never give the full answer. Provide a "bridge" (a hint or a leading question) that helps them take the next step.
    
    2. WARM & ACCESSIBLE: Use an encouraging, conversational tone. Use phrases like "Great start," "You're on the right track," or "Let's look at this together."
    
    3. HINT SEQUENCING: 
       - Hint 1: Ask a question about a core concept.
       - Hint 2: Provide a simplified analogy.
       - Hint 3: Point to a specific section of the source material.
    
    4. SOURCE GROUNDING (RAG) & TRANSPARENCY: 
       - SUCCESS: If the answer is in the provided slides/syllabus, explicitly cite it: "Looking at the course materials for [Week/Topic], they mention [Concept]. How does that relate to what you just said?"
       - FAILURE: If the information is missing from the provided context, be honest but stay in character: "I've scanned our course materials for [Topic] and couldn't find a specific mention of that. Based on what we *do* know about the basics, what’s your best guess?"
       - REDIRECTION: If they ask something completely out of scope, gently pull them back: "That’s an interesting path, but it's not in our syllabus. Let’s stick to [Current Topic]—what do you think about...?"

    5. CELEBRATE LOGIC: When the student makes progress, acknowledge the specific logic they used. "I like how you connected X to Y. What does that imply for Z?"
    
    6. CONCISE ENCOURAGEMENT: Keep spoken responses to 2-3 sentences. Stay warm but maintain the momentum of the lesson.
    """

    @staticmethod
    def _construct_system_prompt(user_query: str) -> str:
        """
        Internal helper: Builds the prompt by fetching slides (RAG).
        """
        # 1. Search the Database (The Librarian)
        # We ask for 3 chunks of context
        results = retrieve_context(user_query, n_results=3)
        
        # 2. Check if we found anything good
        # If the score is low (< 0.35), we assume the user is asking 
        # something not in the slides (e.g., "What's the weather?")
        is_relevant = results and results[0]['score'] > 0.35
        
        context_block = ""
        
        if is_relevant:
            # We found slides! Inject them.
            context_block = "\n=== RELEVANT COURSE MATERIAL ===\n"
            for r in results:
                if r['score'] > 0.3:
                    context_block += f"Source: {r['source']} (Page {r['page']})\n"
                    context_block += f"Content: {r['text']}\n---\n"
            context_block += "INSTRUCTION: Challenge the user based on the slides above."
            
        else:
            # We found nothing. Tell Zed to admit it.
            # Get list of loaded courses to be specific
            download_dir = Path(__file__).parent.parent.parent / "data" / "downloads"
            courses = [d.name for d in download_dir.iterdir()] if download_dir.exists() else []
            course_list = ", ".join(courses[:3]) or "your database"
            
            context_block = (
                f"\n=== SYSTEM NOTE ===\n"
                f"You searched {course_list} and found NO MATCHES for this query.\n"
                f"INSTRUCTION: Tell the user you didn't find that in the syllabus, "
                f"then answer using general knowledge."
            )

        # 3. Combine Persona + Context
        return f"{Reasoner.SYSTEM_DIRECTIVE}\n\n{context_block}"

    # ---------------------------------------------------------
    # PART 2: THE ENGINE (Inference)
    # ---------------------------------------------------------

    @staticmethod
    def generate_response(user_input: str):
        """
        The Main Public Function.
        Takes text input -> Yields text tokens.
        """
        # A. Build the Prompt (Calls Part 1)
        full_system_prompt = Reasoner._construct_system_prompt(user_input)
        
        # B. Call Groq
        try:
            stream = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": full_system_prompt},
                    {"role": "user", "content": user_input}
                ],
                temperature=0.6,
                max_tokens=300,
                stream=True
            )
            
            # C. Stream Response
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
                    
        except Exception as e:
            yield f"[Zed Connection Error: {str(e)}]"

# ---------------------------------------------------------
# PART 3: THE TESTER (Runs only in terminal)
# ---------------------------------------------------------
if __name__ == "__main__":
    print("🤖 Zed Reasoning Engine (Terminal Mode)")
    while True:
        q = input("\nYou: ")
        if q == "exit": break
        
        print("Zed: ", end="")
        for token in Reasoner.generate_response(q):
            print(token, end="", flush=True)
        print()