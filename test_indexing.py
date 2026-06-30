"""
Test Repository Indexing - Quick Diagnostic

Run this to verify indexing is working:
    py test_indexing.py
"""

import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

async def test_indexing():
    print("=" * 60)
    print("Repository Indexing Diagnostic Test")
    print("=" * 60)
    print()
    
    # Test 1: Check Redis connection
    print("[1/6] Testing Redis connection...")
    try:
        from app.redis_client import get_redis
        r = get_redis()
        await r.ping()
        print("[OK] Redis: Connected")
    except Exception as e:
        print(f"[FAIL] Redis: Failed - {e}")
        return
    
    # Test 2: Check ChromaDB connection
    print("\n[2/6] Testing ChromaDB connection...")
    try:
        from app.vector_store.chroma_client import get_chroma_store
        store = await get_chroma_store()
        print("[OK] ChromaDB: Connected")
    except Exception as e:
        print(f"[FAIL] ChromaDB: Failed - {e}")
        return
    
    # Test 3: Check Ollama connection
    print("\n[3/6] Testing Ollama connection...")
    try:
        from app.ollama_client import get_ollama_client
        ollama = get_ollama_client()
        available, latency = await ollama.health_check()
        if available:
            print(f"[OK] Ollama: Available (latency: {latency}ms)")
        else:
            print("[FAIL] Ollama: Not available")
            return
    except Exception as e:
        print(f"[FAIL] Ollama: Failed - {e}")
        return
    
    # Test 4: Check Database connection
    print("\n[4/6] Testing Database connection...")
    try:
        from app.database import get_db_session
        from sqlalchemy import text
        async with get_db_session() as session:
            await session.execute(text("SELECT 1"))
        print("[OK] Database: Connected")
    except Exception as e:
        print(f"[FAIL] Database: Failed - {e}")
        return
    
    # Test 5: Test embedding generation
    print("\n[5/6] Testing embedding generation...")
    try:
        from app.indexing.embedder import ChunkEmbedder
        from app.shared.schemas import CodeChunk, ChunkType
        embedder = ChunkEmbedder(batch_size=1)
        test_chunk = CodeChunk(
            content="def test(): pass",
            file_path="test.py",
            language="python",
            chunk_type=ChunkType.FUNCTION,
            start_line=1,
            end_line=1,
            repo_id="test",
            file_hash="test"
        )
        result = await embedder.embed_chunks([test_chunk])
        if result and len(result) > 0 and len(result[0][1]) > 0:
            print(f"[OK] Embeddings: Working ({len(result[0][1])} dimensions)")
        else:
            print("[FAIL] Embeddings: Failed to generate")
            return
    except Exception as e:
        print(f"[FAIL] Embeddings: Failed - {e}")
        return
    
    # Test 6: Check if worker is needed
    print("\n[6/6] Checking worker status...")
    queue_len = await r.llen("queue:index_jobs")
    print(f"Jobs in queue: {queue_len}")
    
    if queue_len > 0:
        print("\n[WARNING] WORKER NEEDED!")
        print("Jobs are waiting in queue but not being processed.")
        print("\nStart worker with:")
        print("  cd backend")
        print("  py -m app.workers.index_worker")
    else:
        print("[OK] No jobs in queue")
    
    print("\n" + "=" * 60)
    print("All systems operational!")
    print("=" * 60)
    print("\nTo test indexing:")
    print("1. Go to http://localhost:3000/repos")
    print("2. Click 'Connect Repository'")
    print("3. Add a repository path")
    print("4. Check progress API or worker logs")

if __name__ == "__main__":
    asyncio.run(test_indexing())
