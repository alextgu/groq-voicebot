from canvasapi import Canvas

CANVAS_API_URL = "https://q.utoronto.ca"

class CanvasSync:
    def __init__(self, user_api_key: str):
        """
        Initialize with the User's specific token.
        """
        if not user_api_key:
            raise ValueError("Canvas API Token is required.")
            
        self.canvas = Canvas(CANVAS_API_URL, user_api_key)

    def get_course_context(self):
        """
        Scans active courses and returns a formatted string of 
        syllabus text and recent announcements.
        """
        try:
            print(f"🔄 Connecting to Quercus ({CANVAS_API_URL})...")
            user = self.canvas.get_current_user()
            
            # Get courses where the user is an active student
            courses = user.get_courses(enrollment_state='active')
            
            combined_text = ""
            course_count = 0

            for course in courses:
                try:
                    # Filter out weird empty course shells without names
                    if not hasattr(course, 'name'):
                        continue

                    # optional: skip "sandbox" or "test" courses
                    if "sandbox" in course.name.lower():
                        continue

                    print(f"   Found active course: {course.name}")
                    
                    # 1. Capture Syllabus (HTML body or text)
                    syllabus = getattr(course, 'syllabus_body', '') or ""
                    
                    # 2. Capture Recent Announcements (Limit 2)
                    announcements = course.get_discussion_topics(only_announcements=True, limit=2)
                    ann_text = ""
                    for ann in announcements:
                        # Clean up title/message to be concise
                        ann_text += f" - UPDATE: {ann.title} (Posted: {ann.posted_at[:10]})\n"

                    # 3. Combine into a clean block for the AI
                    if syllabus or ann_text:
                        course_count += 1
                        combined_text += f"""
                        === COURSE: {course.name} ===
                        SYLLABUS EXCERPT:
                        {syllabus[:1500]}  # Truncated to prevent context overflow

                        RECENT ANNOUNCEMENTS:
                        {ann_text if ann_text else "No recent updates."}
                        ================================
                        \n"""

                except Exception as e:
                    print(f"   ⚠️ Could not sync course {course.id}: {e}")

            if not combined_text:
                return "No syllabus text found. Ensure your professors use the 'Syllabus' tab in Quercus."
            
            return combined_text

        except Exception as e:
            return f"Canvas Connection Error: {str(e)}"

if __name__ == "__main__":
    # MANUAL TEST MODE
    # This block only runs if you type `python -m app.services.canvas_sync`
    # It allows you to test easily without the frontend.
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Grab key from env for testing, or ask user to paste it
    test_key = os.environ.get("CANVAS_API_KEY")
    if not test_key:
        test_key = input("Paste your Canvas Token for testing: ")
    
    try:
        syncer = CanvasSync(test_key)
        data = syncer.get_course_context()
        print("\n--- SYNC RESULT ---")
        print(data[:500] + "\n... (more data truncated)")
    except Exception as e:
        print(f"Test Failed: {e}")