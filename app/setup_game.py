#!/usr/bin/env python3
"""
setup_game.py - gets an Unreal Tournament folder ready for Killcam '99.

    setup_game.py --ut "C:\\UnrealTournament" --mode copy      a separate copy in <Killcam '99>\\UT
    setup_game.py --ut "C:\\UnrealTournament" --mode direct    use that folder itself
    setup_game.py --undo                                       remove what direct mode added
    setup_game.py --remove-copy                                delete the separate copy

copy:   1. copies the UT folder into <Killcam '99>\\UT (the original is only READ),
        2. takes its download cache along, points the Demo Manager at the copy,
        3. puts the UT2VidHook add-on in the copy (the shipped one; compiled only as a fallback).
        Every write is checked: anything outside the Killcam '99 folder aborts the script.
direct: adds only System\\UT2VidHook.u to the player's folder (listed in direct_manifest.json,
        so --undo can take it out again). No settings file of the player is edited: the tool
        runs UT with its own ini copies. Missing packages a demo needs are added to Cache later,
        and listed in the same manifest.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import kc_config as cfg

ROOT = cfg.APP
DEST = cfg.COPY_DIR
HOOK_PKG = "UT2VidHook"
SHIPPED_HOOK = ROOT / "hook" / cfg.HOOK_FILE     # the pre-built add-on that ships with the app
SKIP_NAMES = re.compile(r"^ut2vid", re.I)        # temporary files of the tool: never copied
REPORT: list[str] = []


def say(msg: str) -> None:
    line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    REPORT.append(line)


def inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def guard(p: Path) -> Path:
    """Copy mode: refuse any write outside the Killcam '99 folder."""
    if not inside(p, ROOT):
        raise SystemExit(f"SAFETY STOP: refused to write outside {ROOT}: {p}")
    return p


def folder_size(p: Path) -> int:
    n = 0
    for dirpath, _d, files in os.walk(p):
        for fn in files:
            try:
                n += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return n


def check_source(p: Path) -> Path:
    if not cfg.is_ut_folder(p):
        raise SystemExit(f"PROBLEM: not an Unreal Tournament folder (no System\\UnrealTournament.exe): {p}")
    sysdir = cfg.system_dir(p)
    if not (sysdir / "udemo.u").exists():
        raise SystemExit("PROBLEM: this UT has no udemo (System\\udemo.u). Killcam '99 needs UT with the "
                         "OldUnreal 469 patch, which includes it.")
    return p


# ---------------- copy mode ----------------

def copy_tree(src: Path, dst: Path) -> tuple[int, int]:
    copied = skipped = 0
    for dirpath, _dirnames, filenames in os.walk(src):
        rel = Path(dirpath).relative_to(src)
        target_dir = guard(dst / rel)
        target_dir.mkdir(parents=True, exist_ok=True)
        for fn in filenames:
            if SKIP_NAMES.match(fn):
                continue
            s, d = Path(dirpath) / fn, guard(target_dir / fn)
            try:
                st = s.stat()
                if d.exists():
                    dt_ = d.stat()
                    if dt_.st_size == st.st_size and int(dt_.st_mtime) == int(st.st_mtime):
                        skipped += 1
                        continue
                shutil.copy2(s, d)  # reads s, writes d only
                copied += 1
                if copied % 500 == 0:
                    say(f"  ... {copied} files copied")
            except OSError as e:
                say(f"  WARNING: could not copy {s}: {e}")
    return copied, skipped


def read_cache_ini(cache_dir: Path) -> dict[str, str]:
    out = {}
    ci = cache_dir / "cache.ini"
    if ci.exists():
        for line in ci.read_text(encoding="latin-1", errors="replace").splitlines():
            m = re.match(r"\s*([0-9A-Fa-f]{32})\s*=\s*(.+?)\s*$", line)
            if m and (cache_dir / f"{m.group(1).upper()}.uxx").exists():
                out[m.group(1).upper()] = m.group(2)
    return out


