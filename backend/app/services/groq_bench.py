"""
groq_bench.py - Benchmark ZED's Full Pipeline

Tests the actual integrations:
1. Groq Whisper (Speech-to-Text) 
2. ChromaDB RAG retrieval
3. Groq LLM response generation
4. ElevenLabs TTS (optional)

Provides latency and tokens/second for each component.
"""

import os
import time
import io
import wave
import struct
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv
from groq import Groq

load_dotenv()


@dataclass
class PipelineResult:
    """Results from a full pipeline benchmark."""
    # Timing (seconds)
    stt_time: float = 0.0           # Speech-to-text
    retrieval_time: float = 0.0      # RAG retrieval
    llm_time: float = 0.0            # LLM generation
    llm_ttft: float = 0.0            # Time to first token
    tts_time: float = 0.0            # Text-to-speech (if tested)
    total_time: float = 0.0
    
    # Tokens
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tokens_per_second: float = 0.0
    
    # Content
    transcription: str = ""
    context_chunks: list = field(default_factory=list)
    response: str = ""
    
    def __str__(self):
        return f"""
╔══════════════════════════════════════════════════════════╗
║                    ZED PIPELINE BENCHMARK                 ║
╠══════════════════════════════════════════════════════════╣
║ 🎤 Speech-to-Text (Whisper):     {self.stt_time*1000:>8.0f} ms           ║
║ 📚 RAG Retrieval (ChromaDB):     {self.retrieval_time*1000:>8.0f} ms           ║
║ 🧠 LLM Generation (Groq):        {self.llm_time*1000:>8.0f} ms           ║
║    └─ Time to first token:       {self.llm_ttft*1000:>8.0f} ms           ║
║    └─ Tokens/second:             {self.tokens_per_second:>8.1f} tok/s       ║
║ 🔊 Text-to-Speech (ElevenLabs):  {self.tts_time*1000:>8.0f} ms           ║
╠══════════════════════════════════════════════════════════╣
║ ⏱️  TOTAL PIPELINE:              {self.total_time*1000:>8.0f} ms           ║
╚══════════════════════════════════════════════════════════╝
"""


