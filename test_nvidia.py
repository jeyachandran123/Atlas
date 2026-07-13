import sys, asyncio
sys.stdout.write("start\n"); sys.stdout.flush()

from app.config import Settings
from openai import AsyncOpenAI

async def test():
    s = Settings()
    sys.stdout.write(f"provider={s.llm_provider} model={s.nvidia_chat_model}\n"); sys.stdout.flush()
    c = AsyncOpenAI(base_url=s.nvidia_base_url, api_key=s.nvidia_api_key.get_secret_value())

    # non-stream test
    try:
        r = await c.chat.completions.create(
            model=s.nvidia_chat_model,
            messages=[{"role": "user", "content": "say hi in 3 words"}],
            max_tokens=20, stream=False,
        )
        sys.stdout.write(f"non-stream: {r.choices[0].message.content}\n"); sys.stdout.flush()
    except Exception as e:
        sys.stdout.write(f"non-stream ERROR: {e}\n"); sys.stdout.flush()

    # stream test
    try:
        stream = await c.chat.completions.create(
            model=s.nvidia_chat_model,
            messages=[{"role": "user", "content": "say hi in 3 words"}],
            max_tokens=20, stream=True,
        )
        sys.stdout.write("stream chunks: "); sys.stdout.flush()
        async for chunk in stream:
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            reasoning = getattr(delta, "reasoning_content", None)
            if content:
                sys.stdout.write(f"[C:{repr(content)}]"); sys.stdout.flush()
            elif reasoning:
                sys.stdout.write(f"[R:{len(reasoning)}chars]"); sys.stdout.flush()
        sys.stdout.write("\nstream done\n"); sys.stdout.flush()
    except Exception as e:
        sys.stdout.write(f"stream ERROR: {e}\n"); sys.stdout.flush()

asyncio.run(test())
sys.stdout.write("end\n"); sys.stdout.flush()
