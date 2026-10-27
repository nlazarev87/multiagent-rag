"""Leakage, document swap and src guard. Knowledge in src is a release blocker."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_universality.py::test_code_knowledge_leakage",
        "tests/test_universality.py::test_document_swap_pass_rate",
        "tests/test_guard.py",
        "-q",
    ]
    code = subprocess.call(command, cwd=ROOT)
    if code:
        print("GATE FAIL: ненулевой leakage или падение swap. Чинить знаниями в коде нельзя.", flush=True)
        return code
    print("GATE OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
