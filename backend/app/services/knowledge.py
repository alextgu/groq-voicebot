"""
knowledge.py - Memory Layer for Zed (RAG Pipeline)

XRX Architecture Role: MEMORY
- PDF ingestion and text extraction
- Smart chunking (by slide/topic)
- Embedding generation using sentence-transformers
- ChromaDB vector storage
- Semantic retrieval for quiz context

Singleton Pattern: Use get_knowledge_base() to get the global instance.
"""

import os
import re
import hashlib
import logging
import threading
from pathlib import Path
from typing import Optional, Literal

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

CHROMA_PERSIST_DIR = Path(
    os.environ.get("CHROMA_PERSIST_DIR") or 
    Path(__file__).parent.parent.parent / "data" / "chroma_db"
)

# Embedding model - all-MiniLM-L6-v2 is fast and good for semantic search
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Collection name in ChromaDB
COLLECTION_NAME = os.environ.get("CHROMA_COLLECTION", "course_knowledge")

# Chunking settings
MAX_CHUNK_SIZE = 500  # characters
CHUNK_OVERLAP = 50    # overlap between chunks

logger = logging.getLogger(__name__)


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
        
        Args:
            pdf_path: Path to the PDF file
        
        Returns:
            List of dicts: [{"page": 1, "text": "...", "source": "filename.pdf"}, ...]
        
        Raises:
            ImportError: If PyMuPDF is not installed
            FileNotFoundError: If PDF doesn't exist
        """
        if fitz is None:
            raise ImportError("PyMuPDF not installed. Run: pip install pymupdf")
        
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        pages = []
        doc = fitz.open(str(pdf_path))
        
        try:
            for page_num, page in enumerate(doc, start=1):
                text = page.get_text("text")
                text = PDFParser._clean_text(text)
                
                if text.strip():
                    pages.append({
                        "page": page_num,
                        "text": text,
                        "source": pdf_path.name,
                        "source_path": str(pdf_path)
                    })
        finally:
            doc.close()
        
        return pages
    
    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean extracted PDF text."""
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        text = re.sub(r'\x00', '', text)  # null bytes
        return text.strip()
    
    @staticmethod
    def extract_from_directory(
        directory: str, 
        extensions: Optional[list[str]] = None,
        recursive: bool = True
    ) -> list[dict]:
        """
        Extract text from all PDFs in a directory.
        
        Args:
            directory: Path to directory containing PDFs
            extensions: File extensions to process (default: ['.pdf'])
            recursive: Whether to search subdirectories
        
        Returns:
            Combined list of all pages from all PDFs
        """
        if extensions is None:
            extensions = ['.pdf']
        
        directory = Path(directory)
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        all_pages = []
        glob_pattern = "**/*" if recursive else "*"
        
        for ext in extensions:
            for pdf_file in directory.glob(f"{glob_pattern}{ext}"):
                logger.info(f"Processing: {pdf_file.name}")
                try:
                    pages = PDFParser.extract_text_from_pdf(str(pdf_file))
                    all_pages.extend(pages)
                    logger.info(f"Extracted {len(pages)} pages from {pdf_file.name}")
                except Exception as e:
                    logger.warning(f"Error processing {pdf_file.name}: {e}")
        
        return all_pages


# ============================================================
# TEXT CHUNKER
# ============================================================

ChunkingStrategy = Literal["page", "size", "topic"]


