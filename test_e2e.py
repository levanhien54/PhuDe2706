import requests
import time
import sys

base_url = "http://localhost:8000"
filename = "test.mp4"
file_path = f"C:/Users/ezycloudx-admin/Downloads/PhuDe27.06/PhuDe27.06/data/input/{filename}"

print("1. Uploading video...")
with open(file_path, "rb") as f:
    res = requests.post(f"{base_url}/api/upload", files={"file": f})
    if res.status_code != 200:
        print(f"Upload failed: {res.text}")
        sys.exit(1)
print(f"Upload successful: {res.json()}")

print("\n2. Starting dubbing job...")
res = requests.post(f"{base_url}/api/dub/{filename}?target_lang=Tiếng Việt&target_style=Tiêu chuẩn&enable_lipsync=false&enable_ocr=true&ocr_mode=blur")
if res.status_code != 200:
    print(f"Start dubbing failed: {res.text}")
    sys.exit(1)
job_id = res.json()["job_id"]
print(f"Job started. ID: {job_id}")

print("\n3. Waiting for processing...")
while True:
    res = requests.get(f"{base_url}/api/status/{filename}")
    if res.status_code == 200:
        data = res.json()
        status = data.get("status")
        print(f"Status: {status}")
        
        if status == "AWAITING_REVIEW":
            print("Phase 1 complete! Automatically resuming Phase 2...")
            res_resume = requests.post(f"{base_url}/api/jobs/{job_id}/resume")
            print(f"Resume: {res_resume.status_code}")
            
        elif status == "COMPLETED":
            print("Job finished successfully!")
            break
        elif status == "FAILED":
            print("Job failed!")
            print(data)
            break
    time.sleep(5)
