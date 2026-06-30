import asyncio
import json
from app.redis_client import enqueue_index_job

async def enqueue_test_job():
    job_data = {
        "job_id": "test-job-123",
        "repo_id": "0132f57f-8cf5-4e4a-92b7-f71014feb4a0",
        "repo_path": "C:\\Users\\Jayachandran\\ProjectsAndDocs\\atlas\\backend",
        "job_type": "incremental"
    }
    
    print(f"Enqueueing job: {job_data}")
    await enqueue_index_job(job_data)
    print("Job enqueued successfully!")

if __name__ == "__main__":
    asyncio.run(enqueue_test_job())
