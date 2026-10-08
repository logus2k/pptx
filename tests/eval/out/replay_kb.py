import asyncio, json, sys
sys.path.insert(0, "backend")
from app.agent import llm, tools as T
cfg = json.load(open("config/config.json"))
M = llm.Models(cfg["services"]["agent_server"], cfg["services"]["tokenizer"]); M.register_presets(); model = M.local()
defs = T.definitions(T.load_schemas())
def call(f):
    r = json.load(open(f)); t = r["turns"][1]
    return [c for c in t["calls"] if c.get("preset") == "slides_assistant"][0]
A = call("tests/scenarios/out/20261007-134802/a-slide-from-the-kb-with-its-source-2.json")
B = call("tests/scenarios/out/20261007-134802/a-slide-from-the-kb-with-its-source-4.json")
offered = [d for d in defs if d["function"]["name"] in B["tools"]]
async def first(msgs):
    names = []
    async for ch in M.stream(model, "slides_assistant", msgs, offered):
        for tc in ((ch.get("choices") or [{}])[0].get("delta") or {}).get("tool_calls") or []:
            if (tc.get("function") or {}).get("name"): names.append(tc["function"]["name"])
    return names[0] if names else "(text)"
bs = B["messages"][0]["content"]
wa, wb = "(where: slide 1: «crédito habitação jovem»)", "(where: slide 1: «o crédito habitação jovem»)"
assert wb in bs
OLD = "Do it now by calling your tools, writing the text yourself from the request and what you find (never filler); then say in one sentence what you changed."
NEW = ("Do it now by calling your tools. Facts about the organisation's products, conditions, policies, processes or "
       "figures come from the knowledge base: kb_search for them first and write from what it finds; anything else, "
       "write yourself from the request (never filler). Then say in one sentence what you changed.")
assert OLD in bs
def now(msgs): return [{**msgs[0], "content": msgs[0]["content"].replace(OLD, NEW)}] + msgs[1:]
variants = {
    "B as sent": B["messages"],
    "B with A's where": [{**B["messages"][0], "content": bs.replace(wb, wa)}] + B["messages"][1:],
    "B without where": [{**B["messages"][0], "content": bs.replace(" " + wb, "")}] + B["messages"][1:],
    "B with A's turn 1": [B["messages"][0]] + A["messages"][1:],
}
variants = {k: v for k, v in variants.items() if k in ("B without where", "B with A's turn 1")}
variants.update({k + " + new Now": now(v) for k, v in list(variants.items())})
async def main():
    for k, m in variants.items():
        res = [await first(m) for _ in range(int(sys.argv[1]))]
        print(k, {x: res.count(x) for x in set(res)})
asyncio.run(main())