class ZEDBenchmark:
    """Benchmark ZED's actual pipeline components."""
    
    def __init__(self):
        self.groq = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        
        # Test prompts simulating real student questions
        self.test_questions = [
            "What is the midterm worth?",
            "Explain recursion in simple terms",
            "What are the key topics for the final exam?",
            "How does backpropagation work?",
            "What is the difference between supervised and unsupervised learning?",
        ]
    
    def _generate_test_audio(self, text: str = "What is the midterm worth?") -> io.BytesIO:
        """
        Generate a simple test audio file (silence with metadata).
        In real usage, this would be actual recorded audio.
        """
        # Create a short silent WAV file for testing STT latency
        sample_rate = 16000
        duration = 1.5  # seconds
        num_samples = int(sample_rate * duration)
        
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            # Write near-silence (very quiet noise to avoid "empty audio" errors)
            samples = struct.pack('<' + 'h' * num_samples, *([10] * num_samples))
            wf.writeframes(samples)
        
        buffer.name = "test_audio.wav"
        buffer.seek(0)
        return buffer
    
    def benchmark_stt(self, audio_buffer: io.BytesIO = None) -> tuple[float, str]:
        """
        Benchmark Groq Whisper speech-to-text.
        
        Returns: (time_seconds, transcription)
        """
        if audio_buffer is None:
            audio_buffer = self._generate_test_audio()
        
        start = time.perf_counter()
        
        try:
            result = self.groq.audio.transcriptions.create(
                file=audio_buffer,
                model="distil-whisper-large-v3-en",
                response_format="json",
                language="en",
                temperature=0.0
            )
            transcription = result.text
        except Exception as e:
            transcription = f"[STT Error: {e}]"
        
        elapsed = time.perf_counter() - start
        return elapsed, transcription
    
    def benchmark_retrieval(self, query: str) -> tuple[float, list]:
        """
        Benchmark ChromaDB RAG retrieval.
        
        Returns: (time_seconds, context_chunks)
        """
        try:
            from app.services.knowledge import retrieve_context
            
            start = time.perf_counter()
            chunks = retrieve_context(query, n_results=3)
            elapsed = time.perf_counter() - start
            
            return elapsed, chunks
        except Exception as e:
            return 0.0, [{"text": f"[Retrieval Error: {e}]", "source": "error"}]
    
    def benchmark_llm(
        self, 
        query: str, 
        context: list = None,
        model: str = "llama-3.1-8b-instant"
    ) -> tuple[float, float, int, str]:
        """
        Benchmark Groq LLM response generation.
        
        Returns: (total_time, ttft, completion_tokens, response)
        """
        # Build prompt with context
        if context:
            context_text = "\n".join([
                f"[{c.get('source', 'unknown')}]: {c.get('text', '')[:300]}"
                for c in context if isinstance(c, dict)
            ])
            system_prompt = f"""You are ZED, an AI study assistant. Use the following course context to help answer the student's question. Be concise and helpful.

COURSE CONTEXT:
{context_text}

If the context doesn't contain relevant information, say so and provide general guidance."""
        else:
            system_prompt = "You are ZED, an AI study assistant. Be concise and helpful."
        
        start = time.perf_counter()
        first_token_time = None
        response_text = ""
        
        stream = self.groq.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            max_tokens=256,
            stream=True,
        )
        
        for chunk in stream:
            if first_token_time is None and chunk.choices[0].delta.content:
                first_token_time = time.perf_counter()
            if chunk.choices[0].delta.content:
                response_text += chunk.choices[0].delta.content
        
        end = time.perf_counter()
        
        total_time = end - start
        ttft = (first_token_time - start) if first_token_time else total_time
        # Estimate tokens (~4 chars per token)
        completion_tokens = len(response_text) // 4
        
        return total_time, ttft, completion_tokens, response_text
    
    def benchmark_tts(self, text: str) -> float:
        """
        Benchmark ElevenLabs TTS (time to start streaming).
        
        Returns: time_seconds (time to first audio chunk)
        """
        try:
            from elevenlabs.client import ElevenLabs
            
            client = ElevenLabs(api_key=os.environ.get("ELEVEN_API_KEY"))
            
            start = time.perf_counter()
            
            # Just measure time to get first chunk, don't play
            audio_stream = client.text_to_speech.stream(
                text=text[:100],  # Short text for speed test
                voice_id="21m00Tcm4TlvDq8ikWAM",
                model_id="eleven_turbo_v2_5",
            )
            
            # Get first chunk
            first_chunk = next(iter(audio_stream))
            elapsed = time.perf_counter() - start
            
            return elapsed
        except Exception as e:
            print(f"   ⚠️ TTS benchmark skipped: {e}")
            return 0.0
    
    def run_full_pipeline(
        self, 
        query: str = None,
        include_stt: bool = False,
        include_tts: bool = False,
        model: str = "llama-3.1-8b-instant"
    ) -> PipelineResult:
        """
        Run a full pipeline benchmark.
        
        Args:
            query: Question to test (random if None)
            include_stt: Whether to benchmark STT (requires audio)
            include_tts: Whether to benchmark TTS
            model: Groq model to use
        """
        import random
        
        if query is None:
            query = random.choice(self.test_questions)
        
        result = PipelineResult()
        pipeline_start = time.perf_counter()
        
        print(f"\n🔍 Query: \"{query}\"")
        print("-" * 50)
        
        # 1. Speech-to-Text (optional)
        if include_stt:
            print("🎤 Testing STT...")
            result.stt_time, result.transcription = self.benchmark_stt()
            print(f"   ✓ {result.stt_time*1000:.0f}ms")
        else:
            result.transcription = query
        
        # 2. RAG Retrieval
        print("📚 Testing RAG retrieval...")
        result.retrieval_time, result.context_chunks = self.benchmark_retrieval(query)
        print(f"   ✓ {result.retrieval_time*1000:.0f}ms ({len(result.context_chunks)} chunks)")
        
        # 3. LLM Generation
        print(f"🧠 Testing LLM ({model})...")
        result.llm_time, result.llm_ttft, result.completion_tokens, result.response = \
            self.benchmark_llm(query, result.context_chunks, model)
        
        # Calculate tokens/second
        generation_time = result.llm_time - result.llm_ttft
        result.tokens_per_second = result.completion_tokens / generation_time if generation_time > 0 else 0
        
        print(f"   ✓ {result.llm_time*1000:.0f}ms (TTFT: {result.llm_ttft*1000:.0f}ms, {result.tokens_per_second:.0f} tok/s)")
        
        # 4. Text-to-Speech (optional)
        if include_tts and result.response:
            print("🔊 Testing TTS...")
            result.tts_time = self.benchmark_tts(result.response)
            print(f"   ✓ {result.tts_time*1000:.0f}ms")
        
        result.total_time = time.perf_counter() - pipeline_start
        
        return result
    
    def run_benchmark_suite(self, runs: int = 3, model: str = "llama-3.1-8b-instant"):
        """Run multiple benchmarks and show averages."""
        print("=" * 60)
        print("🚀 ZED PIPELINE BENCHMARK SUITE")
        print("=" * 60)
        
        results = []
        
        for i, query in enumerate(self.test_questions[:runs]):
            print(f"\n--- Run {i+1}/{runs} ---")
            result = self.run_full_pipeline(query=query, model=model)
            results.append(result)
        
        # Calculate averages
        avg_retrieval = sum(r.retrieval_time for r in results) / len(results)
        avg_llm = sum(r.llm_time for r in results) / len(results)
        avg_ttft = sum(r.llm_ttft for r in results) / len(results)
        avg_tps = sum(r.tokens_per_second for r in results) / len(results)
        avg_total = sum(r.total_time for r in results) / len(results)
        
        print("\n" + "=" * 60)
        print("📊 AVERAGE RESULTS")
        print("=" * 60)
        print(f"  RAG Retrieval:     {avg_retrieval*1000:>8.0f} ms")
        print(f"  LLM Total:         {avg_llm*1000:>8.0f} ms")
        print(f"  LLM TTFT:          {avg_ttft*1000:>8.0f} ms")
        print(f"  Tokens/second:     {avg_tps:>8.0f} tok/s")
        print(f"  Total Pipeline:    {avg_total*1000:>8.0f} ms")
        print("=" * 60)
        
        return results


