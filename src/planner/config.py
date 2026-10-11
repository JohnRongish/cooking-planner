"""Runtime configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path = Path("./data")
    password: str | None = None
    page_size: str = "Letter"
    port: int = 8080
    base_url: str = ""

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'planner.db'}"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AppConfig:
        e = os.environ if env is None else env
        size = e.get("PLANNER_PAGE_SIZE", "Letter").strip()
        if size.lower() not in ("letter", "a4"):
            raise ValueError("PLANNER_PAGE_SIZE must be Letter or A4")
        return cls(
            data_dir=Path(e.get("PLANNER_DATA_DIR", "./data")),
            password=e.get("PLANNER_PASSWORD") or None,
            page_size="A4" if size.lower() == "a4" else "Letter",
            port=int(e.get("PORT", "8080")),
            base_url=e.get("PLANNER_BASE_URL", "").rstrip("/"),
        )
