"""Killcam '99: the app window for ut99_dem2video.py.

Runs a small web server on 127.0.0.1 (this PC only) and opens it as an app window (Edge app mode,
else your browser). Every job runs ut99_dem2video.py, ut_library.py or setup_game.py as a separate
process and its output is shown live. Close the console window or press Quit in the app to stop.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kc_config as cfg  # noqa: E402

cfg.migrate()
import ut99_dem2video as core  # noqa: E402
import ut_library as lib  # noqa: E402
import ut_stream as stream  # noqa: E402

core.SANDBOX = HERE


class _Out:
    """The clips folder from the settings (it can change while the app runs)."""
    def __truediv__(self, other):
        return cfg.out() / other

    def __fspath__(self):
        return str(cfg.out())

    def __str__(self):
        return str(cfg.out())


OUT = _Out()


def sync_core() -> None:
    core.GAME, core.GAME_MODE = cfg.game(), cfg.mode()
    core.SCAN_DIR = cfg.out() / "scans"


sync_core()
CORE = HERE / "ut99_dem2video.py"
PORT = 8799
IS_WINDOWS = os.name == "nt"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# --------------------------------------------------------------------------------------
# Settings (settings.json in the Killcam '99 folder, shared with the command line tool)
# --------------------------------------------------------------------------------------

TRIGGERS = {  # key: (label, group, regex part, on by default)
    "megakill": ("Mega Kill", "multi", "megakill", True),
    "ultrakill": ("Ultra Kill", "multi", "ultrakill", True),
    "monsterkill": ("Monster Kill", "multi", "monsterkill", True),
    "ludicrouskill": ("Ludicrous Kill", "multi", "ludicrouskill", True),
    "holyshit": ("Holy Shit", "multi", "holyshit", True),
    "multikill": ("Multi Kill (lots of clips)", "multi", "multikill", False),
    "killingspree": ("Killing Spree (lots of clips)", "spree", "killingspree", False),
    "rampage": ("Rampage", "spree", "rampage", True),
    "dominating": ("Dominating", "spree", "dominating", True),
    "unstoppable": ("Unstoppable", "spree", "unstoppable", True),
    "godlike": ("Godlike", "spree", "godlike", True),
    "wickedsick": ("Wicked Sick", "spree", "whickedsick|wickedsick", True),
}

DEFAULTS = {
    "demo_folder": "",
    "obs_folder": str(Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Videos"),
    "audio_device": "",
    "scan_jobs": 0,
    "scan_speed": 40,
    "part_before": 8,
    "part_after": 10,
    "settle": 2,
    "format": "mp4",
    "clip_quality": "normal",
    "triggers": [k for k, v in TRIGGERS.items() if v[3]],
    "return_on": True,
    "return_window": 15,
    "capture_on": True,
    "capture_window": 20,
    "carrier_kills": True,
    "obs_track": 0,
    "player": "",
    "obs_reencode": False,
    "open_as_app": True,
    "notify": True,
    "library_sources": [],
    "dev_mode": False,
}


def default_demo_folder() -> str:
    g = cfg.game()
    if g and cfg.mode() == "direct":
        return str(cfg.system_dir(g))  # UT saves demos in System
    return str(HERE.parent)


def settings() -> dict:
    st = dict(DEFAULTS)
    st.update({k: v for k, v in core.load_settings().items() if k in DEFAULTS})
    st["demo_folder"] = st["demo_folder"] or default_demo_folder()
    return st


def clip_args(st: dict) -> list[str]:
    """Command line options for what makes a clip, from the settings."""
    parts = [TRIGGERS[k][2] for k in st["triggers"] if k in TRIGGERS]
    a = ["--clip-on", "|".join(parts) if parts else "^$",
         "--part-before", f"{float(st['part_before']):g}", "--part-after", f"{float(st['part_after']):g}",
         "--return-window", f"{float(st['return_window']) if st['return_on'] else 0:g}",
         "--capture-window", f"{float(st['capture_window']) if st['capture_on'] else 0:g}",
         "--settle", f"{float(st['settle']):g}", "--clip-quality", st["clip_quality"], "--format", st["format"],
         "--no-review"]
    if not st["carrier_kills"]:
        a.append("--no-carrier-kills")
    if st["audio_device"]:
        a += ["--audio-device", st["audio_device"]]
    return a


def scan_args(st: dict) -> list[str]:
    a = ["--scan-speed", f"{float(st['scan_speed']):g}"]
    if int(st["scan_jobs"] or 0) > 0:
        a += ["--scan-jobs", str(int(st["scan_jobs"]))]
    return a


def core_ns(st: dict):
    """The tool's own option set for these settings (to plan clips the same way it will)."""
    ns = core.build_parser().parse_args(clip_args(st))
    ns.out = cfg.out()
    return ns


# --------------------------------------------------------------------------------------
# Jobs: one at a time, output kept for the activity panel
# --------------------------------------------------------------------------------------

