"""
knowledge.py - ChromaDB RAG Pipeline for Zed

This module handles:
1. PDF ingestion and text extraction
2. Smart chunking (by slide/topic)
3. Embedding generation using sentence-transformers
4. ChromaDB vector storage
5. Semantic retrieval for quiz context
"""

import os
import re
import hashlib
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings

# For PDF parsing
try:
    import fitz  
except ImportError:
    fitz = None

# For embeddings - using sentence-transformers (local, fast)
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None


# ============================================================
# CONFIGURATION
# ============================================================

# Where to store the ChromaDB database
CHROMA_PERSIST_DIR = Path(__file__).parent.parent.parent / "data" / "chroma_db"

# Embedding model - all-MiniLM-L6-v2 is fast and good for semantic search
# Alternative: "nomic-ai/nomic-embed-text-v1" (requires trust_remote_code=True)
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Collection name in ChromaDB
COLLECTION_NAME = "course_knowledge"

# Chunking settings
MAX_CHUNK_SIZE = 500  # characters
CHUNK_OVERLAP = 50    # overlap between chunks


# ============================================================
# PDF PARSER
# ============================================================

class PDFParser:
    """
    Extracts text from PDFs with slide-aware chunking.
    Handles both regular PDFs and slide decks.
    """
    
    @staticmethod
    def extract_text_from_pdf(pdf_path: str) -> list[dict]:
        """
        Extract text from a PDF file, page by page.
        
        Returns:
            List of dicts: [{"page": 1, "text": "...", "source": "filename.pdf"}, ...]
        """
        if fitz is None:
            raise ImportError("PyMuPDF not installed. Run: pip install pymupdf")
        
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        pages = []
        doc = fitz.open(str(pdf_path))
        
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text")
            
            # Clean up the text
            text = PDFParser._clean_text(text)
            
            if text.strip():  # Only add non-empty pages
                pages.append({
                    "page": page_num,
                    "text": text,
                    "source": pdf_path.name,
                    "source_path": str(pdf_path)
                })
        
        doc.close()
        return pages
    
    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean extracted PDF text."""
        # Remove excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        
        # Remove common PDF artifacts
        text = re.sub(r'\x00', '', text)  # null bytes
        
        return text.strip()
    
    @staticmethod
    def extract_from_directory(directory: str, extensions: list[str] = None) -> list[dict]:
        """
        Extract text from all PDFs in a directory.
        
        Args:
            directory: Path to directory containing PDFs
            extensions: File extensions to process (default: ['.pdf'])
        
        Returns:
            Combined list of all pages from all PDFs
        """
        if extensions is None:
            extensions = ['.pdf']
        
        directory = Path(directory)
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        all_pages = []
        
        for ext in extensions:
            for pdf_file in directory.glob(f"*{ext}"):
                print(f"📄 Processing: {pdf_file.name}")
                try:
                    pages = PDFParser.extract_text_from_pdf(str(pdf_file))
                    all_pages.extend(pages)
                    print(f"   ✓ Extracted {len(pages)} pages")
                except Exception as e:
                    print(f"   ⚠️ Error processing {pdf_file.name}: {e}")
        
        return all_pages


# ============================================================
# TEXT CHUNKER
# ============================================================

class TextChunker:
    """
    Smart text chunking strategies for course materials.
    """
    
    @staticmethod
    def chunk_by_page(pages: list[dict]) -> list[dict]:
        """
        Simple strategy: Each page/slide is one chunk.
        Best for slide decks where each slide is a coherent unit.
        """
        chunks = []
        for page in pages:
            chunk_id = hashlib.md5(
                f"{page['source']}:{page['page']}".encode()
            ).hexdigest()[:12]
            
            chunks.append({
                "id": chunk_id,
                "text": page["text"],
                "metadata": {
                    "source": page["source"],
                    "page": page["page"],
                    "chunk_type": "page"
                }
            })
        return chunks
    
    @staticmethod
    def chunk_by_size(pages: list[dict], 
                      max_size: int = MAX_CHUNK_SIZE,
                      overlap: int = CHUNK_OVERLAP) -> list[dict]:
        """
        Split text into fixed-size chunks with overlap.
        Better for dense documents like syllabi.
        """
        chunks = []
        
        for page in pages:
            text = page["text"]
            
            # Split into sentences first (smarter boundaries)
            sentences = re.split(r'(?<=[.!?])\s+', text)
            
            current_chunk = ""
            chunk_num = 0
            
            for sentence in sentences:
                if len(current_chunk) + len(sentence) <= max_size:
                    current_chunk += sentence + " "
                else:
                    if current_chunk.strip():
                        chunk_id = hashlib.md5(
                            f"{page['source']}:{page['page']}:{chunk_num}".encode()
                        ).hexdigest()[:12]
                        
                        chunks.append({
                            "id": chunk_id,
                            "text": current_chunk.strip(),
                            "metadata": {
                                "source": page["source"],
                                "page": page["page"],
                                "chunk_num": chunk_num,
                                "chunk_type": "size"
                            }
                        })
                        chunk_num += 1
                    
                    # Start new chunk with overlap
                    words = current_chunk.split()
                    overlap_text = " ".join(words[-overlap//10:]) if words else ""
                    current_chunk = overlap_text + " " + sentence + " "
            
            # Don't forget the last chunk
            if current_chunk.strip():
                chunk_id = hashlib.md5(
                    f"{page['source']}:{page['page']}:{chunk_num}".encode()
                ).hexdigest()[:12]
                
                chunks.append({
                    "id": chunk_id,
                    "text": current_chunk.strip(),
                    "metadata": {
                        "source": page["source"],
                        "page": page["page"],
                        "chunk_num": chunk_num,
                        "chunk_type": "size"
                    }
                })
        
        return chunks
    
    @staticmethod
    def chunk_by_topic(pages: list[dict]) -> list[dict]:
        """
        Attempt to chunk by topic/section headers.
        Looks for patterns like "Topic:", "Chapter:", numbered sections, etc.
        """
        # Header patterns that indicate new topics
        header_patterns = [
            r'^(?:Chapter|Section|Topic|Module|Unit|Lecture)\s*\d*[:\.]?\s*',
            r'^\d+\.\s+[A-Z]',  # "1. Something"
            r'^[A-Z][A-Z\s]{2,}$',  # ALL CAPS HEADERS
            r'^#{1,3}\s+',  # Markdown headers
        ]
        combined_pattern = '|'.join(header_patterns)
        
        chunks = []
        
        for page in pages:
            text = page["text"]
            lines = text.split('\n')
            
            current_topic = ""
            current_content = ""
            chunk_num = 0
            
            for line in lines:
                # Check if this line is a header
                if re.match(combined_pattern, line, re.IGNORECASE):
                    # Save previous topic if exists
                    if current_content.strip():
                        chunk_id = hashlib.md5(
                            f"{page['source']}:{page['page']}:{chunk_num}".encode()
                        ).hexdigest()[:12]
                        
                        chunks.append({
                            "id": chunk_id,
                            "text": f"{current_topic}\n{current_content}".strip(),
                            "metadata": {
                                "source": page["source"],
                                "page": page["page"],
                                "topic": current_topic.strip(),
                                "chunk_type": "topic"
                            }
                        })
                        chunk_num += 1
                    
                    current_topic = line
                    current_content = ""
                else:
                    current_content += line + "\n"
            
            # Save last topic
            if current_content.strip():
                chunk_id = hashlib.md5(
                    f"{page['source']}:{page['page']}:{chunk_num}".encode()
                ).hexdigest()[:12]
                
                chunks.append({
                    "id": chunk_id,
                    "text": f"{current_topic}\n{current_content}".strip(),
                    "metadata": {
                        "source": page["source"],
                        "page": page["page"],
                        "topic": current_topic.strip(),
                        "chunk_type": "topic"
                    }
                })
        
        return chunks


# ============================================================
# KNOWLEDGE BASE (ChromaDB + Embeddings)
# ============================================================

class KnowledgeBase:
    """
    Main class for the RAG pipeline.
    Handles embedding, storage, and retrieval.
    """
    
    def __init__(self, persist_directory: str = None, collection_name: str = None):
        """
        Initialize the knowledge base.
        
        Args:
            persist_directory: Where to store ChromaDB (default: data/chroma_db)
            collection_name: Name of the collection (default: course_knowledge)
        """
        self.persist_dir = Path(persist_directory or CHROMA_PERSIST_DIR)
        self.collection_name = collection_name or COLLECTION_NAME
        
        # Create persist directory if needed
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize embedding model
        if SentenceTransformer is None:
            raise ImportError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )
        
        print(f"🧠 Loading embedding model: {EMBEDDING_MODEL}")
        self.embedder = SentenceTransformer(EMBEDDING_MODEL)
        
        # Initialize ChromaDB with persistence
        print(f"💾 Connecting to ChromaDB at: {self.persist_dir}")
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False)
        )
        
        # Get or create the collection
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Zed course knowledge base"}
        )
        
        print(f"✅ Knowledge base ready! ({self.collection.count()} documents)")
    
    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        return self.embedder.encode(texts, show_progress_bar=True).tolist()
    
    def ingest_chunks(self, chunks: list[dict], batch_size: int = 100):
        """
        Add chunks to the vector store.
        
        Args:
            chunks: List of chunk dicts with 'id', 'text', 'metadata'
            batch_size: How many to process at once
        """
        if not chunks:
            print("⚠️ No chunks to ingest")
            return
        
        print(f"📥 Ingesting {len(chunks)} chunks...")
        
        # Process in batches
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            
            ids = [c["id"] for c in batch]
            texts = [c["text"] for c in batch]
            metadatas = [c["metadata"] for c in batch]
            
            # Generate embeddings
            embeddings = self._embed(texts)
            
            # Upsert to ChromaDB (handles duplicates)
            self.collection.upsert(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas
            )
            
            print(f"   ✓ Batch {i//batch_size + 1}: {len(batch)} chunks")
        
        print(f"✅ Ingestion complete! Total documents: {self.collection.count()}")
    
    def ingest_pdf(self, pdf_path: str, chunking_strategy: str = "page"):
        """
        Convenience method to ingest a single PDF.
        
        Args:
            pdf_path: Path to the PDF file
            chunking_strategy: "page", "size", or "topic"
        """
        pages = PDFParser.extract_text_from_pdf(pdf_path)
        
        if chunking_strategy == "page":
            chunks = TextChunker.chunk_by_page(pages)
        elif chunking_strategy == "size":
            chunks = TextChunker.chunk_by_size(pages)
        elif chunking_strategy == "topic":
            chunks = TextChunker.chunk_by_topic(pages)
        else:
            raise ValueError(f"Unknown chunking strategy: {chunking_strategy}")
        
        self.ingest_chunks(chunks)
    
    def ingest_directory(self, directory: str, chunking_strategy: str = "page"):
        """
        Ingest all PDFs from a directory.
        
        Args:
            directory: Path to directory containing PDFs
            chunking_strategy: "page", "size", or "topic"
        """
        pages = PDFParser.extract_from_directory(directory)
        
        if chunking_strategy == "page":
            chunks = TextChunker.chunk_by_page(pages)
        elif chunking_strategy == "size":
            chunks = TextChunker.chunk_by_size(pages)
        elif chunking_strategy == "topic":
            chunks = TextChunker.chunk_by_topic(pages)
        else:
            raise ValueError(f"Unknown chunking strategy: {chunking_strategy}")
        
        self.ingest_chunks(chunks)
    
    def ingest_text(self, text: str, source: str = "manual", metadata: dict = None):
        """
        Ingest raw text directly (e.g., from Canvas syllabus).
        
        Args:
            text: The text content to ingest
            source: Source identifier
            metadata: Additional metadata
        """
        chunk_id = hashlib.md5(f"{source}:{text[:100]}".encode()).hexdigest()[:12]
        
        chunk = {
            "id": chunk_id,
            "text": text,
            "metadata": {
                "source": source,
                "chunk_type": "raw",
                **(metadata or {})
            }
        }
        
        self.ingest_chunks([chunk])
    
    def retrieve_context(self, query: str, n_results: int = 3) -> list[dict]:
        """
        🎯 THE MAIN RETRIEVAL FUNCTION
        
        Takes the user's spoken text and returns the top relevant chunks.
        
        Args:
            query: The user's question/query text
            n_results: Number of results to return (default: 3)
        
        Returns:
            List of dicts with 'text', 'source', 'page', 'score'
        """
        if self.collection.count() == 0:
            return [{
                "text": "No course materials loaded yet. Please add some PDFs first!",
                "source": "system",
                "page": 0,
                "score": 0.0
            }]
        
        # Embed the query
        query_embedding = self._embed([query])[0]
        
        # Search ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, self.collection.count()),
            include=["documents", "metadatas", "distances"]
        )
        
        # Format results
        formatted = []
        for i in range(len(results["ids"][0])):
            # Convert distance to similarity score (ChromaDB uses L2 distance)
            # Lower distance = more similar, so we invert it
            distance = results["distances"][0][i]
            similarity = 1 / (1 + distance)  # Normalize to 0-1
            
            formatted.append({
                "text": results["documents"][0][i],
                "source": results["metadatas"][0][i].get("source", "unknown"),
                "page": results["metadatas"][0][i].get("page", 0),
                "score": round(similarity, 3),
                "metadata": results["metadatas"][0][i]
            })
        
        return formatted
    
    def clear(self):
        """Clear all documents from the collection."""
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.create_collection(
            name=self.collection_name,
            metadata={"description": "Zed course knowledge base"}
        )
        print("🗑️ Knowledge base cleared!")
    
    def get_stats(self) -> dict:
        """Get statistics about the knowledge base."""
        count = self.collection.count()
        
        # Get unique sources
        if count > 0:
            all_docs = self.collection.get(include=["metadatas"])
            sources = set(m.get("source", "unknown") for m in all_docs["metadatas"])
        else:
            sources = set()
        
        return {
            "total_chunks": count,
            "sources": list(sources),
            "persist_directory": str(self.persist_dir),
            "embedding_model": EMBEDDING_MODEL
        }


# ============================================================
# CONVENIENCE FUNCTION FOR QUICK RETRIEVAL
# ============================================================

# Global instance for quick access
_kb_instance: Optional[KnowledgeBase] = None

def retrieve_context(query: str, n_results: int = 3) -> list[dict]:
    """
    🎯 MAIN ENTRY POINT
    
    Quick retrieval function that can be imported and used directly.
    
    Usage:
        from app.services.knowledge import retrieve_context
        
        results = retrieve_context("What is the midterm worth?")
        for r in results:
            print(f"[{r['score']}] {r['source']} p.{r['page']}")
            print(r['text'][:200])
    """
    global _kb_instance
    
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
    
    return _kb_instance.retrieve_context(query, n_results)


def get_knowledge_base() -> KnowledgeBase:
    """Get or create the global KnowledgeBase instance."""
    global _kb_instance
    
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
    
    return _kb_instance


# ============================================================
# CLI FOR TESTING
# ============================================================

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    
    load_dotenv()
    
    print("=" * 60)
    print("🧠 ZED KNOWLEDGE BASE - CLI")
    print("=" * 60)
    
    kb = KnowledgeBase()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "ingest" and len(sys.argv) > 2:
            # python -m app.services.knowledge ingest /path/to/pdfs
            path = sys.argv[2]
            strategy = sys.argv[3] if len(sys.argv) > 3 else "page"
            
            if os.path.isfile(path):
                kb.ingest_pdf(path, chunking_strategy=strategy)
            elif os.path.isdir(path):
                kb.ingest_directory(path, chunking_strategy=strategy)
            else:
                print(f"❌ Path not found: {path}")
        
        elif command == "query" and len(sys.argv) > 2:
            # python -m app.services.knowledge query "what is the midterm worth"
            query = " ".join(sys.argv[2:])
            results = kb.retrieve_context(query)
            
            print(f"\n🔍 Query: '{query}'")
            print("-" * 40)
            
            for i, r in enumerate(results, 1):
                print(f"\n📄 Result {i} (score: {r['score']})")
                print(f"   Source: {r['source']}, Page: {r['page']}")
                print(f"   {r['text'][:300]}...")
        
        elif command == "stats":
            # python -m app.services.knowledge stats
            stats = kb.get_stats()
            print(f"\n📊 Knowledge Base Stats:")
            print(f"   Total chunks: {stats['total_chunks']}")
            print(f"   Sources: {', '.join(stats['sources']) or 'None'}")
            print(f"   Storage: {stats['persist_directory']}")
            print(f"   Model: {stats['embedding_model']}")
        
        elif command == "clear":
            # python -m app.services.knowledge clear
            confirm = input("⚠️ This will delete all data. Type 'yes' to confirm: ")
            if confirm.lower() == 'yes':
                kb.clear()
        
        else:
            print("Unknown command. Use: ingest, query, stats, clear")
    
    else:
        # Interactive mode
        print("\n📊 Stats:", kb.get_stats())
        print("\nEnter queries to test retrieval (Ctrl+C to exit):")
        
        while True:
            try:
                query = input("\n🔍 Query: ").strip()
                if not query:
                    continue
                
                results = kb.retrieve_context(query)
                
                for i, r in enumerate(results, 1):
                    print(f"\n--- Result {i} (score: {r['score']}) ---")
                    print(f"Source: {r['source']}, Page: {r['page']}")
                    print(r['text'][:400])
                    
            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break

