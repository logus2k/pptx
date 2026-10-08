# Replay one recorded assistant call with its "## Now" hint as sent and as the new place() words it; N runs each.
import asyncio, json, sys
sys.path.insert(0, "backend")
from app.agent import llm, tools as T
cfg = json.load(open("config/config.json"))
M = llm.Models(cfg["services"]["agent_server"], cfg["services"]["tokenizer"]); M.register_presets(); model = M.local()
defs = T.definitions(T.load_schemas())
src, rid, old, new, n = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
r = json.load(open(src)); items = r if isinstance(r, list) else r.get("results") or r
if isinstance(items, dict) and "turns" in items:  # a scenario report: its first turn
    call = [c for c in items["turns"][0]["calls"] if c.get("preset") == "slides_assistant"][0]
else:
    x = [i for i in items if i.get("id") == rid][0]
    call = [c for c in x["calls"] if c.get("preset") == "slides_assistant"][0]
sysm = call["messages"][0]["content"]
assert old in sysm, "old hint not in the recorded call"
offered = [d for d in defs if d["function"]["name"] in call["tools"]]
async def once(s):
    out = {}
    async for ch in M.stream(model, "slides_assistant", [{**call["messages"][0], "content": s}, call["messages"][1]], offered):
        for tc in ((ch.get("choices") or [{}])[0].get("delta") or {}).get("tool_calls") or []:
            k = tc.get("index", 0); f = tc.get("function") or {}
            d = out.setdefault(k, {"name": "", "args": ""}); d["name"] += f.get("name") or ""; d["args"] += f.get("arguments") or ""
    calls = []
    for d in out.values():
        try: a = json.loads(d["args"])
        except ValueError: a = {}
        ops = a.get("operations") or []
        calls.append(f"{d['name']}:{a.get('shape_id')}:{len(ops) or len(a.get('paragraphs') or [])}")
    return ",".join(calls) or "(text)"
async def main():
    for label, s in (("as sent", sysm), ("new", sysm.replace(old, new))):
        res = [await once(s) for _ in range(n)]
        print(label, res)
asyncio.run(main())
