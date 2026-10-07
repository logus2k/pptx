"""The app as `python -m app` starts it, with every request to the model written to $SCENARIO_CALLS (one JSON line a
call: preset, messages, the tools offered), so a scenario's turns can be read with what the model was given."""

from app import telemetry

telemetry.setup("server")

import json  # noqa: E402
import os  # noqa: E402

import uvicorn  # noqa: E402

from app import config, main  # noqa: E402
from app.agent.llm import Models  # noqa: E402

settings = config.load()
services = settings.file.get("services", {})
models = Models(
    services.get("agent_server", "http://agent_server:7701"), services.get("tokenizer", "http://llama-vision:8500/tokenize")
)
stream = models.stream
out = open(os.environ["SCENARIO_CALLS"], "a", encoding="utf-8")  # noqa: SIM115 - for the server's lifetime


def recording(model, preset, messages, tools, max_tokens=None):
    out.write(json.dumps({"preset": preset, "messages": messages, "tools": [d["function"]["name"] for d in tools or []]},
                         ensure_ascii=False) + "\n")  # fmt: skip
    out.flush()
    return stream(model, preset, messages, tools, max_tokens)


models.stream = recording
uvicorn.run(main.create_app(settings, models=models), host="127.0.0.1", port=settings.port, log_level="warning", log_config=None)
