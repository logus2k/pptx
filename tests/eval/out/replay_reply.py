import asyncio, json, sys
sys.path.insert(0, "backend")
from app.agent import llm, tools as T
cfg = json.load(open("config/config.json"))
M = llm.Models(cfg["services"]["agent_server"], cfg["services"]["tokenizer"]); M.register_presets(); model = M.local()
defs = T.definitions(T.load_schemas())
OLD = "If that is all the request asks, call no tool again: say in one sentence what you changed."
NEW = ("If that is all the request asks, call no tool again: say in one sentence, in the language of the person's "
       "request, what you changed, naming each slide by its number as the person sees it (a new slide: the place it is "
       "now), never by its ID.")
async def text(msgs, offered):
    out = ""
    async for ch in M.stream(model, "slides_assistant", msgs, offered):
        out += ((ch.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
    return out.strip().replace("\n", " ")[:140]
async def main():
    for f, place, sid in (("tests/scenarios/out/20261007-124121/a-chart-from-figures-then-a-value-changed.json", 4, 259),
                          ("tests/scenarios/out/20261007-124121/first-use-index-from-kb.json", 1, 256)):
        t = json.load(open(f))["turns"][0]
        c = [c for c in t["calls"] if c.get("preset") == "slides_assistant"][-1]
        offered = [d for d in defs if d["function"]["name"] in c["tools"]]
        s = c["messages"][0]["content"]; assert OLD in s
        new = s.replace(OLD, NEW).replace(f"new slide · id {sid}", f"new slide, now slide {place} · id {sid}")
        for label, sysm in (("as sent", s), ("new", new)):
            res = [await text([{**c["messages"][0], "content": sysm}] + c["messages"][1:], offered) for _ in range(int(sys.argv[1]))]
            print(f.split("/")[-1][:20], label); [print("   ", r) for r in res]
asyncio.run(main())
