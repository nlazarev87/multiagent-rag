"""PR gate: leakage, document swap, src guard, then full scorecard including holdout."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(command):
    return subprocess.call(command, cwd=ROOT)


def main():
    pytest_cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_universality.py::test_code_knowledge_leakage",
        "tests/test_universality.py::test_document_swap_pass_rate",
        "tests/test_guard.py",
        "-q",
    ]
    code = _run(pytest_cmd)
    if code:
        print("GATE FAIL: ненулевой leakage или падение swap. Чинить знаниями в коде нельзя.", flush=True)
        return code
    print("== scorecard all --holdout ==", flush=True)
    score_cmd = [
        sys.executable,
        str(ROOT / "tests" / "eval" / "scorecard.py"),
        "--nodes",
        "all",
        "--holdout",
    ]
    code = _run(score_cmd)
    if code:
        print("GATE FAIL: scorecard ниже пола. Чинить знаниями в коде нельзя.", flush=True)
        return code
    print("GATE OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
