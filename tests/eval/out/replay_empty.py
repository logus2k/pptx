import asyncio, json, sys
sys.path.insert(0, "backend")
from app.agent import llm, tools as T
cfg = json.load(open("config/config.json"))
M = llm.Models(cfg["services"]["agent_server"], cfg["services"]["tokenizer"]); M.register_presets(); model = M.local()
defs = T.definitions(T.load_schemas())
t = json.load(open("tests/scenarios/out/20261007-183932/first-use-index-from-kb-3.json"))["turns"][1]
c = [c for c in t["calls"] if c.get("preset") == "slides_assistant"][0]
offered = [d for d in defs if d["function"]["name"] in c["tools"]]
WHERE = '(where: 1: "(none)")'
s = c["messages"][0]["content"]; assert WHERE in s
ADD = WHERE + "\nSlide 1 has no text yet: write what the request asks on it (fill_slide), not on a new slide, unless the person asks for a new one."
async def calls(sysm):
    # the first two tool calls (a search first, then the edit): the search's recorded result is fed back
    msgs = [{**c["messages"][0], "content": sysm}] + c["messages"][1:]
    names = []
    for _ in range(2):
        out = {}
        async for ch in M.stream(model, "slides_assistant", msgs, offered):
            for tc in ((ch.get("choices") or [{}])[0].get("delta") or {}).get("tool_calls") or []:
                d = out.setdefault(tc.get("index", 0), {"id": tc.get("id") or "x", "name": "", "args": ""})
                f = tc.get("function") or {}; d["name"] += f.get("name") or ""; d["args"] += f.get("arguments") or ""
        if not out: break
        first = out[min(out)]
        try: a = json.loads(first["args"])
        except ValueError: a = {}
        names.append(f"{first['name']}:{a.get('slide_id', a.get('after_slide_id', '-'))}")
        if first["name"] != "kb_search": break
        rec = t["calls"][-1]["messages"]
        kb_ids = {tc["id"] for m in rec if m["role"] == "assistant" for tc in m.get("tool_calls") or [] if tc["function"]["name"] == "kb_search"}
        result = next(m["content"] for m in rec if m["role"] == "tool" and m.get("tool_call_id") in kb_ids)
        names.append(f"(result {len(result)} chars)") if False else None
        msgs = msgs + [{"role": "assistant", "content": "", "tool_calls": [{"id": first["id"], "type": "function", "function": {"name": first["name"], "arguments": first["args"]}}]},
                       {"role": "tool", "tool_call_id": first["id"], "content": result}]
    return " > ".join(names)
async def main():
    for label, sysm in (("as sent", s), ("empty slide named", s.replace(WHERE, ADD))):
        res = [await calls(sysm) for _ in range(int(sys.argv[1]))]
        print(label, {x: res.count(x) for x in set(res)})
asyncio.run(main())
