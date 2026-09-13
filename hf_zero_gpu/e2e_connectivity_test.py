"""End-to-end connectivity test: local -> HF Space (ZeroGPU) -> result.

Creates a 4-second/16-kHz mono WAV, uploads it to the Space's Gradio API,
queues /infer, and streams the SSE result. Usage:
    python e2e_connectivity_test.py [space_url]
"""
import json
import math
import struct
import sys
import urllib.request
import uuid
import wave

SPACE = (sys.argv[1] if len(sys.argv) > 1
         else "https://devanshshar01-satyavoice-gpu.hf.space").rstrip("/")
API = f"{SPACE}/gradio_api"
SAMPLE_RATE = 16000
DURATION_S = 4


def make_wav(path: str) -> str:
    w = wave.open(path, "w")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SAMPLE_RATE)
    frames = b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * 220 * t / SAMPLE_RATE)))
        for t in range(SAMPLE_RATE * DURATION_S)
    )
    w.writeframes(frames)
    w.close()
    return path


def multipart_upload(path: str) -> str:
    boundary = uuid.uuid4().hex
    data = open(path, "rb").read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{path}"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{API}/upload", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=60).read())[0]


def queue_infer(server_path: str) -> str:
    payload = {"data": [{"path": server_path, "meta": {"_type": "gradio.FileData"}}]}
    req = urllib.request.Request(
        f"{API}/call/infer", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=60).read())["event_id"]


def stream_result(event_id: str, timeout_s: int = 600) -> str:
    res = urllib.request.urlopen(
        f"{API}/call/infer/{event_id}", timeout=timeout_s)
    buf = b""
    while True:
        chunk = res.read(1)
        if not chunk:
            break
        buf += chunk
        if b"data:" in buf and buf.rstrip().endswith(b"}"):
            break
    return buf.decode(errors="replace")


if __name__ == "__main__":
    print(f"[1/4] Creating 4s/16kHz/mono WAV ...", end=" ", flush=True)
    wav = make_wav("e2e_test.wav")
    print("ok")
    print(f"[2/4] Uploading to {API}/upload ...", end=" ", flush=True)
    server_path = multipart_upload(wav)
    print(f"ok -> {server_path}")
    print(f"[3/4] Queuing /infer ...", end=" ", flush=True)
    eid = queue_infer(server_path)
    print(f"ok -> event_id={eid}")
    print("[4/4] Streaming result (first GPU call may take minutes for model download) ...")
    print(stream_result(eid))
