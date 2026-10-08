from __future__ import annotations

import json
import os
import threading
from typing import Any

from ..paths import SETTINGS_NAME, ensure_dir

# keys editable from UI / API
EDITABLE = ("hg_api", "http_proxy", "cover_proxy", "cover_token")


class RuntimeSettings:
    """Mutable overlay persisted under DATA_DIR/settings.json."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path = ""
        self.data: dict[str, Any] = {}

    def bind(self, data_dir: str, defaults: dict[str, Any]) -> None:
        ensure_dir(data_dir)
        self._path = os.path.join(data_dir, SETTINGS_NAME)
        loaded: dict[str, Any] = {}
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
                if isinstance(raw, dict):
                    loaded = {k: raw[k] for k in EDITABLE if k in raw}
        except (OSError, ValueError):
            loaded = {}
        with self._lock:
            self.data = {**{k: defaults.get(k, "") for k in EDITABLE}, **loaded}

    def get(self, key: str, default: Any = "") -> Any:
        with self._lock:
            return self.data.get(key, default)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.data)

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            for k, v in patch.items():
                if k not in EDITABLE:
                    continue
                self.data[k] = "" if v is None else str(v).strip()
            snap = dict(self.data)
            path = self._path
        if path:
            try:
                ensure_dir(os.path.dirname(path) or ".")
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(snap, fh, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            except OSError:
                pass
        return snap


R = RuntimeSettings()
