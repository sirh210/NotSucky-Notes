"""A tiny settings file, written the same way notes are.

Preferences are not notes, but losing them should still not be possible by
accident, so the same rules apply: write atomically, never raise at the call
site, and treat an unreadable file as "no preferences yet" rather than an
error to report. A settings file is never worth blocking a launch over.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from notsucky.utils.paths import notes_dir

logger = logging.getLogger(__name__)

SETTINGS_FILENAME = "settings.json"

_cache: dict[str, Any] | None = None


def settings_path() -> Path:
    """Beside the notes directory, not inside it — it is not a note."""
    return notes_dir(create=False).parent / SETTINGS_FILENAME


def load_settings(*, refresh: bool = False) -> dict[str, Any]:
    """Read the settings file, tolerating anything that is not usable."""
    global _cache
    if _cache is not None and not refresh:
        return _cache

    path = settings_path()
    data: dict[str, Any] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data = raw
        else:
            logger.warning("Ignoring settings file: expected an object")
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.warning("Ignoring unreadable settings file: %s", exc)

    _cache = data
    return data


def save_settings(values: dict[str, Any]) -> bool:
    """Atomically write settings. Returns False if it could not be saved."""
    global _cache
    _cache = dict(values)

    path = settings_path()
    tmp_path: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".settings.")
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(values, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    except OSError as exc:
        # A preference that will not stick is a nuisance, not a failure.
        logger.warning("Could not save settings: %s", exc)
        return False
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):  # best-effort cleanup
                os.unlink(tmp_path)
    return True


def get_setting(key: str, default: Any = None) -> Any:
    return load_settings().get(key, default)


def set_setting(key: str, value: Any) -> bool:
    values = dict(load_settings())
    values[key] = value
    return save_settings(values)


def reset_cache() -> None:
    """Drop the in-memory copy. For tests, and after the store moves."""
    global _cache
    _cache = None
