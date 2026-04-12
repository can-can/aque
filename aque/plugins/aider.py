"""Aider plugin for aque.

Aider has no persistent config hook. Aque injects --notifications-command
at launch time via run.py. This plugin is a no-op stub so aider appears
in the agent type list.
"""


def is_installed() -> bool:
    return False


def install_hook() -> None:
    pass
