"""
canvas_sync.py - ETL Layer for Canvas LMS

XRX Architecture Role: INPUT (Extract-Transform-Load)
- Extracts PDFs from Canvas (Files tab + Modules)
- Downloads to local filesystem
- NO knowledge base imports - pure ETL

Usage:
    python -m app.services.canvas_sync download
    python -m app.services.canvas_sync list
"""

import os
import re
import hashlib
import logging
import requests
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from canvasapi import Canvas
from canvasapi.exceptions import Forbidden, ResourceDoesNotExist

# ============================================================
# CONFIGURATION
# ============================================================

CANVAS_API_URL = os.environ.get("CANVAS_API_URL", "https://q.utoronto.ca")
DEFAULT_DOWNLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "downloads"

logger = logging.getLogger(__name__)


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class DownloadResult:
    """Result of a download operation."""
    path: str
    filename: str
    course: str
    source: str  # "files_tab" or "modules" or "external_url"
    success: bool
    error: Optional[str] = None


# ============================================================
# UTILITIES
# ============================================================

def sanitize_filename(name: str) -> str:
    """Sanitize a filename for safe filesystem storage."""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip().strip('.')
    name = re.sub(r'[_\s]+', '_', name)
    return name[:100]


# ============================================================
# CANVAS SYNC - PURE ETL
# ============================================================

