# -*- coding: utf-8 -*-
"""ACP handshake probe: start `agy acp`, send initialize (optionally session/new + one prompt) and print the JSON
that goes back and forth. Useful to see which models / thought levels an account offers.

    HOME=<account dir> HTTPS_PROXY=<proxy> python3 scripts/acp_probe.py [--prompt "Reply with OK"] [--model <id>] [--effort low|medium|high] [--image <path>]

Prints protocol fields only, never credentials."""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

AGY = os.environ.get("AGY_BIN", os.path.join(os.environ.get("AGY_ROOT", "/opt/acp-ant"), "bin", "agy"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt")
    ap.add_argument("--model")
    ap.add_argument("--effort")
    ap.add_argument("--agent")
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--image")
    ap.add_argument("--gemini-dir")
    a = ap.parse_args()
    home = os.environ["HOME"]
    gem = a.gemini_dir or os.path.join(home, ".gemini")
    ws = os.path.join(home, "workspace")
    os.makedirs(ws, exist_ok=True)
    argv = [AGY, "acp", "--gemini-dir", gem, "--disable-telemetry"]
    if a.agent:
        argv += ["--agent", a.agent]
    env = {k: v for k, v in os.environ.items() if k != "DBUS_SESSION_BUS_ADDRESS"}
    p = subprocess.Popen(argv, cwd=ws, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True, bufsize=1)
    pending, notes = {}, []

    def reader():
        for line in p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                print("NONJSON", line[:200]); continue
            if "id" in msg and ("result" in msg or "error" in msg):
                pending[msg["id"]] = msg
            elif "method" in msg and "id" in msg:   # agent -> client request (permission etc.)
                print("AGENT-REQUEST", json.dumps(msg, ensure_ascii=False)[:600])
                resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {"outcome": {"outcome": "cancelled"}}} if msg["method"] == "session/request_permission" \
                    else {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported"}}
                p.stdin.write(json.dumps(resp) + "\n"); p.stdin.flush()
            else:
                notes.append(msg)
    threading.Thread(target=reader, daemon=True).start()
    nid = [0]

    def req(method, params, timeout=a.timeout):
        nid[0] += 1
        i = nid[0]
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}) + "\n"); p.stdin.flush()
        t = time.time()
        while i not in pending:
            if time.time() - t > timeout:
                return {"timeout": True}
            time.sleep(0.05)
        return pending.pop(i)

    t0 = time.time()
    r = req("initialize", {"protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                           "clientInfo": {"name": "acp-ant-probe", "version": "0.1"}}, 60)
    print("INITIALIZE %.1fs" % (time.time() - t0), json.dumps(r, ensure_ascii=False)[:2500])
    if not a.prompt:
        p.terminate(); return
    t1 = time.time()
    r = req("session/new", {"cwd": ws, "mcpServers": []}, 90)
    print("SESSION/NEW %.1fs" % (time.time() - t1), json.dumps(r, ensure_ascii=False)[:3000])
    sid = (r.get("result") or {}).get("sessionId")
    if not sid:
        p.terminate(); return
    if a.model:
        print("SET MODEL", json.dumps(req("session/set_config_option", {"sessionId": sid, "configId": "model", "value": a.model}, 30), ensure_ascii=False)[:600])
    if a.effort:
        print("SET EFFORT", json.dumps(req("session/set_config_option", {"sessionId": sid, "configId": "thought_level", "value": a.effort}, 30), ensure_ascii=False)[:600])
    notes.clear()
    t2 = time.time()
    blocks = [{"type": "text", "text": a.prompt}]
    if a.image:
        import base64 as _b
        out = subprocess.run(["ffmpeg", "-v", "error", "-i", a.image, "-vf", "scale='min(1536,iw)':-2", "-frames:v", "1", "-q:v", "4",
                              "-f", "image2", "-c:v", "mjpeg", "pipe:1"], capture_output=True).stdout
        blocks.append({"type": "image", "mimeType": "image/jpeg", "data": _b.b64encode(out).decode()})

    def watch():
        seen = 0
        while True:
            time.sleep(2)
            new = notes[seen:]
            seen = len(notes)
            for n in new:
                u = (n.get("params") or {}).get("update") or {}
                k = u.get("sessionUpdate")
                if k not in ("agent_message_chunk", "agent_thought_chunk"):
                    print("  +%.0fs UPDATE %s %s" % (time.time() - t2, k, json.dumps(u, ensure_ascii=False)[:300]), flush=True)
    threading.Thread(target=watch, daemon=True).start()
    r = req("session/prompt", {"sessionId": sid, "prompt": blocks})
    text = "".join(((n.get("params") or {}).get("update") or {}).get("content", {}).get("text", "") for n in notes
                   if ((n.get("params") or {}).get("update") or {}).get("sessionUpdate") == "agent_message_chunk")
    kinds = sorted({((n.get("params") or {}).get("update") or {}).get("sessionUpdate") for n in notes})
    print("PROMPT %.1fs" % (time.time() - t2), json.dumps(r, ensure_ascii=False)[:800])
    print("UPDATE KINDS", kinds)
    print("TEXT", repr(text[:500]))
    p.terminate()


if __name__ == "__main__":
    main()
