from __future__ import annotations

import os
import shutil

# hg-dl/ (repo root), independent of process cwd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

SETTINGS_NAME = "settings.json"
CACHE_NAME = "cache.json"
TASKS_NAME = "tasks.json"
FAVORITES_NAME = "favorites.json"
COMPLETED_NAME = "completions.json"

# legacy locations (pre data/ split)
_LEGACY_SETTINGS = (".hg_settings.json",)
_LEGACY_CACHE = (".hg_cache.json",)


def resolve_path(value: str, default_rel: str) -> str:
    """Absolute path; relative values resolve against project root, not cwd."""
    raw = (value or "").strip() or default_rel
    if os.path.isabs(raw):
        return os.path.normpath(raw)
    return os.path.normpath(os.path.join(ROOT, raw))


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _first_existing(candidates: list[str]) -> str | None:
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


def migrate_runtime_files(data_dir: str, out_dir: str) -> None:
    """Move old downloads/.hg_* into data/{settings,cache}.json once."""
    ensure_dir(data_dir)
    settings_dst = os.path.join(data_dir, SETTINGS_NAME)
    cache_dst = os.path.join(data_dir, CACHE_NAME)

    legacy_roots = [
        out_dir,
        os.path.join(ROOT, "downloads"),
        os.path.join(ROOT, "backend", "downloads"),
    ]

    if not os.path.isfile(settings_dst):
        src = _first_existing(
            [os.path.join(r, name) for r in legacy_roots for name in _LEGACY_SETTINGS]
        )
        if src:
            try:
                shutil.move(src, settings_dst)
            except OSError:
                try:
                    shutil.copy2(src, settings_dst)
                except OSError:
                    pass

    if not os.path.isfile(cache_dst):
        src = _first_existing(
            [os.path.join(r, name) for r in legacy_roots for name in _LEGACY_CACHE]
        )
        if src:
            try:
                shutil.move(src, cache_dst)
            except OSError:
                try:
                    shutil.copy2(src, cache_dst)
                except OSError:
                    pass
