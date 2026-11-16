"""Download ffmpeg for Killcam '99 into tools\\ffmpeg (no installer, no admin rights).

Takes the current release build from gyan.dev, checks it against the published SHA-256, unpacks
ffmpeg.exe and ffprobe.exe, and checks that it can record a window in the background (the
'gfxcapture' filter, ffmpeg 8.1 or newer).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEST = HERE / "tools" / "ffmpeg"
URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
UA = {"User-Agent": "Killcam99-setup"}


def say(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def main() -> int:
    work = HERE / "tools" / "_download"
    work.mkdir(parents=True, exist_ok=True)
    zpath = work / "ffmpeg.zip"
    say(f"Downloading ffmpeg from {URL} ...")
    try:
        want = get(URL + ".sha256").decode("ascii", "replace").split()[0].lower()
        h, done = hashlib.sha256(), 0
        with urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=60) as r, open(zpath, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            step = max(1, total // 20) if total else 1 << 23
            nxt = step
            while chunk := r.read(1 << 20):
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if done >= nxt and total:
                    say(f"=== [{done * 100 // total}/100] ===")
                    nxt += step
    except OSError as e:
        say(f"PROBLEM: the download failed ({e}). Check the internet connection and try again.")
        return 1
    if h.hexdigest() != want:
        say("PROBLEM: the download is damaged (checksum does not match). Try again.")
        zpath.unlink(missing_ok=True)
        return 1
    say("Checksum OK. Unpacking ...")
    DEST.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            base = name.rsplit("/", 1)[-1].lower()
            if base in ("ffmpeg.exe", "ffprobe.exe") and "/bin/" in name:
                with z.open(name) as src, open(DEST / base, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    shutil.rmtree(work, ignore_errors=True)
    exe = DEST / "ffmpeg.exe"
    if not exe.exists():
        say("PROBLEM: ffmpeg.exe was not in the download.")
        return 1
    out = subprocess.run([str(exe), "-hide_banner", "-filters"], capture_output=True, text=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    ver = subprocess.run([str(exe), "-version"], capture_output=True, text=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.split("\n")[0]
    say(ver)
    if " gfxcapture " not in out:
        say("WARNING: this ffmpeg cannot record in the background (needs 8.1 or newer); the game window must stay visible.")
    say(f"Done: ffmpeg is in {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
