"""Build the ready-to-run Killcam '99 release from this repository.

    py tools\\build_release.py              dist\\Killcam99\\ and dist\\Killcam99-<version>.zip
    py tools\\build_release.py --no-zip     only the folder

The repository already has the installed layout (Killcam99.bat, README.txt, app\\). The release
adds what does not belong in git: a portable Python 3.12 (python.org's "embeddable" build) with
numpy and pyaudiowpatch, inside app\\python. Downloads are cached in tools\\_cache.

Never copied: app\\data (settings, index, logs), app\\UT (a game copy), app\\tools (ffmpeg),
app\\python from a previous run, __pycache__.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"
DIST = REPO / "dist"
OUT = DIST / "Killcam99"
CACHE = REPO / "tools" / "_cache"
PY_VER = "3.12.10"
PY_URL = f"https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip"
LIBS = ["numpy", "pyaudiowpatch"]
SKIP = {"data", "UT", "tools", "python", "__pycache__"}

sys.path.insert(0, str(APP))
import kc_config as cfg  # noqa: E402


def say(m: str) -> None:
    print(m, flush=True)


def fetch(url: str, dest: Path) -> Path:
    if not dest.exists():
        say(f"downloading {url}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as r, open(dest.with_suffix(".part"), "wb") as f:
            shutil.copyfileobj(r, f)
        dest.with_suffix(".part").replace(dest)
    return dest


def portable_python(target: Path) -> None:
    z = fetch(PY_URL, CACHE / f"python-{PY_VER}-embed-amd64.zip")
    with zipfile.ZipFile(z) as zz:
        zz.extractall(target)
    pth = next(target.glob("python3*._pth"))
    # ".." = app\, where the program files are; site-packages holds the libraries
    pth.write_text("python312.zip\n.\nLib\\site-packages\n..\nimport site\n", encoding="ascii")
    site = target / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    wheels = CACHE / "wheels"
    subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary", ":all:", "--python-version", "3.12",
                    "--platform", "win_amd64", "--implementation", "cp", "-d", str(wheels), *LIBS], check=True)
    for w in wheels.glob("*.whl"):
        with zipfile.ZipFile(w) as zz:
            zz.extractall(site)
    say(f"portable Python {PY_VER} with {', '.join(LIBS)} ready")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-zip", action="store_true")
    a = ap.parse_args()
    if not (APP / "packs" / "base" / "Cache" / "cache.ini").exists():
        say("PROBLEM: app\\packs\\base is missing.")
        return 1
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "app").mkdir(parents=True)
    shutil.copy2(REPO / "Killcam99.bat", OUT / "Killcam99.bat")
    shutil.copy2(REPO / "README.txt", OUT / "README.txt")
    for p in APP.iterdir():
        if p.name in SKIP:
            continue
        (shutil.copytree if p.is_dir() else shutil.copy2)(p, OUT / "app" / p.name)
    for junk in OUT.rglob("__pycache__"):
        shutil.rmtree(junk, ignore_errors=True)
    portable_python(OUT / "app" / "python")
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    say(f"folder ready: {OUT} ({size / 2**20:.0f} MB)")
    if not a.no_zip:
        zpath = DIST / f"Killcam99-{cfg.VERSION}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for f in sorted(OUT.rglob("*")):
                if f.is_file():
                    z.write(f, Path("Killcam99") / f.relative_to(OUT))
        say(f"release ready: {zpath} ({zpath.stat().st_size / 2**20:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
