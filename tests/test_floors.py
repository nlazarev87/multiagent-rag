import json
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent / "eval"
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import scorecard


def test_floors_hold():
    floors_path = scorecard.FLOORS
    last_path = scorecard.LAST
    assert floors_path.exists(), "сначала запишите tests/eval/floors.json прогоном текущего кода"
    assert last_path.exists(), "нет tests/eval/last.json — сначала прогон scorecard"
    floors = json.loads(floors_path.read_text(encoding="utf-8"))
    latest = json.loads(last_path.read_text(encoding="utf-8"))
    violations = scorecard.compare(floors, latest)
    assert violations == [], "\n".join(violations)
