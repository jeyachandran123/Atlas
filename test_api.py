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
import base64
import requests

INVOKE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

LOCAL_IMAGE = r"C:\Users\Jayachandran\ProjectsAndDocs\Projects\Unityworks_vision_AI\vision-os-data\candidates\p9-live\v1\live-20260827-a\cam-13\cam-13_092955_860.jpg"

api_key = "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"

if not api_key:
    raise RuntimeError("NVIDIA_API_KEY environment variable is not set")


def image_to_data_url(path):
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    return f"data:image/jpeg;base64,{encoded}"


image_url = image_to_data_url(LOCAL_IMAGE)

headers = {
    "Authorization": f"Bearer {api_key}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

payload = {
    "model": "nvidia/ising-calibration-1.5-31b",
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image_url
                    },
                },
                {
                    "type": "text",
                    "text": """Analyze this CCTV image.

Tell me:
1. What objects or people are visible?
2. What is happening in the scene?
3. Are there any unusual or potentially important events?
4. Give a concise description of the scene."""
                },
            ],
        }
    ],
    "max_tokens": 4096,
    "temperature": 0.2,
    "top_p": 0.95,
    "stream": False,
}

print("Sending image to NVIDIA...")

response = requests.post(
    INVOKE_URL,
    headers=headers,
    json=payload,
    timeout=120,
)

response.raise_for_status()

result = response.json()

print("\n===== MODEL RESPONSE =====\n")
print(result["choices"][0]["message"]["content"])