def merge_caches(donors: list[Path]) -> int:
    """Cache1 and the like next to Cache: their packages go into the copy's Cache too."""
    dest_cache = guard(DEST / "Cache")
    dest_cache.mkdir(exist_ok=True)
    have = read_cache_ini(dest_cache)
    added = []
    for donor in donors:
        for sub in sorted(donor.glob("Cache*")):
            if not sub.is_dir():
                continue
            for guid, name in read_cache_ini(sub).items():
                if guid in have:
                    continue
                try:
                    dst = guard(dest_cache / f"{guid}.uxx")
                    if not (dst.exists() and dst.stat().st_size == (sub / f"{guid}.uxx").stat().st_size):
                        shutil.copy2(sub / f"{guid}.uxx", dst)
                    have[guid] = name
                    added.append((guid, name))
                except OSError as e:
                    say(f"  WARNING: {sub.name}\\{guid}.uxx: {e}")
    if added:
        ci = guard(dest_cache / "cache.ini")
        text = "[Cache]\r\n"
        if ci.exists():
            with open(ci, "r", encoding="latin-1", newline="") as f:
                text = f.read()
        if not text.endswith(("\n", "\r")):
            text += "\r\n"
        text += "".join(f"{g}={n}\r\n" for g, n in added)
        with open(ci, "w", encoding="latin-1", newline="") as f:
            f.write(text)
    return len(added)


def patch_text_file(p: Path, fn) -> None:
    guard(p)
    with open(p, "r", encoding="latin-1", newline="") as f:
        text = f.read()
    new = fn(text)
    if new != text:
        with open(p, "w", encoding="latin-1", newline="") as f:
            f.write(new)


def add_edit_packages(text: str) -> str:
    lines = text.split("\r\n") if "\r\n" in text else text.split("\n")
    nl = "\r\n" if "\r\n" in text else "\n"
    have = {ln.strip().lower() for ln in lines}
    last = max((i for i, ln in enumerate(lines) if ln.strip().lower().startswith("editpackages=")), default=None)
    if last is None:
        raise SystemExit("No EditPackages= lines found in UnrealTournament.ini of the copy.")
    extra = [f"EditPackages={p}" for p in ("udemo", HOOK_PKG) if f"editpackages={p.lower()}" not in have]
    return nl.join(lines[:last + 1] + extra + lines[last + 1:])


def fix_absolute_paths(source: Path) -> None:
    """Settings files of the copy must not point back into the original: such paths are rewritten."""
    for ini in sorted((DEST / "System").glob("*.ini")):
        with open(ini, "r", encoding="latin-1", newline="") as f:
            text = f.read()
        new = re.sub(re.escape(str(source)), lambda m: str(DEST), text, flags=re.I)
        if new != text:
            with open(guard(ini), "w", encoding="latin-1", newline="") as f:
                f.write(new)
            say(f"  {ini.name}: paths into the original now point at the copy")


