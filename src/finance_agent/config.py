"""Runtime configuration loaded from environment variables.

Keeps all deployment-specific values (tokens, paths, model id) in one place so the
rest of the code never reads os.environ directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no dependency on python-dotenv).

    Only sets a key if it is not already present in the environment, so real
    environment variables always win over the file.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    cortensor_api_key: str
    model: str
    db_path: Path
    openminion_config: Path

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"


def load_config() -> Config:
    """Load configuration, reading .env from the project root first."""
    _load_dotenv(_DEFAULT_ROOT / ".env")
    return Config(
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        cortensor_api_key=os.environ.get("CORTENSOR_API_KEY", ""),
        model=os.environ.get("FINANCE_MODEL", "gemma4"),
        db_path=Path(os.environ.get("FINANCE_DB", str(_DEFAULT_ROOT / "finance.db"))),
        openminion_config=Path(
            os.environ.get(
                "OPENMINION_CONFIG", str(_DEFAULT_ROOT / "openminion" / "agents.json")
            )
        ),
    )
