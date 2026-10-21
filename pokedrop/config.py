"""Loads stores.yaml and swaps ${ENV_VARS} for real values, so secrets such as
webhook URLs live in GitHub Secrets (or a .env file) rather than in the repo."""
from __future__ import annotations

import os
import re

import yaml

_ENV = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand(value):
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def _load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load(path: str) -> dict:
    _load_dotenv(os.path.join(os.path.dirname(os.path.abspath(path)), ".env"))
    with open(path, encoding="utf-8") as fh:
        cfg = _expand(yaml.safe_load(fh) or {})
    cfg.setdefault("settings", {})
    cfg.setdefault("stores", [])
    rrp_path = os.path.join(os.path.dirname(os.path.abspath(path)), cfg["settings"].get("rrp_file", "rrp.yaml"))
    rrp = {}
    if os.path.exists(rrp_path):
        with open(rrp_path, encoding="utf-8") as fh:
            rrp = yaml.safe_load(fh) or {}
    cfg["rrp"] = rrp
    ids = [s["id"] for s in cfg["stores"]]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"Duplicate store ids in {path}: {', '.join(sorted(dupes))}")
    return cfg
