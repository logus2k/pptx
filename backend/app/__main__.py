"""python -m app: the server (app/main.py)."""

# logging first (Banco CTT's standard: app/telemetry.py), before the libraries are imported and log
from app import telemetry

telemetry.setup("server")

import logging  # noqa: E402
import sys  # noqa: E402

from app import config  # noqa: E402

try:
    settings = config.load()
except config.ConfigError as e:
    logging.getLogger("slides").error(f"cannot start: {e}")
    sys.exit(2)

from app.main import main  # noqa: E402

main(settings)
