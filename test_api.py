# import base64
# import mimetypes
# import os
# import time

# import requests

# URL = "https://8001-dep-01m2557me92ezh0h028hvke7cg-d.cloudspaces.litng.ai/predict"
# KEY = "86bbf8d7e88ccb5e33f3200511d4d774"

# # Change these to real files on your PC
# LOCAL_IMAGE = r"C:\Users\Jayachandran\ProjectsAndDocs\Projects\Unityworks_vision_AI\vision-os-data\candidates\p9-live\v1\live-20260827-a\cam-13\cam-13_092955_860.jpg"
# EXCEL_FILE = r"C:\Users\Jayachandran\ProjectsAndDocs\Projects\docs\Vision os product usecase\grocery-shopping-list.xlsx"
# EXCEL_MAX_ROWS = 50  # large sheets won't fit in the model's context


# def call_api(name, payload):
#     print(f"\n===== {name} =====")
#     start = time.time()
#     try:
#         r = requests.post(URL, headers={"X-API-Key": KEY}, json=payload, timeout=300)
#         print(f"Status: {r.status_code}  ({time.time() - start:.1f}s)")
#         print(r.json().get("output", r.text) if r.ok else r.text)
#     except Exception as e:
#         print("FAILED:", e)


# def image_to_data_uri(path):
#     mime = mimetypes.guess_type(path)[0] or "image/jpeg"
#     with open(path, "rb") as f:
#         return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


# # 1. Text only
# call_api("1. Text", {"prompt": "Explain what an IP address is in 2 sentences."})

# # 2. Image from a public URL (replace with any public image link)
# call_api("2. Image URL", {
#     "prompt": "Describe this image in 3 sentences.",
#     "image_url": "https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demonstration_1.png",
# })

# # 3. Image from your PC (sent as base64)
# if os.path.exists(LOCAL_IMAGE):
#     call_api("3. Local image", {
#         "prompt": "Describe this image. If it contains text, read out the text.",
#         "image_url": image_to_data_uri(LOCAL_IMAGE),
#     })
# else:
#     print("\n===== 3. Local image ===== SKIPPED (set LOCAL_IMAGE to a real file)")

# # 4. Excel file (converted to text on your PC, then sent in the prompt)
# if os.path.exists(EXCEL_FILE):
#     import pandas as pd  # pip install pandas openpyxl

#     df = pd.read_excel(EXCEL_FILE)
#     table_text = df.head(EXCEL_MAX_ROWS).to_csv(index=False)
#     call_api("4. Excel", {
#         "prompt": (
#             f"Here is data from an Excel sheet (first {EXCEL_MAX_ROWS} rows, CSV format):\n\n"
#             f"{table_text}\n\n"
#             "Summarize what this data contains and point out any notable patterns."
#         ),
#         "max_new_tokens": 700,
#     })
# else:
#     print("\n===== 4. Excel ===== SKIPPED (set EXCEL_FILE to a real file)")

# import os
# import requests

# INVOKE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# api_key = "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"

# if not api_key:
#     raise RuntimeError("NVIDIA_API_KEY environment variable is not set")

# headers = {
#     "Authorization": f"Bearer {api_key}",
#     "Accept": "application/json",
#     "Content-Type": "application/json",
# }

# payload = {
#     "model": "nvidia/ising-calibration-1.5-31b",
#     "messages": [
#         {
#             "role": "user",
#             "content": [
#                 {
#                     "type": "image_url",
#                     "image_url": {
#                         "url": "https://assets.ngc.nvidia.com/products/api-catalog/ising-calibration-1-35b-a3b/resonator_spectroscopy.png"
#                     },
#                 },
#                 {
#                     "type": "text",
#                     "text": """Hi"""
#                 },
#             ],
#         }
#     ],
#     "max_tokens": 4096,
#     "temperature": 1.0,
#     "top_p": 0.95,
#     "stream": False,
# }

# response = requests.post(
#     INVOKE_URL,
#     headers=headers,
#     json=payload,
#     timeout=120,
# )

# response.raise_for_status()

# result = response.json()

# print("\n===== MODEL RESPONSE =====\n")

# print(result["choices"][0]["message"]["content"])








import os
import requests
from openai import OpenAI

# ============================================================
# NVIDIA Nemotron 3 Ultra 550B A55B - General Reasoning Test
# ============================================================


API_KEY = "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"
if not API_KEY:
    raise RuntimeError("NVIDIA_API_KEY environment variable is not set")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=API_KEY,
)

prompt = """
You are being tested as a general-purpose AI assistant.

Answer the following questions carefully:

1. Explain what caused the Apollo 11 Moon landing to become possible,
   including the major technological and scientific developments
   that led to it.

2. What happened during the Apollo 11 mission from launch to landing
   and return to Earth? Give a concise chronological explanation.

3. Explain the difference between:
   - a black hole's event horizon
   - the singularity
   - the accretion disk

4. Now answer this reasoning question:

   If humanity discovered a planet 50 light-years away today and
   observed that an intelligent civilization there destroyed itself
   in a nuclear war, could that civilization still exist at the
   present time from their own perspective?

   Explain the answer using the finite speed of light.

5. Finally, clearly separate:
   - facts you are highly confident about
   - things that depend on assumptions
   - information you cannot know without access to current/live data

Do not use the internet.
Do not pretend to have real-time information.
Focus on accuracy and reasoning.
"""

print("=" * 70)
print("NVIDIA NEMOTRON 3 ULTRA 550B A55B")
print("GENERAL REASONING TEST")
print("=" * 70)

completion = client.chat.completions.create(
    model="nvidia/nemotron-3-ultra-550b-a55b",

    messages=[
        {
            "role": "user",
            "content": prompt
        }
    ],

    temperature=0.2,
    top_p=0.95,
    max_tokens=16384,

    extra_body={
        "chat_template_kwargs": {
            "enable_thinking": False
        }
    },

    stream=True
)

