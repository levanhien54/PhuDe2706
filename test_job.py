# -*- coding: utf-8 -*-
import httpx
import time
resp = httpx.post("http://127.0.0.1:8000/api/dub/son.mp4")
print(resp.json())
job_id = resp.json()["job_id"]
while True:
    time.sleep(5)
    st = httpx.get(f"http://127.0.0.1:8000/api/status/son.mp4").json()
    if st.get("status") in ("AWAITING_REVIEW", "COMPLETED", "FAILED"):
        print("Final:", st)
        if st.get("status") == "AWAITING_REVIEW":
            print("Resuming...")
            httpx.post(f"http://127.0.0.1:8000/api/jobs/{job_id}/resume")
        elif st.get("status") in ("COMPLETED", "FAILED"):
            break
    print("Status:", st.get("status"))
