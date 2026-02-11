"""Lightweight error logging for in-app diagnostics."""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
import traceback

from flask import current_app


def record_exception(context: str, exc: BaseException) -> None:
    """Append exception details to data/logs/app_errors.log for offline inspection."""

    try:
        root = Path(current_app.config["DATA_ROOT"]) / "logs"
        root.mkdir(parents=True, exist_ok=True)
        log_path = root / "app_errors.log"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now(UTC).isoformat()}Z] {context}\n")
            handle.write("".join(traceback.format_exception(exc)))
            handle.write("\n")
    except Exception:
        # Never let logging failures break the request cycle.
        pass
