r"""Killcam '99: where everything lives, and how the game folder is used.

An installed copy looks like this; only the first three are meant to be seen:

    Killcam99\
      Killcam99.bat          start here
      README.txt             the manual
      Clips\                 finished videos: Demos\<type>\, Recordings\, Rejected\
      app\                   (hidden) everything else:
        *.py, *.html          the program          (APP)
        python\, tools\       portable Python, ffmpeg
        hook\, UT2VidHook\    the in-game add-on (built, source)
        packs\base\           packages that ship  (PACKS); packs\downloads: found online
        UT\                   the separate copy of the game, in copy mode
        data\                 settings.json, package index, manifest, log  (DATA)
          work\               scans, temporary recordings, bookkeeping   (out())

A developer folder (this file not inside a folder called "app") keeps everything in one place.
Settings keys: game_folder, game_mode, setup_done, clips_folder, source_folder.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

APP_NAME = "Killcam '99"
APP_ID = "killcam99"
VERSION = "1.3.0"

APP = Path(__file__).resolve().parent
INSTALLED = APP.name.lower() == "app"
ROOT = APP.parent if INSTALLED else APP     # the folder the player sees
DATA = APP / "data" if INSTALLED else APP
WORK = DATA / "work"
LOG = DATA / "killcam.log" if INSTALLED else APP / "ut2vid_log.txt"
PACKS = APP / "packs"
BASE_PACK = PACKS / "base"
DOWNLOADS = PACKS / "downloads"
TOOLS = APP / "tools"
COPY_DIR = APP / "UT"                       # where the "separate copy" lives
MANIFEST = DATA / "direct_manifest.json"     # what was added to the player's own UT folder
HOOK_FILE = "UT2VidHook.u"
TEMP_PREFIX = "ut2vid_"                     # every temporary file the tool writes into System starts so
VIDEO_EXTS = {".mp4", ".mkv", ".m4v", ".mov", ".webm"}
DATA.mkdir(parents=True, exist_ok=True)


def settings_file() -> Path:
    return DATA / "settings.json"


def load() -> dict:
    try:
        return json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(**kv) -> dict:
    st = load()
    st.update(kv)
    for k in [k for k, v in kv.items() if v is None]:
        st.pop(k, None)
    tmp = settings_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.replace(tmp, settings_file())
    return st


def is_ut_folder(p: Path | str | None) -> bool:
    if not p:
        return False
    p = Path(p)
    return any((p / s / "UnrealTournament.exe").is_file() for s in ("System", "System64"))


def migrate() -> None:
    """Older folders: a built copy in APP/UT from before the setup wizard counts as set up, and
    clips from the old single output folder move to the Clips folder."""
    st = load()
    if "game_folder" not in st and is_ut_folder(COPY_DIR):
        srcs = list(st.get("library_sources") or [])
        old_lib = APP / "library"
        if (old_lib / "Cache" / "cache.ini").exists() and str(old_lib) not in srcs:
            srcs.append(str(old_lib))  # the old copied library becomes one of 'your package folders'
        save(game_folder=str(COPY_DIR), game_mode="copy", setup_done=True,
             out_folder=st.get("out_folder") or str(APP / "videos"), library_sources=srcs)
    migrate_layout()
    clips().mkdir(parents=True, exist_ok=True)


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    try:
        os.replace(src, dst)
    except OSError:
        shutil.move(str(src), str(dst))


def _merge(src: Path, dst: Path) -> None:
    """A bookkeeping text file: move it, or add its lines to one that is already there."""
    if not dst.exists():
        _move(src, dst)
        return
    with open(dst, "a", encoding="utf-8") as f:
        f.write(src.read_text(encoding="utf-8", errors="replace"))
    src.unlink()


def migrate_layout(log=print) -> None:
    """Before 1.1 one output folder held the clips and the work files together. Videos go to the
    Clips folder (Demos, Recordings, Rejected), the rest to data/work; the clip list follows."""
    st = load()
    old = st.get("out_folder")
    if not old:
        return
    old = Path(old)
    target = Path(st.get("clips_folder") or ROOT / "Clips")
    names = {"clips": "Demos", "obs_clips": "Recordings"}
    if old.is_dir():
        for sub, new in (*names.items(), ("rejected", "Rejected")):
            src = old / sub
            if not src.is_dir():
                continue
            for f in sorted(src.rglob("*")):
                if not f.is_file():
                    continue
                rel = f.relative_to(src)
                if f.suffix.lower() in VIDEO_EXTS:
                    if sub == "rejected" and rel.parts and rel.parts[0] in names:
                        rel = Path(names[rel.parts[0]], *rel.parts[1:])
                    _move(f, target / new / rel)
                elif sub in names and f.parent == src:  # parts_done.txt, done.txt, events.txt, check.txt
                    _merge(f, WORK / f.name)
        idx = old / "clip_index.json"
        if idx.exists():
            try:
                items = json.loads(idx.read_text(encoding="utf-8"))
                for x in items:
                    parts = Path(x.get("file", "")).parts
                    if parts and parts[0] in names:
                        x["file"] = str(Path(names[parts[0]], *parts[1:]))
                idx.write_text(json.dumps(items, indent=1), encoding="utf-8")
            except (OSError, ValueError):
                pass
        if not same(old, WORK):
            for f in list(old.iterdir()):
                if f.name in names or f.name == "rejected":
                    if f.is_dir() and not any(p.is_file() for p in f.rglob("*")):
                        shutil.rmtree(f, ignore_errors=True)
                    continue
                _move(f, WORK / f.name)
            try:
                old.rmdir()
            except OSError:
                pass
    save(clips_folder=str(target), out_folder=None)
    log(f"Clips are now in {target}; work files in {WORK}")


def game() -> Path | None:
    g = load().get("game_folder")
    return Path(g) if g and is_ut_folder(g) else None


def mode() -> str:
    return load().get("game_mode") or "copy"


def setup_done() -> bool:
    return bool(load().get("setup_done")) and game() is not None


def out() -> Path:
    """The work folder: scans, temporary recordings, the clip list and bookkeeping."""
    o = load().get("out_folder")  # only until migrate_layout has run
    return Path(o) if o else WORK


def clips() -> Path:
    """Where finished videos go (with Demos, Recordings and Rejected inside)."""
    c = load().get("clips_folder")
    return Path(c) if c else ROOT / "Clips"


def same(a: Path | str | None, b: Path | str | None) -> bool:
    if not a or not b:
        return False
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def system_dir(root: Path) -> Path:
    return root / "System64" if (root / "System64" / "UnrealTournament.exe").is_file() else root / "System"


# ---------------- direct mode: remember every change so it can be undone ----------------

def manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"game": None, "files": [], "cache": []}


def _save_manifest(m: dict) -> None:
    MANIFEST.write_text(json.dumps(m, indent=1), encoding="utf-8")


def record_file(path: Path) -> None:
    """A file Killcam '99 added to the player's own UT folder (only tracked in direct mode)."""
    if mode() != "direct":
        return
    m = manifest()
    m["game"] = m.get("game") or str(game())
    if str(path) not in m["files"]:
        m["files"].append(str(path))
        _save_manifest(m)


def record_replaced(path: Path) -> None:
    """Before Killcam '99 replaces a file in the player's own UT folder (direct mode; today only
    NPLoader's native loader for the wrong CPU type): keep the original, so Remove puts it back
    byte for byte. The first original is the one kept."""
    if mode() != "direct" or not path.is_file():
        return
    m = manifest()
    m["game"] = m.get("game") or str(game())
    reps = m.setdefault("replaced", [])
    if any(r["file"] == str(path) for r in reps):
        return
    bak = DATA / "direct_backup" / f"{len(reps)}_{path.name}"
    bak.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, bak)
    reps.append({"file": str(path), "backup": str(bak)})
    _save_manifest(m)


def record_cache(cache_dir: Path, guid: str, filename: str, new_file: bool) -> None:
    """A package added to the player's Cache (the .uxx, when new, and its cache.ini line)."""
    if mode() != "direct" or not same(cache_dir.parent, game()):
        return
    m = manifest()
    m["game"] = m.get("game") or str(game())
    m["cache"].append({"guid": guid, "file": filename, "uxx": new_file})
    _save_manifest(m)


def undo_direct(log=print) -> int:
    """Remove everything the manifest lists from the player's UT folder. Returns the number removed."""
    m = manifest()
    n = 0
    for f in m.get("files", []):
        p = Path(f)
        if p.exists():
            p.unlink()
            n += 1
            log(f"removed {p}")
    for r in m.get("replaced", []):  # files Killcam '99 replaced: the originals go back
        bak, p = Path(r["backup"]), Path(r["file"])
        if bak.is_file():
            shutil.copy2(bak, p)
            bak.unlink()
            n += 1
            log(f"restored {p}")
    g = Path(m["game"]) if m.get("game") else None
    if g and m.get("cache"):
        ci = g / "Cache" / "cache.ini"
        guids = {c["guid"].upper() for c in m["cache"]}
        for c in m["cache"]:
            if c.get("uxx"):
                p = g / "Cache" / f"{c['guid'].upper()}.uxx"
                if p.exists():
                    p.unlink()
                    n += 1
        if ci.exists():
            with open(ci, "r", encoding="latin-1", newline="") as fh:
                lines = fh.read().splitlines(keepends=True)
            keep = [ln for ln in lines if not (re.match(r"\s*([0-9A-Fa-f]{32})\s*=", ln)
                                                and ln.split("=", 1)[0].strip().upper() in guids)]
            with open(ci, "w", encoding="latin-1", newline="") as fh:
                fh.write("".join(keep))
        log(f"removed {len(m['cache'])} package(s) from {g / 'Cache'}")
    if g:
        n += clean_temp(system_dir(g), log)
    MANIFEST.unlink(missing_ok=True)
    return n


def clean_temp(sysdir: Path | None, log=None) -> int:
    """Delete the temporary ut2vid_* files from a System folder (needed in direct mode: the
    player's folder must look untouched between runs)."""
    if not sysdir or not sysdir.is_dir():
        return 0
    n = 0
    for p in sysdir.iterdir():
        if p.name.lower().startswith(TEMP_PREFIX) and p.is_file():
            try:
                p.unlink()
                n += 1
            except OSError:
                pass  # in use by a running UT: it goes next time
        elif p.name.lower().startswith(TEMP_PREFIX) and p.is_dir():  # ut2vid_pkgs_*: package versions per run
            shutil.rmtree(p, ignore_errors=True)
            n += 0 if p.exists() else 1
    if n and log:
        log(f"cleaned {n} temporary file(s) in {sysdir}")
    return n


def free_bytes(p: Path) -> int:
    try:
        return shutil.disk_usage(p if p.exists() else p.anchor).free
    except OSError:
        return 0
