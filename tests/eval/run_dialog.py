import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scorecard
import dialog
import store
from agents import CONFIRMED
from coordinator import run
from ingest import ingest_dir

tmp = tempfile.mkdtemp(prefix="score-dialog-")
saved = store.CHROMA
store.CHROMA = Path(tmp)
store.reset()
dialog.reset()
store.upsert_chunks(ingest_dir(scorecard.DOCS))
hits = 0
try:
    for query, fact, banned, statuses, name in scorecard.DIALOG_STEPS:
        result = run(query, "shop-pump")
        allowed = statuses or {CONFIRMED}
        ok = result["status"] in allowed
        if fact:
            ok = ok and fact.lower() in result["answer"].lower()
        if banned:
            ok = ok and banned.lower() not in result["answer"].lower()
        if name:
            ok = ok and name in result["document_names"]
        hits += int(ok)
        print(f"e2e_dialog {query!r}: ok={ok} status={result['status']} calls={store.calls}", flush=True)
finally:
    store.CHROMA = saved
    store.reset()
    dialog.reset()
print(f"hits={hits}/8", flush=True)
raise SystemExit(0 if hits == 8 else 1)
