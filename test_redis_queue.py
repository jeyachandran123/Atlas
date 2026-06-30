import asyncio
import json
from app.redis_client import get_redis, enqueue_index_job

async def test_queue():
    r = get_redis()
    
    # Test 1: Direct LPUSH
    print("Test 1: Direct LPUSH")
    await r.lpush('queue:index_jobs', json.dumps({'test': 'direct'}))
    length = await r.llen('queue:index_jobs')
    print(f"Queue length after direct push: {length}")
    
    # Test 2: Using enqueue function
    print("\nTest 2: Using enqueue_index_job function")
    await enqueue_index_job({'test': 'function'})
    length = await r.llen('queue:index_jobs')
    print(f"Queue length after function: {length}")
    
    # Test 3: Check what's in the queue
    print("\nTest 3: Queue contents")
    items = await r.lrange('queue:index_jobs', 0, -1)
    for i, item in enumerate(items):
        print(f"Item {i}: {item}")

if __name__ == "__main__":
    asyncio.run(test_queue())
