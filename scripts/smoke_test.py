# -*- coding: utf-8 -*-
"""Smoke test for a running ACP-Ant gateway: short reply / system prompt / image reading / concurrency.

    python3 scripts/smoke_test.py [image path] [concurrency]

Gateway URL: AGY_GATEWAY_URL (default http://127.0.0.1:8095). Key: AGY_GATEWAY_KEY, or read from
$AGY_ROOT/gateway.env (default /opt/acp-ant/gateway.env). The key is never printed.
Image reading needs ffmpeg (used to shrink the picture)."""
import base64
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("AGY_GATEWAY_URL", "http://127.0.0.1:8095").rstrip("/")
MODEL = os.environ.get("AGY_TEST_MODEL", "gemini-3.8-flash-medium")
KEY = os.environ.get("AGY_GATEWAY_KEY", "")
if not KEY:
    env_file = os.path.join(os.environ.get("AGY_ROOT", "/opt/acp-ant"), "gateway.env")
    with open(env_file) as f:
        KEY = f.read().split("AGY_GATEWAY_KEY=", 1)[1].split("\n", 1)[0].strip()


def call(messages, model=MODEL, timeout=300):
    t = time.time()
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps({"model": model, "messages": messages}).encode(),
                                 headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        return round(time.time() - t, 1), d.get("x_account"), d["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return round(time.time() - t, 1), None, "HTTP %s %s" % (e.code, e.read().decode()[:300])


def small_jpeg(path):
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "scale='min(1536,iw)':-2", "-frames:v", "1", "-q:v", "4",
                          "-f", "image2", "-c:v", "mjpeg", "pipe:1"], capture_output=True).stdout
    return "data:image/jpeg;base64," + base64.b64encode(out).decode()


print("short reply  ", call([{"role": "user", "content": "Reply with exactly one word: OK"}]))
print("system prompt", call([{"role": "system", "content": "Whatever language the user writes in, answer in French, in one sentence."},
                             {"role": "user", "content": "Introduce yourself in one sentence."}]))
if len(sys.argv) > 1:
    img = small_jpeg(sys.argv[1])
    print("image        ", call([{"role": "user", "content": [
        {"type": "text", "text": "Read out every piece of text you can see in this picture, one line each. Do not guess."},
        {"type": "image_url", "image_url": {"url": img}}]}]))
n = int(sys.argv[2]) if len(sys.argv) > 2 else 0
if n:
    t = time.time()
    with cf.ThreadPoolExecutor(n) as ex:
        rs = list(ex.map(lambda i: call([{"role": "user", "content": "Tell me one fun fact about honey in one sentence (#%d)." % i}]), range(n)))
    print("%d concurrent requests, %.1fs total" % (n, time.time() - t))
    for r in rs:
        print("  ", r[0], r[1], r[2][:60].replace("\n", " "))