class Job:
    def __init__(self, kind: str, title: str, cmds: list[list[str]]) -> None:
        self.kind, self.title, self.cmds = kind, title, cmds
        self.lines: list[str] = []
        self.state = "running"
        self.rc: int | None = None
        self.started = time.time()
        self.ended: float | None = None
        self.progress: tuple[int, int] | None = None
        self.step = "Starting ..."
        self.proc: subprocess.Popen | None = None
        self.stop_wanted = False
        self.id = secrets.token_hex(4)
        threading.Thread(target=self.run, daemon=True).start()

    def add(self, line: str) -> None:
        line = line.rstrip("\r\n")
        self.lines.append(line)
        if len(self.lines) > 30000:
            del self.lines[:5000]
        body = re.sub(r"^\[\d\d:\d\d:\d\d\] ", "", line)
        m = re.search(r"=== \[(\d+)/(\d+)\]", body)
        if m:
            self.progress = (int(m.group(1)), int(m.group(2)))
        for pat, fmt in ((r"^Scan: (.+?)(  \(already scanned\))?$", "Scanning {0}"),
                         (r"^Demo: (.+)$", "Recording the moments of {0}"),
                         (r"^Recording: (.+?)  \(", "Listening to {0}"),
                         (r"^Scanning (\d+) demo\(s\) first", "Scanning {0} demo(s) first"),
                         (r"^  muxing|^  corner marker", "Cutting the clips"),
                         (r"^Compiling ", "Building the add-on")):
            m = re.search(pat, body)
            if m:
                self.step = fmt.format(*m.groups())
                break

    def run(self) -> None:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        rc = 0
        for cmd in self.cmds:
            if self.stop_wanted:
                break
            self.add("> " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
            try:
                self.proc = subprocess.Popen(cmd, cwd=str(HERE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL, env=env, creationflags=NOWIN)
            except OSError as e:
                self.add(f"PROBLEM: could not start: {e}")
                rc = 1
                break
            for raw in iter(self.proc.stdout.readline, b""):
                self.add(raw.decode("utf-8", "replace"))
            rc = self.proc.wait()
            if rc != 0 and self.kind != "install":
                break
        self.rc = rc
        self.ended = time.time()
        self.state = "stopped" if self.stop_wanted else ("done" if rc in (0, 2) else "failed")
        self.step = {"stopped": "Stopped", "done": "Finished", "failed": "Finished with a problem"}[self.state]

    def stop(self) -> None:
        self.stop_wanted = True
        p = self.proc
        if p and p.poll() is None:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=NOWIN)
            else:
                p.terminate()
        if cfg.game():
            core.stop_leftover_ut(cfg.game())  # UT instances the tool started

    def info(self, since: int = 0) -> dict:
        new_clips = 0
        if self.state != "running":
            new_clips = sum(1 for x in read_index() if x.get("created", 0) >= self.started - 1)
        return {"id": self.id, "kind": self.kind, "title": self.title, "state": self.state, "rc": self.rc,
                "started": self.started, "ended": self.ended, "progress": self.progress, "step": self.step,
                "lines": self.lines[since:], "next": len(self.lines), "new_clips": new_clips,
                "scans_changed": newest_scan()}


JOB: Job | None = None
JOB_LOCK = threading.Lock()


def py() -> list[str]:
    return [sys.executable, "-u"]


def start_job(kind: str, body: dict) -> tuple[bool, str]:
    global JOB
    with JOB_LOCK:
        if JOB and JOB.state == "running":
            return False, "Another job is still running. Stop it first or wait until it is done."
        st = settings()
        demos = [str(Path(d)) for d in body.get("demos") or []]
        folder = [st["demo_folder"]]
        if kind == "clips":
            extra = []
            moments = body.get("moments") or {}
            if moments:  # picked moments: {demo path: [call times]}
                demos = [str(Path(d)) for d in moments]
                mf = OUT / "_work" / "moments.json"
                mf.parent.mkdir(parents=True, exist_ok=True)
                mf.write_text(json.dumps({Path(d).name: [float(t) for t in ts] for d, ts in moments.items()}),
                              encoding="utf-8")
                extra = ["--moments", str(mf)]
            cmds = [py() + [str(CORE), "--clips-only", "--scan-first", *scan_args(st), *clip_args(st), *extra,
                            *(demos or folder)]]
            n_m = sum(len(v) for v in moments.values())
            title = (f"Record {n_m} picked moment(s)" if moments else
                     f"Kill clips from {len(demos)} demo(s)" if demos else "Kill clips from all new demos")
        elif kind == "scan":
            redo = bool(demos) or bool(body.get("all"))
            cmds = [py() + [str(CORE), "--scan", *scan_args(st), *clip_args(st)] + (["--overwrite"] if redo else [])
                    + (demos or folder)]
            title = (f"Scan {len(demos)} demo(s)" if demos else "Rescan all demos" if body.get("all")
                     else "Scan new demos")
        elif kind in ("obs", "obs_find", "obs_debug", "obs_rescan"):
            files = [str(Path(f)) for f in body.get("files") or []]
            moments = body.get("moments") or {}  # picked moments: {recording path: [call times]}
            a = ["--obs", st["obs_folder"], *clip_args(st)]
            if moments:
                files = [str(Path(f)) for f in moments]
                mf = OUT / "_work" / "obs_moments.json"
                mf.parent.mkdir(parents=True, exist_ok=True)
                mf.write_text(json.dumps({Path(f).name: [float(t) for t in ts] for f, ts in moments.items()}),
                              encoding="utf-8")
                a += ["--moments", str(mf)]
            for f in files:
                a += ["--obs-file", f]
            if st.get("player"):
                a += ["--player", st["player"]]
            if st["obs_reencode"]:
                a.append("--obs-reencode")
            if kind == "obs_find" or body.get("find_only"):
                a.append("--obs-find-only")
            if kind in ("obs_debug", "obs_rescan"):
                a.append("--overwrite")
            if kind == "obs_rescan":
                a.append("--rescan")
            if kind == "obs_debug":
                a += ["--stream-compare", "--obs-debug"]
            cmds = [py() + [str(CORE), *a]]
            n_m = sum(len(v) for v in moments.values())
            title = (f"Cut {n_m} picked moment(s) from {len(files)} recording(s)" if moments else
                     (f"Read {len(files)} recording(s) again" if files else "Read all recordings again")
                     if kind == "obs_rescan" else
                     "Compare the screen reading with the demos" if kind == "obs_debug" else
                     (f"Find moments in {len(files)} recording(s)" if files else "Find moments in new recordings")
                     if kind == "obs_find" or body.get("find_only") else
                     f"Make clips from {len(files)} recording(s)" if files else "Make clips from new recordings")
        elif kind == "watch":
            d = body.get("demo") or ""
            a = ["--watch", d] + (["--at", f"{float(body['at']):.2f}"] if body.get("at") is not None else [])
            cmds = [py() + [str(CORE), *a]]
            title = f"Watch {Path(d).name}"
        elif kind == "library_build":
            cmds = [py() + [str(HERE / "ut_library.py"), "build"]]
            title = "Refresh packages"
        elif kind == "library_fetch":
            a = []
            for g in body.get("guids") or []:
                a += ["--guid", str(g)]
            cmds = [py() + [str(HERE / "ut_library.py"), "fetch", *a]]
            title = "Search online for missing packages" if not a else f"Search online for {len(a) // 2} package version(s)"
        elif kind == "setup":
            ut = body.get("ut") or core.load_settings().get("source_folder") or (
                str(cfg.game()) if cfg.mode() == "direct" and cfg.game() else "")
            mode = body.get("mode") if body.get("mode") in ("copy", "direct") else cfg.mode()
            if not ut:
                return False, "Pick your Unreal Tournament folder first."
            cmds = [py() + [str(HERE / "setup_game.py"), "--ut", ut, "--mode", mode],
                    py() + [str(HERE / "ut_library.py"), "build"]]
            title = "Set up Unreal Tournament (" + ("separate copy" if mode == "copy" else "your own folder") + ")"
        elif kind == "undo":
            cmds = [py() + [str(HERE / "setup_game.py"), "--undo"]]
            title = "Remove Killcam '99 from your UT folder"
        elif kind == "remove_copy":
            cmds = [py() + [str(HERE / "setup_game.py"), "--remove-copy"]]
            title = "Delete the separate copy"
        elif kind == "validate":
            cmds = [py() + [str(CORE), "--validate"]]
            title = "Compare scans with the sound detection"
        elif kind == "install":
            cmds = [py() + [str(HERE / "get_ffmpeg.py")]]
            title = "Download ffmpeg"
        else:
            return False, f"unknown job {kind}"
        sync_core()
        JOB = Job(kind, title, cmds)
        return True, JOB.id


# --------------------------------------------------------------------------------------
# Data for the panel
# --------------------------------------------------------------------------------------

def read_index() -> list[dict]:
    try:
        return json.loads(core.index_file(core.types_ns(out=cfg.out())).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


INFO_FILE = cfg.DATA / "demo_info.json"
_info_lock = threading.Lock()
_info: dict = {}
_map_thread: threading.Thread | None = None


def demo_info_cache() -> dict:
    global _info
    if not _info:
        try:
            _info = json.loads(INFO_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _info = {}
    return _info


def find_maps_later(files: list[Path]) -> None:
    """Renamed demos: read the map from the demo's package list in the background (slow-ish)."""
    global _map_thread
    if _map_thread and _map_thread.is_alive():
        return

    def work():
        info = demo_info_cache()
        for f in files:
            key = f"{f.name}|{f.stat().st_size}"
            if key in info:
                continue
            try:
                reqs = core.demo_packages(f) or []
                mp = next((Path(x["fname"]).stem for x in reqs if x["fname"].lower().endswith(".unr")), "")
            except Exception:
                mp = ""
            with _info_lock:
                info[key] = {"map": mp}
                try:
                    INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
                    INFO_FILE.write_text(json.dumps(info), encoding="utf-8")
                except OSError:
                    pass

    _map_thread = threading.Thread(target=work, daemon=True)
    _map_thread.start()


def list_demos() -> dict:
    st = settings()
    folder = Path(st["demo_folder"])
    if not folder.is_dir():
        return {"folder": str(folder), "error": "This folder does not exist. Pick your demo folder.", "demos": []}
    ns = core_ns(st)
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".dem" and not p.name.startswith("ut2vid_tmp"))
    info = demo_info_cache()
    cat = lib.load_catalog()
    removed = lib.removed_demos()
    need_maps, rows = [], []
    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            continue
        r = core.load_scan(f, ns)
        total = (r or {}).get("total") or core.estimate_duration(f)
        start, _ex = core.demo_start_exact(f, total)
        mp = core.map_from_filename(f.name) or (r or {}).get("map") or info.get(f"{f.name}|{size}", {}).get("map")
        if mp is None:
            need_maps.append(f)
        moments, status = [], "new"
        if r and r.get("end"):
            core.refresh_calls(r["messages"], core.demo_player(f.name), core.scan_speed(r, ns)[0])
            parts = core.plan_parts(r["messages"], ns)
            for a, b, names, t in parts:
                moments.append({"t": t, "a": a, "b": b, "labels": [core.display(n) for n in names],
                                "category": core.clip_category(names), "done": core.part_done(f, (a, b, names, t), ns)})
            done = sum(m["done"] for m in moments)
            status = ("nothing" if not moments else "done" if done == len(moments) else
                      "partly" if done else "todo")
        elif r:
            status = "incomplete"
        rows.append({"name": f.name, "path": str(f), "size": size, "when": start, "map": mp or "",
                     "length": total, "status": status, "moments": moments,
                     "missing": lib.missing_count(f.name, cat), "pkgs_known": f.name in cat.get("demos", {}),
                     "removed": f.name.lower() in removed})
    if need_maps:
        find_maps_later(need_maps)
    rows.sort(key=lambda x: x["when"] or 0, reverse=True)
    return {"folder": str(folder), "demos": rows, "maps_pending": bool(need_maps)}


_REC_CACHE: dict = {}


def recording_moments(rec: Path, stt, ns, obs_dir: Path, have: set[str]) -> list[dict]:
    """The moments worth a clip in a recording that was read before, worked out from the saved
    reading with the current clip options (the reading itself is never repeated here)."""
    f = cfg.out() / "stream_scans" / (rec.stem + ".json")
    try:
        fm = f.stat().st_mtime
    except OSError:
        return []
    sig = (str(f), fm, json.dumps({k: getattr(ns, k, None) for k in sorted(vars(ns))}, default=str))
    parts = _REC_CACHE.get(sig)
    if parts is None:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            if r.get("size") != stt.st_size or r.get("mtime") != int(stt.st_mtime):
                return []  # the recording changed since it was read
            player = ns.player or r.get("player")
            if player is None:  # read before player names were saved: work it out once, like the cutter does
                player = stream.find_player(stream.events_of(r), rec, ns)
                r["player"] = player
                tmp = f.with_suffix(".tmp")
                tmp.write_text(json.dumps(r), encoding="utf-8")
                os.replace(tmp, f)
                os.utime(f, (fm, fm))  # same reading: keep its time, so the cache stays valid
            msgs = stream.recording_messages(r, rec, ns, player)
            parts = [(a, b, names, t) for a, b, names, t in core.plan_parts(msgs, ns) if b > 0]
        except Exception:
            parts = []
        _REC_CACHE[sig] = parts
    ext = stream.clip_ext(rec, ns)
    return [{"t": t, "a": a, "b": b, "labels": [core.display(n) for n in names],
             "category": core.clip_category(names),
             "done": core.clip_dest(obs_dir, names, rec.stem, t, ext).name.lower() in have}
            for a, b, names, t in parts]


def list_recordings() -> dict:
    st = settings()
    folder = Path(st["obs_folder"])
    if not folder.is_dir():
        return {"folder": str(folder), "error": "This folder does not exist. Pick your recordings folder.",
                "recordings": []}
    ns = core.types_ns(out=cfg.out())
    ledger = core.obs_ledger(ns)
    by_path = {}
    for key, (status, _when) in ledger.items():
        parts = key.split("|", 2)
        if len(parts) == 3:
            by_path[parts[2]] = (key, status)
    clips: dict[str, int] = {}
    for x in core.ClipStore(cfg.out()).items:
        if x.get("source") == "obs":
            clips[x.get("origin", "")] = clips.get(x.get("origin", ""), 0) + 1
    files = []
    for p in folder.rglob("*"):
        if p.suffix.lower() in core.VIDEO_EXTS and p.is_file() and not core.inside(p, cfg.out()):
            files.append(p)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    cns = core_ns(st)
    cns.player = st.get("player") or ""
    cns.obs_reencode = st["obs_reencode"]
    cns.demos = [st["demo_folder"]]  # where the player name can be looked up
    cd = core.clip_dirs(cfg.out())
    have = {f.name.lower() for d in (cd["obs_clips"], cd["rejected"]) if d.is_dir() for f in d.rglob("*") if f.is_file()}
    have |= {Path(x["file"]).name.lower() for x in core.ClipStore(cfg.out()).deleted}
    rows = []
    for p in files[:400]:
        stt = p.stat()
        key = f"{stt.st_size}|{int(stt.st_mtime)}|{p}"
        known = by_path.get(str(p))
        status = "new"
        if known:
            status = "changed" if known[0] != key else (
                "waiting" if known[1] == "retry" else "read" if known[1] == "read" else "checked")
        moments = recording_moments(p, stt, cns, cd["obs_clips"], have) if status in ("read", "checked") else []
        start, exact = core.recording_start(p, 0)
        rows.append({"name": p.name, "path": str(p), "folder": str(p.parent.relative_to(folder)) if p.parent != folder else "",
                     "size": stt.st_size, "when": start if exact else stt.st_mtime, "status": status,
                     "clips": clips.get(p.name, 0), "fresh": time.time() - stt.st_mtime < 120,
                     "moments": moments})
    return {"folder": str(folder), "recordings": rows, "more": max(0, len(files) - 400)}


CLIPS = {"store": None}


def list_clips() -> dict:
    store = core.ClipStore(cfg.out())
    CLIPS["store"] = store
    items = []
    for x in store.items:
        y = {k: v for k, v in x.items()}
        y["name"] = Path(x["file"]).name
        try:
            y["size"] = store.file_of(x["id"]).stat().st_size
        except OSError:
            y["size"] = 0
        items.append(y)
    return {"items": items, "folder": str(cfg.clips())}


_health_cache: dict = {}


def health() -> dict:
    g = cfg.game()
    sysd = cfg.system_dir(g) if g else None
    hook_u = sysd / cfg.HOOK_FILE if sysd else None
    shipped = HERE / "hook" / cfg.HOOK_FILE
    stale = bool(hook_u and hook_u.exists() and shipped.exists() and hook_u.read_bytes() != shipped.read_bytes())
    if "ffmpeg" not in _health_cache or time.time() - _health_cache.get("t", 0) > 60:
        ff = core.find_ffmpeg()
        _health_cache.update(t=time.time(), ffmpeg=ff, gfx=bool(ff and core.has_gfxcapture(ff)))
    import importlib.util as iu
    mods = {m: iu.find_spec(m) is not None for m in ("numpy", "pyaudiowpatch")}
    work = cfg.out() / "_work"
    work_bytes = sum(f.stat().st_size for f in work.rglob("*") if f.is_file()) if work.is_dir() else 0
    where = "a separate copy" if cfg.mode() == "copy" else "your own UT folder"
    checks = [
        {"id": "build", "ok": cfg.setup_done(), "label": "Unreal Tournament", "fix": "wizard",
         "detail": f"{g} ({where})" if cfg.setup_done() else "not set up yet"},
        {"id": "hook", "ok": bool(hook_u and hook_u.exists()) and not stale, "warn": stale,
         "label": "Kill detection add-on (UT2VidHook)", "fix": "setup" if cfg.setup_done() else None,
         "detail": "a newer version came with this release" if stale else
         ("in place" if hook_u and hook_u.exists() else "not in place")},
        {"id": "ffmpeg", "ok": bool(_health_cache["ffmpeg"]), "label": "ffmpeg (recording and cutting)",
         "fix": "install", "detail": ("found" + ("" if _health_cache["gfx"] else ", but too old to record in the background (8.1+)"))
         if _health_cache["ffmpeg"] else "not downloaded yet", "warn": bool(_health_cache["ffmpeg"]) and not _health_cache["gfx"]},
        {"id": "numpy", "ok": mods["numpy"], "label": "numpy (sound detection)", "fix": None,
         "detail": "included" if mods["numpy"] else "missing: unzip Killcam '99 again"},
        {"id": "audio", "ok": mods["pyaudiowpatch"], "label": "pyaudiowpatch (recording the game sound)",
         "fix": None, "detail": "included" if mods["pyaudiowpatch"] else "missing: unzip Killcam '99 again"},
    ]
    return {"checks": checks, "work_bytes": work_bytes}


def newest_scan() -> float:
    d = cfg.out() / "scans"
    try:
        return max((f.stat().st_mtime for f in d.glob("*.json")), default=0.0)
    except OSError:
        return 0.0


def state() -> dict:
    sync_core()
    idx = core.ClipStore(cfg.out()).items  # only clips that still exist (deleted ones are dropped from the list)
    cats: dict[str, int] = {}
    for x in idx:
        if x.get("status") != "rejected":
            cats[x.get("category", "?")] = cats.get(x.get("category", "?"), 0) + 1
    return {"settings": settings(), "defaults": DEFAULTS,
            "triggers": [{"key": k, "label": v[0], "group": v[1]} for k, v in TRIGGERS.items()],
            "health": health(), "clips_total": sum(cats.values()), "clips_by_type": cats,
            "clips_new": sum(1 for x in idx if x.get("status") == "new"),
            "job": JOB.info(len(JOB.lines)) if JOB else None,
            "here": str(HERE), "out": str(cfg.out()), "clips": str(cfg.clips()), "cpu_threads": os.cpu_count() or 0,
            "game": game_state(), "app": {"name": cfg.APP_NAME, "version": cfg.VERSION},
            "code_changed": code_changed(), "scans_changed": newest_scan(),
            "auto_jobs": core.auto_scan_jobs()}


_audio_cache: dict = {}


def audio_devices(refresh: bool = False) -> list[str]:
    if refresh or "list" not in _audio_cache:
        try:
            r = subprocess.run(py() + [str(CORE), "--list-audio"], capture_output=True, text=True, timeout=60,
                               cwd=str(HERE), creationflags=NOWIN, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            names = [l.strip() for l in r.stdout.splitlines() if l.startswith("  ") and l.strip()]
            names = [re.sub(r"\s*\[Loopback\]\s*$", "", n) for n in names]
        except (OSError, subprocess.SubprocessError):
            names = []
        _audio_cache["list"] = sorted(dict.fromkeys(names))
    return _audio_cache["list"]


def ask_folder(title: str, start: str) -> str | None:
    r = subprocess.run(py() + [str(CORE), "--ask-folder", title, start], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, cwd=str(HERE), timeout=3600,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    m = re.search(r"^FOLDER=(.*)$", r.stdout, re.M)
    return m.group(1).strip() if m and m.group(1).strip() else None


def open_path(p: Path, select: bool = False) -> None:
    if not IS_WINDOWS:
        return
    try:
        if select:
            subprocess.Popen(["explorer", "/select,", str(p)])
        elif p.is_file():
            os.startfile(str(p))  # noqa
        else:
            p.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["explorer", str(p)])
    except OSError:
        pass


def clean_work() -> int:
    """Delete the temporary recordings in videos\\_work (only when no job runs)."""
    n = 0
    work = cfg.out() / "_work"
    if work.is_dir():
        for f in work.iterdir():
            if f.is_file():
                try:
                    n += f.stat().st_size
                    f.unlink()
                except OSError:
                    pass
    return n


# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------

TOKEN = secrets.token_hex(16)
STARTED = time.time()
RESTART = {"wanted": False}
CODE_FILES = [CORE, HERE / "ut_library.py", HERE / "killcam_app.py", HERE / "killcam_app.html", HERE / "kc_config.py"]


def code_changed() -> bool:
    """True when the tool was updated after this window started (the running panel uses the old code)."""
    for f in CODE_FILES:
        try:
            if f.stat().st_mtime > STARTED + 1:
                return True
        except OSError:
            pass
    return False
SERVER: ThreadingHTTPServer | None = None
SETTING_TYPES = {k: type(v) for k, v in DEFAULTS.items()}


class Handler(BaseHTTPRequestHandler):
    server_version = "Killcam99"

    def log_message(self, *a):
        pass

    def _host_ok(self) -> bool:
        # Host must be this PC (DNS rebinding) and the browser must not mark the request as coming
        # from another web page (cross-site requests, <video>/<img> embeds of clips and data)
        return core.local_request_ok(self.headers)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self):
        if not self._host_ok():
            self.send_error(403)
            return
        path, _, query = self.path.partition("?")
        q = dict(x.split("=", 1) for x in query.split("&") if "=" in x)
        # everything but the page itself, its icon and the 'is it running' ping needs the token the
        # page carries (header for data, ?t= for <video> sources): nothing else on this PC or in a
        # browser can read your folders, logs or clips through this server
        if (path.startswith("/api/") and path != "/api/ping") or path.startswith("/media/"):
            given = self.headers.get("X-Killcam-Token") or q.get("t") or ""
            if not hmac.compare_digest(given, TOKEN):
                self.send_error(403)
                return
        try:
            if path in ("/", "/index.html"):
                page = (HERE / "killcam_app.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif path in ("/icon.svg", "/favicon.ico"):
                self._send(200, (HERE / "icon.svg").read_bytes(), "image/svg+xml")
            elif path == "/api/ping":
                self._json({"app": cfg.APP_ID})
            elif path == "/api/state":
                self._json(state())
            elif path == "/api/job":
                self._json(JOB.info(int(q.get("since", 0))) if JOB else {})
            elif path == "/api/demos":
                self._json(list_demos())
            elif path == "/api/recordings":
                self._json(list_recordings())
            elif path == "/api/clips":
                self._json(list_clips())
            elif path == "/api/library":
                self._json(lib.table_data())
            elif path == "/api/demo-packages":
                import urllib.parse
                self._json(lib.demo_report(urllib.parse.unquote(q.get("path", ""))))
            elif path == "/api/setup-info":
                self._json(setup_info())
            elif path == "/api/check-ut":
                import urllib.parse
                self._json(check_ut(urllib.parse.unquote(q.get("path", ""))))
            elif path == "/api/diagnostics":
                self._send(200, diagnostics().encode("utf-8"), "text/plain; charset=utf-8")
            elif path == "/api/audio":
                self._json({"devices": audio_devices(q.get("refresh") == "1")})
            elif path.startswith("/media/"):
                self._media(path)
            else:
                self.send_error(404)
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as e:  # keep the panel alive, show the problem
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _media(self, path: str) -> None:
        store = CLIPS["store"]
        m = re.fullmatch(r"/media/(\d+)", path)
        if not store or not m or int(m.group(1)) >= len(store.items):
            self.send_error(404)
            return
        f = store.file_of(int(m.group(1)))
        size = f.stat().st_size
        start, end = 0, size - 1
        rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "video/mp4" if f.suffix.lower() in (".mp4", ".m4v", ".mov") else
                         "video/x-matroska" if f.suffix.lower() == ".mkv" else "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(f, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(1 << 20, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def do_POST(self):
        if not self._host_ok():
            self.send_error(403)
            return
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 1 << 20)) or b"{}")
        except ValueError:
            body = {}
        if not hmac.compare_digest(str(body.get("token", "")), TOKEN):
            self._json({"ok": False, "error": "refused"}, 403)
            return
        try:
            self._post(self.path, body)
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as e:
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def _post(self, path: str, body: dict) -> None:
        if path == "/api/run":
            ok, msg = start_job(body.get("kind", ""), body)
            self._json({"ok": ok, "error": None if ok else msg, "id": msg if ok else None})
        elif path == "/api/job-clear":
            global JOB
            with JOB_LOCK:
                if JOB and JOB.state != "running":
                    JOB = None
            self._json({"ok": True})
        elif path == "/api/stop":
            if JOB and JOB.state == "running":
                JOB.stop()
            self._json({"ok": True})
        elif path == "/api/settings":
            cur = core.load_settings()
            for k, v in (body.get("values") or {}).items():
                if k not in DEFAULTS:
                    continue
                t = SETTING_TYPES[k]
                try:
                    v = (bool(v) if t is bool else int(float(v)) if t is int else float(v) if t is float
                         else [str(x) for x in v] if k == "library_sources"
                         else [x for x in v if x in TRIGGERS] if t is list else str(v))
                except (TypeError, ValueError):
                    continue
                cur[k] = v
            core.save_settings(**cur)
            sync_core()
            self._json({"ok": True, "settings": settings()})
        elif path == "/api/reset-settings":
            core.save_settings(**{k: v for k, v in DEFAULTS.items() if k not in ("demo_folder", "obs_folder")})
            self._json({"ok": True, "settings": settings()})
        elif path == "/api/demo-remove":
            names = [Path(str(n)).name for n in body.get("names") or []]
            cur = list(core.load_settings().get("hidden_demos") or [])
            low = {n.lower() for n in names}
            if body.get("put_back"):
                cur = [n for n in cur if n.lower() not in low]
            else:
                cur += [n for n in names if n.lower() not in {c.lower() for c in cur}]
            core.save_settings(hidden_demos=cur)
            self._json({"ok": True, "removed": len(cur)})
        elif path == "/api/setup-save":
            vals = {k: str(body[k]) for k in ("demo_folder", "obs_folder", "clips_folder") if body.get(k)}
            core.save_settings(**vals)
            sync_core()
            self._json({"ok": True, "settings": settings()})
        elif path == "/api/pick-folder":
            which = body.get("which")
            if which in ("ut", "out", "demo_any"):  # the wizard: only answer, the wizard saves
                got = ask_folder({"ut": "Your Unreal Tournament folder", "out": "Where to save your clips",
                                  "demo_any": "Folder with your UT demos"}[which], body.get("start") or str(Path.home()))
                self._json({"ok": bool(got), "folder": got})
                return
            if which == "out_now":
                got = ask_folder("Where to save your clips", str(cfg.clips()))
                if got:
                    core.save_settings(clips_folder=got)
                    sync_core()
                self._json({"ok": bool(got), "folder": got})
                return
            if which == "libsrc":
                got = ask_folder("A folder with UT packages (a UT install, a map collection or a cache folder)",
                                 str(Path.home() / "Desktop"))
                if got:
                    cur = settings()["library_sources"]
                    if got not in cur:
                        core.save_settings(library_sources=cur + [got])
                self._json({"ok": bool(got), "folder": got})
                return
            key, title = {"demo": ("demo_folder", "Folder with your UT demos"),
                          "obs": ("obs_folder", "Folder with your OBS / Streamlabs recordings")}[which]
            got = ask_folder(title, settings()[key])
            if got:
                core.save_settings(**{key: got})
            self._json({"ok": bool(got), "folder": got})
        elif path == "/api/open":
            what = body.get("what")
            st = settings()
            o = cfg.out()
            cd = core.clip_dirs(o)
            target = {"demos": Path(st["demo_folder"]), "recordings": Path(st["obs_folder"]),
                      "clips": cd["clips"], "obs_clips": cd["obs_clips"], "scans": o / "scans", "all_clips": cfg.clips(),
                      "rejected": cd["rejected"], "app": cfg.ROOT, "log": cfg.LOG,
                      "game": cfg.game() or HERE, "packs": cfg.PACKS, "library_csv": lib.CSV}.get(what)
            if what == "file" and body.get("path"):
                open_path(Path(body["path"]), select=True)
            elif target:
                open_path(target)
            self._json({"ok": True})
        elif path == "/api/clip-status":
            store = CLIPS["store"] or core.ClipStore(cfg.out())
            ok, msg = store.set_status(int(body.get("id", -1)), body.get("status"))
            self._json({"ok": ok, "status": msg} if ok else {"ok": False, "error": msg})
        elif path == "/api/clip-delete":
            store = CLIPS["store"] or core.ClipStore(cfg.out())
            ids = [int(i) for i in body.get("ids") or []]
            if body.get("rejected"):
                ids = [x["id"] for x in store.items if x.get("status") == "rejected"]
            n, freed, problems = store.delete(ids)
            CLIPS["store"] = None
            self._json({"ok": not problems or n > 0, "deleted": n, "freed": freed, "problems": problems,
                        "error": ("Could not delete: " + ", ".join(problems)) if problems and not n else None})
        elif path == "/api/clip-open":
            store = CLIPS["store"]
            if store:
                store.open(int(body.get("id", -1)), bool(body.get("play")))
            self._json({"ok": True})
        elif path == "/api/clean":
            if JOB and JOB.state == "running":
                self._json({"ok": False, "error": "Not while a job runs."})
            else:
                self._json({"ok": True, "freed": clean_work()})
        elif path == "/api/restart":
            if JOB and JOB.state == "running":
                self._json({"ok": False, "error": "A job is running; restart when it is done."})
                return
            RESTART["wanted"] = True
            self._json({"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.3), SERVER.shutdown()), daemon=True).start()
        elif path == "/api/quit":
            if JOB and JOB.state == "running":
                JOB.stop()
            self._json({"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.3), SERVER.shutdown()), daemon=True).start()
        else:
            self._json({"ok": False, "error": "unknown"}, 404)


def game_state() -> dict:
    m = cfg.manifest()
    st = core.load_settings()
    return {"folder": str(cfg.game() or ""), "mode": cfg.mode(), "setup_done": cfg.setup_done(),
            "source": st.get("source_folder") or "", "copy_exists": cfg.is_ut_folder(cfg.COPY_DIR),
            "direct_files": len(m.get("files", [])) + len(m.get("cache", [])), "direct_game": m.get("game") or ""}


def folder_bytes(p: Path, limit_s: float = 8.0) -> int:
    t0, n = time.time(), 0
    for dirpath, _d, files in os.walk(p):
        for fn in files:
            try:
                n += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
        if time.time() - t0 > limit_s:
            break
    return n


def check_ut(path: str) -> dict:
    """What the wizard shows about one folder: is it UT, can Killcam '99 use it, how big is it."""
    p = Path(path) if path else None
    if not p or not p.is_dir():
        return {"path": path, "ok": False, "problem": "This folder does not exist."}
    if not cfg.is_ut_folder(p):
        return {"path": path, "ok": False,
                "problem": "This is not an Unreal Tournament folder: it has no System\\UnrealTournament.exe."}
    sysd = cfg.system_dir(p)
    if not (sysd / "udemo.u").exists():
        return {"path": path, "ok": False, "problem": "This UT has no udemo. Update it with the OldUnreal 469 patch first."}
    if core.inside(p, cfg.ROOT) or core.inside(cfg.ROOT, p):
        return {"path": path, "ok": False, "problem": "Pick your own UT folder, not one inside Killcam '99."}
    demos = len(list(sysd.glob("*.dem")))
    return {"path": str(p), "ok": True, "size": folder_bytes(p), "free": cfg.free_bytes(HERE), "demos": demos,
            "system": str(sysd)}


def setup_info() -> dict:
    """Candidate UT folders and folder suggestions for the setup wizard."""
    cands: list[str] = []
    st = core.load_settings()
    if st.get("source_folder"):
        cands.append(st["source_folder"])
    if cfg.mode() == "direct" and cfg.game():
        cands.append(str(cfg.game()))
    try:
        hit = core.find_ut_dir(None)
        if hit:
            cands.append(str(hit))
    except Exception:
        pass
    for r in lib.find_roots([Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"], depth=3):
        if cfg.is_ut_folder(r):
            cands.append(str(r))
    seen, out = set(), []
    for c in cands:
        k = str(Path(c).resolve()).lower()
        if k not in seen and not core.inside(Path(c), cfg.ROOT):
            seen.add(k)
            out.append({"path": c, "name": Path(c).name})
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    return {"candidates": out[:8], "game": game_state(), "settings": settings(),
            "default_out": str(cfg.ROOT / "Clips"), "default_obs": str(home / "Videos"),
            "app": str(HERE)}


def diagnostics() -> str:
    """A text to paste into a bug report: versions, folders, checks and the end of the log."""
    h = health()
    lines = [f"{cfg.APP_NAME} {cfg.VERSION}", f"Python {sys.version.split()[0]} on {sys.platform}",
             f"App folder: {HERE}", f"Game: {cfg.game()} ({cfg.mode()}), set up: {cfg.setup_done()}",
             f"Clips folder: {cfg.clips()}", f"Work folder: {cfg.out()}", ""]
    lines += [f"{'OK  ' if c['ok'] else 'FIX '}{c['label']}: {c['detail']}" for c in h["checks"]]
    log = cfg.LOG
    if log.exists():
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
        lines += ["", "--- end of the log ---"] + tail
    return "\n".join(lines)


def open_window(url: str) -> None:
    """An app window (Edge without address bar and tabs), else the normal browser."""
    if IS_WINDOWS and settings().get("open_as_app", True):
        for exe in (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
                    os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")):
            if Path(exe).exists():
                try:
                    subprocess.Popen([exe, f"--app={url}", "--window-size=1480,940"])
                    return
                except OSError:
                    break
    webbrowser.open(url)


def main() -> int:
    global SERVER
    # already open? then just show it again
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/ping", timeout=1) as r:
            if json.loads(r.read()).get("app") == cfg.APP_ID:
                print(f"{cfg.APP_NAME} is already open; showing it.")
                open_window(f"http://127.0.0.1:{PORT}/")
                return 0
    except (OSError, ValueError):
        pass
    for attempt in range(20 if "--restarted" in sys.argv else 1):  # after a restart the old one may still hold the port
        try:
            SERVER = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
            break
        except OSError:
            time.sleep(0.5)
    if SERVER is None:
        SERVER = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{SERVER.server_address[1]}/"
    print("=" * 72)
    print(f"  {cfg.APP_NAME} is open in its own window.")
    print(f"  (If not: open {url} in your browser.)")
    print("  Keep this window open while you use it; close it or press Quit to stop.")
    print("=" * 72)
    if "--no-window" not in sys.argv and "--restarted" not in sys.argv:
        open_window(url)
    try:
        SERVER.serve_forever()
    except KeyboardInterrupt:
        pass
    if JOB and JOB.state == "running":
        JOB.stop()
    if RESTART["wanted"]:
        SERVER.server_close()
        # the new panel runs the updated code; it shares this console window, so it stays open
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--restarted"], cwd=str(HERE))
        print(f"Restarting {cfg.APP_NAME} with the updated code ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
