"""Plugin system for agent type hook installers.

Built-in plugins live in this package (aque/plugins/*.py).
User plugins live in ~/.aque/plugins/*.py.
Module name = type name (claude.py -> --type claude).
"""

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType


log = logging.getLogger(__name__)


# Capability vocabulary recognised by the launch coordinator and plugin loader.
# Top-level public callables in a plugin module whose names aren't in this set
# get a warn-log at load time — catches typos like ``presign`` vs ``preassign``
# without requiring an explicit ``CAPABILITIES`` list (which would be a second
# source of truth that can drift from the actual methods).
_HOOK_CAPABILITY: frozenset[str] = frozenset({
    "is_installed",
    "install_hook",
})

# Session capture is all-or-nothing: a plugin that exposes ``preassign``
# without ``resume_command`` would launch agents that can never resume.
# ``has_session_capture`` enforces the bundle.
_CAPTURE_CAPABILITY: frozenset[str] = frozenset({
    "preassign",
    "summarize",
    "resume_command",
})

# The vocabulary the warn-log recognises. Anything else at module top level
# (public, callable, defined locally) gets a warning so typos like
# ``presign`` vs ``preassign`` surface at plugin load time.
KNOWN_CAPABILITIES: frozenset[str] = (
    _HOOK_CAPABILITY | _CAPTURE_CAPABILITY | frozenset({"existing_uuids"})
)


def has_session_capture(plugin: ModuleType | None) -> bool:
    """True when ``plugin`` exposes the full session-capture bundle.

    Single predicate for every dispatch site in ``LaunchCoordinator`` —
    structurally rules out the divergence where one branch treats a type as
    capture-capable and another doesn't.
    """
    if plugin is None:
        return False
    return all(
        callable(getattr(plugin, name, None)) for name in _CAPTURE_CAPABILITY
    )


def _load_module_from_path(name: str, path: Path) -> ModuleType | None:
    """Load a Python module from a file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _has_hook_bundle(module: ModuleType) -> bool:
    return all(
        callable(getattr(module, name, None)) for name in _HOOK_CAPABILITY
    )


def _is_valid_plugin(module: ModuleType) -> bool:
    """A plugin is valid if it exposes EITHER the hook bundle OR the session
    capture bundle. Pre-built-in-claude rewrites required hooks; now the
    built-in claude plugin is capture-only, so the gate has to accept that."""
    return _has_hook_bundle(module) or has_session_capture(module)


def _warn_unknown_capabilities(module: ModuleType, source: str) -> None:
    """Warn-log public callables whose names aren't in ``KNOWN_CAPABILITIES``.

    Skips underscore-prefixed names (private convention), non-callables
    (module constants), and callables imported from other modules (e.g.
    ``from pathlib import Path``).
    """
    module_name = getattr(module, "__name__", "")
    for attr in dir(module):
        if attr.startswith("_"):
            continue
        if attr in KNOWN_CAPABILITIES:
            continue
        value = getattr(module, attr, None)
        if not callable(value):
            continue
        if getattr(value, "__module__", module_name) != module_name:
            continue
        log.warning(
            "aque plugin %s: unknown capability %r — typo? known: %s",
            source, attr, sorted(KNOWN_CAPABILITIES),
        )


def discover_plugins(
    user_plugin_dir: Path | None = None,
) -> dict[str, ModuleType]:
    """Discover built-in and user plugins. Returns {name: module}."""
    plugins: dict[str, ModuleType] = {}

    # Built-in plugins: sibling .py files in this package. Use
    # ``import_module`` so we get the canonical sys.modules entry — that's
    # what ``patch("aque.plugins.claude.summarize", ...)`` modifies, and it
    # also avoids re-executing the module on every ``get_plugin`` call.
    builtin_dir = Path(__file__).parent
    for py_file in sorted(builtin_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        name = py_file.stem
        try:
            module = importlib.import_module(f"aque.plugins.{name}")
        except ImportError:
            continue
        if _is_valid_plugin(module):
            _warn_unknown_capabilities(module, source=f"builtin:{name}")
            plugins[name] = module

    # User plugins: ~/.aque/plugins/*.py (overrides built-in)
    if user_plugin_dir is None:
        user_plugin_dir = Path.home() / ".aque" / "plugins"
    if user_plugin_dir.is_dir():
        for py_file in sorted(user_plugin_dir.glob("*.py")):
            name = py_file.stem
            module = _load_module_from_path(f"aque_user_plugin_{name}", py_file)
            if module and _is_valid_plugin(module):
                _warn_unknown_capabilities(module, source=f"user:{name}")
                plugins[name] = module

    return plugins


def get_plugin(name: str, user_plugin_dir: Path | None = None) -> ModuleType | None:
    """Get a single plugin by name. Returns None if not found."""
    plugins = discover_plugins(user_plugin_dir=user_plugin_dir)
    return plugins.get(name)
