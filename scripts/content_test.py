# -*- coding: utf-8 -*-
"""Offline test: content the model cannot receive is refused with HTTP 400, never dropped.

    python3 scripts/content_test.py

Needs only what the gateway itself needs (no accounts, no network, no running gateway, no httpx). The model call is replaced by a fake, so
the test also checks that refused requests never reach Antigravity and that text + images still go through."""
import asyncio
import atexit
import base64
import json
import os
import shutil
import sys
import tempfile

os.environ["AGY_ROOT"] = tempfile.mkdtemp(prefix="acp-ant-test-")
atexit.register(shutil.rmtree, os.environ["AGY_ROOT"], True)
os.environ["AGY_GATEWAY_KEY"] = "test-key"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]   # source checkout (scripts/..) or next to acp_ant.py

import acp_ant as gw  # noqa: E402

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 16).decode()
MP4 = base64.b64encode(b"\0\0\0\x18ftypmp42" + b"\0" * 16).decode()
PDF = base64.b64encode(b"%PDF-1.4 test").decode()
WAV = base64.b64encode(b"RIFF\0\0\0\0WAVEfmt ").decode()
TXT = base64.b64encode("Secret code: 4817".encode()).decode()

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name, "" if cond else "  -> " + str(detail)[:300]))


def refused(name, fn, *words):
    try:
        out = fn()
    except gw.BadContent as e:
        msg = str(e)
        check(name, all(w in msg for w in words), "message lacks %s: %s" % (words, msg))
        return e
    check(name, False, "not refused, got %r" % (out,))
    return None


def oa(*parts, role="user"):
    return {"model": "gemini-3.8-flash", "messages": [{"role": role, "content": list(parts)}]}


def uri(mime, data):
    return "data:%s;base64,%s" % (mime, data)


