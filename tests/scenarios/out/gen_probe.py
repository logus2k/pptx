import asyncio, json, sys, time, traceback
sys.path.insert(0, "backend")
from app import config
from app.main import Services
from app.agent import outline
s = config.load({"SLIDES_CONFIG_FILE": "config/config.json", "SLIDES_DATA_DIR": "/tmp/probe", "SLIDES_FRONTEND_DIR": "frontend",
                 "SLIDES_CORTEX_SERVICE_KEY": __import__("os").environ.get("SLIDES_CORTEX_SERVICE_KEY", "")})
app = Services(s)
model = app.models.local()
t0 = time.monotonic()
async def progress(stage, done, total): print(f"{time.monotonic()-t0:7.1f}s {stage} {done}/{total}", flush=True)
async def go():
    try:
        r = await outline.draft(app, model, "antonio.s.cruz@bancoctt.pt", "p", {"kind": "kb_topic", "query": "crédito habitação jovem"},
                                kind="corporate", slides=6, language="pt", progress=progress)
        print("done", time.monotonic()-t0, r["read"], [x["title"] for x in r["slides"]])
    except Exception:
        traceback.print_exc()
asyncio.run(go())