def compile_hook() -> bool:
    """Developers only (copy mode): compile the add-on from UT2VidHook\\Classes with the copy's UCC."""
    sysdir = DEST / "System"
    dst_cls = guard(DEST / HOOK_PKG / "Classes")
    dst_cls.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / HOOK_PKG / "Classes").glob("*.uc"):
        shutil.copy2(f, guard(dst_cls / f.name))
    patch_text_file(sysdir / "UnrealTournament.ini", add_edit_packages)
    u = guard(sysdir / cfg.HOOK_FILE)
    u.unlink(missing_ok=True)
    say(f"Compiling {HOOK_PKG} with {sysdir / 'UCC.exe'} ...")
    r = subprocess.run([str(sysdir / "UCC.exe"), "make", "-silent"], cwd=str(sysdir),
                       capture_output=True, text=True, errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    (cfg.DATA / "ucc_make.log").write_text(out, encoding="utf-8")
    if u.exists():
        say(f"  {cfg.HOOK_FILE} built.")
        shutil.copy2(u, guard(SHIPPED_HOOK))  # becomes the shipped one
        return True
    say(f"  PROBLEM: {cfg.HOOK_FILE} was not built. Last UCC output:")
    for ln in [ln for ln in out.splitlines() if ln.strip()][-15:]:
        say("    ucc| " + ln)
    return False


def hook_source_newer() -> bool:
    if not SHIPPED_HOOK.exists():
        return True
    t = SHIPPED_HOOK.stat().st_mtime
    return any(f.stat().st_mtime > t for f in (ROOT / HOOK_PKG / "Classes").glob("*.uc"))


def install_hook(game: Path, record: bool) -> bool:
    if not SHIPPED_HOOK.exists():
        say(f"PROBLEM: the add-on {SHIPPED_HOOK} is missing from the Killcam '99 folder. Unzip the release again.")
        return False
    dst = cfg.system_dir(game) / cfg.HOOK_FILE
    existed = dst.exists()
    shutil.copy2(SHIPPED_HOOK, dst)
    if record and not existed:
        cfg.record_file(dst)
    say(f"  add-on placed: {dst}")
    return True


def setup_copy(source: Path, compile_: bool) -> bool:
    if inside(source, cfg.ROOT) or inside(cfg.ROOT, source):
        raise SystemExit("PROBLEM: the UT folder and the Killcam '99 folder must not contain each other.")
    need, free = folder_size(source), cfg.free_bytes(ROOT)
    have = folder_size(DEST) if DEST.exists() else 0
    say(f"Original (only read): {source}  ({need / 2**30:.1f} GB)")
    say(f"Copy:                 {DEST}")
    if need - have > free:
        say(f"PROBLEM: not enough free space: {(need - have) / 2**30:.1f} GB needed, {free / 2**30:.1f} GB free.")
        return False
    say("Copying Unreal Tournament ...")
    c, s = copy_tree(source, DEST)
    say(f"  {c} files copied, {s} already up to date.")
    n = merge_caches([source])
    if n:
        say(f"  {n} downloaded packages from extra cache folders added.")
    ud = DEST / "System" / "udemo.ini"
    if ud.exists():
        sysdir = str(DEST / "System") + "\\"
        patch_text_file(ud, lambda t: re.sub(r"(?im)^(DemoPaths\[0\]=).*$", lambda m: m.group(1) + sysdir, t))
    fix_absolute_paths(source)
    if hook_source_newer() and not compile_:
        say("  note: the add-on source is newer than hook\\UT2VidHook.u (developers: run with --compile)")
    if compile_ or not SHIPPED_HOOK.exists():
        if not compile_hook():
            return False
    return install_hook(DEST, record=False)


def setup_direct(game: Path) -> bool:
    say(f"Your UT folder: {game}")
    say("Only the add-on is added now; packages a demo needs are added to Cache when it is converted.")
    m = cfg.manifest()
    if m.get("game") and not cfg.same(m["game"], game):
        say(f"Another folder was used directly before ({m['game']}): removing what was added there first.")
        cfg.undo_direct(say)
    cfg.save(game_folder=str(game), game_mode="direct")  # so the manifest records this folder
    return install_hook(game, record=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Get a UT folder ready for Killcam '99")
    ap.add_argument("--ut", help="the Unreal Tournament folder")
    ap.add_argument("--mode", choices=["copy", "direct"], default="copy")
    ap.add_argument("--compile", action="store_true", help="compile the add-on (developers, copy mode)")
    ap.add_argument("--undo", action="store_true", help="remove what direct mode added to the UT folder")
    ap.add_argument("--remove-copy", action="store_true", help="delete the separate copy")
    a = ap.parse_args()
    if a.undo:
        n = cfg.undo_direct(say)
        if cfg.mode() == "direct":
            cfg.save(setup_done=False)
        say(f"Done: {n} file(s) removed. Your UT folder is as it was before Killcam '99.")
        return 0
    if a.remove_copy:
        if cfg.mode() == "copy" and cfg.setup_done():
            cfg.save(setup_done=False)
        if DEST.exists():
            shutil.rmtree(guard(DEST))
        say("Done: the separate copy is deleted.")
        return 0
    if not a.ut:
        ap.error("--ut is needed")
    source = check_source(Path(a.ut).resolve())
    if a.mode == "copy":
        if cfg.manifest().get("game"):
            say("Removing what Killcam '99 added to your UT folder before (it now uses a copy) ...")
            cfg.undo_direct(say)
        ok = setup_copy(source, a.compile)
        if ok:
            cfg.save(game_folder=str(DEST), game_mode="copy", setup_done=True, source_folder=str(source))
    else:
        ok = setup_direct(source)
        if ok:
            cfg.save(game_folder=str(source), game_mode="direct", setup_done=True)
    (cfg.DATA / "setup_report.txt").write_text("\n".join(REPORT) + "\n", encoding="utf-8")
    say("Done. Killcam '99 is ready." if ok else "Stopped: see the messages above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