def quick_test(query: str = "What is the midterm worth?"):
    """Quick single pipeline test."""
    bench = ZEDBenchmark()
    result = bench.run_full_pipeline(query=query)
    print(result)
    return result


if __name__ == "__main__":
    import sys
    
    print("🔥 ZED Pipeline Benchmark")
    print("-" * 40)
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "suite":
            # Full benchmark suite
            bench = ZEDBenchmark()
            bench.run_benchmark_suite(runs=5)
        elif sys.argv[1] == "tts":
            # Include TTS in test
            bench = ZEDBenchmark()
            result = bench.run_full_pipeline(include_tts=True)
            print(result)
        elif sys.argv[1] == "full":
            # Full pipeline with STT and TTS
            bench = ZEDBenchmark()
            result = bench.run_full_pipeline(include_stt=True, include_tts=True)
            print(result)
        else:
            # Custom query
            query = " ".join(sys.argv[1:])
            quick_test(query)
    else:
        print("\nUsage:")
        print("  python -m app.services.groq_bench                    - Quick single test")
        print("  python -m app.services.groq_bench suite              - Run 5 benchmark iterations")
        print("  python -m app.services.groq_bench tts                - Include TTS benchmark")
        print("  python -m app.services.groq_bench full               - Full pipeline (STT + TTS)")
        print("  python -m app.services.groq_bench \"your question\"    - Test specific question")
        print("\nRunning quick test...\n")
        quick_test()
