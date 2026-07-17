# -*- coding: utf-8 -*-
"""Small dependency-free loader for Render Secret Files.

Render mounts uploaded secret files at /etc/secrets/<filename> at runtime.
This module reads simple KEY=VALUE files before the application reads os.environ.
Existing environment variables always win over file values.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

# Presentation Studio v105 bootstrap. This import hook is installed before
# main.py imports presentation_studio, so no monolithic source rewrite is needed.
try:
    from presentation_v105_patch import install_import_hook, patch_main_version_async
    install_import_hook()
    patch_main_version_async()
except Exception:
    # Secrets must remain available even if an optional presentation patch fails.
    pass

_LOADED_SOURCES: dict[str, str] = {}
_BOOTSTRAPPED = False
_PRESENTATION_V106_PATCHED = False
_PRESENTATION_V107_PATCHED = False

DEFAULT_SECRET_PATHS = (
    "/etc/secrets/runway.env",
    "/etc/secrets/runway.txt",
    "/etc/secrets/neyro_bot.env",
    "/etc/secrets/neyrobot.env",
    "/etc/secrets/ai_providers.env",
    "/etc/secrets/providers.env",
    # Compatibility: the user already has this Secret File in Render.
    # It is safe to append RUNWAYML_API_SECRET to it if creating a second file is inconvenient.
    "/etc/secrets/yookassa.env",
    # Native Render services also expose secret files from the service root.
    "runway.env",
    "runway.txt",
    "neyro_bot.env",
    "neyrobot.env",
    "ai_providers.env",
    "providers.env",
    "yookassa.env",
)


def _strip_wrapping_quotes(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def parse_secret_file(path: str | os.PathLike[str]) -> dict[str, str]:
    """Parse a tiny .env-like file without shell expansion.

    Supported:
      KEY=value
      export KEY=value
      comments and blank lines

    A file containing only a raw key_... token is treated as RUNWAYML_API_SECRET.
    """
    p = Path(path)
    try:
        raw_text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return {}

    stripped = raw_text.strip()
    if stripped.startswith("key_") and "=" not in stripped and "\n" not in stripped:
        return {"RUNWAYML_API_SECRET": stripped}

    result: dict[str, str] = {}
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            continue
        value = _strip_wrapping_quotes(value)
        if value:
            result[key] = value
    return result


def bootstrap_secret_environment(paths: Iterable[str] | None = None) -> dict[str, str]:
    """Load values from existing secret files into os.environ once.

    Environment variables already set by Render have priority and are never overwritten.
    Returns a mapping of loaded key -> source path.
    """
    global _BOOTSTRAPPED, _PRESENTATION_V106_PATCHED, _PRESENTATION_V107_PATCHED
    candidates = tuple(paths or DEFAULT_SECRET_PATHS)
    for path in candidates:
        parsed = parse_secret_file(path)
        if not parsed:
            continue
        for key, value in parsed.items():
            if not (os.environ.get(key) or "").strip():
                os.environ[key] = value
                _LOADED_SOURCES[key] = str(path)
    _BOOTSTRAPPED = True

    # v105 has already installed its import hook above. Importing the studio here
    # applies v105 first; v106 then safely patches the resulting class before
    # main.py imports PresentationStudio. No automatic brief-finalization remains.
    if not _PRESENTATION_V106_PATCHED:
        try:
            import presentation_studio as _presentation_studio
            from presentation_v106_patch import patch_main_version_async, patch_module
            patch_module(_presentation_studio)
            patch_main_version_async()
            _PRESENTATION_V106_PATCHED = True
        except Exception:
            # Secret loading and the rest of the bot must remain operational even
            # if an optional presentation enhancement cannot be installed.
            pass

    # v107 must be installed after v106 so final visual/style/palette additions
    # are intercepted before the multipart main-brief collector can see them.
    if not _PRESENTATION_V107_PATCHED:
        try:
            import presentation_studio as _presentation_studio
            from presentation_v107_patch import patch_main_version_async, patch_module
            patch_module(_presentation_studio)
            patch_main_version_async()
            _PRESENTATION_V107_PATCHED = True
        except Exception:
            pass

    return dict(_LOADED_SOURCES)


def get_secret(*names: str) -> tuple[str, str]:
    """Return the first non-empty value and a safe source label."""
    if not _BOOTSTRAPPED:
        bootstrap_secret_environment()
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            source_path = _LOADED_SOURCES.get(name)
            if source_path:
                return value, f"Secret File: {Path(source_path).name}"
            return value, f"Environment: {name}"
    return "", "—"


def secret_source(name: str) -> str:
    """Return a safe source label for a specific key, without exposing its value."""
    if not _BOOTSTRAPPED:
        bootstrap_secret_environment()
    source_path = _LOADED_SOURCES.get(name)
    if source_path:
        return f"Secret File: {Path(source_path).name}"
    if (os.environ.get(name) or "").strip():
        return f"Environment: {name}"
    return "—"