print("\n===== MODEL REASONING =====\n")

reasoning_started = False
answer_started = False

for chunk in completion:

    if not chunk.choices:
        continue

    delta = chunk.choices[0].delta

    # Print reasoning tokens
    reasoning = getattr(delta, "reasoning_content", None)

    if reasoning:
        if not reasoning_started:
            print("[Thinking]\n")
            reasoning_started = True

        print(reasoning, end="", flush=True)

    # Print final answer
    if delta.content is not None:

        if not answer_started:
            print("\n\n" + "=" * 70)
            print("===== FINAL ANSWER =====")
            print("=" * 70 + "\n")

            answer_started = True

        print(delta.content, end="", flush=True)

print("\n\n" + "=" * 70)
print("TEST COMPLETE")
print("=" * 70)



# import os
# from openai import OpenAI

# # ============================================================
# # NVIDIA DeepSeek V4 Pro 0813 - General Reasoning Test
# # ============================================================

# API_KEY = "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"

# if not API_KEY:
#     raise RuntimeError("NVIDIA_API_KEY environment variable is not set")

# client = OpenAI(
#     base_url="https://integrate.api.nvidia.com/v1",
#     api_key=API_KEY,
# )

# prompt = """
# You are being evaluated as a general-purpose AI assistant.

# Complete the following benchmark carefully.

# ### 1. General Knowledge

# Explain why the Earth's sky appears blue during the daytime.
# Explain the physics involved, but keep it understandable.

# ### 2. Physics Reasoning

# Imagine two identical clocks.

# Clock A remains on Earth.
# Clock B travels at 99% of the speed of light for a long journey
# and then returns to Earth.

# When they meet again, will the clocks show the same elapsed time?

# Explain why or why not using special relativity.
# Do not just give the answer — explain the reasoning.

# ### 3. Computer Science

# Explain the difference between:

# - CPU
# - GPU
# - RAM
# - VRAM

# Then explain why large AI models are generally run on GPUs
# rather than CPUs.

# ### 4. Coding Reasoning

# Consider this Python code:

#     numbers = [1, 2, 3, 4, 5]

#     result = []

#     for x in numbers:
#         if x % 2 == 0:
#             result.append(x * x)

# What is the final value of `result`?

# Then explain exactly how the program reaches that result.

# ### 5. Logical Reasoning

# A farmer has 17 sheep.

# All but 9 of the sheep run away.

# How many sheep remain?

# Explain the wording carefully.

# ### 6. AI Reasoning

# Explain the difference between:

# - training a language model
# - fine-tuning a language model
# - inference
# - retrieval-augmented generation (RAG)

# Give one practical example for each.

# ### 7. Knowledge Boundary Test

# Without using the internet, explain:

# - what information you can reliably know from your training
# - what information may have changed after your training
# - what information requires live/current data

# Do NOT pretend to have real-time information.

# ### 8. Self-Evaluation

# At the end, classify your answers into:

# HIGH CONFIDENCE
# MEDIUM CONFIDENCE
# LOW CONFIDENCE

# Explain briefly why you assigned those confidence levels.

# Important requirements:

# - Think carefully before answering.
# - Prioritize factual accuracy over creativity.
# - Do not use the internet.
# - Do not fabricate facts.
# - If something cannot be determined, explicitly say so.
# """

# print("=" * 70)
# print("NVIDIA DEEPSEEK V4 PRO 0813")
# print("GENERAL + REASONING BENCHMARK")
# print("=" * 70)

# completion = client.chat.completions.create(
#     model="deepseek-ai/deepseek-v4-pro-0813",

#     messages=[
#         {
#             "role": "user",
#             "content": prompt
#         }
#     ],

#     temperature=0.2,
#     top_p=0.95,
#     max_tokens=16384,
#     seed=42,

#     extra_body={
#         "chat_template_kwargs": {
#             "thinking": True
#         }
#     },

#     stream=False,
# )

# message = completion.choices[0].message

# print("\n===== MODEL RESPONSE =====\n")

# # DeepSeek may expose reasoning separately depending
# # on NVIDIA's endpoint configuration.
# reasoning = getattr(message, "reasoning_content", None)

# if reasoning:
#     print("===== REASONING =====\n")
#     print(reasoning)
#     print("\n" + "=" * 70)

# print("===== FINAL ANSWER =====\n")
# print(message.content)

# print("\n" + "=" * 70)
# print("TEST COMPLETE")
# print("=" * 70)


import os
import time
from openai import OpenAI

API_KEY = os.getenv("NVIDIA_API_KEY")

if not API_KEY:
    raise RuntimeError("NVIDIA_API_KEY environment variable is not set")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=API_KEY,
)

prompt = """
Explain in simple terms:

Why is the sky blue?

Give the answer in 5-8 sentences.
Do not overthink the answer.
"""

print("Sending request...")
start = time.time()

completion = client.chat.completions.create(
    model="deepseek-ai/deepseek-v4-pro-0813",

    messages=[
        {
            "role": "user",
            "content": prompt
        }
    ],

    temperature=0.2,
    top_p=0.95,

    # VERY IMPORTANT
    max_tokens=512,

    seed=42,

    extra_body={
        "chat_template_kwargs": {
            "thinking": False
        }
    },

    stream=False,
)

elapsed = time.time() - start

print("\n===== RESPONSE =====\n")
print(completion.choices[0].message.content)

print("\n===== PERFORMANCE =====")
print(f"Time: {elapsed:.2f} seconds")

if completion.usage:
    print(f"Input tokens:  {completion.usage.prompt_tokens}")
    print(f"Output tokens: {completion.usage.completion_tokens}")