import os
import re
import requests
from pathlib import Path
from canvasapi import Canvas
from canvasapi.exceptions import Forbidden, ResourceDoesNotExist

CANVAS_API_URL = "https://q.utoronto.ca"
DEFAULT_DOWNLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "downloads"

def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip().strip('.')
    name = re.sub(r'[_\s]+', '_', name)
    return name[:100]

class CanvasSync:
    def __init__(self, user_api_key: str):
        if not user_api_key:
            raise ValueError("Canvas API Token is required.")
        self.canvas = Canvas(CANVAS_API_URL, user_api_key)

    def _get_pdfs_from_modules(self, course, existing_file_ids: set = None) -> list:
        """
        Scan course Modules for PDF files.
        
        Args:
            course: Canvas course object
            existing_file_ids: Set of file IDs already found (to avoid duplicates)
        
        Returns:
            List of file objects found in modules
        """
        if existing_file_ids is None:
            existing_file_ids = set()
            
        found_files = []
        try:
            modules = course.get_modules()
            module_count = 0
            
            for module in modules:
                module_count += 1
                try:
                    items = module.get_module_items()
                    for item in items:
                        # Check for File type items
                        if item.type == 'File':
                            try:
                                # Skip if we already have this file from the Files tab
                                if item.content_id in existing_file_ids:
                                    continue
                                    
                                # Fetch the actual file object using its ID
                                f = course.get_file(item.content_id)
                                if f.filename.lower().endswith('.pdf'):
                                    found_files.append(f)
                                    existing_file_ids.add(item.content_id)
                            except (Forbidden, ResourceDoesNotExist):
                                continue
                        
                        # Also check for ExternalUrl items that might be direct PDF links
                        elif item.type == 'ExternalUrl':
                            url = getattr(item, 'external_url', '')
                            if url.lower().endswith('.pdf'):
                                # Store as a dict with URL info for special handling
                                found_files.append({
                                    'type': 'external_url',
                                    'url': url,
                                    'title': getattr(item, 'title', 'external.pdf')
                                })
                                
                except Exception as e:
                    # Some modules might have restricted access
                    continue
            
            if found_files:
                print(f"      📦 Found {len(found_files)} PDFs in {module_count} modules")
                            
        except Forbidden:
            print(f"      🔒 Modules tab restricted")
        except Exception as e:
            print(f"      ⚠️ Module scan error: {e}")
            
        return found_files

    def download_course_pdfs(self, download_dir: str = None, course_filter: list[str] = None) -> list[str]:
        download_dir = Path(download_dir or DEFAULT_DOWNLOAD_DIR)
        download_dir.mkdir(parents=True, exist_ok=True)
        downloaded_paths = []
        
        print(f"📥 Scanning Canvas for PDFs...")
        user = self.canvas.get_current_user()
        courses = user.get_courses(enrollment_state='active')
        
        for course in courses:
            try:
                if not hasattr(course, 'name') or "sandbox" in course.name.lower():
                    continue
                
                if course_filter and not any(f.lower() in course.name.lower() for f in course_filter):
                    continue
                
                # Setup folder
                safe_course_name = sanitize_filename(course.name)
                course_dir = download_dir / safe_course_name
                course_dir.mkdir(parents=True, exist_ok=True)
                
                print(f"\n📂 {course.name}")
                
                # Collect PDFs from multiple sources
                pdf_files = []
                found_file_ids = set()
                
                # SOURCE 1: Files tab (main file repository)
                try:
                    all_files = list(course.get_files())
                    files_tab_pdfs = [f for f in all_files if f.filename.lower().endswith('.pdf')]
                    if files_tab_pdfs:
                        print(f"      📁 Files tab: {len(files_tab_pdfs)} PDFs")
                        for f in files_tab_pdfs:
                            found_file_ids.add(f.id)
                        pdf_files.extend(files_tab_pdfs)
                except Forbidden:
                    print(f"      🔒 Files tab restricted")
                except Exception as e:
                    print(f"      ⚠️ Files tab error: {e}")
                
                # SOURCE 2: Modules (many profs put files here instead)
                module_pdfs = self._get_pdfs_from_modules(course, found_file_ids)
                pdf_files.extend(module_pdfs)

                # Check if we found anything
                if not pdf_files:
                    print("   (No PDFs found)")
                    continue
                
                print(f"   📄 Total: {len(pdf_files)} PDFs")

                for file in pdf_files:
                    # Handle external URL PDFs (from modules)
                    if isinstance(file, dict) and file.get('type') == 'external_url':
                        safe_filename = sanitize_filename(file['title'])
                        if not safe_filename.lower().endswith('.pdf'):
                            safe_filename += '.pdf'
                        local_path = course_dir / safe_filename
                        download_url = file['url']
                        file_size = None  # Unknown for external URLs
                    else:
                        # Regular Canvas file object
                        safe_filename = sanitize_filename(file.filename)
                        if not safe_filename.lower().endswith('.pdf'):
                            safe_filename += '.pdf'
                        local_path = course_dir / safe_filename
                        download_url = file.url
                        file_size = getattr(file, 'size', None)
                    
                    # Smart Sync Check
                    should_download = True
                    if local_path.exists():
                        if file_size and local_path.stat().st_size == file_size:
                            should_download = False
                            # print(f"   ⏭️  Up to date: {safe_filename}")
                    
                    if should_download:
                        try:
                            print(f"   ⬇️  Downloading: {safe_filename}")
                            response = requests.get(download_url, stream=True, timeout=60)
                            response.raise_for_status()
                            with open(local_path, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    f.write(chunk)
                            downloaded_paths.append(str(local_path))
                        except Exception as e:
                            print(f"      ❌ Failed: {e}")

            except Exception as e:
                print(f"   ⚠️ Error processing course: {e}")
        
        print(f"\n✅ Sync complete! {len(downloaded_paths)} new PDFs.")
        return downloaded_paths

    def download_and_ingest(self, download_dir: str = None, course_filter: list[str] = None):
        from app.services.knowledge import get_knowledge_base
        paths = self.download_course_pdfs(download_dir, course_filter)
        
        if paths:
            print(f"\n🧠 Updating Knowledge Base...")
            kb = get_knowledge_base()
            kb.ingest_directory(str(download_dir or DEFAULT_DOWNLOAD_DIR), chunking_strategy="page")
        
        return paths

    def list_course_files(self, file_extension: str = None) -> dict:
        """List files without downloading (scans both Files tab and Modules)."""
        result = {}
        try:
            print(f"📋 Listing Canvas files...")
            user = self.canvas.get_current_user()
            courses = user.get_courses(enrollment_state='active')
            
            for course in courses:
                if not hasattr(course, 'name') or "sandbox" in course.name.lower():
                    continue
                    
                course_files = []
                seen_ids = set()
                
                # Source 1: Files tab
                try:
                    files = course.get_files()
                    for file in files:
                        if file_extension and not file.filename.lower().endswith(file_extension.lower()):
                            continue
                        
                        course_files.append({
                            "filename": file.filename,
                            "size": getattr(file, 'size', 0),
                            "source": "files_tab"
                        })
                        seen_ids.add(file.id)
                except Forbidden:
                    pass
                except Exception:
                    pass
                
                # Source 2: Modules
                try:
                    modules = course.get_modules()
                    for module in modules:
                        try:
                            items = module.get_module_items()
                            for item in items:
                                if item.type == 'File':
                                    if item.content_id in seen_ids:
                                        continue
                                    try:
                                        f = course.get_file(item.content_id)
                                        if file_extension and not f.filename.lower().endswith(file_extension.lower()):
                                            continue
                                        course_files.append({
                                            "filename": f.filename,
                                            "size": getattr(f, 'size', 0),
                                            "source": "modules"
                                        })
                                        seen_ids.add(item.content_id)
                                    except (Forbidden, ResourceDoesNotExist):
                                        continue
                        except Exception:
                            continue
                except Exception:
                    pass
                
                if course_files:
                    result[course.name] = course_files
                    files_count = sum(1 for f in course_files if f['source'] == 'files_tab')
                    modules_count = sum(1 for f in course_files if f['source'] == 'modules')
                    print(f"   {course.name}: {len(course_files)} files (Files: {files_count}, Modules: {modules_count})")
            
            return result
        except Exception as e:
            print(f"❌ Error: {e}")
            return result


if __name__ == "__main__":
    # CLI TESTER
    import sys
    from dotenv import load_dotenv
    
    load_dotenv()
    
    key = os.environ.get("CANVAS_API_KEY")
    if not key:
        key = input("Paste Canvas Token: ")
    
    syncer = CanvasSync(key)
    
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    
    if command == "download":
        syncer.download_course_pdfs()
    elif command == "ingest":
        syncer.download_and_ingest()
    elif command == "list":
        syncer.list_course_files(file_extension=".pdf")
    else:
        print("Usage: python -m app.services.canvas_sync [download|ingest|list]")