class TextChunker:
    """Smart text chunking strategies for course materials."""
    
    @staticmethod
    def chunk(
        pages: list[dict], 
        strategy: ChunkingStrategy = "page",
        max_size: int = MAX_CHUNK_SIZE,
        overlap: int = CHUNK_OVERLAP
    ) -> list[dict]:
        """
        Chunk pages using the specified strategy.
        
        Args:
            pages: List of page dicts from PDFParser
            strategy: "page", "size", or "topic"
            max_size: Max chunk size for "size" strategy
            overlap: Overlap size for "size" strategy
        
        Returns:
            List of chunk dicts with 'id', 'text', 'metadata'
        """
        if strategy == "page":
            return TextChunker._chunk_by_page(pages)
        elif strategy == "size":
            return TextChunker._chunk_by_size(pages, max_size, overlap)
        elif strategy == "topic":
            return TextChunker._chunk_by_topic(pages)
        else:
            raise ValueError(f"Unknown chunking strategy: {strategy}")
    
    @staticmethod
    def _chunk_by_page(pages: list[dict]) -> list[dict]:
        """Each page/slide is one chunk."""
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
    def _chunk_by_size(
        pages: list[dict], 
        max_size: int,
        overlap: int
    ) -> list[dict]:
        """Split text into fixed-size chunks with overlap."""
        chunks = []
        
        for page in pages:
            text = page["text"]
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
                    
                    words = current_chunk.split()
                    overlap_text = " ".join(words[-overlap//10:]) if words else ""
                    current_chunk = overlap_text + " " + sentence + " "
            
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
    def _chunk_by_topic(pages: list[dict]) -> list[dict]:
        """Chunk by topic/section headers."""
        header_patterns = [
            r'^(?:Chapter|Section|Topic|Module|Unit|Lecture)\s*\d*[:\.]?\s*',
            r'^\d+\.\s+[A-Z]',
            r'^[A-Z][A-Z\s]{2,}$',
            r'^#{1,3}\s+',
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
                if re.match(combined_pattern, line, re.IGNORECASE):
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
# KNOWLEDGE BASE (ChromaDB + Embeddings) - SINGLETON
# ============================================================

class KnowledgeBase:
    """
    Main class for the RAG pipeline.
    Handles embedding, storage, and retrieval.
    
    Use get_knowledge_base() to get the singleton instance.
    """
    
    _instance: Optional["KnowledgeBase"] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern - only one instance allowed."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self, 
        persist_directory: Optional[str] = None, 
        collection_name: Optional[str] = None
    ):
        """
        Initialize the knowledge base (only runs once due to singleton).
        
        Args:
            persist_directory: Where to store ChromaDB
            collection_name: Name of the collection
        """
        if self._initialized:
            return
        
        self.persist_dir = Path(persist_directory or CHROMA_PERSIST_DIR)
        self.collection_name = collection_name or COLLECTION_NAME
        
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        if SentenceTransformer is None:
            raise ImportError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )
        
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        self.embedder = SentenceTransformer(EMBEDDING_MODEL)
        
        logger.info(f"Connecting to ChromaDB at: {self.persist_dir}")
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False)
        )
        
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Zed course knowledge base"}
        )
        
        logger.info(f"Knowledge base ready! ({self.collection.count()} documents)")
        self._initialized = True
    
    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        return self.embedder.encode(texts, show_progress_bar=False).tolist()
    
    # ----------------------------------------------------------
    # INGESTION METHODS
    # ----------------------------------------------------------
    
    def ingest_chunks(self, chunks: list[dict], batch_size: int = 100) -> int:
        """
        Add chunks to the vector store.
        
        Args:
            chunks: List of chunk dicts with 'id', 'text', 'metadata'
            batch_size: How many to process at once
        
        Returns:
            Number of chunks ingested
        """
        if not chunks:
            logger.warning("No chunks to ingest")
            return 0
        
        logger.info(f"Ingesting {len(chunks)} chunks...")
        
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            
            ids = [c["id"] for c in batch]
            texts = [c["text"] for c in batch]
            metadatas = [c["metadata"] for c in batch]
            
            embeddings = self._embed(texts)
            
            self.collection.upsert(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas
            )
        
        logger.info(f"Ingestion complete! Total: {self.collection.count()}")
        return len(chunks)
    
    def ingest_pdf(
        self, 
        pdf_path: str, 
        chunking_strategy: ChunkingStrategy = "page"
    ) -> int:
        """
        Ingest a single PDF.
        
        Args:
            pdf_path: Path to the PDF file
            chunking_strategy: "page", "size", or "topic"
        
        Returns:
            Number of chunks ingested
        """
        pages = PDFParser.extract_text_from_pdf(pdf_path)
        chunks = TextChunker.chunk(pages, strategy=chunking_strategy)
        return self.ingest_chunks(chunks)
    
    def ingest_directory(
        self, 
        directory: str, 
        chunking_strategy: ChunkingStrategy = "page",
        recursive: bool = True
    ) -> int:
        """
        Ingest all PDFs from a directory.
        
        Args:
            directory: Path to directory containing PDFs
            chunking_strategy: "page", "size", or "topic"
            recursive: Whether to search subdirectories
        
        Returns:
            Number of chunks ingested
        """
        pages = PDFParser.extract_from_directory(directory, recursive=recursive)
        chunks = TextChunker.chunk(pages, strategy=chunking_strategy)
        return self.ingest_chunks(chunks)
    
    def ingest_text(
        self, 
        text: str, 
        source: str = "manual", 
        metadata: Optional[dict] = None
    ) -> int:
        """
        Ingest raw text directly.
        
        Args:
            text: The text content to ingest
            source: Source identifier
            metadata: Additional metadata
        
        Returns:
            Number of chunks ingested (1)
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
        
        return self.ingest_chunks([chunk])
    
    # ----------------------------------------------------------
    # RETRIEVAL METHODS
    # ----------------------------------------------------------
    
    def search(
        self, 
        query: str, 
        n_results: int = 3,
        score_threshold: float = 0.0
    ) -> list[dict]:
        """
        🎯 MAIN RETRIEVAL FUNCTION
        
        Semantic search for relevant course materials.
        
        Args:
            query: The user's question/query text
            n_results: Number of results to return
            score_threshold: Minimum similarity score (0-1)
        
        Returns:
            List of dicts with 'text', 'source', 'page', 'score'
        """
        if self.collection.count() == 0:
            return []
        
        query_embedding = self._embed([query])[0]
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, self.collection.count()),
            include=["documents", "metadatas", "distances"]
        )
        
        formatted = []
        for i in range(len(results["ids"][0])):
            distance = results["distances"][0][i]
            similarity = 1 / (1 + distance)
            
            if similarity >= score_threshold:
                formatted.append({
                    "text": results["documents"][0][i],
                    "source": results["metadatas"][0][i].get("source", "unknown"),
                    "page": results["metadatas"][0][i].get("page", 0),
                    "score": round(similarity, 3),
                    "metadata": results["metadatas"][0][i]
                })
        
        return formatted
    
    # Alias for backward compatibility
    def retrieve_context(self, query: str, n_results: int = 3) -> list[dict]:
        """Alias for search() - backward compatibility."""
        return self.search(query, n_results)
    
    # ----------------------------------------------------------
    # UTILITY METHODS
    # ----------------------------------------------------------
    
    def clear(self) -> None:
        """Clear all documents from the collection."""
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.create_collection(
            name=self.collection_name,
            metadata={"description": "Zed course knowledge base"}
        )
        logger.info("Knowledge base cleared!")
    
    def get_stats(self) -> dict:
        """Get statistics about the knowledge base."""
        count = self.collection.count()
        
        sources = set()
        if count > 0:
            all_docs = self.collection.get(include=["metadatas"])
            sources = set(m.get("source", "unknown") for m in all_docs["metadatas"])
        
        return {
            "total_chunks": count,
            "sources": list(sources),
            "persist_directory": str(self.persist_dir),
            "embedding_model": EMBEDDING_MODEL
        }
    
    @property
    def count(self) -> int:
        """Number of documents in the collection."""
        return self.collection.count()


# ============================================================
# SINGLETON ACCESSOR FUNCTIONS
# ============================================================

def get_knowledge_base() -> KnowledgeBase:
    """
    Get the global KnowledgeBase singleton instance.
    
    This is the recommended way to access the knowledge base.
    Thread-safe and ensures only one ChromaDB connection.
    
    Usage:
        from app.services.knowledge import get_knowledge_base
        
        kb = get_knowledge_base()
        results = kb.search("What is the midterm worth?")
    """
    return KnowledgeBase()


def retrieve_context(query: str, n_results: int = 3) -> list[dict]:
    """
    Quick retrieval function for backward compatibility.
    
    Usage:
        from app.services.knowledge import retrieve_context
        
        results = retrieve_context("What is the midterm worth?")
    """
    return get_knowledge_base().search(query, n_results)


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("🧠 ZED KNOWLEDGE BASE - CLI")
    print("=" * 60)
    
    kb = get_knowledge_base()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "ingest" and len(sys.argv) > 2:
            path = sys.argv[2]
            strategy = sys.argv[3] if len(sys.argv) > 3 else "page"
            
            if os.path.isfile(path):
                count = kb.ingest_pdf(path, chunking_strategy=strategy)
                print(f"✅ Ingested {count} chunks from {path}")
            elif os.path.isdir(path):
                count = kb.ingest_directory(path, chunking_strategy=strategy)
                print(f"✅ Ingested {count} chunks from {path}")
            else:
                print(f"❌ Path not found: {path}")
        
        elif command == "query" and len(sys.argv) > 2:
            query = " ".join(sys.argv[2:])
            results = kb.search(query)
            
            print(f"\n🔍 Query: '{query}'")
            print("-" * 40)
            
            for i, r in enumerate(results, 1):
                print(f"\n📄 Result {i} (score: {r['score']})")
                print(f"   Source: {r['source']}, Page: {r['page']}")
                print(f"   {r['text'][:300]}...")
        
        elif command == "stats":
            stats = kb.get_stats()
            print(f"\n📊 Knowledge Base Stats:")
            print(f"   Total chunks: {stats['total_chunks']}")
            print(f"   Sources: {', '.join(stats['sources']) or 'None'}")
            print(f"   Storage: {stats['persist_directory']}")
            print(f"   Model: {stats['embedding_model']}")
        
        elif command == "clear":
            confirm = input("⚠️ This will delete all data. Type 'yes' to confirm: ")
            if confirm.lower() == 'yes':
                kb.clear()
        
        else:
            print("Usage: python -m app.services.knowledge [ingest|query|stats|clear]")
    
    else:
        print("\n📊 Stats:", kb.get_stats())
        print("\nEnter queries to test retrieval (Ctrl+C to exit):")
        
        while True:
            try:
                query = input("\n🔍 Query: ").strip()
                if not query:
                    continue
                
                results = kb.search(query)
                
                for i, r in enumerate(results, 1):
                    print(f"\n--- Result {i} (score: {r['score']}) ---")
                    print(f"Source: {r['source']}, Page: {r['page']}")
                    print(r['text'][:400])
                    
            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break

