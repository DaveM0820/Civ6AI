"""Offline smoke: validate snapshot input + fake sidecar on a saved io_log."""
from __future__ import print_function

import json
import os
import subprocess
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
JOURNAL_DIR = os.path.join(
    os.path.expanduser("~"),
    "OneDrive", "Documents", "My Games", "beyond the sword", "civ4ai-autotest",
)
RUN_V2 = os.path.join(REPO_ROOT, "sidecar", "run_v2.py")


def find_sample_input():
    io_dir = os.path.join(JOURNAL_DIR, "io_logs")
    if not os.path.isdir(io_dir):
        return None
    candidates = []
    for name in os.listdir(io_dir):
        if name.endswith("_input.json"):
            candidates.append(os.path.join(io_dir, name))
    if not candidates:
        return None
    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


def main():
    sample = find_sample_input()
    if not sample:
        print(json.dumps({"ok": False, "error": "no io_logs *_input.json found"}))
        print("SMOKE_SIDECAR=SKIP")
        return 0

    journal = os.path.join(JOURNAL_DIR, "smoke_test_journal.json")
    personality_dir = os.path.join(JOURNAL_DIR, "sidecar-personalities")
    personality = os.path.join(personality_dir, "ai_player_0000_personality.json")
    if not os.path.isfile(personality):
        for name in sorted(os.listdir(personality_dir)):
            if name.endswith(".json") and name != "smoke.json":
                personality = os.path.join(personality_dir, name)
                break

    with open(sample, "r") as handle:
        payload = json.load(handle)
    snapshot = payload.get("snapshot") or payload
    state_path = os.path.join(JOURNAL_DIR, "smoke_snapshot.json")
    with open(state_path, "w") as handle:
        json.dump(snapshot, handle)

    cmd = [
        sys.executable, RUN_V2,
        "--state", state_path,
        "--journal", journal,
        "--personality", personality,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    ok = proc.returncode == 0
    record = None
    if os.path.isfile(journal):
        with open(journal, "r") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    record = json.loads(line)
    result = {
        "ok": ok and record and record.get("status") == "approved",
        "sample_input": sample,
        "returncode": proc.returncode,
        "stderr": stderr.decode("utf-8", "replace")[:2000],
        "stdout_preview": stdout.decode("utf-8", "replace")[:500],
        "journal_status": record.get("status") if record else None,
        "chat_count": len((record or {}).get("validated", {}).get("chat_messages", [])),
        "command_count": len((record or {}).get("commands", [])),
    }
    print(json.dumps(result, indent=2))
    if result["ok"]:
        print("SMOKE_SIDECAR=PASS")
        return 0
    print("SMOKE_SIDECAR=FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
