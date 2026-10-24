"""Configuration: reads settings from environment variables or a local .env file.

The Notion secret is only ever read from the environment. It is excluded from
the Settings repr so it cannot leak into logs or tracebacks.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOTION_VERSION = "2026-03-11"
DEFAULT_STATE_PATH = PROJECT_ROOT / "data" / "state" / "notion_state.json"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
EXTRACTION_PATH = PROJECT_ROOT / "data" / "extracted" / "extraction.json"
PROJECTS_MAPPING_PATH = PROJECT_ROOT / "data" / "mapping" / "projects.json"

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_HEX32_AT_END_RE = re.compile(r"([0-9a-f]{32})$", re.I)


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


def parse_notion_id(value: str) -> str:
    """Return the dashed UUID for a Notion page URL, 32-char ID or UUID.

    Notion URLs end in "<slug>-<32 hex chars>"; the API expects the same ID,
    usually written with dashes. We still verify it against the API before
    writing anything (see check_access.py).
    """
    value = (value or "").strip()
    if not value:
        raise ConfigError("Empty Notion page reference.")
    match = _UUID_RE.search(value)
    if match:
        return match.group(0).lower()
    last_segment = value.split("?")[0].split("#")[0].rstrip("/").split("/")[-1]
    match = _HEX32_AT_END_RE.search(last_segment.replace("-", ""))
    if not match:
        raise ConfigError(f"Could not find a 32-character Notion ID in {value!r}.")
    h = match.group(1).lower()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


@dataclass(frozen=True)
class Settings:
    parent_page_id: str
    token: str | None = field(default=None, repr=False)
    notion_version: str = NOTION_VERSION
    state_path: Path = DEFAULT_STATE_PATH
    log_dir: Path = DEFAULT_LOG_DIR


def load_settings(require_token: bool = True, env_file: Path | None = None) -> Settings:
    """Load and validate settings. Raises ConfigError with a fix-it message."""
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)

    parent_ref = os.getenv("NOTION_PARENT_PAGE", "").strip()
    if not parent_ref:
        raise ConfigError(
            "NOTION_PARENT_PAGE is not set. Copy .env.example to .env and set it to "
            "your Personal HQ page URL."
        )

    token = os.getenv("NOTION_TOKEN", "").strip() or None
    if require_token and not token:
        raise ConfigError(
            "NOTION_TOKEN is not set. Put your integration secret in the .env file "
            "(never in code or chat). Use --offline for a dry run without it."
        )
    if token and (len(token) < 20 or any(ch.isspace() for ch in token)):
        raise ConfigError(
            "NOTION_TOKEN looks malformed (too short or contains spaces). "
            "Re-copy it from https://www.notion.so/profile/integrations."
        )

    state_path = Path(os.getenv("PERSONAL_HQ_STATE", DEFAULT_STATE_PATH))
    return Settings(parent_page_id=parse_notion_id(parent_ref), token=token, state_path=state_path)
