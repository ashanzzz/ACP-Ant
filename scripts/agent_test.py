# -*- coding: utf-8 -*-
"""Checks the parts agents rely on: tool calling (OpenAI tool_calls, Anthropic tool_use and Responses function / custom calls, with and without streaming,
including a full round trip with the tool result), JSON mode and token counting.

    python3 scripts/agent_test.py [model]

Gateway URL: AGY_GATEWAY_URL (default http://127.0.0.1:8095). Key: AGY_GATEWAY_KEY, or read from
$AGY_ROOT/gateway.env (default /opt/acp-ant/gateway.env). The key is never printed."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("AGY_GATEWAY_URL", "http://127.0.0.1:8095").rstrip("/")
MODEL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AGY_TEST_MODEL", "gemini-3.8-flash-medium")
KEY = os.environ.get("AGY_GATEWAY_KEY", "")
if not KEY:
    with open(os.path.join(os.environ.get("AGY_ROOT", "/opt/acp-ant"), "gateway.env")) as f:
        KEY = f.read().split("AGY_GATEWAY_KEY=", 1)[1].split("\n", 1)[0].strip()

WEATHER_OAI = [{"type": "function", "function": {"name": "get_weather", "description": "Current weather for a city",
                                                  "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
WEATHER_ANT = [{"name": "get_weather", "description": "Current weather for a city",
                "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}]
ASK = "What's the weather in Paris right now? Use the tool."
results = []


def post(path, body, headers=None, stream=False):
    h = {"Content-Type": "application/json", "Authorization": "Bearer " + KEY}
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=h)
    r = urllib.request.urlopen(req, timeout=300)
    if not stream:
        return json.load(r)
    return [line.decode().rstrip("\n") for line in r]


def check(name, ok, detail=""):
    results.append(ok)
    print("%s  %-44s %s" % ("PASS" if ok else "FAIL", name, detail))


def run(name, fn):
    t = time.time()
    try:
        fn()
    except urllib.error.HTTPError as e:
        check(name, False, "HTTP %s %s" % (e.code, e.read().decode()[:200]))
    except Exception as e:  # noqa: BLE001
        check(name, False, repr(e)[:200])
    print("      (%.1fs)" % (time.time() - t))


def oai_tool():
    d = post("/v1/chat/completions", {"model": MODEL, "messages": [{"role": "user", "content": ASK}], "tools": WEATHER_OAI})
    ch = d["choices"][0]
    tc = (ch["message"].get("tool_calls") or [{}])[0]
    args = json.loads(tc.get("function", {}).get("arguments") or "{}")
    check("openai: tool_calls", ch["finish_reason"] == "tool_calls" and tc.get("function", {}).get("name") == "get_weather"
          and "paris" in str(args).lower(), str(tc)[:120])
    msgs = [{"role": "user", "content": ASK}, {"role": "assistant", "content": ch["message"].get("content"), "tool_calls": ch["message"]["tool_calls"]},
            {"role": "tool", "tool_call_id": tc["id"], "content": "17°C, light rain"}]
    d = post("/v1/chat/completions", {"model": MODEL, "messages": msgs, "tools": WEATHER_OAI})
    ans = d["choices"][0]["message"].get("content") or ""
    check("openai: answer uses the tool result", d["choices"][0]["finish_reason"] == "stop" and "17" in ans, ans[:100].replace("\n", " "))


def oai_stream():
    lines = post("/v1/chat/completions", {"model": MODEL, "stream": True, "stream_options": {"include_usage": True},
                                          "messages": [{"role": "user", "content": ASK}], "tools": WEATHER_OAI}, stream=True)
    chunks = [json.loads(x[6:]) for x in lines if x.startswith("data: {")]
    calls = [c for ch in chunks for c in (ch.get("choices") or [{}])[0].get("delta", {}).get("tool_calls") or [] if ch.get("choices")]
    finish = [ch["choices"][0]["finish_reason"] for ch in chunks if ch.get("choices") and ch["choices"][0].get("finish_reason")]
    usage = [ch["usage"] for ch in chunks if ch.get("usage")]
    check("openai stream: tool_calls delta + usage", bool(calls) and calls[0]["function"]["name"] == "get_weather" and finish == ["tool_calls"]
          and bool(usage) and "data: [DONE]" in lines, str(calls)[:100])


def oai_json():
    d = post("/v1/chat/completions", {"model": MODEL, "response_format": {"type": "json_object"},
                                      "messages": [{"role": "user", "content": "Give me a JSON object with keys name and age for a fictional person."}]})
    c = d["choices"][0]["message"]["content"]
    try:
        ok = isinstance(json.loads(c), dict)
    except ValueError:
        ok = False
    check("openai: response_format json_object", ok, c[:80])


def ant_tool():
    h = {"x-api-key": KEY, "anthropic-version": "2023-06-01"}
    d = post("/v1/messages", {"model": MODEL, "max_tokens": 1024, "messages": [{"role": "user", "content": ASK}], "tools": WEATHER_ANT}, h)
    tu = next((b for b in d["content"] if b["type"] == "tool_use"), {})
    check("anthropic: tool_use", d["stop_reason"] == "tool_use" and tu.get("name") == "get_weather" and "paris" in str(tu.get("input")).lower(), str(tu)[:120])
    msgs = [{"role": "user", "content": ASK}, {"role": "assistant", "content": d["content"]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tu["id"], "content": "17°C, light rain"}]}]
    d = post("/v1/messages", {"model": MODEL, "max_tokens": 1024, "messages": msgs, "tools": WEATHER_ANT}, h)
    txt = "".join(b.get("text", "") for b in d["content"] if b["type"] == "text")
    check("anthropic: answer uses the tool result", d["stop_reason"] == "end_turn" and "17" in txt, txt[:100].replace("\n", " "))


def ant_stream():
    h = {"x-api-key": KEY, "anthropic-version": "2023-06-01"}
    lines = post("/v1/messages", {"model": MODEL, "max_tokens": 1024, "stream": True, "messages": [{"role": "user", "content": ASK}],
                                  "tools": WEATHER_ANT}, h, stream=True)
    events = [x[7:] for x in lines if x.startswith("event: ")]
    datas = [json.loads(x[6:]) for x in lines if x.startswith("data: ")]
    starts = [d["content_block"] for d in datas if d["type"] == "content_block_start"]
    partial = "".join(d["delta"].get("partial_json", "") for d in datas if d["type"] == "content_block_delta")
    stop = [d["delta"]["stop_reason"] for d in datas if d["type"] == "message_delta"]
    check("anthropic stream: tool_use events", events[0] == "message_start" and events[-1] == "message_stop" and stop == ["tool_use"]
          and any(s["type"] == "tool_use" and s["name"] == "get_weather" for s in starts) and "paris" in partial.lower(), partial[:80])


def ant_count():
    d = post("/v1/messages/count_tokens", {"model": MODEL, "messages": [{"role": "user", "content": "Hello there"}], "tools": WEATHER_ANT},
             {"x-api-key": KEY})
    check("anthropic: count_tokens", isinstance(d.get("input_tokens"), int) and d["input_tokens"] > 0, str(d))


def resp_tool():
    tools = [{"type": "function", "name": "get_weather", "description": "Current weather for a city",
              "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}]
    d = post("/v1/responses", {"model": MODEL, "instructions": "You are a helpful assistant.", "input": [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": ASK}]}], "tools": tools})
    fc = next((o for o in d["output"] if o["type"] == "function_call"), {})
    check("responses: function_call", fc.get("name") == "get_weather" and "paris" in fc.get("arguments", "").lower(), str(fc)[:120])
    d = post("/v1/responses", {"model": MODEL, "input": [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": ASK}]},
        {"type": "function_call", "call_id": fc["call_id"], "name": "get_weather", "arguments": fc["arguments"]},
        {"type": "function_call_output", "call_id": fc["call_id"], "output": "17°C, light rain"}], "tools": tools})
    check("responses: answer uses the tool result", "17" in (d.get("output_text") or ""), (d.get("output_text") or "")[:100].replace("\n", " "))


def resp_custom_stream():
    tools = [{"type": "custom", "name": "write_note", "description": "Save a free-form note. The input is the raw note text."}]
    lines = post("/v1/responses", {"model": MODEL, "stream": True, "input": [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Save a note that says exactly: buy milk"}]}],
        "tools": tools}, stream=True)
    datas = [json.loads(x[6:]) for x in lines if x.startswith("data: ")]
    done = [d["item"] for d in datas if d["type"] == "response.output_item.done"]
    ctc = next((i for i in done if i["type"] == "custom_tool_call"), {})
    check("responses stream: custom tool call", datas[0]["type"] == "response.created" and datas[-1]["type"] == "response.completed"
          and ctc.get("name") == "write_note" and "milk" in ctc.get("input", ""), str(ctc)[:120])


for name, fn in (("openai tools", oai_tool), ("openai stream tools", oai_stream), ("openai json", oai_json),
                 ("anthropic tools", ant_tool), ("anthropic stream tools", ant_stream), ("anthropic count", ant_count),
                 ("responses tools", resp_tool), ("responses custom stream", resp_custom_stream)):
    run(name, fn)
print("\n%d / %d passed (model %s)" % (sum(results), len(results), MODEL))
sys.exit(0 if all(results) else 1)
