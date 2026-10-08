"""The app's configuration: the environment (secrets, paths, port) and the administrators' configuration file
(technical design section 1.2), validated at start-up against contracts/config.schema.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import jsonschema

REPO_DIR = Path(__file__).resolve().parents[2]  # the repository (frontend/, contracts/, config/)


class ConfigError(Exception):
    """The configuration cannot be used: the app refuses to start."""


@dataclass(frozen=True)
class Settings:
    """Everything the app reads from outside, resolved once."""

    env: str  # ENVS: dev | test | preprod | prod | local
    port: int
    data_dir: Path
    frontend_dir: Path
    proxy_secret: str  # "" = no check (development only)
    dev_user: str  # stands in for the proxy's identity when there is no secret (development only)
    file: dict  # the configuration file, validated
    cortex_key: str = ""  # SLIDES_CORTEX_SERVICE_KEY: the Knowledge Base's service key ("" = no KB)

    @property
    def administrators(self) -> frozenset[str]:
        return frozenset(a.strip().lower() for a in self.file["administrators"])

    @property
    def templates_dir(self) -> Path:
        return Path(self.file["templates_dir"])


# dev and test: development; preprod and prod: behind the proxy (prod refuses to run without its secret); local: on a
# person's own computer, without a proxy
ENVS = ("dev", "test", "preprod", "prod", "local")


def _check_file(data: dict) -> None:
    schema = json.loads((REPO_DIR / "contracts" / "config.schema.json").read_text(encoding="utf-8"))
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "(top level)"
        raise ConfigError(f"configuration file: {where}: {e.message}") from None
    # what the schema says in words (no patterns): plain string checks
    url = data["public_url"]
    if not (url.startswith(("http://", "https://")) and url.endswith("/")):
        raise ConfigError("configuration file: public_url must start with http:// or https:// and end with /")


def load(environ: dict[str, str] | None = None) -> Settings:
    """Read the environment and the configuration file; raise ConfigError when either cannot be used."""
    e = os.environ if environ is None else environ
    env = (e.get("SLIDES_ENV") or "dev").strip().lower()
    path = Path(e.get("SLIDES_CONFIG_FILE") or REPO_DIR / "config" / "config.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"configuration file not found: {path}") from None
    except json.JSONDecodeError as ex:
        raise ConfigError(f"configuration file {path} is not JSON: {ex}") from None
    _check_file(data)
    secret = (e.get("SLIDES_PROXY_SECRET") or "").strip()
    dev_user = (e.get("SLIDES_DEV_USER") or "").strip().lower()
    if env not in ENVS:
        raise ConfigError(f"SLIDES_ENV must be one of {', '.join(ENVS)} (it is {env!r})")
    if env == "local":
        # a Slides on a person's own computer (security review L4, the user's choice): no proxy, so the person is
        # SLIDES_DEV_USER; only on a localhost address (the compose file publishes the port on 127.0.0.1 only: the
        # container cannot see how its port is published)
        from urllib.parse import urlsplit

        if urlsplit(data["public_url"]).hostname not in ("localhost", "127.0.0.1"):
            raise ConfigError("SLIDES_ENV=local needs a public_url on localhost or 127.0.0.1")
        if not dev_user:
            raise ConfigError("SLIDES_ENV=local needs SLIDES_DEV_USER: the person using it (there is no proxy to say)")
        if secret:
            raise ConfigError("SLIDES_ENV=local has no proxy: leave SLIDES_PROXY_SECRET empty")
    if env == "prod" and not secret:
        raise ConfigError(
            "SLIDES_PROXY_SECRET is required when SLIDES_ENV=prod: without it anyone reaching the port could claim any identity"
        )
    if env == "prod" and dev_user:
        raise ConfigError("SLIDES_DEV_USER is refused when SLIDES_ENV=prod")
    try:
        port = int(e.get("SLIDES_PORT") or "2720")
    except ValueError:
        raise ConfigError("SLIDES_PORT must be a number") from None
    return Settings(
        env=env,
        port=port,
        data_dir=Path(e.get("SLIDES_DATA_DIR") or REPO_DIR / "data"),
        frontend_dir=Path(e.get("SLIDES_FRONTEND_DIR") or REPO_DIR / "frontend"),
        proxy_secret=secret,
        dev_user=dev_user,
        file=data,
        cortex_key=(e.get("SLIDES_CORTEX_SERVICE_KEY") or "").strip(),
    )
