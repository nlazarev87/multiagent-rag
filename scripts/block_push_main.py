#!/usr/bin/env python3
"""pre-push hook: запрещает пуш в main/master (мерж — только через PR).

Читает refs из stdin (как это делает git pre-push); если stdin пуст —
смотрит текущую ветку через `git rev-parse --abbrev-ref HEAD`.

Override (осознанно): ALLOW_MAIN_PUSH=1.
"""
import os
import subprocess
import sys

ALLOW = os.environ.get("ALLOW_MAIN_PUSH", "").strip().lower() in ("1", "true", "yes")
PROTECTED = ("refs/heads/main", "refs/heads/master", "main", "master")


def _blocked_from_stdin():
    blocked = []
    data = sys.stdin.read()
    for line in data.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in PROTECTED:
            blocked.append(parts[2])
    return blocked


def _current_branch():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def main() -> int:
    if ALLOW:
        return 0

    blocked = _blocked_from_stdin()
    if not blocked:
        branch = _current_branch()
        if branch in PROTECTED:
            blocked = [branch]

    if blocked:
        sys.stderr.write(
            "pre-push: пуш в %s запрещён — мерж только через PR. "
            "(override: ALLOW_MAIN_PUSH=1)\n" % ", ".join(blocked)
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