class CanvasSync:
    """
    ETL Layer for Canvas LMS.
    
    Responsibilities:
    - Connect to Canvas API
    - Discover PDFs in Files tab and Modules
    - Download files to local filesystem
    
    Does NOT:
    - Import knowledge base
    - Perform embeddings
    - Manage vector storage
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Canvas connection.
        
        Args:
            api_key: Canvas API token. Falls back to CANVAS_API_KEY env var.
        
        Raises:
            ValueError: If no API key is provided or found.
        """
        self.api_key = api_key or os.environ.get("CANVAS_API_KEY")
        
        if not self.api_key:
            raise ValueError(
                "Canvas API Token required. "
                "Pass api_key or set CANVAS_API_KEY environment variable."
            )
        
        self.canvas = Canvas(CANVAS_API_URL, self.api_key)
        self._user = None
    
    @property
    def user(self):
        """Lazy-load current user."""
        if self._user is None:
            self._user = self.canvas.get_current_user()
        return self._user
    
    # ----------------------------------------------------------
    # DISCOVERY: Find PDFs in Modules (Priority Source)
    # ----------------------------------------------------------
    
    def _get_pdfs_from_modules(self, course, existing_ids: set) -> list:
        """
        Scan course Modules for PDF files.
        
        Modules are the PRIMARY source - many professors organize
        content here rather than the Files tab.
        
        Args:
            course: Canvas course object
            existing_ids: Set of file IDs already found (deduplication)
        
        Returns:
            List of file objects or external URL dicts
        """
        found_files = []
        
        try:
            modules = list(course.get_modules())
            
            for module in modules:
                try:
                    items = module.get_module_items()
                    
                    for item in items:
                        # Canvas File items
                        if item.type == 'File':
                            content_id = getattr(item, 'content_id', None)
                            if not content_id or content_id in existing_ids:
                                continue
                            
                            try:
                                file_obj = course.get_file(content_id)
                                if file_obj.filename.lower().endswith('.pdf'):
                                    found_files.append({
                                        'type': 'canvas_file',
                                        'file': file_obj,
                                        'source': 'modules'
                                    })
                                    existing_ids.add(content_id)
                            except (Forbidden, ResourceDoesNotExist):
                                continue
                        
                        # External URL items (direct PDF links)
                        elif item.type == 'ExternalUrl':
                            url = getattr(item, 'external_url', '')
                            if url.lower().endswith('.pdf'):
                                found_files.append({
                                    'type': 'external_url',
                                    'url': url,
                                    'title': getattr(item, 'title', 'external.pdf'),
                                    'source': 'modules'
                                })
                
                except Exception as e:
                    logger.debug(f"Module access error: {e}")
                    continue
            
            if found_files:
                logger.info(f"Found {len(found_files)} PDFs in {len(modules)} modules")
        
        except Forbidden:
            logger.debug("Modules tab restricted")
        except Exception as e:
            logger.warning(f"Module scan error: {e}")
        
        return found_files
    
    def _get_pdfs_from_files_tab(self, course, existing_ids: set) -> list:
        """
        Scan course Files tab for PDFs.
        
        Args:
            course: Canvas course object
            existing_ids: Set of file IDs already found (deduplication)
        
        Returns:
            List of file dicts
        """
        found_files = []
        
        try:
            all_files = list(course.get_files())
            
            for file_obj in all_files:
                if file_obj.id in existing_ids:
                    continue
                    
                if file_obj.filename.lower().endswith('.pdf'):
                    found_files.append({
                        'type': 'canvas_file',
                        'file': file_obj,
                        'source': 'files_tab'
                    })
                    existing_ids.add(file_obj.id)
            
            if found_files:
                logger.info(f"Found {len(found_files)} PDFs in Files tab")
        
        except Forbidden:
            logger.debug("Files tab restricted")
        except Exception as e:
            logger.warning(f"Files tab error: {e}")
        
        return found_files
    
    # ----------------------------------------------------------
    # DOWNLOAD: Fetch files to local filesystem
    # ----------------------------------------------------------
    
    def _download_file(
        self, 
        file_info: dict, 
        course_dir: Path, 
        course_name: str
    ) -> DownloadResult:
        """
        Download a single file.
        
        Args:
            file_info: Dict with file metadata
            course_dir: Directory to save to
            course_name: Name of the course
        
        Returns:
            DownloadResult with success/failure info
        """
        try:
            # Determine filename and URL based on type
            if file_info['type'] == 'canvas_file':
                file_obj = file_info['file']
                base_filename = sanitize_filename(file_obj.filename)
                download_url = file_obj.url
                file_size = getattr(file_obj, 'size', None)
                file_id = file_obj.id  # Canvas file ID for uniqueness
            else:  # external_url
                base_filename = sanitize_filename(file_info['title'])
                if not base_filename.lower().endswith('.pdf'):
                    base_filename += '.pdf'
                download_url = file_info['url']
                file_size = None
                # Use hash of URL as unique ID for external files
                file_id = hashlib.md5(file_info['url'].encode()).hexdigest()[:8]
            
            # COLLISION FIX: Append Canvas ID to filename to guarantee uniqueness
            # e.g., "Week1_Readings.pdf" → "Week1_Readings_12345.pdf"
            name_part, ext = base_filename.rsplit('.', 1) if '.' in base_filename else (base_filename, 'pdf')
            filename = f"{name_part}_{file_id}.{ext}"
            
            local_path = course_dir / filename
            
            # Smart sync: skip if file exists and size matches
            if local_path.exists():
                if file_size and local_path.stat().st_size == file_size:
                    return DownloadResult(
                        path=str(local_path),
                        filename=filename,
                        course=course_name,
                        source=file_info['source'],
                        success=True
                    )
            
            # Download with streaming
            logger.info(f"Downloading: {filename}")
            response = requests.get(download_url, stream=True, timeout=60)
            response.raise_for_status()
            
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return DownloadResult(
                path=str(local_path),
                filename=filename,
                course=course_name,
                source=file_info['source'],
                success=True
            )
        
        except Exception as e:
            return DownloadResult(
                path="",
                filename=file_info.get('title', 'unknown'),
                course=course_name,
                source=file_info.get('source', 'unknown'),
                success=False,
                error=str(e)
            )
    
    # ----------------------------------------------------------
    # PUBLIC API
    # ----------------------------------------------------------
    
    def download_pdfs(
        self,
        download_dir: Optional[str] = None,
        course_filter: Optional[list[str]] = None,
        modules_first: bool = True
    ) -> list[DownloadResult]:
        """
        Download PDFs from Canvas courses.
        
        Args:
            download_dir: Where to save files (default: data/downloads)
            course_filter: List of course name substrings to filter
            modules_first: If True, prioritize Modules over Files tab
        
        Returns:
            List of DownloadResult objects
        """
        download_dir = Path(download_dir or DEFAULT_DOWNLOAD_DIR)
        download_dir.mkdir(parents=True, exist_ok=True)
        
        results: list[DownloadResult] = []
        
        print("📥 Scanning Canvas for PDFs...")
        courses = self.user.get_courses(enrollment_state='active')
        
        for course in courses:
            try:
                # Skip sandbox courses
                if not hasattr(course, 'name') or "sandbox" in course.name.lower():
                    continue
                
                # Apply course filter
                if course_filter:
                    if not any(f.lower() in course.name.lower() for f in course_filter):
                        continue
                
                print(f"\n📂 {course.name}")
                
                # Setup course directory
                safe_name = sanitize_filename(course.name)
                course_dir = download_dir / safe_name
                course_dir.mkdir(parents=True, exist_ok=True)
                
                # Collect PDFs (deduplicated)
                found_ids: set = set()
                pdf_files: list = []
                
                # Priority order based on modules_first flag
                if modules_first:
                    pdf_files.extend(self._get_pdfs_from_modules(course, found_ids))
                    pdf_files.extend(self._get_pdfs_from_files_tab(course, found_ids))
                else:
                    pdf_files.extend(self._get_pdfs_from_files_tab(course, found_ids))
                    pdf_files.extend(self._get_pdfs_from_modules(course, found_ids))
                
                if not pdf_files:
                    print("   (No PDFs found)")
                    continue
                
                print(f"   📄 Found {len(pdf_files)} PDFs")
                
                # Download each file
                for file_info in pdf_files:
                    result = self._download_file(file_info, course_dir, course.name)
                    results.append(result)
                    
                    if result.success:
                        print(f"   ✅ {result.filename}")
                    else:
                        print(f"   ❌ {result.filename}: {result.error}")
            
            except Exception as e:
                logger.error(f"Course error ({course.name}): {e}")
        
        # Summary
        successful = sum(1 for r in results if r.success)
        print(f"\n✅ Complete! {successful}/{len(results)} files downloaded.")
        
        return results
    
    def list_files(
        self,
        extension: Optional[str] = ".pdf",
        course_filter: Optional[list[str]] = None
    ) -> dict[str, list[dict]]:
        """
        List available files without downloading.
        
        Args:
            extension: File extension to filter (e.g., ".pdf")
            course_filter: List of course name substrings to filter
        
        Returns:
            Dict mapping course names to lists of file info dicts
        """
        result: dict[str, list[dict]] = {}
        
        print("📋 Listing Canvas files...")
        courses = self.user.get_courses(enrollment_state='active')
        
        for course in courses:
            try:
                if not hasattr(course, 'name') or "sandbox" in course.name.lower():
                    continue
                
                if course_filter:
                    if not any(f.lower() in course.name.lower() for f in course_filter):
                        continue
                
                found_ids: set = set()
                course_files: list[dict] = []
                
                # Scan modules first
                module_files = self._get_pdfs_from_modules(course, found_ids)
                for f in module_files:
                    if f['type'] == 'canvas_file':
                        file_obj = f['file']
                        if extension and not file_obj.filename.lower().endswith(extension.lower()):
                            continue
                        course_files.append({
                            "filename": file_obj.filename,
                            "size": getattr(file_obj, 'size', 0),
                            "source": "modules"
                        })
                    else:
                        course_files.append({
                            "filename": f['title'],
                            "size": 0,
                            "source": "external_url"
                        })
                
                # Then Files tab
                files_tab = self._get_pdfs_from_files_tab(course, found_ids)
                for f in files_tab:
                    file_obj = f['file']
                    if extension and not file_obj.filename.lower().endswith(extension.lower()):
                        continue
                    course_files.append({
                        "filename": file_obj.filename,
                        "size": getattr(file_obj, 'size', 0),
                        "source": "files_tab"
                    })
                
                if course_files:
                    result[course.name] = course_files
                    modules_count = sum(1 for f in course_files if f['source'] == 'modules')
                    files_count = sum(1 for f in course_files if f['source'] == 'files_tab')
                    print(f"   {course.name}: {len(course_files)} files "
                          f"(Modules: {modules_count}, Files: {files_count})")
            
            except Exception as e:
                logger.error(f"Course error: {e}")
        
        return result
    
    def get_download_paths(self, results: list[DownloadResult]) -> list[str]:
        """
        Extract successful download paths from results.
        
        Args:
            results: List of DownloadResult objects
        
        Returns:
            List of file paths (strings)
        """
        return [r.path for r in results if r.success and r.path]


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    
    # Get API key
    key = os.environ.get("CANVAS_API_KEY")
    if not key:
        key = input("Paste Canvas Token: ")
    
    syncer = CanvasSync(api_key=key)
    
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    
    if command == "download":
        results = syncer.download_pdfs()
        paths = syncer.get_download_paths(results)
        print(f"\n📁 Downloaded to: {DEFAULT_DOWNLOAD_DIR}")
        print(f"   Paths: {paths[:3]}..." if len(paths) > 3 else f"   Paths: {paths}")
    
    elif command == "list":
        files = syncer.list_files(extension=".pdf")
        total = sum(len(v) for v in files.values())
        print(f"\n📊 Total: {total} PDFs across {len(files)} courses")
    
    else:
        print("Usage: python -m app.services.canvas_sync [download|list]")
        print("\nCommands:")
        print("  download  - Download all PDFs from Canvas")
        print("  list      - List available PDFs without downloading")