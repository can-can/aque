"""Plugin system for agent type hook installers.

Built-in plugins live in this package (aque/plugins/*.py).
User plugins live in ~/.aque/plugins/*.py.
Module name = type name (claude.py -> --type claude).
"""

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_module_from_path(name: str, path: Path) -> ModuleType | None:
    """Load a Python module from a file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _is_valid_plugin(module: ModuleType) -> bool:
    """Check that a module exposes the required plugin interface."""
    return callable(getattr(module, "is_installed", None)) and callable(
        getattr(module, "install_hook", None)
    )


def discover_plugins(
    user_plugin_dir: Path | None = None,
) -> dict[str, ModuleType]:
    """Discover built-in and user plugins. Returns {name: module}."""
    plugins: dict[str, ModuleType] = {}

    # Built-in plugins: sibling .py files in this package
    builtin_dir = Path(__file__).parent
    for py_file in sorted(builtin_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        name = py_file.stem
        module = _load_module_from_path(f"aque.plugins.{name}", py_file)
        if module and _is_valid_plugin(module):
            plugins[name] = module

    # User plugins: ~/.aque/plugins/*.py (overrides built-in)
    if user_plugin_dir is None:
        user_plugin_dir = Path.home() / ".aque" / "plugins"
    if user_plugin_dir.is_dir():
        for py_file in sorted(user_plugin_dir.glob("*.py")):
            name = py_file.stem
            module = _load_module_from_path(f"aque_user_plugin_{name}", py_file)
            if module and _is_valid_plugin(module):
                plugins[name] = module

    return plugins


def get_plugin(name: str, user_plugin_dir: Path | None = None) -> ModuleType | None:
    """Get a single plugin by name. Returns None if not found."""
    plugins = discover_plugins(user_plugin_dir=user_plugin_dir)
    return plugins.get(name)
