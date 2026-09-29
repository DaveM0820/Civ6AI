"""Civ6AI hourly health check. Read-only. ASCII only. Hidden-window safe."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
HOME = Path.home()
REPO = HOME / "OneDrive" / "Documents" / "Civ6AI"
LA = Path(os.environ.get("LOCALAPPDATA", ""))
LUA_LOG = LA / "Firaxis Games" / "Sid Meier's Civilization VI" / "Logs" / "Lua.log"
STATE_PATH = REPO / "runtime" / "hourly_watch_state.json"
LIVE_WORKERS = REPO / "runtime" / "live_workers.json"
REPORT = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": True, "issues": [], "milestones": []}


def asc(s):
    return str(s).encode("ascii", "backslashreplace").decode("ascii")


def out(k, v=""):
    print(("%s %s" % (k, asc(v))).rstrip())


def issue(msg):
    REPORT["ok"] = False
    REPORT["issues"].append(msg)
    out("ISSUE", msg)


def run_ps(cmd, timeout=30):
    si = subprocess.STARTUPINFO()
    si.dwFlags |= 1
    si.wShowWindow = 0
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=si,
            encoding="utf-8",
            errors="replace",
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except Exception as e:
        return 1, "", str(e)


def task_lines():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= 1
    si.wShowWindow = 0
    try:
        r = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=si,
            encoding="utf-8",
            errors="replace",
        )
        return r.stdout.splitlines() if r.stdout else []
    except Exception as e:
        issue("tasklist_failed: %s" % e)
        return []


def check_civ6():
    # Window titles via Win32 + process presence
    rc, stdout, err = run_ps(
        "Get-Process CivilizationVI*,CivilizationVI_DX12* -ErrorAction SilentlyContinue | "
        "Select-Object Id,ProcessName,MainWindowTitle | ConvertTo-Json -Compress"
    )
    civ = []
    if stdout.strip():
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                data = [data]
            civ = data
        except Exception:
            out("CIV6_RAW", stdout[:500])
    if not civ:
        # fallback tasklist
        for line in task_lines():
            if re.search(r"CivilizationVI", line, re.I):
                civ.append({"Id": "?", "ProcessName": "CivilizationVI", "MainWindowTitle": "unknown"})
    if not civ:
        issue("civ6_not_running")
        REPORT["civ6"] = None
        return
    REPORT["civ6"] = civ
    for p in civ:
        title = (p.get("MainWindowTitle") or "").strip()
        out("CIV6", "pid=%s name=%s title=%s" % (p.get("Id"), p.get("ProcessName"), title or "(none)"))
        if re.search(r"crash|fatal|exception", title, re.I):
            issue("civ6_crash_title: %s" % title)


def check_lmstudio():
    models = []
    try:
        with urllib.request.urlopen("http://localhost:1234/api/v0/models", timeout=8) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
        raw = body.get("data") if isinstance(body, dict) else body
        if isinstance(raw, list):
            for m in raw:
                mid = m.get("id") if isinstance(m, dict) else str(m)
                state = m.get("state") if isinstance(m, dict) else ""
                models.append("%s[%s]" % (mid, state or "?"))
        out("LMSTUDIO", "up models=%s" % (",".join(models) if models else "none"))
        REPORT["lmstudio"] = {"up": True, "models": models}
        if not models:
            issue("lmstudio_no_models_loaded")
        elif not any("loaded" in m.lower() or "[" not in m for m in models):
            # if state present and none loaded
            if all("[not-loaded]" in m.lower() or "[idle]" in m.lower() for m in models if "[" in m):
                # still ok if any is loaded-ish
                if not any("loaded" in m.lower() for m in models):
                    # LM Studio v0 API uses state loaded
                    pass
        loaded = [m for m in models if "loaded" in m.lower()]
        if models and not loaded:
            # check alternate: /v1/models
            try:
                with urllib.request.urlopen("http://localhost:1234/v1/models", timeout=5) as r:
                    v1 = json.loads(r.read().decode("utf-8", "replace"))
                v1ids = [x.get("id") for x in (v1.get("data") or []) if isinstance(x, dict)]
                out("LMSTUDIO_V1", ",".join(v1ids) if v1ids else "empty")
                if not v1ids:
                    issue("lmstudio_no_model_on_v1")
            except Exception as e:
                issue("lmstudio_v1_failed: %s" % e)
    except Exception as e:
        issue("lmstudio_down: %s" % e)
        REPORT["lmstudio"] = {"up": False, "error": str(e)}


def pid_alive(pid):
    try:
        pid = int(pid)
    except Exception:
        return False
    si = subprocess.STARTUPINFO()
    si.dwFlags |= 1
    si.wShowWindow = 0
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=si,
            encoding="utf-8",
            errors="replace",
        )
        return str(pid) in (r.stdout or "")
    except Exception:
        return False


def check_workers():
    REPORT["workers"] = {"path": str(LIVE_WORKERS), "exists": LIVE_WORKERS.is_file(), "alive": [], "dead": []}
    if not LIVE_WORKERS.is_file():
        issue("live_workers_missing")
        out("WORKERS", "missing")
        return
    try:
        data = json.loads(LIVE_WORKERS.read_text(encoding="utf-8"))
    except Exception as e:
        issue("live_workers_bad_json: %s" % e)
        return
    out("WORKERS_JSON", json.dumps(data)[:800])
    # shapes: list of {role,pid} or dict with workers/pids
    entries = []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        if "workers" in data and isinstance(data["workers"], list):
            entries = data["workers"]
        else:
            # flatten dict values that look like worker records
            for k, v in data.items():
                if isinstance(v, dict) and ("pid" in v or "PID" in v):
                    rec = dict(v)
                    rec.setdefault("role", k)
                    entries.append(rec)
                elif isinstance(v, list):
                    entries.extend(v)
                elif k in ("pids", "processes") and isinstance(v, list):
                    for p in v:
                        entries.append({"pid": p, "role": "pid"})
    if not entries:
        issue("live_workers_empty")
        return
    for e in entries:
        if not isinstance(e, dict):
            continue
        pid = e.get("pid") or e.get("PID") or e.get("process_id")
        role = e.get("role") or e.get("name") or e.get("seat") or "?"
        alive = pid_alive(pid) if pid is not None else False
        tag = "alive" if alive else "DEAD"
        out("WORKER", "%s pid=%s %s" % (role, pid, tag))
        if alive:
            REPORT["workers"]["alive"].append({"role": role, "pid": pid})
        else:
            REPORT["workers"]["dead"].append({"role": role, "pid": pid})
            issue("worker_dead: %s pid=%s" % (role, pid))


def parse_turn_from_text(text):
    """Return best game/LLM turn from Lua.log. Ignore stop_turn=N and blob chunk indexes."""
    turns = []
    for line in text.splitlines():
        if "|blob|" in line:
            continue
        if "CIV6AI" not in line and "Civ6Ai" not in line:
            continue
        # Explicit structured markers only (never stop_turn=60 from autotest config).
        for pat in (
            r"snapshot_dumped\|player=\d+\|turn=(\d+)",
            r"pending_apply(?:_ok)?\|player=\d+\|turn=(\d+)",
            r"inbox_wait\|player=\d+\|turn=(\d+)",
            r"inbox_wait_abandoned\|player=\d+\|turn=(\d+)",
            r"local_turn_begin[^\d\n]*(\d+)",
            r"finish_seat[^\d\n]*(\d+)",
            r"game_turn=(\d+)",
            r"(?<![a-z_])turn=(\d+)",
        ):
            for m in re.finditer(pat, line, re.I):
                try:
                    turns.append(int(m.group(1)))
                except Exception:
                    pass
    return max(turns) if turns else None


def check_lua_and_session():
    REPORT["lua"] = {"exists": LUA_LOG.is_file()}
    turn = None
    errors = []
    if LUA_LOG.is_file():
        st = LUA_LOG.stat()
        out("LUALOG", "size=%s mtime=%s" % (st.st_size, time.ctime(st.st_mtime)))
        REPORT["lua"]["size"] = st.st_size
        REPORT["lua"]["mtime"] = st.st_mtime
        # read last ~1.5MB
        data = LUA_LOG.read_bytes()
        if len(data) > 1500000:
            data = data[-1500000:]
        text = data.decode("utf-8", "replace")
        turn = parse_turn_from_text(text)
        # error / breaker / timeout lines
        for line in text.splitlines()[-8000:]:
            if re.search(
                r"(inbox_apply_timeout|inbox_wait_abandoned|circuit.?breaker|CircuitBreaker|model_unloaded|FATAL|Traceback|sidecar.*(fail|error)|pending_apply.*fail|player_ops_unavailable)",
                line,
                re.I,
            ):
                if re.search(r"no_moves_left|script_move_no_progress|enable_timeout|worldtracker|plot_occupied|operation_rejected|probe\|move\|fail", line, re.I):
                    continue
                if "CIV6AI" in line or "civ6ai" in line.lower() or "sidecar" in line.lower() or "Traceback" in line:
                    errors.append(line.strip()[:220])
        # Re-parse with structured CIV6AI markers only (parse_turn_from_text already did this).
        out("LUA_TURN_GUESS", turn if turn is not None else "none")
        if errors:
            out("LUA_ERR_COUNT", len(errors))
            for e in errors[-12:]:
                out("LUA_ERR", e)
            REPORT["lua"]["recent_errors"] = errors[-20:]
            # only flag if very recent (mtime within 20 min) AND error-like
            if time.time() - st.st_mtime < 1200 and errors:
                issue("lua_recent_errors: %d" % len(errors))
    else:
        issue("lua_log_missing")

    # sessions / decision freshness
    session_roots = [
        HOME / "OneDrive" / "Documents" / "My Games" / "Sid Meier's Civilization VI" / "civ6ai",
        HOME / "Documents" / "My Games" / "Sid Meier's Civilization VI" / "civ6ai",
        REPO / "sessions",
        LUA_LOG.parent / "civ6ai",
    ]
    decisions = []
    snapshots = []
    runtime_json = None
    for root in session_roots:
        out("SESSION_ROOT", "%s exists=%s" % (root, root.is_dir()))
        rt = root / "runtime.json"
        if rt.is_file() and runtime_json is None:
            try:
                runtime_json = json.loads(rt.read_text(encoding="utf-8"))
                out("RUNTIME_JSON", json.dumps(runtime_json)[:500])
            except Exception as e:
                out("RUNTIME_JSON_ERR", e)
        sess = root / "sessions" if (root / "sessions").is_dir() else root
        if not sess.is_dir():
            continue
        active_sid = None
        if isinstance(runtime_json, dict):
            active_sid = str(runtime_json.get("session_id") or "").strip() or None
        # Prefer turn_metrics / apply_turn markers from the ACTIVE session.
        if active_sid:
            active_dir = sess / active_sid if (sess / active_sid).is_dir() else None
            if active_dir is None and sess.name == active_sid:
                active_dir = sess
            if active_dir is not None and active_dir.is_dir():
                tm = active_dir / "turn_metrics.jsonl"
                if tm.is_file():
                    try:
                        for line in tm.read_text(encoding="utf-8", errors="replace").splitlines():
                            if not line.strip():
                                continue
                            rec = json.loads(line)
                            t = rec.get("turn")
                            if isinstance(t, int):
                                turn = max(turn or 0, t)
                    except Exception:
                        pass
                for done in active_dir.glob("PLAYER_*/apply_turn_*.done"):
                    m = re.search(r"apply_turn_(\d+)\.done$", done.name)
                    if m:
                        turn = max(turn or 0, int(m.group(1)))
                for decp in active_dir.glob("PLAYER_*/decision.json"):
                    try:
                        d = json.loads(decp.read_text(encoding="utf-8", errors="replace"))
                        t = (d.get("metrics") or {}).get("turn")
                        if isinstance(t, int):
                            turn = max(turn or 0, t)
                        for c in d.get("commands") or []:
                            if isinstance(c, dict) and isinstance(c.get("turn"), int):
                                turn = max(turn or 0, c["turn"])
                    except Exception:
                        pass
        # look for PLAYER_* dirs or decision.json
        for p in sess.rglob("decision.json"):
            try:
                st = p.stat()
                decisions.append((st.st_mtime, p, st.st_size))
            except Exception:
                pass
        for p in sess.rglob("snapshot.json"):
            try:
                st = p.stat()
                snapshots.append((st.st_mtime, p, st.st_size))
                # try turn from snapshot
                try:
                    snap = json.loads(p.read_text(encoding="utf-8"))
                    for key in ("turn", "gameTurn", "GameTurn", "Turn"):
                        if key in snap and isinstance(snap[key], int):
                            turn = max(turn or 0, snap[key])
                    # nested
                    gs = snap.get("game") or snap.get("state") or {}
                    if isinstance(gs, dict):
                        for key in ("turn", "gameTurn", "Turn"):
                            if key in gs and isinstance(gs[key], int):
                                turn = max(turn or 0, gs[key])
                except Exception:
                    pass
            except Exception:
                pass

    decisions.sort(reverse=True)
    snapshots.sort(reverse=True)
    REPORT["turn"] = turn
    out("TURN", turn if turn is not None else "unknown")
    if decisions:
        mt, path, sz = decisions[0]
        age = time.time() - mt
        out("DECISION_LATEST", "age_s=%.0f size=%s path=%s" % (age, sz, path))
        REPORT["decision"] = {"age_s": age, "path": str(path), "size": sz, "mtime": mt}
        if age > 3600:
            issue("decision_stale_age_s=%.0f" % age)
    else:
        out("DECISION_LATEST", "none")
        REPORT["decision"] = None
        # only issue if workers claimed live AND session is not brand-new
        workers_age = None
        try:
            lw = LIVE_WORKERS
            if lw.is_file():
                started = json.loads(lw.read_text(encoding="utf-8")).get("started_at")
                if started:
                    # 2026-09-25T08:00:20Z
                    from datetime import datetime, timezone
                    dt = datetime.strptime(started.replace("Z",""), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                    workers_age = time.time() - dt.timestamp()
        except Exception:
            workers_age = None
        if REPORT.get("workers", {}).get("alive") and (workers_age is None or workers_age > 600):
            issue("decision_missing_while_workers_alive")
        elif REPORT.get("workers", {}).get("alive"):
            out("DECISION_PENDING", "workers_age_s=%s (new session grace)" % (int(workers_age) if workers_age is not None else "?"))

    if snapshots:
        mt, path, sz = snapshots[0]
        out("SNAPSHOT_LATEST", "age_s=%.0f size=%s path=%s" % (time.time() - mt, sz, path))
        REPORT["snapshot"] = {"age_s": time.time() - mt, "path": str(path), "size": sz}

    # sidecar logs
    for name in ("lua_bridge.log", "job_poller.log", "seat_worker.log"):
        p = REPO / "runtime" / "logs" / name
        if not p.is_file():
            # also glob seat logs
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            out("LOG_%s" % name, "lines=%d mtime=%s" % (len(lines), time.ctime(p.stat().st_mtime)))
            for line in lines[-8:]:
                if re.search(r"error|fail|timeout|breaker|Traceback|reject", line, re.I):
                    out("LOGERR_%s" % name, line[:220])
        except Exception as e:
            out("LOG_ERR", "%s %s" % (name, e))

    # seat worker logs
    logdir = REPO / "runtime" / "logs"
    if logdir.is_dir():
        for p in sorted(logdir.glob("*.log"))[-12:]:
            if p.name in ("lua_bridge.log", "job_poller.log"):
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                bad = [l for l in lines[-30:] if re.search(r"error|fail|timeout|breaker|Traceback|reject|model_unloaded", l, re.I)]
                if bad:
                    out("SEATLOG", "%s bad=%d last=%s" % (p.name, len(bad), bad[-1][:180]))
            except Exception:
                pass

    return turn


def check_user_busy():
    # Heuristic: if Civ6 title looks like multiplayer lobby / friend's game, or Additional Content open
    civ = REPORT.get("civ6") or []
    for p in civ:
        title = (p.get("MainWindowTitle") or "")
        if re.search(r"Additional Content|Multiplayer|Lobby", title, re.I):
            out("USER_BUSY_HINT", title)
            REPORT["user_busy_hint"] = title


def load_prev():
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(prev_turn):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "ts": REPORT["ts"],
        "turn": REPORT.get("turn"),
        "ok": REPORT["ok"],
        "issues": REPORT["issues"],
        "prev_turn": prev_turn,
        "milestone_10_notified": False,
        "milestone_50_notified": False,
    }
    # preserve notification flags
    old = load_prev()
    state["milestone_10_notified"] = bool(old.get("milestone_10_notified"))
    state["milestone_50_notified"] = bool(old.get("milestone_50_notified"))
    turn = REPORT.get("turn")
    if isinstance(turn, int):
        if turn >= 10:
            state["reached_10"] = True
        if turn >= 50:
            state["reached_50"] = True
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    out("STATE_SAVED", STATE_PATH)


def main():
    out("BEGIN", REPORT["ts"])
    out("REPO", REPO if REPO.is_dir() else "MISSING")
    if not REPO.is_dir():
        issue("repo_missing")
    prev = load_prev()
    prev_turn = prev.get("turn")
    out("PREV_TURN", prev_turn if prev_turn is not None else "none")
    out("PREV_OK", prev.get("ok"))
    check_civ6()
    check_lmstudio()
    check_workers()
    turn = check_lua_and_session()
    check_user_busy()

    # progress
    advanced = False
    if isinstance(turn, int) and isinstance(prev_turn, int):
        advanced = turn > prev_turn
        out("PROGRESS", "prev=%s now=%s advanced=%s" % (prev_turn, turn, advanced))
    elif isinstance(turn, int) and prev_turn is None:
        out("PROGRESS", "first_check turn=%s" % turn)
    else:
        out("PROGRESS", "unknown")

    # milestones
    if isinstance(turn, int):
        if turn >= 10 and not prev.get("milestone_10_notified") and not prev.get("reached_10_notified"):
            REPORT["milestones"].append(10)
            out("MILESTONE", 10)
        if turn >= 50 and not prev.get("milestone_50_notified"):
            REPORT["milestones"].append(50)
            out("MILESTONE", 50)

    # stall detection: civ6+workers+lms up but no turn advance and decision stale > 45min
    decision = REPORT.get("decision") or {}
    if (
        REPORT.get("civ6")
        and REPORT.get("lmstudio", {}).get("up")
        and REPORT.get("workers", {}).get("alive")
        and not advanced
        and isinstance(prev_turn, int)
        and isinstance(turn, int)
        and turn == prev_turn
        and decision.get("age_s", 0) > 2700
    ):
        issue("stalled_same_turn=%s decision_age_s=%.0f" % (turn, decision.get("age_s", 0)))

    save_state(prev_turn)
    out("OK", REPORT["ok"])
    out("ISSUES", "; ".join(REPORT["issues"]) if REPORT["issues"] else "none")
    out("MILESTONES", REPORT["milestones"] if REPORT["milestones"] else "none")
    # compact JSON summary last line for parser
    summary = {
        "ok": REPORT["ok"],
        "turn": REPORT.get("turn"),
        "prev_turn": prev_turn,
        "advanced": advanced if isinstance(turn, int) else None,
        "issues": REPORT["issues"],
        "milestones": REPORT["milestones"],
        "civ6": bool(REPORT.get("civ6")),
        "lmstudio": REPORT.get("lmstudio", {}).get("up"),
        "workers_alive": len(REPORT.get("workers", {}).get("alive") or []),
        "workers_dead": len(REPORT.get("workers", {}).get("dead") or []),
        "decision_age_s": (REPORT.get("decision") or {}).get("age_s"),
        "user_busy_hint": REPORT.get("user_busy_hint"),
    }
    print("SUMMARY_JSON " + json.dumps(summary))


if __name__ == "__main__":
    main()
