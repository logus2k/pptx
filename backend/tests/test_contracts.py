"""The socket.io contract (contracts/socket-events.schema.json) against the code: the server handles exactly its client
events and emits only its server events. The names are read from the source with Python's own parser (ast): the
@sio.event handlers' names, and the first argument of every sio.emit / self.emit call."""

from __future__ import annotations

import ast
import json

from .conftest import REPO

BACKEND = REPO / "backend" / "app"
CONTRACT = json.loads((REPO / "contracts" / "socket-events.schema.json").read_text(encoding="utf-8"))
CONNECTION = {"connect", "disconnect"}  # socket.io's own


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def test_the_server_handles_exactly_the_contract_s_client_events():
    handled = set()
    for node in ast.walk(_tree(BACKEND / "main.py")):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and any(
            isinstance(d, ast.Attribute) and d.attr == "event" for d in node.decorator_list
        ):
            handled.add(node.name)
    assert handled - CONNECTION == set(CONTRACT["client_to_server"])


def test_the_server_emits_only_the_contract_s_server_events():
    emitted = set()
    for path in [BACKEND / "main.py", *(BACKEND / "agent").glob("*.py")]:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "emit" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    emitted.add(first.value)
    # the waiting cards are emitted by kind (loop.py _wait): question, plan, instructions_proposed
    emitted |= {"question", "plan", "instructions_proposed"}
    assert emitted <= set(CONTRACT["server_to_client"]), emitted - set(CONTRACT["server_to_client"])
    assert set(CONTRACT["server_to_client"]) <= emitted, set(CONTRACT["server_to_client"]) - emitted
