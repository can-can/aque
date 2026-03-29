#!/usr/bin/env python3
"""Fake AI agent for demo recording. Simulates work then goes idle."""

import argparse
import random
import sys
import time

WORK_LINES = [
    "Reading {file}...",
    "Searching for patterns in {file}...",
    "Found 3 matches in {file}",
    "Editing {file}...",
    "Running tests...",
    "  PASS test_auth.py::test_login",
    "  PASS test_auth.py::test_logout",
    "  PASS test_api.py::test_create",
    "Analyzing dependencies...",
    "Checking types...",
    "  All checks passed",
    "Writing changes to {file}...",
    "Committing: fix edge case in {module}",
    "Reviewing diff...",
    "  +14 -3 lines changed",
]

FILES = [
    "src/auth.py", "src/api.py", "src/models.py", "src/utils.py",
    "tests/test_auth.py", "tests/test_api.py", "config/settings.yaml",
]

MODULES = ["auth", "api", "models", "utils", "config"]


def work_phase(duration: float, label: str) -> None:
    print(f"\033[1m{label}\033[0m starting...\n")
    start = time.monotonic()
    while time.monotonic() - start < duration:
        line = random.choice(WORK_LINES)
        line = line.format(
            file=random.choice(FILES),
            module=random.choice(MODULES),
        )
        print(f"  {line}")
        sys.stdout.flush()
        time.sleep(random.uniform(0.3, 0.8))
    print(f"\n\033[1m{label}\033[0m done. Waiting for review.\n")
    sys.stdout.flush()


def idle_phase() -> None:
    sys.stdout.write("\u276f ")
    sys.stdout.flush()
    # Block forever (or until killed)
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-duration", type=float, default=5)
    parser.add_argument("--label", type=str, default="agent")
    parser.add_argument("--delay", type=float, default=0, help="Seconds to wait before starting work")
    args = parser.parse_args()

    if args.delay > 0:
        time.sleep(args.delay)
    work_phase(args.work_duration, args.label)
    idle_phase()


if __name__ == "__main__":
    main()
