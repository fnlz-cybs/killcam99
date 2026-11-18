"""Killcam '99 updates from the GitHub releases of fnlz-cybs/killcam99.

    check                          is a newer release out? (one request to the GitHub API)
    download --version V --url U --size N [--digest sha256:...]
                                   fetch the release zip, check it, unpack it into data\\update\\new
    apply --from DIR --to DIR --wait-pid PID [--restart]
                                   (run by the app, with the NEW release's own Python, after the app
                                   closed) copy the new files over the install, then start it again

What stays as it is: your clips (Clips), your settings and work files (app\\data), the separate game
copy (app\\UT), ffmpeg (app\\tools) and packages found online (app\\packs\\downloads).
Nothing personal is sent: GitHub sees one request with a generic program name.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = "fnlz-cybs/killcam99"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
AGENT = "Killcam99-update-check"
# never replaced by an update (paths relative to the install folder, the one with Killcam99.bat)
KEEP = ("Clips/", "app/data/", "app/UT/", "app/tools/", "app/packs/downloads/")


def say(m: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + m, flush=True)


def version_tuple(v: str) -> tuple[int, ...]:
    out = []
    for part in v.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def latest_release(timeout: float = 10) -> dict:
    """{version, name, notes, page, asset: {name, url, size, digest}} of the latest release."""
    req = urllib.request.Request(API, headers={"User-Agent": AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rel = json.loads(r.read().decode("utf-8"))
    asset = next((a for a in rel.get("assets", []) if a.get("name", "").lower().endswith(".zip")
                  and a["name"].lower().startswith("killcam99")), None)
    return {"version": rel.get("tag_name", "").lstrip("vV"), "name": rel.get("name") or rel.get("tag_name", ""),
            "notes": (rel.get("body") or "").strip(), "page": rel.get("html_url", ""),
            "asset": {"name": asset["name"], "url": asset["browser_download_url"], "size": asset.get("size", 0),
                      "digest": asset.get("digest") or ""} if asset else None}


def check(current: str) -> dict:
    rel = latest_release()
    rel["current"] = current
    rel["newer"] = bool(rel["version"]) and version_tuple(rel["version"]) > version_tuple(current)
    return rel


def staging(data: Path) -> Path:
    return data / "update"


def staged_version(data: Path) -> str | None:
    """The version unpacked in data\\update\\new and ready to apply, or None."""
    cfg = staging(data) / "new" / "Killcam99" / "app" / "kc_config.py"
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            if line.startswith("VERSION"):
                return line.split("=", 1)[1].strip().strip('"\'')
    except OSError:
        return None
    return None


def download(data: Path, version: str, url: str, size: int, digest: str) -> int:
    st = staging(data)
    shutil.rmtree(st, ignore_errors=True)
    st.mkdir(parents=True)
    z = st / f"Killcam99-{version}.zip"
    say(f"Downloading Killcam '99 {version} ({size / 1e6:.0f} MB) from GitHub ...")
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    h = hashlib.sha256()
    got, step, next_note = 0, 1 << 20, 0
    with urllib.request.urlopen(req, timeout=60) as r, open(z, "wb") as f:
        while True:
            b = r.read(step)
            if not b:
                break
            f.write(b)
            h.update(b)
            got += len(b)
            if size and got >= next_note:
                pct = min(100, int(got * 100 / size))
                print(f"=== [{pct}/100] ===", flush=True)  # the app's progress bar
                next_note = got + size // 50
    if size and got != size:
        say(f"PROBLEM: the download is {got} bytes, GitHub said {size}. Try again later.")
        return 1
    if digest.lower().startswith("sha256:") and h.hexdigest() != digest.split(":", 1)[1].lower():
        say("PROBLEM: the download does not match GitHub's checksum. Nothing was changed.")
        return 1
    say("Download checked" + (" (size and SHA-256)." if digest else " (size)."))
    with zipfile.ZipFile(z) as zz:
        bad = [n for n in zz.namelist() if not n.startswith("Killcam99/") or ".." in Path(n).parts]
        if bad:
            say(f"PROBLEM: unexpected files in the zip ({bad[0]}). Nothing was changed.")
            return 1
        zz.extractall(st / "new")
    z.unlink()
    got_v = staged_version(data)
    if got_v != version:
        say(f"PROBLEM: the zip holds version {got_v}, not {version}. Nothing was changed.")
        return 1
    say(f"READY: Killcam '99 {version} is unpacked. Restart Killcam '99 to finish the update.")
    return 0


def wait_for_exit(pid: int, timeout: float = 60) -> None:
    if os.name != "nt":
        return
    import ctypes
    k32 = ctypes.WinDLL("kernel32")
    h = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if h:
        k32.WaitForSingleObject(h, int(timeout * 1000))
        k32.CloseHandle(h)
    time.sleep(1.0)


def apply(src: Path, dst: Path, pid: int, restart: bool) -> int:
    """Copy the new release over the install (only what changed), keeping everything in KEEP."""
    wait_for_exit(pid)
    say(f"Updating {dst} ...")
    n = kept = 0
    for f in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = f.relative_to(src).as_posix()
        if rel.startswith(KEEP):
            kept += 1
            continue
        t = dst / rel
        if t.exists() and t.stat().st_size == f.stat().st_size and t.read_bytes() == f.read_bytes():
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(10):  # a file can stay locked for a moment after the app closed
            try:
                shutil.copy2(f, t)
                n += 1
                break
            except OSError:
                time.sleep(0.5)
        else:
            say(f"PROBLEM: could not replace {rel}. Close Killcam '99 and unzip the release by hand.")
            return 1
    say(f"Done: {n} file(s) updated.")
    (dst / "app" / "data" / "update" / "applied.txt").write_text(time.strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
    if restart and os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "", str(dst / "Killcam99.bat")], cwd=str(dst),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Killcam '99 updates from GitHub")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--current", default="0")
    d = sub.add_parser("download")
    d.add_argument("--data", type=Path, required=True)
    d.add_argument("--version", required=True)
    d.add_argument("--url", required=True)
    d.add_argument("--size", type=int, default=0)
    d.add_argument("--digest", default="")
    a = sub.add_parser("apply")
    a.add_argument("--from", dest="src", type=Path, required=True)
    a.add_argument("--to", dest="dst", type=Path, required=True)
    a.add_argument("--wait-pid", type=int, default=0)
    a.add_argument("--restart", action="store_true")
    args = ap.parse_args()
    if args.cmd == "check":
        print(json.dumps(check(args.current), indent=1))
        return 0
    if args.cmd == "download":
        return download(args.data, args.version, args.url, args.size, args.digest)
    return apply(args.src, args.dst, args.wait_pid, args.restart)


if __name__ == "__main__":
    sys.exit(main())