# ---- OpenAI Chat Completions parser -------------------------------------------------------------------------------
_s, msgs, _t, _c = gw.from_openai(oa({"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {"url": uri("image/png", PNG)}}))
check("openai: text + data-URI image kept", [p["type"] for p in msgs[0]["parts"]] == ["text", "image"], msgs)
e = refused("openai: file part with video/mp4 refused", lambda: gw.from_openai(oa(
    {"type": "text", "text": "break this video down"}, {"type": "file", "file": {"file_data": uri("video/mp4", MP4), "filename": "a.mp4"}})),
    '"file"', "video/mp4", "messages[0].content[1]")
check("openai: refusal names the parameter", e is not None and e.param == "messages[0].content[1]", e and e.param)
refused("openai: input_audio refused", lambda: gw.from_openai(oa({"type": "input_audio", "input_audio": {"data": WAV, "format": "wav"}})),
        '"input_audio"')
refused("openai: video_url refused", lambda: gw.from_openai(oa({"type": "video_url", "video_url": {"url": "https://x/v.mp4"}})), '"video_url"')
refused("openai: unknown part type refused", lambda: gw.from_openai(oa({"type": "something_new"})), '"something_new"')
refused("openai: image_url carrying a video data URI refused", lambda: gw.from_openai(oa({"type": "image_url", "image_url": {"url": uri("video/mp4", MP4)}})),
        "video/mp4")
refused("openai: PDF file refused", lambda: gw.from_openai(oa({"type": "file", "file": {"file_data": uri("application/pdf", PDF)}})), "application/pdf")
refused("openai: file by file_id refused", lambda: gw.from_openai(oa({"type": "file", "file": {"file_id": "file-123"}})), "file_id")
refused("openai: unreadable image reference refused", lambda: gw.from_openai(oa({"type": "image_url", "image_url": {"url": "file-abc"}})), "data: URI")
refused("openai: image in a system message refused", lambda: gw.from_openai(oa({"type": "image_url", "image_url": {"url": uri("image/png", PNG)}}, role="system")),
        "only contain text")
_s, msgs, _t, _c = gw.from_openai(oa({"type": "file", "file": {"file_data": uri("image/png", PNG)}}))
check("openai: file part holding an image becomes an image", msgs[0]["parts"][0]["type"] == "image", msgs)
_s, msgs, _t, _c = gw.from_openai(oa({"type": "file", "file": {"file_data": uri("text/plain", TXT), "filename": "note.txt"}}))
check("openai: plain-text file becomes text", "Secret code: 4817" in msgs[0]["parts"][0].get("text", ""), msgs)
_s, msgs, _t, _c = gw.from_openai({"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": [{"type": "refusal", "refusal": "no"}]}]})
check("openai: assistant refusal part kept as text", msgs[1]["parts"] == [{"type": "text", "text": "no"}], msgs)
_s, msgs, _t, _c = gw.from_openai({"messages": [{"role": "user", "content": "plain string"}]})
check("openai: plain string content unchanged", msgs[0]["parts"] == [{"type": "text", "text": "plain string"}], msgs)


# ---- Anthropic Messages parser -------------------------------------------------------------------------------------
def an(*blocks):
    return {"model": "claude-sonnet-5-5", "max_tokens": 100, "messages": [{"role": "user", "content": list(blocks)}]}


refused("anthropic: PDF document refused", lambda: gw.from_anthropic(an(
    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": PDF}})), "application/pdf", "messages.0.content.0")
refused("anthropic: document by URL refused", lambda: gw.from_anthropic(an({"type": "document", "source": {"type": "url", "url": "https://x/a.pdf"}})),
        '"url"')
refused("anthropic: document by file_id refused", lambda: gw.from_anthropic(an({"type": "document", "source": {"type": "file", "file_id": "f"}})), '"file"')
refused("anthropic: image with a video media_type refused", lambda: gw.from_anthropic(an(
    {"type": "image", "source": {"type": "base64", "media_type": "video/mp4", "data": MP4}})), "video/mp4")
refused("anthropic: image by file_id refused", lambda: gw.from_anthropic(an({"type": "image", "source": {"type": "file", "file_id": "f"}})), '"file"')
refused("anthropic: unknown block refused", lambda: gw.from_anthropic(an({"type": "container_upload", "file_id": "f"})), '"container_upload"')
refused("anthropic: PDF inside a tool_result refused", lambda: gw.from_anthropic({"messages": [
    {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "read", "input": {}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": PDF}}]}]}]}), "application/pdf", "messages.1.content.0.content.0")
_s, msgs, _t, _c = gw.from_anthropic(an({"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": "Secret code: 4817"}},
                                        {"type": "text", "text": "what is the code?"}))
check("anthropic: plain-text document kept", "Secret code: 4817" in gw._joined_text(msgs[0]["parts"]), msgs)
_s, msgs, _t, _c = gw.from_anthropic(an({"type": "document", "source": {"type": "content", "content": [
    {"type": "text", "text": "page one"}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}]}}))
check("anthropic: content document kept (text + image)", [p["type"] for p in msgs[0]["parts"]] == ["text", "image"], msgs)
_s, msgs, _t, _c = gw.from_anthropic(an({"type": "search_result", "source": "https://x", "title": "T", "content": [{"type": "text", "text": "found it"}]}))
check("anthropic: search_result kept as text", "found it" in gw._joined_text(msgs[0]["parts"]), msgs)
_s, msgs, _t, _c = gw.from_anthropic({"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": [
    {"type": "thinking", "thinking": "hmm", "signature": "s"}, {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {}},
    {"type": "web_search_tool_result", "tool_use_id": "s1", "content": []}, {"type": "text", "text": "answer"}]}]})
check("anthropic: model-made history blocks still skipped", msgs[1]["parts"] == [{"type": "text", "text": "answer"}], msgs)
refused("anthropic: image in system refused", lambda: gw.from_anthropic({"system": [
    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}], "messages": [{"role": "user", "content": "q"}]}), "system")


# ---- OpenAI Responses parser ---------------------------------------------------------------------------------------
def rs(*parts):
    return {"model": "gemini-3.8-flash", "input": [{"type": "message", "role": "user", "content": list(parts)}]}


refused("responses: input_file PDF refused", lambda: gw.from_responses(rs({"type": "input_file", "filename": "a.pdf", "file_data": uri("application/pdf", PDF)})),
        "application/pdf", "input[0].content[0]")
refused("responses: input_file by file_id refused", lambda: gw.from_responses(rs({"type": "input_file", "file_id": "file-1"})), "file_id")
refused("responses: input_audio refused", lambda: gw.from_responses(rs({"type": "input_audio", "input_audio": {"data": WAV, "format": "wav"}})), '"input_audio"')
refused("responses: input_image by file_id refused", lambda: gw.from_responses(rs({"type": "input_image", "file_id": "file-1"})), "file_id")
_s, msgs, _t, _c, _x = gw.from_responses(rs({"type": "input_text", "text": "hi"}, {"type": "input_image", "image_url": uri("image/png", PNG)}))
check("responses: text + image kept", [p["type"] for p in msgs[0]["parts"]] == ["text", "image"], msgs)
_s, msgs, _t, _c, _x = gw.from_responses(rs({"type": "input_file", "filename": "n.md", "file_data": uri("text/markdown", TXT)}))
check("responses: markdown file becomes text", "4817" in gw._joined_text(msgs[0]["parts"]), msgs)

# ---- remote image links --------------------------------------------------------------------------------------------
check("sniff: png / jpeg / webp / not an image", (gw._sniff_image(b"\x89PNG\r\n\x1a\nxxxx"), gw._sniff_image(b"\xff\xd8\xff\xe0"),
                                                gw._sniff_image(b"RIFF\0\0\0\0WEBPVP8 "), gw._sniff_image(b"\0\0\0\x18ftypmp42"))
      == ("image/png", "image/jpeg", "image/webp", None))
gw.FETCH_IMAGES = False
_s, msgs, _t, _c = gw.from_openai(oa({"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}))
refused("links: image link refused when downloads are off", lambda: asyncio.run(gw.fetch_remote_images(msgs)), "AGY_FETCH_IMAGES=0", "messages[0].content[0]")
gw.FETCH_IMAGES = True


def _not_an_image(url):
    raise ValueError("the link is not an image (Content-Type video/mp4)")


real_fetch, gw._fetch_image = gw._fetch_image, _not_an_image
_s, msgs, _t, _c = gw.from_openai(oa({"type": "image_url", "image_url": {"url": "https://example.com/v.mp4"}}))
refused("links: link that is not an image refused", lambda: asyncio.run(gw.fetch_remote_images(msgs)), "not an image", "video/mp4")

# ---- HTTP: error formats, and refused requests never reach the model ----------------------------------------------
calls = []


async def fake_generate(model_name, system, blocks, effort_override=None):
    calls.append(blocks)
    yield "text", "ok", "fake"
    yield "usage", '{"inputTokens": 10, "outputTokens": 1}', "fake"


class Resp:
    def __init__(self, status, body):
        self.status_code, self.text = status, body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)


async def _asgi_post(path, body, headers):
    """POST straight into the ASGI app (no server, no httpx; startup events do not run, so no account is touched)."""
    raw = json.dumps(body).encode()
    hdrs = [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]
    hdrs += [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http", "path": path,
             "raw_path": path.encode(), "query_string": b"", "root_path": "", "headers": hdrs, "client": ("127.0.0.1", 1), "server": ("test", 80)}
    state = {"sent": False, "status": None, "body": []}

    async def receive():
        if not state["sent"]:
            state["sent"] = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await asyncio.sleep(3600)

    async def send(msg):
        if msg["type"] == "http.response.start":
            state["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            state["body"].append(msg.get("body", b""))
    await gw.app(scope, receive, send)
    return Resp(state["status"], b"".join(state["body"]))


class Client:
    def post(self, path, headers, json):
        return asyncio.run(_asgi_post(path, json, headers))


gw.generate = fake_generate
client = Client()
H = {"Authorization": "Bearer test-key"}

r = client.post("/v1/chat/completions", headers=H, json=oa({"type": "text", "text": "describe"},
                                                            {"type": "file", "file": {"file_data": uri("video/mp4", MP4)}}))
j = r.json()
check("http chat: 400 OpenAI error naming the part", r.status_code == 400 and j["error"]["type"] == "invalid_request_error"
      and j["error"]["code"] == "unsupported_content" and j["error"]["param"] == "messages[0].content[1]" and '"file"' in j["error"]["message"], (r.status_code, j))
r = client.post("/v1/chat/completions", headers=H, json=dict(oa({"type": "input_audio", "input_audio": {"data": WAV, "format": "wav"}}), stream=True))
check("http chat stream: 400 before streaming starts", r.status_code == 400 and '"input_audio"' in r.json()["error"]["message"], (r.status_code, r.text[:200]))
r = client.post("/v1/messages", headers=H, json=an({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": PDF}}))
j = r.json()
check("http messages: 400 Anthropic error", r.status_code == 400 and j["type"] == "error" and j["error"]["type"] == "invalid_request_error"
      and "application/pdf" in j["error"]["message"], (r.status_code, j))
r = client.post("/v1/messages/count_tokens", headers=H, json=an({"type": "document", "source": {"type": "url", "url": "https://x/a.pdf"}}))
check("http count_tokens: 400 Anthropic error", r.status_code == 400 and r.json()["type"] == "error", (r.status_code, r.text[:200]))
r = client.post("/v1/responses", headers=H, json=rs({"type": "input_audio", "input_audio": {"data": WAV, "format": "wav"}}))
j = r.json()
check("http responses: 400 OpenAI error", r.status_code == 400 and j["error"]["param"] == "input[0].content[0]", (r.status_code, j))
check("refused requests never reached the model", calls == [], len(calls))

r = client.post("/v1/chat/completions", headers=H, json=oa({"type": "text", "text": "what is this?"},
                                                            {"type": "image_url", "image_url": {"url": uri("image/png", PNG)}}))
sent = calls[-1] if calls else []
check("http chat: text + image still answered", r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "ok"
      and any(b["type"] == "image" and b["mimeType"] == "image/png" for b in sent), (r.status_code, r.text[:200]))
r = client.post("/v1/messages", headers=H, json=an({"type": "text", "text": "hello"}))
check("http messages: plain text still answered", r.status_code == 200 and r.json()["content"][0]["text"] == "ok", (r.status_code, r.text[:200]))
gw._fetch_image = real_fetch

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
