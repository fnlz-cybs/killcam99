#!/usr/bin/env python3
"""
ut99_dem2video.py  -  Convert Unreal Tournament (UT99) .dem demos into .mp4 / .mkv videos.

How it works
------------
A UT99 demo is a recording of network traffic, not video, so only the game engine can
render it. For every demo this tool:

  1. copies the demo into UT's System folder under a safe temporary name,
  2. starts UnrealTournament.exe in a borderless window with "exec=" so it runs
     DEMOPLAY on its own (needs the OldUnreal patch 469e or newer),
  3. records the game window with ffmpeg (gdigrab) and the PC's sound output with
     WASAPI loopback (pyaudiowpatch),
  4. notices when the demo has finished (UT releases the demo file / the log shows a
     level change / the game exits / a timeout based on the demo's length),
  5. closes UT and muxes picture and sound, correcting the start offset between them.

Playback is real time, so a 25 minute demo takes about 25 minutes to convert.
Do not use the PC while it runs: whatever covers the game window ends up in the video,
and every sound the PC plays ends up in the audio.

Requirements (Windows)
----------------------
  * Unreal Tournament with the OldUnreal 469e (or newer) patch, plus every map/mod the
    demos use (UT will refuse to play a demo with missing packages).
  * Python 3.9+            https://www.python.org/downloads/
  * ffmpeg on PATH         winget install Gyan.FFmpeg
  * pip install pyaudiowpatch   (only for sound; use --no-audio to skip)

Missing maps and mods
---------------------
Every demo lists the exact version (GUID) of each map, mod and texture it was recorded
with. Before recording, the tool checks those against your UT folder. Exact matches it
finds in other UT folders next to it (e.g. on the Desktop) are copied into this UT's
Cache. Anything still missing is looked up on medor.no-ip.org/uz and the redirect
servers in udemo.ini, unpacked with UCC and kept only if the version matches exactly.
Nothing outside UT's Cache folder is changed. Demos that still miss something are
skipped and listed in videos/missing_packages.txt.

Examples
--------
  py ut99_dem2video.py                               # all demos next to this script
  py ut99_dem2video.py --only Grudge --limit 1       # quick test on one demo
  py ut99_dem2video.py --dry-run                     # check setup and packages, change nothing
  py ut99_dem2video.py --prepare-only                # only gather missing maps/mods
  py ut99_dem2video.py --ut "D:\\Games\\UnrealTournament" --format mp4 --fps 60
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

IS_WINDOWS = os.name == "nt"
TMP_DEMO = "ut2vid_tmp.dem"
EXEC_FILE = "ut2vid_exec.txt"
INI_FILE = "ut2vid.ini"
USER_INI_FILE = "ut2vid_user.ini"
LOG_FILE = "ut2vid.log"

# Log lines that mean "the demo is over" (playback ended and UT left the level).
END_PATTERNS = [
    r"LoadMap:\s*(Entry|UT-Logo-Map|CityIntro)",
    r"Browse:\s*\S*\?(closed|failed)",
    r"Demo\b.*\b(ended|finished|stopped|playback complete)",
    r"Failed;?\s*returning to Entry",
]
# Log lines that mean "the demo could not be played at all".
FAIL_PATTERNS = [
    r"Browse:\s*\S*\?failed",
    r"Can't find file for package",
    r"[Pp]ackage .* version mismatch",
    r"Pending connect .* failed",
    r"Couldn't open demo",
    r"Critical:",
]


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------

LOG_PATH: Path | None = None
SANDBOX: Path | None = None   # the Killcam '99 program folder, once the game is set up (kc_config)
GAME: Path | None = None      # the UT folder in use (a copy in SANDBOX\UT, or the player's own: GAME_MODE "direct")
GAME_MODE = "copy"

try:
    import kc_config
except ImportError:  # the converter on its own, without Killcam '99 around it
    kc_config = None


SAY_LOCK = threading.RLock()
WIN_LOCK = threading.Lock()  # window juggling (find, move, give focus back) one instance at a time


def say(msg: str) -> None:
    line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
    with SAY_LOCK:  # parallel scans: one line at a time
        print(line, flush=True)
        if LOG_PATH:
            try:
                with open(LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass


def fmt_dur(sec: float | None) -> str:
    if sec is None:
        return "?"
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def map_from_filename(name: str) -> str | None:
    """'..._[A_B]_CTF-Duku-CL.dem' -> 'CTF-Duku-CL' (UT auto-demo naming)."""
    stem = Path(name).stem
    m = re.search(r"\]_([A-Za-z0-9]+-[^_]+)$", stem)
    if m:
        return m.group(1)
    m = re.search(r"((?:CTF|DM|DOM|AS|BT|TDM|CTF4|MH|JB|SB)-[^\s]+)$", stem, re.I)
    return m.group(1) if m else None


def demo_start(name) -> float | None:
    """Start minute from udemo's file name '..._[2026_01_17_0012]_...' (str or Path), else None."""
    m = re.search(r"\[(\d{4})_(\d{2})_(\d{2})_(\d{2})(\d{2})\]", Path(str(name)).name)
    if not m:
        return None
    try:
        return dt.datetime(*map(int, m.groups())).timestamp()
    except ValueError:
        return None


def demo_start_exact(path: Path, total: float | None) -> tuple[float | None, bool]:
    """Start of a demo to the second: UT writes the demo until it stops recording, so the file's
    modification time minus the demo's length is its start (checked against udemo's file names:
    it always lands inside the minute in the name). Works for renamed demos too, as long as the
    file time was kept (copying does keep it). Returns (start, exact); falls back to the minute
    in the name (exact=False) when the length is unknown or the two disagree."""
    named = demo_start(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return named, False
    if total and total > 0:
        t = mtime - total
        if named is None or -90 <= t - named <= 150:
            return t, True
    return named, False


SCAN_DIR: Path | None = None  # <out>/scans, set at start-up
RUN_ID = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # clips made in this run are 'new' on the review page


def scan_total(path: Path) -> float | None:
    """Demo length as read by an earlier scan (exact), or None."""
    if SCAN_DIR is None:
        return None
    f = SCAN_DIR / (path.stem + ".json")
    try:
        import json
        return float(json.loads(f.read_text(encoding="utf-8")).get("total") or 0) or None
    except (OSError, ValueError, TypeError):
        return None


def estimate_duration(path: Path) -> float | None:
    """UT names auto-recorded demos with their start time ([YYYY_MM_DD_HHMM]) and the file's
    modification time is when recording stopped, so the difference is the demo length."""
    m = re.search(r"\[(\d{4})_(\d{2})_(\d{2})_(\d{2})(\d{2})\]", path.name)
    if not m:
        return scan_total(path)  # renamed demo: the length an earlier scan read from the demo
    y, mo, d, h, mi = map(int, m.groups())
    try:
        start = dt.datetime(y, mo, d, h, mi).timestamp()  # local time, like the filename
    except ValueError:
        return None
    est = path.stat().st_mtime - start
    if 0 < est < 4 * 3600:
        return est
    return None


def count_packets(path: Path) -> int | None:
    """Sanity check of the demo framing: [int32 frame][8 bytes][int32 len][len bytes]."""
    import struct
    try:
        with open(path, "rb") as f:
            n = 0
            while True:
                hdr = f.read(16)
                if len(hdr) < 16:
                    return n if not hdr else None
                (length,) = struct.unpack_from("<i", hdr, 12)
                if length < 0 or length > 1_000_000:
                    return None
                f.seek(length, 1)
                n += 1
    except OSError:
        return None


# --------------------------------------------------------------------------------------
# Package requirements: every demo starts with "USES GUID=... PKG=... FNAME=..." lines that
# list each package (map, mod, texture...) at the exact version the server used. They are
# stored bit-packed, so the stream is scanned at all 8 bit offsets.
# --------------------------------------------------------------------------------------

USES_RE = re.compile(rb"USES GUID=([0-9A-F]{32}) PKG=([\x21-\x7e]+) FLAGS=(\d+) SIZE=(\d+) GEN=(\d+) FNAME=([\x21-\x7e]+)")
PKG_EXTS = (".u", ".unr", ".utx", ".uax", ".umx")
PKG_CLIENT_OPTIONAL = 0x02
_SAFE_NAME = re.compile(r"[A-Za-z0-9_\-+.\[\]()!~#$&'@^{}=,;%]{1,96}")


def is_bare_name(name: str) -> bool:
    """A bare file name: no folder separators, drive letters or '..', so it can never point
    outside the folder it is joined to. Package and file names from demos and web pages pass
    through this before they are used in a path."""
    return bool(_SAFE_NAME.fullmatch(name or "")) and ".." not in name


def local_request_ok(headers) -> bool:
    """Requests to the local web pages must come from the page itself: the Host must be this PC
    (blocks DNS rebinding) and the browser must not mark the request as coming from another site
    (blocks other web pages embedding or calling these pages, e.g. playing clips in <video>)."""
    host = (headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
    site = (headers.get("Sec-Fetch-Site") or "").lower()
    return host in ("127.0.0.1", "localhost") and site in ("", "same-origin", "none")


def safe_file_name(name: str, fallback: str = "download") -> str:
    """Reduce a name taken from a URL or archive to a safe bare file name."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[^A-Za-z0-9_\-+.\[\]()!~#$&'@^{}=,;%]", "_", base).strip(". ")
    base = base.replace("..", "_")[:120]
    return base or fallback


def demo_packages(path: Path, nbytes: int = 2_000_000) -> list[dict] | None:
    """Scan each demo packet ([int32 frame][8 bytes][int32 len][payload]) at all 8 bit offsets,
    plus the raw stream for strings that span packet boundaries."""
    import struct
    with open(path, "rb") as f:
        data = f.read(nbytes)
    if not data:
        return None
    chunks, o = [data], 0
    while o + 16 <= len(data):
        (ln,) = struct.unpack_from("<i", data, o + 12)
        if ln < 0 or o + 16 + ln > len(data):
            break
        chunks.append(data[o + 16:o + 16 + ln])
        o += 16 + ln
    found: dict[str, dict] = {}
    for chunk in chunks:
        if b"" == chunk:
            continue
        n, size = int.from_bytes(chunk, "little"), len(chunk)
        for k in range(8):
            for m in USES_RE.finditer((n >> k).to_bytes(size, "little")):
                g, pkg, flags, sz, gen, fname = (x.decode("latin-1") for x in m.groups())
                if not (is_bare_name(pkg) and is_bare_name(fname)):
                    continue  # a demo is untrusted input: names become file names, so no paths allowed
                found.setdefault(g, {"guid": g, "pkg": pkg, "flags": int(flags), "size": int(sz), "gen": int(gen),
                                     "fname": fname})
    return list(found.values()) or None


def pkg_guid(path: Path) -> str | None:
    """GUID from an Unreal package header. Version 68+ stores it in the header; older
    packages (many stock 1999 textures/sounds) keep it as the last 'heritage' entry."""
    import struct
    try:
        with open(path, "rb") as f:
            h = f.read(64)
            tag, ver = struct.unpack_from("<IH", h, 0)
            if tag != 0x9E2A83C1:
                return None
            if ver >= 68:
                return "".join(f"{x:08X}" for x in struct.unpack_from("<4I", h, 36))
            count, offset = struct.unpack_from("<II", h, 36)
            if count < 1 or count > 10000:
                return None
            f.seek(offset + 16 * (count - 1))
            return "".join(f"{x:08X}" for x in struct.unpack("<4I", f.read(16)))
    except (OSError, struct.error):
        return None


def candidate_filenames(req: dict) -> list[str]:
    if not req["fname"].lower().endswith(".uxx"):
        return [req["fname"]]
    pkg = req["pkg"]
    if re.match(r"(?i)(CTF|DM|DOM|AS|BT|TDM|CTF4|MH|JB|SB|RA|LMS|EOL)-", pkg):
        return [pkg + ".unr"]
    return [pkg + e for e in (".u", ".utx", ".uax", ".umx", ".unr")]


class Install:
    """Packages one UT folder can provide: its Cache (by GUID) and its package folders."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.cache_dir = root / "Cache"
        self.cache: dict[str, str] = {}
        ci = self.cache_dir / "cache.ini"
        if ci.exists():
            for line in ci.read_text(encoding="latin-1", errors="replace").splitlines():
                m = re.match(r"\s*([0-9A-Fa-f]{32})\s*=\s*(.+?)\s*$", line)
                if m and (self.cache_dir / f"{m.group(1).upper()}.uxx").exists():
                    self.cache[m.group(1).upper()] = m.group(2)
        self.files: dict[str, list[Path]] = {}
        if (root / "System").is_dir() or (root / "System64").is_dir():
            for sub in ("System", "System64", "Maps", "Textures", "Sounds", "Music"):
                d = root / sub
                if d.is_dir():
                    for p in d.iterdir():
                        if p.suffix.lower() in PKG_EXTS:
                            self.files.setdefault(p.stem.lower(), []).append(p)
        else:  # a loose folder of packages (a map collection): every package file below it
            for dirpath, _dirs, names in os.walk(root):
                for n in names:
                    p = Path(dirpath) / n
                    if p.suffix.lower() in PKG_EXTS:
                        self.files.setdefault(p.stem.lower(), []).append(p)
        self._guid_memo: dict[Path, str | None] = {}

    def find(self, req: dict) -> tuple[Path, str] | None:
        """(file, filename) holding exactly this package version, or None."""
        g = req["guid"]
        if g in self.cache:
            return self.cache_dir / f"{g}.uxx", self.cache[g]
        unknown = None
        for p in self.files.get(req["pkg"].lower(), []):
            if p not in self._guid_memo:
                self._guid_memo[p] = pkg_guid(p)
            if self._guid_memo[p] == g:
                return p, p.name
            if self._guid_memo[p] is None:
                unknown = p
        if unknown is not None:  # unreadable header: give it the benefit of the doubt
            return unknown, unknown.name
        return None

    def _ini_text(self) -> str:
        try:
            return (self.cache_dir / "cache.ini").read_text(encoding="latin-1", errors="replace")
        except OSError:
            return ""

    def has_name(self, req: dict) -> bool:
        return req["pkg"].lower() in self.files

    def add_to_cache(self, src: Path, guid: str, filename: str) -> None:
        self.cache_dir.mkdir(exist_ok=True)
        dst = self.cache_dir / f"{guid}.uxx"
        new_file = not dst.exists()
        if new_file:
            shutil.copyfile(src, dst)
        if kc_config and not re.search(rf"(?im)^\s*{guid}\s*=", self._ini_text()):
            kc_config.record_cache(self.cache_dir, guid, filename, new_file)  # direct mode: undoable
        ci = self.cache_dir / "cache.ini"
        text = ""
        if ci.exists():
            with open(ci, "r", encoding="latin-1", newline="") as f:
                text = f.read()
        if not text.strip():
            text = "[Cache]\r\n"
        if not re.search(rf"(?im)^\s*{guid}\s*=", text):
            if not text.endswith(("\n", "\r")):
                text += "\r\n"
            text += f"{guid}={filename}\r\n"
            with open(ci, "w", encoding="latin-1", newline="") as f:
                f.write(text)
        self.cache[guid] = filename


def find_other_installs(ut_dir: Path, extra: list[str]) -> list[Install]:
    roots: list[Path] = [Path(e) for e in extra]
    base = ut_dir.parent
    # Killcam '99 knows its sources (package_sources); only the bare converter looks next to the game
    for dirpath, dirnames, _ in ([] if SANDBOX else os.walk(base)):
        depth = len(Path(dirpath).relative_to(base).parts)
        if depth >= 3:
            dirnames[:] = []
        here = Path(dirpath)
        if (here / "System").is_dir() and ((here / "Cache").is_dir() or (here / "Maps").is_dir()):
            roots.append(here)
            dirnames[:] = []
    out, seen = [], {ut_dir.resolve()}
    for r in roots:
        try:
            rr = r.resolve()
        except OSError:
            continue
        if rr not in seen and rr.is_dir():
            seen.add(rr)
            out.append(Install(rr))
    return out


def unpack_uz(data: bytes, fname: str, work: Path, sysdir: Path, log) -> Path | None:
    """Unpack a .uz file (UT's redirect format) with the build's own UCC. Returns the package file
    (in work), or None. UCC writes into System; nothing of ours stays there."""
    if len(data) < 8 or data[:4] not in (b"\xd2\x04\x00\x00", b"\x2e\x16\x00\x00"):
        return None  # not a .uz file (1234 / 5678 signature)
    if not is_bare_name(fname):
        return None  # never let a name from a demo or server point outside work / System
    ucc = sysdir / "UCC.exe"
    work.mkdir(parents=True, exist_ok=True)
    uz = work / (fname + ".uz")
    uz.write_bytes(data)
    out = None
    guard = sysdir / fname
    backup = guard.with_name(guard.name + ".ut2vid_bak") if guard.exists() else None
    try:
        if backup:
            shutil.move(str(guard), str(backup))
        run_quiet([str(ucc), "decompress", str(uz)], timeout=300)
        for cand in (work / fname, sysdir / fname):
            if cand.exists():
                out = work / (fname + ".unpacked")
                if out.exists():
                    out.unlink()
                shutil.move(str(cand), str(out))  # works across drives
                break
    finally:
        if guard.exists() and backup is not None:
            try:
                guard.unlink()
            except OSError:
                pass
        if backup and backup.exists():
            shutil.move(str(backup), str(guard))
        elif backup is None and guard.exists():
            try:
                guard.unlink()
            except OSError:
                pass
        try:
            uz.unlink()
        except OSError:
            pass
    return out


def download_package(req: dict, sources: list[str], work: Path, sysdir: Path, log) -> tuple[Path, str] | None:
    """Try each redirect/archive for <file>.uz, unpack it with UCC and keep it only if the
    GUID matches the demo exactly."""
    import urllib.parse
    import urllib.request
    work.mkdir(parents=True, exist_ok=True)
    for fname in candidate_filenames(req):
        for base in sources:
            url = base + urllib.parse.quote(fname) + ".uz"
            try:
                rq = urllib.request.Request(url, headers={"User-Agent": "Unreal"})
                with urllib.request.urlopen(rq, timeout=30) as r:
                    data = r.read()
            except Exception:
                continue
            out = unpack_uz(data, fname, work, sysdir, log)
            if not out:
                if len(data) >= 8 and data[:4] in (b"\xd2\x04\x00\x00", b"\x2e\x16\x00\x00"):
                    log(f"    could not unpack {url}")
                continue
            g = pkg_guid(out)
            if g == req["guid"]:
                log(f"    downloaded {fname} from {base} (version matches)")
                return out, fname
            log(f"    {base} has {fname}, but a different version")
            out.unlink(missing_ok=True)
    return None


# Mods whose old versions live in GitHub releases (package name -> owner/repo).
GITHUB_REPOS = {"instagibplus": "Deaod/InstaGibPlus", "newctf": "Deaod/NewCTF"}


def github_package(req: dict, repo: str, around: float | None, work: Path, log) -> tuple[Path, str] | None:
    """Look through a repo's release zips (closest to the demo's date first) for a package
    file with exactly the GUID the demo needs."""
    import io
    import json
    import urllib.request
    import zipfile
    hdr = {"User-Agent": "ut99_dem2video", "Accept": "application/vnd.github+json"}
    releases = []
    for page in (1, 2, 3):
        try:
            rq = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}", headers=hdr)
            with urllib.request.urlopen(rq, timeout=30) as r:
                batch = json.load(r)
        except Exception as e:
            log(f"    GitHub {repo}: {e}")
            break
        releases += batch
        if len(batch) < 100:
            break
    assets = []
    for rel in releases:
        try:
            when = dt.datetime.strptime(rel.get("published_at") or "", "%Y-%m-%dT%H:%M:%SZ").timestamp()
        except ValueError:
            when = 0.0
        for a in rel.get("assets", []):
            n = a.get("name", "").lower()
            if n.endswith(".zip") and "src" not in n:
                # releases published before the demo was recorded are the likeliest
                dist = (around - when) if around and when <= around else (abs(when - around) + 1e10 if around else 0)
                assets.append((dist, a["browser_download_url"], a["name"]))
    assets.sort()
    want = {req["pkg"].lower() + e for e in PKG_EXTS}
    cache_dir = work / "github"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for _, url, name in assets:
        local = cache_dir / safe_file_name(name, "asset.zip")
        try:
            if not local.exists():
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ut99_dem2video"}), timeout=120) as r:
                    local.write_bytes(r.read())
            with zipfile.ZipFile(local) as z:
                for zi in z.infolist():
                    base = zi.filename.replace("\\", "/").rsplit("/", 1)[-1]
                    if base.lower() in want:
                        data = z.read(zi)
                        tmp = work / (base + ".github")
                        tmp.write_bytes(data)
                        if pkg_guid(tmp) == req["guid"]:
                            log(f"    found {base} (exact version) in {repo} release asset {name}")
                            return tmp, base
                        tmp.unlink(missing_ok=True)
        except Exception as e:
            log(f"    skipped {name}: {e}")
    log(f"    no release of {repo} contains this exact {req['pkg']} version")
    return None


def find_7zip() -> str | None:
    for c in (shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if c and Path(c).exists():
            return c
    return None


def files_in_archive(archive: Path, wanted: set[str], work: Path) -> list[tuple[str, bytes]]:
    """(name, data) of members whose file name (any folder) is in `wanted` (lower-case)."""
    import zipfile
    out = []
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for zi in z.infolist():
                base = zi.filename.replace("\\", "/").rsplit("/", 1)[-1]
                if base.lower() in wanted:
                    out.append((base, z.read(zi)))
        return out
    sz = find_7zip()
    if not sz:
        return out
    dest = work / (archive.name + ".x")
    shutil.rmtree(dest, ignore_errors=True)
    # 'e' flattens folders and only the wanted names are extracted: an archive from the internet can
    # neither write outside dest (zip slip) nor fill the disk with everything else it holds
    run_quiet([sz, "e", "-y", f"-o{dest}", str(archive), *sorted(wanted), "-r"], timeout=300)
    for p in dest.rglob("*"):
        if p.is_file() and p.name.lower() in wanted:
            out.append((p.name, p.read_bytes()))
    shutil.rmtree(dest, ignore_errors=True)
    return out


def medor_archives(req: dict, work: Path, log, limit: int = 30) -> tuple[Path, str] | None:
    """Search medor.no-ip.org for archives named after the package (e.g. old mod releases in
    Zeroping/Newnet) and look inside them for the exact package version."""
    import urllib.parse
    import urllib.request
    base = "https://medor.no-ip.org/"
    try:
        q = urllib.request.Request(base + "index.php?dir=&search_mode=f&search=" + urllib.parse.quote(req["pkg"]),
                                   headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(q, timeout=60) as r:
            html = r.read().decode("latin-1", "replace")
    except Exception as e:
        log(f"    medor search failed: {e}")
        return None
    links = []
    hrefs = re.findall(r'href="([^"#?]+\.(?:zip|7z|rar))"', html, re.I)
    # AutoIndex can also link as index.php?dir=<folder>&file=<name>
    for d_, f_ in re.findall(r'href="[^"]*?dir=([^"&]*)&(?:amp;)?file=([^"&]+\.(?:zip|7z|rar))"', html, re.I):
        hrefs.append(urllib.parse.unquote(d_).rstrip("/") + "/" + f_)
    for href in hrefs:
        url = urllib.parse.urljoin(base, href)
        name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        if req["pkg"].lower() in name.lower() and "_src" not in name.lower() and url not in links:
            links.append(url)
    if not links:
        return None
    if any(not u.lower().endswith(".zip") for u in links) and not find_7zip():
        log("    (install 7-Zip to also search .7z/.rar archives)")
    want = {req["pkg"].lower() + e for e in PKG_EXTS}
    arch_dir = work / "archives"
    arch_dir.mkdir(parents=True, exist_ok=True)
    for url in links[:limit]:
        local = arch_dir / safe_file_name(urllib.parse.unquote(url.rsplit("/", 1)[-1]), "archive.zip")
        try:
            if not local.exists():
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=180) as r:
                    local.write_bytes(r.read())
            for name, data in files_in_archive(local, want, arch_dir):
                tmp = work / (name + ".archive")
                tmp.write_bytes(data)
                if pkg_guid(tmp) == req["guid"]:
                    log(f"    found {name} (exact version) in {local.name}")
                    return tmp, name
                tmp.unlink(missing_ok=True)
        except Exception as e:
            log(f"    skipped {local.name}: {e}")
    return None


def redirect_sources(sysdir: Path, extra: list[str]) -> list[str]:
    srcs = list(extra) + ["http://pgaming.site.nfoservers.com/redirect/",  # PassionateGaming (servers in the demos)
                          "https://deaod.de/ut99/",                          # Deaod (iCTF league maps, IG+, NewCTF)
                          "https://medor.no-ip.org/uz/", "http://uz.ut-files.com/"]
    ud = sysdir / "udemo.ini"
    if ud.exists():
        for m in re.finditer(r"(?im)^RedirectServers\[\d+\]=(.+)$", ud.read_text(encoding="latin-1", errors="replace")):
            v = m.group(1).strip()
            if v and v != "(Empty)":
                srcs.append(v if "://" in v else "http://" + v)
    out = []
    for u in srcs:
        u = u if u.endswith("/") else u + "/"
        if u not in out:
            out.append(u)
    return out


def check_demos(demos: list[Path], target: Install, others: list[Install], args, sysdir: Path) -> dict[Path, list[dict]]:
    """Make sure every package each demo needs is in the target install, importing exact
    matches from other UT folders and (unless disabled) downloading them. Returns the
    packages still missing per demo."""
    sources = [] if args.no_download else redirect_sources(sysdir, args.redirect)
    nf_file = args.out / "_work" / "not_found_online_v2.txt"
    not_found: dict[str, float] = {}
    if nf_file.exists() and not args.retry_online:
        for line in nf_file.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and time.time() - float(parts[1]) < 7 * 86400:
                not_found[parts[0]] = float(parts[1])
    resolved: dict[str, bool] = {}
    missing: dict[Path, list[dict]] = {}
    for d in demos:
        reqs = demo_packages(d)
        if reqs is None:
            mp = map_from_filename(d.name)
            if mp and not target.has_name({"pkg": mp}):
                missing[d] = [{"pkg": mp, "guid": "?", "flags": 1, "fname": mp + ".unr", "size": 0}]
            continue
        still = []
        for r in reqs:
            g = r["guid"]
            if g not in resolved:
                ok = target.find(r) is not None
                if not ok and not args.no_import:
                    for inst in others:
                        hit = inst.find(r)
                        if hit:
                            if args.dry_run:
                                say(f"  would copy {r['pkg']} from {inst.root.name}")
                            else:
                                target.add_to_cache(hit[0], g, r["pkg"] + Path(hit[1]).suffix)
                                say(f"  copied {r['pkg']} ({g[:8]}..) from {inst.root.name}")
                            ok = True
                            break
                if not ok and sources and not args.dry_run and g not in not_found:
                    say(f"  looking online for {r['pkg']} ...")
                    hit = download_package(r, sources, args.out / "_work" / "downloads", sysdir, say)
                    repo = GITHUB_REPOS.get(r["pkg"].lower())
                    if not hit and repo:
                        say(f"  searching GitHub releases of {repo} for {r['pkg']} ...")
                        hit = github_package(r, repo, demo_start(d), args.out / "_work" / "downloads", say)
                    if not hit:
                        say(f"  searching archives on medor.no-ip.org for {r['pkg']} ...")
                        hit = medor_archives(r, args.out / "_work" / "downloads", say)
                    if hit:
                        target.add_to_cache(hit[0], g, r["pkg"] + Path(hit[1]).suffix)
                        if SANDBOX:  # keep a copy in packs\downloads, so it is never downloaded again
                            try:
                                sys.path.insert(0, str(SANDBOX))
                                import ut_library
                                ut_library.add_package(hit[0], r["pkg"] + Path(hit[1]).suffix, "online")
                            except Exception as e:
                                say(f"  (not kept in the downloads pack: {e})")
                        hit[0].unlink(missing_ok=True)
                        ok = True
                    else:
                        not_found[g] = time.time()
                        nf_file.parent.mkdir(parents=True, exist_ok=True)
                        with open(nf_file, "a", encoding="utf-8") as f:
                            f.write(f"{g} {not_found[g]:.0f} {r['pkg']}\n")
                resolved[g] = ok
            if not resolved[g] and not (r["flags"] & PKG_CLIENT_OPTIONAL):
                still.append(r)
        if still:
            missing[d] = still
    return missing


def prepare_packages(demos: list[Path], args, ut_dir: Path) -> dict[Path, list[dict]]:
    """Copy the exact packages these demos need from the other UT installs (and the download
    sources). Returns the demos that still miss something, with what they miss."""
    sysdir = ut_system_dir(ut_dir) if any((ut_dir / s / "UnrealTournament.exe").exists()
                                          for s in ("System", "System64")) else ut_dir / "System"
    others = [] if args.no_import else find_other_installs(ut_dir, args.import_from)
    if others:
        say(f"  other UT folders searched for exact matches: {', '.join(i.root.name for i in others)}")
    return check_demos(demos, Install(ut_dir), others, args, sysdir)


def installed_maps(ut_dir: Path) -> set[str]:
    """Map names UT can load: Maps/*.unr plus downloaded maps listed in Cache/cache.ini."""
    names: set[str] = set()
    for p in (ut_dir / "Maps").glob("*.unr"):
        names.add(p.stem.lower())
    ci = ut_dir / "Cache" / "cache.ini"
    if ci.exists():
        for line in ci.read_text(encoding="latin-1", errors="replace").splitlines():
            if "=" in line:
                v = line.split("=", 1)[1].strip()
                if v.lower().endswith(".unr"):
                    names.add(v[:-4].lower())
    return names


def find_ffmpeg() -> str | None:
    """The ffmpeg Killcam '99 downloaded (tools\\ffmpeg), else on PATH, else where winget puts it."""
    own = Path(__file__).resolve().parent / "tools" / "ffmpeg" / "ffmpeg.exe"
    if own.exists():
        return str(own)
    hit = shutil.which("ffmpeg")
    if hit:
        return hit
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    cands = [local / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"]
    cands += sorted((local / "Microsoft" / "WinGet" / "Packages").glob("*FFmpeg*/**/bin/ffmpeg.exe"))
    cands += [Path(r"C:\ffmpeg\bin\ffmpeg.exe"), Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe")]
    for c in cands:
        if c.exists():
            return str(c)
    return None


def offer_install(need_ffmpeg: bool, need_audio: bool, need_numpy: bool = False) -> None:
    """Ask once whether to install the missing tools, then do it."""
    if not (need_ffmpeg or need_audio or need_numpy) or not sys.stdin or not sys.stdin.isatty():
        return
    what = " and ".join(x for x, n in (("ffmpeg (via winget)", need_ffmpeg), ("pyaudiowpatch (via pip)", need_audio),
                                       ("numpy (via pip)", need_numpy)) if n)
    try:
        ans = input(f"Install {what} now? [Y/n] ").strip().lower()
    except EOFError:
        return
    if ans not in ("", "y", "yes", "j", "ja"):
        return
    if need_ffmpeg:
        say("Installing ffmpeg ...")
        subprocess.run(["winget", "install", "--id", "Gyan.FFmpeg", "-e",
                        "--accept-source-agreements", "--accept-package-agreements"])
    pips = [p for p, n in (("pyaudiowpatch", need_audio), ("numpy", need_numpy)) if n]
    if pips:
        say(f"Installing {', '.join(pips)} ...")
        subprocess.run([sys.executable, "-m", "pip", "install", *pips])
        import importlib
        import site
        try:
            site.addsitedir(site.getusersitepackages())  # pip may install per-user
        except Exception:
            pass
        importlib.invalidate_caches()


def run_quiet(cmd: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


# --------------------------------------------------------------------------------------
# Locating UT and preparing its config
# --------------------------------------------------------------------------------------

def find_ut_dir(hint: str | None) -> Path | None:
    cands: list[Path] = []
    if hint:
        cands.append(Path(hint))
    if IS_WINDOWS:
        try:
            import winreg
            for root, key in [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Unreal Technology\Installed Apps\UnrealTournament"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Unreal Technology\Installed Apps\UnrealTournament"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Unreal Technology\Installed Apps\UnrealTournament"),
            ]:
                try:
                    with winreg.OpenKey(root, key) as k:
                        cands.append(Path(winreg.QueryValueEx(k, "Folder")[0]))
                except OSError:
                    pass
        except ImportError:
            pass
        for drive in "CDEFG":
            for sub in ["UnrealTournament", "Games\\UnrealTournament", "UT99", "Games\\UT99",
                        "OldUnreal\\UnrealTournament", "GOG Games\\Unreal Tournament GOTY",
                        "Program Files (x86)\\Unreal Tournament", "Program Files (x86)\\GOG Galaxy\\Games\\Unreal Tournament GOTY",
                        "Program Files (x86)\\Steam\\steamapps\\common\\Unreal Tournament",
                        "Program Files\\Unreal Tournament", "Unreal Tournament"]:
                cands.append(Path(f"{drive}:\\{sub}"))
    for c in cands:
        if c.name.lower() == "system":
            c = c.parent
        if (c / "System" / "UnrealTournament.exe").exists() or (c / "System64" / "UnrealTournament.exe").exists():
            return c
    return None


def ut_system_dir(ut_dir: Path) -> Path:
    # 469e+ also ships a 64-bit build in System64; prefer it when present.
    for sub in ("System64", "System"):
        if (ut_dir / sub / "UnrealTournament.exe").exists():
            return ut_dir / sub
    raise FileNotFoundError(f"UnrealTournament.exe not found under {ut_dir}")


def user_system_dir() -> Path | None:
    """469 can keep ini/log files in Documents\\UnrealTournament\\System."""
    docs = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents" / "UnrealTournament" / "System"
    return docs if docs.exists() else None


RENDERERS = {"d3d9": "D3D9Drv.D3D9RenderDevice", "d3d11": "D3D11Drv.D3D11RenderDevice",
             "opengl": "OpenGLDrv.OpenGLRenderDevice", "vulkan": "VulkanDrv.VulkanRenderDevice"}


def set_ini_value(text: str, section: str, key: str, value: str) -> str:
    """Set key=value inside [section] (added if missing), keeping everything else."""
    lines = text.splitlines()
    out, in_sec, done, found_sec = [], False, False, False
    for line in lines:
        st = line.strip()
        if st.startswith("[") and st.endswith("]"):
            if in_sec and not done:
                out.append(f"{key}={value}")
                done = True
            in_sec = st.lower() == f"[{section.lower()}]"
            found_sec = found_sec or in_sec
            out.append(line)
            continue
        if in_sec and st.split("=", 1)[0].strip().lower() == key.lower():
            if not done:
                out.append(f"{key}={value}")
                done = True
            continue
        out.append(line)
    if in_sec and not done:
        out.append(f"{key}={value}")
    elif not found_sec:
        out += ["", f"[{section}]", f"{key}={value}"]
    return "\r\n".join(out) + "\r\n"


def patch_ini(src_text: str, width: int, height: int, renderer: str = "keep") -> str:
    """Force windowed mode at the capture resolution in [WinDrv.WindowsClient] and
    optionally switch the renderer in [Engine.Engine]."""
    if renderer != "keep":
        src_text = re.sub(r"(?im)^(GameRenderDevice\s*=).*$", lambda m: m.group(1) + RENDERERS[renderer], src_text)
    wanted = {"StartupFullscreen": "False", "StartupBorderless": "False", "WindowedViewportX": str(width),
              "WindowedViewportY": str(height), "WindowedColorBits": "32", "WinPosX": "0", "WinPosY": "0",
              "CaptureMouse": "False"}
    out, in_sec, seen = [], False, set()
    lines = src_text.splitlines()
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if in_sec:
                out += [f"{k}={v}" for k, v in wanted.items() if k not in seen]
            in_sec = s.lower() == "[windrv.windowsclient]"
            out.append(line)
            continue
        if in_sec and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in wanted:
                out.append(f"{k}={wanted[k]}")
                seen.add(k)
                continue
        out.append(line)
    if in_sec:
        out += [f"{k}={v}" for k, v in wanted.items() if k not in seen]
    elif not any(l.strip().lower() == "[windrv.windowsclient]" for l in lines):
        out += ["", "[WinDrv.WindowsClient]"] + [f"{k}={v}" for k, v in wanted.items()]
    return "\r\n".join(out) + "\r\n"


# --------------------------------------------------------------------------------------
# Windows: window handling
# --------------------------------------------------------------------------------------

class Win:
    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        self.u32 = ctypes.windll.user32
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                self.u32.SetProcessDPIAware()
            except Exception:
                pass

    def screen_size(self) -> tuple[int, int]:
        return self.u32.GetSystemMetrics(0), self.u32.GetSystemMetrics(1)

    def windows_of_pid(self, pid: int) -> list[int]:
        ct, wt, u32 = self.ct, self.wt, self.u32
        found: list[int] = []
        proto = ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def cb(hwnd, _):
            p = wt.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ct.byref(p))
            if p.value == pid and u32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True
        u32.EnumWindows(proto(cb), 0)
        return found

    def class_name(self, hwnd: int) -> str:
        buf = self.ct.create_unicode_buffer(256)
        self.u32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def game_window(self, pid: int) -> int | None:
        """UT's viewport window (class contains 'Viewport'); the splash screen is ignored."""
        for h in self.windows_of_pid(pid):
            if "viewport" in self.class_name(h).lower() and self.client_rect_on_screen(h)[2] >= 320:
                return h
        return None

    def client_rect_on_screen(self, hwnd: int) -> tuple[int, int, int, int]:
        ct, wt, u32 = self.ct, self.wt, self.u32
        r = wt.RECT()
        u32.GetClientRect(hwnd, ct.byref(r))
        pt = wt.POINT(0, 0)
        u32.ClientToScreen(hwnd, ct.byref(pt))
        return pt.x, pt.y, r.right - r.left, r.bottom - r.top

    def make_borderless_at_origin(self, hwnd: int, w: int, h: int, background: bool = False) -> None:
        u32 = self.u32
        GWL_STYLE, WS_POPUP, WS_VISIBLE = -16, 0x80000000, 0x10000000
        HWND_TOPMOST, HWND_BOTTOM, SWP_FRAMECHANGED, SWP_SHOWWINDOW, SWP_NOACTIVATE = -1, 1, 0x0020, 0x0040, 0x0010
        u32.SetWindowLongW(hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE)
        if background:  # stay behind the user's windows; window capture still sees it
            u32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, w, h, SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOACTIVATE)
        else:
            u32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, w, h, SWP_FRAMECHANGED | SWP_SHOWWINDOW)
            self.focus(hwnd)

    def foreground(self) -> int:
        return self.u32.GetForegroundWindow()

    def close(self, hwnd: int) -> None:
        self.u32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE: lets UT shut down cleanly

    def focus(self, hwnd: int) -> None:
        self.u32.ShowWindow(hwnd, 9)  # SW_RESTORE
        self.u32.SetForegroundWindow(hwnd)


# --------------------------------------------------------------------------------------
# Audio: WASAPI loopback recorder with silence padding (keeps audio on the wall clock)
# --------------------------------------------------------------------------------------

class LoopbackRecorder:
    """Records what the default output device plays. WASAPI loopback delivers nothing while
    the PC is silent, so gaps are filled with silence to keep audio locked to real time.
    start_epoch is the wall-clock time of the first sample in the WAV."""

    SLACK = 0.25  # seconds of missing audio tolerated before padding with silence

    def __init__(self, wav_path: Path, device_hint: str | None = None) -> None:
        import pyaudiowpatch as pyaudio  # noqa: F401  (import check)
        self.wav_path = wav_path
        self.device_hint = device_hint
        self.device_name = "?"
        self.q: queue.Queue[bytes] = queue.Queue()
        self.stop_evt = threading.Event()
        self.start_epoch: float | None = None
        self.error: str | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        for _ in range(100):
            if self.start_epoch is not None or self.error:
                break
            time.sleep(0.05)
        if self.error:
            raise RuntimeError(self.error)

    def stop(self) -> None:
        self.stop_evt.set()
        self.thread.join(timeout=10)

    def _run(self) -> None:
        import pyaudiowpatch as pyaudio
        pa = pyaudio.PyAudio()
        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            spk = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
            if self.device_hint:
                matches = [d for d in pa.get_loopback_device_info_generator()
                           if self.device_hint.lower() in d["name"].lower()]
                if not matches:
                    raise RuntimeError(f"No loopback device matching '{self.device_hint}' (see --list-audio).")
                spk = matches[0]
            if not spk.get("isLoopbackDevice"):
                for lb in pa.get_loopback_device_info_generator():
                    if spk["name"] in lb["name"]:
                        spk = lb
                        break
                else:
                    raise RuntimeError("No WASAPI loopback device found for the default speakers.")
            rate, ch = int(spk["defaultSampleRate"]), int(spk["maxInputChannels"])
            self.device_name = spk["name"]
            frame_bytes = 2 * ch

            def cb(in_data, frame_count, time_info, status):
                self.q.put(in_data)
                return (None, pyaudio.paContinue)

            stream = pa.open(format=pyaudio.paInt16, channels=ch, rate=rate, input=True,
                             input_device_index=spk["index"], frames_per_buffer=rate // 50,
                             stream_callback=cb)
            wf = wave.open(str(self.wav_path), "wb")
            wf.setnchannels(ch)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            stream.start_stream()
            self.start_epoch = t0 = time.time()
            written = 0
            while not self.stop_evt.is_set():
                got = False
                try:
                    while True:
                        chunk = self.q.get_nowait()
                        wf.writeframes(chunk)
                        written += len(chunk) // frame_bytes
                        got = True
                except queue.Empty:
                    pass
                if not got:
                    expected = int((time.time() - t0) * rate)
                    if expected - written > self.SLACK * rate:
                        pad = expected - written - int(0.05 * rate)
                        wf.writeframes(b"\x00" * pad * frame_bytes)
                        written += pad
                time.sleep(0.01)
            stream.stop_stream()
            stream.close()
            while not self.q.empty():
                wf.writeframes(self.q.get_nowait())
            wf.close()
        except Exception as e:  # surfaced to the main thread
            self.error = f"Audio capture failed: {e}"
        finally:
            pa.terminate()


# --------------------------------------------------------------------------------------
# Video: ffmpeg
# --------------------------------------------------------------------------------------

def pick_encoder(ffmpeg: str, wanted: str) -> list[str]:
    presets = {
        "nvenc": ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"],
        "amf": ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "20", "-qp_p", "22"],
        "qsv": ["-c:v", "h264_qsv", "-global_quality", "22"],
        "x264": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"],
    }
    order = [wanted] if wanted != "auto" else ["nvenc", "amf", "qsv", "x264"]
    for name in order:
        args = presets[name]
        test = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                "color=c=black:s=640x360:d=0.2", *args, "-pix_fmt", "yuv420p", "-f", "null", "-"]
        try:
            if run_quiet(test, 30).returncode == 0:
                return args
        except Exception:
            pass
    raise RuntimeError("No working H.264 encoder found in ffmpeg.")


def has_gfxcapture(ffmpeg: str) -> bool:
    try:
        return " gfxcapture " in run_quiet([ffmpeg, "-hide_banner", "-filters"], 30).stdout
    except Exception:
        return False


class VideoCapture:
    def __init__(self, ffmpeg: str, out: Path, rect: tuple[int, int, int, int], fps: int,
                 enc_args: list[str], hwnd: int | None = None) -> None:
        x, y, w, h = rect
        w, h = w - w % 2, h - h % 2
        self.window_mode = hwnd is not None
        if self.window_mode:
            # Windows.Graphics.Capture (ffmpeg 8.1+): records the UT window even when other
            # windows cover it (it must not be minimised).
            graph = (f"gfxcapture=hwnd={hwnd}:max_framerate={fps}:capture_cursor=0,"
                     f"hwdownload,format=bgra,fps={fps},scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p")
            self.cmd = [ffmpeg, "-hide_banner", "-y", "-filter_complex", graph,
                        *enc_args, "-pix_fmt", "yuv420p", str(out)]
        else:
            self.cmd = [ffmpeg, "-hide_banner", "-y", "-thread_queue_size", "1024",
                        "-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", "0",
                        "-offset_x", str(x), "-offset_y", str(y), "-video_size", f"{w}x{h}",
                        "-i", "desktop", *enc_args, "-pix_fmt", "yuv420p", str(out)]
        self.out = out
        self.start_epoch: float | None = None
        self.stderr_tail: list[str] = []
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL, text=True, bufsize=1,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read_err(self) -> None:
        assert self.proc and self.proc.stderr
        buf = ""
        while True:
            ch = self.proc.stderr.read(1)
            if not ch:
                break
            if ch in "\r\n":
                if buf:
                    # gdigrab stamps frames with wall-clock time; ffmpeg prints it as "start:".
                    m = re.search(r"start:\s*([\d.]+)", buf)
                    if m and self.start_epoch is None and not self.window_mode:
                        self.start_epoch = float(m.group(1))
                    if self.window_mode and self.start_epoch is None and "Press [q]" in buf:
                        self.start_epoch = time.time()  # capture starts right after this line
                    self.stderr_tail = (self.stderr_tail + [buf])[-15:]
                buf = ""
            else:
                buf += ch

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if not self.proc:
            return
        try:
            if self.proc.poll() is None and self.proc.stdin:
                self.proc.stdin.write("q")
                self.proc.stdin.flush()
                self.proc.stdin.close()
            self.proc.wait(timeout=60)
        except Exception:
            self.proc.kill()
            self.proc.wait()


# ---- announcer detection (kept self-contained so it can be pasted into the main script) ----
KILL_SR, KILL_NFFT, KILL_HOP, KILL_BANDS = 16000, 512, 160, 48
DISTINCT = 1.4   # a wanted call must score this much better than any other sample


class KillDetector:
    """Finds announcer lines in a game recording by matching log band-energy spectrograms of
    each announcer sample against the recording (Pearson correlation, then a z-score against
    that sample's own background so samples of different length/loudness compare fairly)."""

    def __init__(self, signal):
        import numpy as np
        self.np = np
        self.bands = self._bands()
        self.sig = self._features(signal)                       # frames x bands
        self.N = self.sig.shape[0]
        self.L = 1 << int(np.ceil(np.log2(self.N + 1000)))
        self.S = np.fft.rfft(self.sig, self.L, axis=0).astype(np.complex64)  # per band, once
        rows = self.sig.sum(axis=1).astype(np.float64)
        rows2 = (self.sig.astype(np.float64) ** 2).sum(axis=1)
        self.cs = np.concatenate([[0.0], np.cumsum(rows)])
        self.cs2 = np.concatenate([[0.0], np.cumsum(rows2)])

    def _bands(self):
        np = self.np
        edges = np.geomspace(150, 7000, KILL_BANDS + 1)
        freqs = np.fft.rfftfreq(KILL_NFFT, 1 / KILL_SR)
        m = np.zeros((KILL_BANDS, len(freqs)), np.float32)
        for i in range(KILL_BANDS):
            m[i, (freqs >= edges[i]) & (freqs < edges[i + 1])] = 1
            if not m[i].any():
                m[i, np.argmin(abs(freqs - edges[i]))] = 1
        return m

    def _features(self, x):
        np = self.np
        x = np.asarray(x, np.float32)
        if len(x) < KILL_NFFT:
            x = np.pad(x, (0, KILL_NFFT - len(x)))
        n = 1 + (len(x) - KILL_NFFT) // KILL_HOP
        win = np.hanning(KILL_NFFT).astype(np.float32)
        out = np.empty((n, KILL_BANDS), np.float32)
        step = 4096
        base = np.arange(KILL_NFFT)[None, :]
        for s in range(0, n, step):
            k = min(step, n - s)
            fr = x[base + KILL_HOP * np.arange(s, s + k)[:, None]] * win
            mag = np.abs(np.fft.rfft(fr, axis=1)) ** 2
            out[s:s + k] = np.log10(mag @ self.bands.T + 1e-3)
        out -= out.mean(axis=1, keepdims=True)
        return out

    def zscores(self, template):
        np = self.np
        t = self._features(template)
        T, F = t.shape
        if self.N < T:
            return np.zeros(0, np.float32)
        t = t - t.mean()
        t /= np.sqrt((t ** 2).sum()) + 1e-9
        K = np.fft.rfft(t[::-1], self.L, axis=0)
        corr = np.fft.irfft((self.S * K).sum(axis=1), self.L)[T - 1:self.N]
        tot = self.cs[T:] - self.cs[:-T]
        tot2 = self.cs2[T:] - self.cs2[:-T]
        var = np.maximum(tot2 - tot ** 2 / (T * F), 1e-9)
        sc = corr / np.sqrt(var)
        med = np.median(sc)
        mad = np.median(np.abs(sc - med)) * 1.4826 + 1e-6
        return ((sc - med) / mad).astype(np.float32)

    @staticmethod
    def family(name: str) -> str:
        n = name.lower().split("~")[0]
        if any(k in n for k in ("spree", "rampage", "dominat", "unstopp", "godlike", "sick")):
            return "spree"
        if n.endswith("kill") or "holyshit" in n:
            return "kill"
        return "other"

    def detect(self, templates, wanted, z_min=5.5, min_gap=1.5):
        """Peaks of every template are found on their own, so two calls that play at the same
        time (a kill call and a spree call) are both kept. A wanted peak is only rejected when a
        non-wanted sample of the same family (e.g. 'multikill' vs 'ultrakill') matches better at
        that same moment, which means the wanted one was a look-alike. Returns
        (wanted_events, all_events) as [(time_sec, name, z)]."""
        np = self.np
        z = {}
        for n, tpl in templates.items():
            r = self.zscores(tpl)
            if len(r):
                z[n] = r
        if not z:
            return [], []
        gap = int(min_gap * KILL_SR / KILL_HOP)
        near = int(0.25 * KILL_SR / KILL_HOP)
        wide = int(0.6 * KILL_SR / KILL_HOP)
        peaks = []
        for n, r in z.items():
            cand = np.where(r >= z_min)[0]
            taken = np.zeros(len(r), bool)
            for j in cand[np.argsort(-r[cand])]:
                if taken[max(0, j - gap):j + gap].any():
                    continue
                taken[j] = True
                peaks.append((int(j), n, float(r[j])))
        keep = []
        for j, n, v in peaks:
            if n in wanted:
                fam = self.family(n)
                same = max((float(r[max(0, j - near):j + near + 1].max()) for m, r in z.items()
                            if m != n and self.family(m) == fam and m not in wanted and j < len(r)), default=-1e9)
                other = max((float(r[max(0, j - near):j + near + 1].max()) for m, r in z.items()
                             if m != n and self.family(m) != fam and m not in wanted and j < len(r)), default=-1e9)
                if same > v:
                    continue  # a lower call of the same kind fits better: look-alike
                if other > 1.2 * v:
                    continue  # clearly a different (non-trigger) call, e.g. 'dominating'
                # A real announcer line matches its own sample far better than any other sample
                # (measured on real clips: 1.6x to 2.8x). Game noise that only resembles a call
                # gives several samples about the same score (1.2x to 1.3x): reject those.
                # A call of the other kind that is itself clearly present (a kill call and a
                # spree call played together) and a wanted call of the same kind (Mega vs Ultra
                # Kill: a clip either way) do not count against it.
                base = n.split("~")[0]
                rival = -1e9
                for m, r in z.items():
                    if m == n or m.split("~")[0] == base or j >= len(r):
                        continue
                    if m in wanted and self.family(m) == fam:
                        continue  # e.g. megakill vs ultrakill: either way it is a wanted clip
                    loc = float(r[max(0, j - wide):j + wide + 1].max())
                    if self.family(m) != fam and loc >= z_min:
                        continue
                    rival = max(rival, loc)
                if rival > 0 and v < DISTINCT * rival:
                    continue
            keep.append((j, n, v))
        # one announcement can light up two look-alikes of the same kind: keep the best within
        # 1 s. (Not wider: 'Multi Kill' followed by 'Ultra Kill' 2 s later is a real sequence.)
        keep.sort(key=lambda e: -e[2])
        final = []
        for j, n, v in keep:
            if any(abs(j - j2) <= int(1.0 * KILL_SR / KILL_HOP) and self.family(n) == self.family(n2) for j2, n2, _ in final):
                continue
            final.append((j, n, v))
        events = sorted((j * KILL_HOP / KILL_SR, n, v) for j, n, v in final)
        return ([(t, n.split("~")[0], v) for t, n, v in events if n in wanted],
                [(t, n.split("~")[0], v) for t, n, v in events])


def read_package_sounds(path: Path) -> dict[str, bytes]:
    """name -> WAV bytes for every Sound object in an Unreal .uax package."""
    import struct
    data = path.read_bytes()

    def compact(b, o):
        b0 = b[o]; o += 1
        neg, v = b0 & 0x80, b0 & 0x3F
        if b0 & 0x40:
            sh = 6
            while True:
                x = b[o]; o += 1
                v |= (x & 0x7F) << sh
                sh += 7
                if not x & 0x80:
                    break
        return (-v if neg else v), o

    tag, ver, _lic, _flags, nc, no, ec, eo = struct.unpack_from("<IHHIIIII", data, 0)
    if tag != 0x9E2A83C1:
        return {}
    names, o = [], no
    for _ in range(nc):
        if ver >= 64:
            ln, o = compact(data, o)
            names.append(data[o:o + ln - 1].decode("latin-1"))
            o += ln
        else:
            e = data.index(b"\0", o)
            names.append(data[o:e].decode("latin-1"))
            o = e + 1
        o += 4
    out, o = {}, eo
    for _ in range(ec):
        _c, o = compact(data, o)
        _s, o = compact(data, o)
        o += 4
        nm, o = compact(data, o)
        o += 4
        size, o = compact(data, o)
        off = 0
        if size > 0:
            off, o = compact(data, o)
        blob = data[off:off + size]
        i = blob.find(b"RIFF")
        if i >= 0:
            ln = struct.unpack_from("<I", blob, i + 4)[0] + 8
            out[names[nm]] = blob[i:i + ln]
    return out


def wav_to_mono16k(wav_bytes: bytes):
    import io
    import numpy as np
    with wave.open(io.BytesIO(wav_bytes)) as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif sw == 2:
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    else:
        return None
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    t = np.arange(0, len(x) / sr, 1 / KILL_SR)
    return np.interp(t, np.arange(len(x)) / sr, x).astype(np.float32)


CALL_SAMPLE = re.compile(r"kill$|holyshit|spree|rampage|dominat|unstopp|godlike|sick|headshot|firstblood")
_SOUND_CACHE: dict = {}


def _add_template(tpl: dict, key: str, x) -> None:
    """Add a sample; a second, different version of the same call is kept as 'name~2'."""
    for k, v in tpl.items():
        if k.split("~")[0] == key and len(v) == len(x) and abs(float(v[:4000].sum()) - float(x[:4000].sum())) < 1e-3:
            return
    if key in tpl:
        i = 2
        while f"{key}~{i}" in tpl:
            i += 1
        key = f"{key}~{i}"
    tpl[key] = x


def package_samples(p: Path, only_calls: bool) -> dict:
    if (p, only_calls) not in _SOUND_CACHE:
        out = {}
        try:
            if p.stat().st_size < 30_000_000:
                for name, wav in read_package_sounds(p).items():
                    key = name.lower()
                    if only_calls and not CALL_SAMPLE.search(key):
                        continue
                    x = wav_to_mono16k(wav)
                    if x is not None and len(x) > KILL_SR // 4:
                        out[key] = x
        except Exception as e:
            say(f"  note: could not read sounds from {p.name}: {e}")
        _SOUND_CACHE[(p, only_calls)] = out
    return _SOUND_CACHE[(p, only_calls)]


def announcer_templates(ut_dir: Path) -> dict:
    """All announcer samples UT can play: Sounds/*announ*.uax plus cached announcer packages."""
    pkgs = [p for p in (ut_dir / "Sounds").glob("*.uax") if "announ" in p.name.lower()]
    ci = ut_dir / "Cache" / "cache.ini"
    if ci.exists():
        for line in ci.read_text(encoding="latin-1", errors="replace").splitlines():
            m = re.match(r"\s*([0-9A-Fa-f]{32})\s*=\s*(.+\.uax)\s*$", line)
            if m and "announ" in m.group(2).lower():
                f = ut_dir / "Cache" / f"{m.group(1).upper()}.uxx"
                if f.exists():
                    pkgs.append(f)
    tpl = {}
    for p in pkgs:
        for key, x in package_samples(p, False).items():
            _add_template(tpl, key, x)
    return tpl


def demo_templates(base: dict, ut_dir: Path, demo: Path) -> dict:
    """The announcer samples plus the call samples that mods used by this demo bring along
    (InstaGibPlus, for instance, ships its own 'Holy Shit' and 'Ludicrous Kill')."""
    tpl = dict(base)
    added = []
    for req in demo_packages(demo) or []:
        fn = req.get("fname") or ""
        for d in ("Cache", "System", "Sounds"):
            f = ut_dir / d / fn
            if fn and f.exists():
                for key, x in package_samples(f, True).items():
                    n = len(tpl)
                    _add_template(tpl, key, x)
                    if len(tpl) > n:
                        added.append(f"{req.get('pkg')}.{key}")
                break
    if added:
        say(f"  extra call samples from this demo's mods: {', '.join(added)}")
    return tpl

def media_duration(ffmpeg: str, src: Path) -> float | None:
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(src)], capture_output=True, text=True, errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def audio_track_count(ffmpeg: str, src: Path) -> int:
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(src)], capture_output=True, text=True, errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return len(re.findall(r"Stream #\d+:\d+.*?: Audio:", r.stderr))


def detect_calls(ffmpeg: str, src: Path, templates: dict, pattern: str, track: int = 0,
                 chunk: float = 1200.0, overlap: float = 15.0, z_min: float = 5.5):
    """Announcer calls in one audio track of any media file, processed in 20-minute pieces so
    hours-long recordings fit in memory. Returns (wanted_hits, all_calls) in the file's timeline."""
    import numpy as np
    wanted = {n for n in templates if re.search(pattern, n, re.I)}
    hits: list = []
    heard: list = []

    def add(lst, t, n, z):
        for i, (t2, n2, z2) in enumerate(lst):
            if n2 == n and abs(t2 - t) < 2.0:
                if z > z2:
                    lst[i] = (t, n, z)
                return
        lst.append((t, n, z))

    start = 0.0
    while True:
        r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}",
                            "-t", f"{chunk + overlap:.3f}", "-i", str(src), "-map", f"0:a:{track}",
                            "-ac", "1", "-ar", str(KILL_SR), "-f", "s16le", "-"],
                           capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        sig = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768
        if len(sig) < KILL_SR:
            break
        h, he = KillDetector(sig).detect(templates, wanted, z_min=z_min)
        for t, n, z in h:
            add(hits, t + start, n, z)
        for t, n, z in he:
            add(heard, t + start, n, z)
        if len(sig) < (chunk + overlap) * KILL_SR * 0.98:
            break
        start += chunk
    hits.sort()
    heard.sort()
    return hits, heard


def find_kills(ffmpeg: str, media: Path, templates: dict, pattern: str, offset: float = 0.0,
               track: int = 0) -> list[tuple[float, str, float]]:
    """Wanted calls, shifted by `offset` seconds (audio timeline -> video timeline)."""
    hits, heard = detect_calls(ffmpeg, media, templates, pattern, track=track)
    if heard:
        say("    calls heard: " + ", ".join(f"{fmt_dur(t + offset)} {n}" for t, n, _ in heard))
    return [(t + offset, n, z) for t, n, z in hits]


def clip_encoder_args(enc_args: list[str], quality: str) -> list[str]:
    """Encoder settings for clips: 'high' = same as recording, 'normal' about half the size."""
    if quality == "high":
        return enc_args
    step = 3 if quality == "normal" else 6
    out = list(enc_args)
    for key in ("-cq", "-crf", "-qp_i", "-qp_p", "-global_quality"):
        if key in out:
            i = out.index(key) + 1
            out[i] = str(int(out[i]) + step)
    return out


def make_clips(ffmpeg: str, video: Path, stem: str, source_name: str, hits, args, enc_args,
               clip_dir: Path, ext: str, audio: Path | None = None, audio_offset: float = 0.0,
               copy: bool = False, source: str = "demo") -> list[Path]:
    """Cut [hit - before, hit + after] around each detection (overlapping windows merged).
    audio/audio_offset: take the sound from a separate file whose t=0 sits at video time
    audio_offset. copy: cut without re-encoding (fast, starts on the nearest key frame)."""
    if not hits:
        return []
    clip_dir.mkdir(parents=True, exist_ok=True)
    spans: list[list] = []
    for t, name, _z in sorted(hits):
        a, b = max(0.0, t - args.clip_before), t + args.clip_after
        if spans and a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
            spans[-1][2].append(name)
        else:
            spans.append([a, b, [name]])
    out = []
    for a, b, names in spans:
        first = min(t for t, n, _ in hits if a <= t <= b)
        names = order_names(names)
        dst = clip_dest(clip_dir, names, stem, first, ext)
        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{a:.3f}", "-i", str(video)]
        if audio is not None:
            a_aud = a - audio_offset
            if a_aud >= 0:
                cmd += ["-ss", f"{a_aud:.3f}", "-i", str(audio)]
            else:
                cmd += ["-itsoffset", f"{-a_aud:.3f}", "-i", str(audio)]
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        else:
            cmd += ["-map", "0:v:0", "-map", "0:a?"]
        cmd += ["-t", f"{b - a:.3f}"]
        if copy:
            cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        else:
            cmd += [*enc_args, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
            if audio is not None:
                cmd += ["-ac", "2"]
        if ext == "mp4":
            cmd += ["-movflags", "+faststart"]
        r = subprocess.run(cmd + [str(dst)], capture_output=True, text=True, errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0:
            out.append(dst)
            add_to_index(args, dst, source=source, origin=source_name, category=clip_category(names),
                         labels=[display(x) for x in names], t_call=first, check="found by sound only",
                         warn=False, timing="sound")
        else:
            say(f"  clip failed: {r.stderr.strip()[-300:]}")
    with open(ledger_dir(args) / "events.txt", "a", encoding="utf-8") as f:
        for t, name, z in hits:
            f.write(f"{source_name}\t{fmt_dur(t)}\t{name}\t" + ("game message" if z < 0 else f"score {z:.0f}") + "\n")
    return out


# --------------------------------------------------------------------------------------
# Sandbox (Demobuild) + message scan (UT2VidHook add-on) + validation
# --------------------------------------------------------------------------------------

HOOK_CONSOLE = "UT2VidHook.UT2VidConsole"


def inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def rotate_log(path: Path, keep_bytes: int = 2_000_000) -> None:
    """Keep the log small: past 2 MB the old part moves to <name>.old.txt (one generation)."""
    try:
        if path.exists() and path.stat().st_size > keep_bytes:
            old = path.with_name(path.stem + ".old.txt")
            old.unlink(missing_ok=True)
            path.rename(old)
    except OSError:
        pass


def package_sources() -> list[Path]:
    """Where missing packages are copied from, in this order: the shipped base pack, packages found
    online earlier, then the player's own package folders (Packages page). Only ever READ."""
    out: list[Path] = []
    if kc_config:
        for p in (kc_config.BASE_PACK, kc_config.DOWNLOADS):
            if (p / "Cache" / "cache.ini").exists():
                out.append(p)
        for f in load_settings().get("library_sources") or []:
            if Path(f).is_dir():
                out.append(Path(f))
    return out


def desktop_installs() -> list[Path]:
    """UT folders on the Desktop. Only ever READ (as package donors)."""
    base = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    out = []
    if not base.is_dir():
        return out
    for dirpath, dirnames, _ in os.walk(base):
        here = Path(dirpath)
        if len(here.relative_to(base).parts) >= 3:
            dirnames[:] = []
        if SANDBOX and inside(here, SANDBOX):
            dirnames[:] = []
            continue
        if (here / "System").is_dir() and ((here / "Cache").is_dir() or (here / "Maps").is_dir()):
            out.append(here)
            dirnames[:] = []
    return out


CALL_WORDS = [  # checked in this order against the message text (letters only, lower case)
    ("holyshit", "holyshit"), ("ludicrous", "ludicrouskill"), ("monsterkill", "monsterkill"),
    ("ultrakill", "ultrakill"), ("megakill", "megakill"), ("triplekill", "multikill"),
    ("multikill", "multikill"), ("doublekill", "doublekill"), ("wickedsick", "whickedsick"),
    ("whickedsick", "whickedsick"), ("godlike", "godlike"), ("unstoppable", "unstoppable"),
    ("dominating", "dominating"), ("rampage", "rampage"), ("killingspree", "killingspree"),
    ("firstblood", "firstblood"), ("headshot", "headshot"),
]
MULTIKILL_SWITCH = {1: "doublekill", 2: "multikill", 3: "ultrakill"}
# What each multi-kill message class plays per switch (read from the mods' own code). Used when a
# message has no text: 2k4Combos sends Ludicrous Kill / Holy Shit with an empty string but WITH sound.
MULTIKILL_TABLES = {
    "multikillmessage": {1: "doublekill", 2: "multikill", 3: "ultrakill",
                         **{i: "monsterkill" for i in range(4, 10)}},           # Botpack: 10+ silent
    "mmultikillmessage": {1: "doublekill", 2: "multikill", 3: "megakill", 4: "ultrakill", 5: "monsterkill",
                          6: "ludicrouskill", **{i: "holyshit" for i in range(7, 21)}},  # 2k4Combos (UT2004 style)
    # SmartCTF 4D++ v4 "enhanced" multi kills: Double, Triple, Multi, MEGA seen in your demos; the
    # levels above that are assumed to go on like UT2004 (not seen yet, so not verified)
    "smartctfenhancedmultikillmessage": {1: "doublekill", 2: "multikill", 3: "multikill", 4: "megakill",
                                         5: "ultrakill", 6: "monsterkill", 7: "ludicrouskill",
                                         **{i: "holyshit" for i in range(8, 21)}},
}
# Message types seen in the scanned demos; anything else is reported so new announcers get noticed.
KNOWN_MESSAGES = {
    "multikillmessage", "mmultikillmessage", "killingspreemessage", "firstbloodmessage", "deathmatchmessage",
    "ddeathmessageplus", "igplus_deathmessageplus", "deathmessageplus", "eradicateddeathmessage",
    "killermessageplus", "victimmessage", "decapitationmessage", "ctfmessage", "ctfmessage2", "timemessage",
    "purehitsound", "smartctfaudiomsg", "smartctfmessage", "smartctfcoolmsg", "itemmessageplus",
    "pickupmessageplus", "criticaleventplus", "criticaleventlowplus", "assaultmessage", "controlpointmessage",
    "countdownmessage", "teamgamemessage", "lmsoutmessage", "stringmessageplus", "redsaymessageplus",
    "teamsaymessageplus", "saymessageplus", "specspreemessage", "smartctfenhancedmultikillmessage",
    "smartctfenhanceddeathmessageplus",
}


def msg_call(cls: str, switch: int, text: str) -> str | None:
    """Announcer call that belongs to a HUD message, or None. A message without text is not
    shown and has no call (Botpack sends 'multi kill level 10+' that way, silently), and
    "X's killing spree was ended by Y" is not a spree call."""
    short = cls.lower().split(".")[-1]
    if not text.strip():
        if "multikill" in short and switch > 0:
            table = MULTIKILL_TABLES.get(short, MULTIKILL_TABLES["mmultikillmessage"])
            return table.get(switch)
        return None
    low = text.lower()
    if "ended by" in low or "was ended" in low:
        return None
    t = re.sub(r"[^a-z]", "", low)
    for word, call in CALL_WORDS:
        if word in t:
            return call
    if "multikill" in short and switch > 0:
        return MULTIKILL_TABLES.get(short, MULTIKILL_TABLES["mmultikillmessage"]).get(switch)
    return None


def msg_own(m: dict, player: str) -> bool:
    """Is this message about the demo's recorder? Multi-kill messages (Botpack's and mods' such
    as 2k4Combos.MMultiKillMessage) only ever go to the killer."""
    cls = m["class"].lower()
    return bool(m.get("recorder")) or "multikill" in cls.split(".")[-1] or same_player(m.get("who", ""), player)


def refresh_calls(messages: list[dict], player: str, speed: float | None = None) -> list[dict]:
    """Recompute call/own (scans saved by an older version keep working), then replace the
    multi kill messages by multi kills worked out from your own kill times (see derive_multikills).
    speed: the server's game speed if already known (else measured from these messages)."""
    messages[:] = [m for m in messages if not m.get("derived")]
    for m in messages:
        m["call"] = msg_call(m["class"], int(m["switch"]), m.get("text", ""))
        m["own"] = msg_own(m, player)
    if len(messages) > 1:
        derive_multikills(messages, speed)
    return messages


def game_speed(messages: list[dict]) -> float | None:
    """The server's game speed (UT 'hardcore' mode runs at 110%). Demo time runs in real seconds,
    the game's own timers in game seconds. A dropped CTF flag goes home by itself after 25 game
    seconds, so 'X dropped the flag' -> 'The flag was returned' (nobody touching it in between)
    measures the speed: 22.7 s in the demo means 25 / 22.7 = 1.10. None if the demo has none."""
    ctf = [m for m in messages if m["class"].lower().endswith(".ctfmessage") and m["t"] >= 0]
    delays = []
    for i, m in enumerate(ctf):
        if int(m["switch"]) != 2:
            continue
        col = re.search(r"\b(red|blue|green|gold)\b", m.get("text", ""), re.I)
        if not col:
            continue
        for n in ctf[i + 1:]:
            c2 = re.search(r"\b(red|blue|green|gold)\b", n.get("text", ""), re.I)
            if c2 and c2.group(1).lower() == col.group(1).lower():
                if int(n["switch"]) == 3 and 15.0 <= n["t"] - m["t"] <= 35.0:
                    delays.append(n["t"] - m["t"])
                break
    if not delays:
        return None
    delays.sort()
    return round(25.0 / delays[len(delays) // 2], 3)


def own_kill_events(messages: list[dict]) -> list[tuple[float, bool]]:
    """Your own kills as [(demo time, is_kill)], from the server's death messages, so exact at any
    playback speed. Mirrors Botpack DeathMessagePlus.ClientReceive: every death message that names
    you as the killer of someone else counts (switch 0 = kill, 8 = telefrag); your own suicide
    (switch 1) resets the multi kill count. 'You killed ...' (KillerMessagePlus, one per kill, also
    two kills in the same instant) is used; the kill feed only when a demo has no such lines."""
    return [(t, k) for t, k, _v in own_kills_detail(messages)]


def own_kills_detail(messages: list[dict]) -> list[tuple[float, bool, str | None]]:
    """Like own_kill_events, plus the victim's name where the message gives it ('You killed X')."""
    def pick(match):
        out = []
        for m in messages:
            if m["t"] >= 0 and m.get("recorder") and match(m["class"].lower()) and int(m["switch"]) in (0, 1, 8):
                v = re.match(r"You killed (.+?)!?$", m.get("text", "").strip())
                out.append((m["t"], int(m["switch"]) != 1, v.group(1) if v else None))
        return out
    ev = pick(lambda c: "killermessage" in c)
    if not any(k for _, k, _v in ev):
        ev = pick(lambda c: "deathmessage" in c)
    return sorted(ev, key=lambda e: e[0])


def own_kill_times(messages: list[dict]) -> list[float]:
    return [t for t, k in own_kill_events(messages) if k]


def derive_multikills(messages: list[dict], speed: float | None = None) -> None:
    """UT does not send multi kills from the server: the PLAYING client counts them itself
    (Botpack DeathMessagePlus.ClientReceive: a kill less than 3 s of game time after your previous
    one raises the level). During demo playback that count is redone with the playback clock, so
    a fast scan or a slow-motion playback gets them wrong (Acrony's 'Monster Kills' at 20x).
    So the multi kill messages are ignored and the levels are recomputed from your kill times,
    exactly like the game does, on the demo's own clock. The announcer scheme (Botpack, the
    UT2004-style 2k4Combos one or SmartCTF's enhanced one) is taken from the multi kill message
    type seen in the demo. Each derived multi kill also carries its streak ('chain': the kill
    times and victims so far) and, where the scheme differs from Botpack, the Botpack name
    ('alt_call'), so a clip is never lost because a mod names the same streak lower."""
    events = own_kills_detail(messages)
    if not any(k for _, k, _v in events):
        verify_multikills(messages)  # no kill feed: keep the messages, minus impossible ones
        return
    kinds = {m["class"].lower().split(".")[-1] for m in messages if "multikill" in m["class"].lower()}
    scheme = next((k for k in ("smartctfenhancedmultikillmessage", "mmultikillmessage") if k in kinds),
                  "multikillmessage")
    table, botpack = MULTIKILL_TABLES[scheme], MULTIKILL_TABLES["multikillmessage"]
    for m in messages:
        if "multikill" in m["class"].lower() and m.get("call"):
            m["msg_call"], m["call"] = m["call"], None
    if speed is None:
        speed = game_speed(messages) or 1.0
    window = 3.0 / speed  # the game's 3 s are game seconds; the demo counts real seconds
    level, last, chain = 0, -1e9, []
    for k, is_kill, victim in events:
        if not is_kill:          # suicide: the count starts over (the game keeps LastKillTime)
            level, chain = 0, []
            continue
        if k - last < window:
            level += 1
        else:
            level, chain = 0, []
        chain.append([k, victim])
        last = k
        if level and table.get(level):
            alt = botpack.get(level)
            messages.append({"t": k, "where": "derived", "class": "ut2vid.MultiKill", "switch": level,
                             "recorder": True, "own": True, "who": "", "text": table[level],
                             "call": table[level], "derived": True, "chain": [list(c) for c in chain],
                             **({"alt_call": alt} if alt and alt != table[level] else {})})
    messages.sort(key=lambda m: m["t"])


def verify_multikills(messages: list[dict]) -> None:
    """A multi kill of level N (message switch N) needs N+1 of your own kills, each within 3.5 s of
    the previous one (the game uses 3 s; one missing kill message is tolerated). Some servers send runaway levels (seen in Acrony: 'Monster Kill'
    for single kills seconds apart, the game's kill timer was stuck); those are dropped here.
    Kills come from 'You killed ...' (KillerMessagePlus). Demos without those are left alone."""
    kills = sorted({round(m["t"], 1) for m in messages if m.get("recorder") and int(m["switch"]) == 0
                    and ("killermessage" in m["class"].lower() or "deathmessage" in m["class"].lower())})
    if not kills:
        return
    for m in messages:
        if not (m.get("call") and m.get("own") and "multikill" in m["class"].lower()):
            continue
        near = [k for k in kills if abs(k - m["t"]) < 0.6]
        chain = 0
        if near:
            last, chain = near[-1], 1
            for k in reversed([k for k in kills if k < last]):
                if last - k > 3.5:
                    break
                chain, last = chain + 1, k
        if chain < int(m["switch"]):  # level N = N+1 kills; one missing kill message is tolerated
            m["bogus"] = f"{m['call']} with only {chain} kill(s) in a row"
            m["call"] = None


def demo_player(name: str) -> str:
    """Recorder's player name from udemo's file name: '<player>_[yyyy_mm_dd_hhmm]_...'."""
    m = re.match(r"(.*?)_\[\d{4}_\d\d_\d\d_\d{4}\]", name)
    return m.group(1) if m else ""


def same_player(a: str, b: str) -> bool:
    norm = lambda x: re.sub(r"[^a-z0-9]", "", x.lower())
    return bool(a and b) and norm(a) == norm(b)


def parse_scan_log(text: str, player: str = "") -> dict:
    res = {"start": False, "end": False, "total": None, "messages": [], "progress": [], "warnings": [],
           "hooked": False, "game_speed": None}
    tds = []
    for line in text.splitlines():
        if "UT2VID " not in line:
            continue
        body = line.split("UT2VID ", 1)[1]
        if body.startswith("SCAN START"):
            res["start"] = True
            m = re.search(r"total=([\d.]+)", body)
            res["total"] = float(m.group(1)) if m else None
            m = re.search(r" map=(\S+)", body)
            if m:
                res["map"] = m.group(1)
            m = re.search(r" version=(\d+)", body)
            res["hook_version"] = int(m.group(1)) if m else 15
        elif body.startswith("SCAN END"):
            res["end"] = True
        elif body.startswith("HOOKED"):
            res["hooked"] = True
        elif body.startswith("PROGRESS"):
            m = re.search(r"t=([\d.]+)", body)
            if m:
                res["progress"].append(float(m.group(1)))
            m = re.search(r"td=([\d.]+) speed=([\d.]+)", body)
            if m:
                td, sp = float(m.group(1)), float(m.group(2))
                # udemo may or may not fold its playback speed into the level's time dilation
                g = td / sp if sp > 0 and 0.5 <= td / sp <= 2.5 else td
                if 0.5 <= g <= 2.5:
                    tds.append(round(g, 3))
        elif body.startswith("WARN"):
            res["warnings"].append(body)
        elif body.startswith("MSG"):
            m = re.match(r"MSG t=([-\d.]+) where=(\S+) class=(\S+) switch=(-?\d+) recorder=(\S+) who=(.*?) text=(.*)$", body)
            if m:
                t, where, cls, sw, rec, who, txt = m.groups()
                if any(abs(float(t) - o["t"]) < 1.0 and o["class"] == cls and o["switch"] == int(sw)
                       and o["text"] == txt.strip() for o in res["messages"][-6:]):
                    continue  # the same message delivered twice
                m = {"t": float(t), "where": where, "class": cls, "switch": int(sw),
                     "recorder": rec.lower() == "true", "who": who.strip(), "text": txt.strip()}
                refresh_calls([m], player)
                res["messages"].append(m)
    if tds:
        tds.sort()
        res["game_speed"] = tds[len(tds) // 2]
    if len(res["messages"]) > 1:
        derive_multikills(res["messages"], res["game_speed"])
    return res


def default_game_speed(args) -> float:
    """For demos where the speed cannot be measured: the usual speed of the servers in your other
    scans (competitive servers mostly run 'hardcore', 1.10x), else 1.00x."""
    import json
    if getattr(args, "_default_speed", None):
        return args._default_speed
    vals = []
    for f in (args.out / "scans").glob("*.json"):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        v = r.get("game_speed") or game_speed(r.get("messages", []))
        if v:
            vals.append(v)
    vals.sort()
    args._default_speed = vals[len(vals) // 2] if len(vals) >= 3 else 1.0
    return args._default_speed


def scan_speed(r: dict, args) -> tuple[float, str]:
    """Game speed for one scan and where it came from."""
    if r.get("game_speed"):
        return r["game_speed"], "read from the game"
    v = game_speed(r.get("messages", []))
    if v:
        return v, "measured from flag auto-returns"
    return default_game_speed(args), "usual speed of your other demos"


def scan_one(demo: Path, args, ut_exe: Path, sysdir: Path, win, slot: int = 0, emit=None) -> dict | None:
    """Play one demo as fast as possible with the UT2VidHook console and collect its HUD messages.
    slot: which of the parallel scan instances this is; every instance has its own demo copy,
    exec file, log, ini and user ini (UT writes its ini files when it exits, so they can't be shared).
    emit: where the report lines go (parallel scans print each demo's report as one block)."""
    emit = emit or say
    tag = f"[{slot + 1}] " if getattr(args, "_jobs", 1) > 1 else ""
    est = estimate_duration(demo) or 30 * 60
    max_wait = est * 1.1 + 180  # never slower than real time (+ margin)
    emit(f"Scan: {demo.name}")
    tmp_demo, exec_file, log_file = f"ut2vid_tmp_s{slot}.dem", f"ut2vid_exec_s{slot}.txt", f"ut2vid_scan{slot}.log"
    copy = sysdir / tmp_demo
    shutil.copyfile(demo, copy)
    (sysdir / exec_file).write_text(f"DEMOPLAY {tmp_demo}\r\n", encoding="ascii")
    log = sysdir / log_file
    try:
        log.unlink()
    except OSError:
        pass
    cmd = [str(ut_exe), "Entry", f"exec={exec_file}", f"log={log_file}", f"ini={args.scan_ini.format(slot=slot)}",
           "-nosound"]
    if args.user_ini_path:
        cmd.append(f"userini={args.user_ini_path.format(slot=slot)}")
    # Parallel scans load one at a time: a game only starts once the previous one is playing its
    # demo (or after 30 s). Two games loading packages at the same moment could make the second
    # one report a package as missing that is there ("Cannot play demo due to missing packages").
    gate = getattr(args, "_start_gate", None)
    gated = bool(gate) and gate.acquire()
    with WIN_LOCK:
        prev_fg = win.foreground()
    t0 = time.time()
    ut = subprocess.Popen(cmd, cwd=str(sysdir))
    boost_process(ut.pid, above_normal=getattr(args, "_jobs", 1) == 1)
    hwnd = None
    # watchdog: a scan that stops moving is stopped (and retried by run_scans) instead of
    # waiting for the time limit; the demo has to start within 2 minutes and then keep going
    last_t, moved_at, last_look, last_say, stalled, no_start = -1.0, t0, 0.0, t0, False, False
    try:
        while ut.poll() is None and time.time() - t0 < max_wait:
            if gated and (last_t >= 0 or time.time() - t0 > 30):
                gate.release()  # this one is playing: the next game may start loading
                gated = False
            if hwnd is None:
                with WIN_LOCK:
                    hwnd = win.game_window(ut.pid)
                    if hwnd:
                        win.make_borderless_at_origin(hwnd, *args.scan_res, background=True)
                        if prev_fg:
                            win.u32.SetForegroundWindow(prev_fg)
            time.sleep(1)
            now = time.time()
            if now - last_look >= (5 if last_t >= 0 else 1.5) and log.exists():
                last_look = now
                try:
                    txt = log.read_text(encoding="latin-1", errors="replace")
                except OSError:
                    txt = ""
                ts = re.findall(r"UT2VID (?:PROGRESS|MSG) t=([\d.]+)", txt)
                t_now = max(map(float, ts)) if ts else -1.0
                if t_now > last_t:
                    last_t, moved_at = t_now, now
                if last_t < 0 and re.search(r"Cannot play demo|Pending connect to \S+ failed", txt):
                    emit("  the game could not start the demo; closing it to try again")
                    no_start = True
                    break  # fail fast: run_scans retries straight away instead of after 2 minutes
                if "UT2VID SCAN END" in txt:
                    moved_at = now  # done, UT is closing
                if now - last_say >= 30 and last_t >= 0:
                    last_say = now
                    say(f"  {tag}... {demo.name[:40]}: demo time {fmt_dur(last_t)} after {fmt_dur(now - t0)}")
            if now - moved_at > (120 if last_t < 0 else 90):
                stalled = True
                break
        if ut.poll() is None:
            if not no_start:
                emit("  the scan stopped moving, stopping UT" if stalled else "  time limit reached, stopping UT")
            shutdown_ut(ut, win, hwnd)
    finally:
        if ut.poll() is None:
            ut.kill()
        if gated:
            gate.release()
        for _ in range(10):
            try:
                copy.unlink()
                break
            except OSError:
                time.sleep(0.5)
    took = time.time() - t0
    if not log.exists():
        emit("  ERROR: UT wrote no log")
        return None
    text = log.read_text(encoding="latin-1", errors="replace")
    res = parse_scan_log(text, demo_player(demo.name))
    res.update(demo=demo.name, seconds=round(took, 1), stalled=stalled, demo_path=str(demo))
    played = re.findall(r"Attempting to play demo (\S+)", text)
    if res["start"] and (len(played) != 1 or played[0].lower() != tmp_demo.lower()):
        # another UT start handed its command to this one: the messages may be from two demos
        emit(f"  WARNING: this game played {len(played)} demo(s) ({', '.join(played) or 'none'}); scan not trusted")
        res["start"] = False
    st, exact = demo_start_exact(demo, res.get("total"))
    res.update(demo_start=st, demo_start_exact=exact)
    if not res["start"]:
        bad = [l for l in text.splitlines() if re.search("|".join(FAIL_PATTERNS), l)][:8]
        emit("  ERROR: the scan never started" + (" (is UT2VidHook built? run setup)" if HOOK_CONSOLE.split(".")[0] not in text else ""))
        for l in bad:
            emit(f"    log| {l}")
        return res
    if not res["end"]:
        emit("  WARNING: the scan did not reach the end of the demo")
    if not res["hooked"]:
        emit("  WARNING: the add-on could not attach to the recorded player, so no messages were caught")
    spd, src = scan_speed(res, args)
    refresh_calls(res["messages"], demo_player(demo.name), spd)
    calls = [m for m in res["messages"] if m["call"] and m["own"]]
    reached = max([res.get("total") or 0] if res["end"] else [0] + res["progress"] + [m["t"] for m in res["messages"]])
    speed = reached / took if took > 0 else 0
    emit(f"  {len(res['messages'])} messages, {len(calls)} own announcer calls; "
        f"{fmt_dur(reached)} of demo in {fmt_dur(took)} ({speed:.1f}x real time)")
    for m in calls:
        emit(f"    {fmt_dur(m['t'])}  {m['call']:<14} {m['text']}")
    for w in res["warnings"]:
        emit(f"  {w}")
    unknown = sorted({m["class"] for m in res["messages"]
                      if not m.get("derived") and m["class"].lower().split(".")[-1] not in KNOWN_MESSAGES})
    emit(f"  game speed: {spd:.2f}x ({src})")
    if unknown:
        emit("  NOTE: message types not seen before (a mod with its own announcer?): " + ", ".join(unknown))
        res["unknown_classes"] = unknown
    return res


def hook_ini(text: str, mode: int, progress: float, speed: float = 1.0) -> str:
    """Switch an ini copy to the UT2VidHook console (1 = fast scan, 2 = only log while recording),
    keeping the console settings the user has."""
    text = set_ini_value(text, "Engine.Engine", "Console", HOOK_CONSOLE)
    m = re.search(r"(?ims)^\[UTMenu\.UTConsole\]\s*$(.*?)(?=^\[|\Z)", text)
    if m:
        for line in m.group(1).splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                text = set_ini_value(text, HOOK_CONSOLE, k.strip(), v.strip())
    for k, v in (("UVMode", str(mode)), ("UVPlayback", "0"), ("UVSpeed", f"{speed:g}"),
                 ("UVQuitWhenDone", "True" if mode == 1 else "False"), ("UVProgressEvery", f"{progress:g}")):
        text = set_ini_value(text, HOOK_CONSOLE, k, v)
    return text


def sandbox_exe(sysdir: Path, tag: str) -> Path | None:
    """A renamed copy of the build's UnrealTournament.exe (ut2vid_ut_<tag>.exe). UT 469 runs one copy
    per program name: a second start of the same name hands its command to the one that runs, even
    to your own UT outside the build. Every Killcam '99 start (each scan instance, the recording,
    watching) uses its own name, so they never land in each other or in a game you are playing.
    None if the copy cannot be made (then the caller falls back to the original)."""
    src = sysdir / "UnrealTournament.exe"
    exe = sysdir / f"ut2vid_ut_{tag}.exe"
    try:
        if not exe.exists() or exe.stat().st_size != src.stat().st_size or exe.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(src, exe)
        loc = sysdir / "UnrealTournament.int"  # window titles and texts are looked up under the program name
        if loc.exists() and not (sysdir / f"ut2vid_ut_{tag}.int").exists():
            shutil.copy2(loc, sysdir / f"ut2vid_ut_{tag}.int")
        return exe
    except OSError as e:
        say(f"  note: could not make {exe.name} ({e})")
        return None


def stop_leftover_ut(ut_dir: Path) -> None:
    """Close UT processes of the game folder left running by an interrupted run (they lock the
    log and make the next start fail). Only processes started from inside the sandbox are touched."""
    if not (IS_WINDOWS and SANDBOX and GAME and inside(ut_dir, GAME)):
        return
    pattern = str(ut_dir.resolve()).replace("'", "''") + "\\*"
    # the player's own UT folder: never close their UnrealTournament.exe, only the tool's renamed copies
    names = "ut2vid_ut_s*,ut2vid_ut_rec" if GAME_MODE == "direct" else "UnrealTournament,ut2vid_ut_s*,ut2vid_ut_rec"
    ps = (f"$p = Get-Process {names} -ErrorAction SilentlyContinue | "
          f"Where-Object {{ $_.Path -and $_.Path -like '{pattern}' }}; "
          "if ($p) { $p | Stop-Process -Force; Write-Output $p.Count }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                           text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        n = r.stdout.strip()
        if n:
            say(f"  closed {n} Unreal Tournament window(s) left over from an earlier run")
            time.sleep(2)
    except Exception:
        pass


def boost_process(pid: int, above_normal: bool = True) -> None:
    """Keep Windows from slowing UT down while it runs in the background: switch off 'efficiency
    mode' (EcoQoS power throttling) and raise the priority a little. A throttled UT draws fewer
    frames, which makes recordings choppy. Your PC stays usable (above normal, not high)."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        from ctypes import wintypes

        class PPTS(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x0200 | 0x0400, False, pid)  # PROCESS_SET_INFORMATION | QUERY_INFORMATION
        if not h:
            return
        if above_normal:  # parallel scans stay at normal priority, so the PC stays responsive
            k32.SetPriorityClass(h, 0x00008000)  # ABOVE_NORMAL_PRIORITY_CLASS
        st = PPTS(1, 0x1, 0x0)  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED: off
        k32.SetProcessInformation(h, 4, ctypes.byref(st), ctypes.sizeof(st))  # ProcessPowerThrottling
        k32.CloseHandle(h)
    except Exception:
        pass


def hook_built(sysdir: Path) -> bool:
    return (sysdir / f"{HOOK_CONSOLE.split('.')[0]}.u").exists()


def hook_calls(seen: list[tuple[float, str]], video_epoch: float, pattern: str, player: str,
               return_window: float = 15.0, speed: float | None = None, capture_window: float = 20.0):
    """Announcer calls from the hook's log lines, placed on the video timeline.
    seen = [(wall clock when the line showed up in the log, line)]. Lines can show up late
    (UT writes its log in blocks) but never early, so per stretch of demo the smallest
    'wall clock minus demo time' is the true link between the two clocks.
    Returns (wanted_hits, all_own_calls, all_messages, ok)."""
    anchors, msgs, hooked = [], [], False
    for wall, line in seen:
        if "UT2VID " not in line:
            continue
        hooked = hooked or "UT2VID HOOKED" in line
        m = re.search(r"UT2VID (?:MSG|PROGRESS|SEGMENT (?:START|END) n=\d+) t=([-\d.]+)", line)
        if m:
            anchors.append((float(m.group(1)), wall - float(m.group(1))))
        if "UT2VID MSG" in line:
            msgs += parse_scan_log(line, player)["messages"]
    refresh_calls(msgs, player, speed)
    if not anchors or not hooked:
        return [], [], [], False

    def vtime(t):
        near = [o for ta, o in anchors if abs(ta - t) <= 90] or [o for _, o in anchors]
        return t + min(near) - video_epoch

    calls, allmsgs = [], []
    for m in msgs:
        vt = vtime(m["t"])
        allmsgs.append((vt, m))
        if m["call"] and m["own"]:
            if not any(abs(vt - t2) < 2.0 and c2 == m["call"] for t2, c2, _ in calls):
                calls.append((vt, m["call"], -1.0))
    calls.sort()
    import types
    ev = wanted_events(msgs, types.SimpleNamespace(clip_on=pattern, return_window=return_window,
                                                   capture_window=capture_window))
    wanted = [(vtime(t), "+".join(order_names(n)), -1.0) for t, n, _ in ev]
    return wanted, calls, allmsgs, True


MULTI_PLUS = {"multikill", "megakill", "ultrakill", "monsterkill", "ludicrouskill", "holyshit"}
COMBOS = ("flagreturn", "capture", "fckill")


def carrier_kill_times(messages: list[dict]) -> set[float]:
    """Your kills that killed a flag carrier: the victim drops the flag at that moment
    ('<victim> dropped the blue flag!', CTFMessage switch 2). Matched by name when the kill
    message names the victim ('You killed X'), else by time alone (within 0.3 s)."""
    drops = [(m["t"], m.get("who", "")) for m in messages if m["t"] >= 0 and not m.get("recorder")
             and m["class"].lower().endswith(".ctfmessage") and int(m["switch"]) == 2]
    out = set()
    for k, is_kill, victim in own_kills_detail(messages):
        if not is_kill:
            continue
        if victim:
            if any(-0.3 <= t - k <= 1.0 and same_player(who, victim) for t, who in drops):
                out.add(k)
        elif any(abs(t - k) <= 0.3 for t, _w in drops):
            out.add(k)
    return out


def wanted_events(messages: list[dict], args) -> list[tuple[float, list[str], float]]:
    """Everything worth a clip: [(demo time, names, demo time the action lasts until)].
    1. your own announcer calls matching --clip-on (Mega Kill and up, Rampage and up, ...);
       a multi kill also counts when its Botpack name matches (a mod may name it lower);
    2. a Multi Kill or higher of yours followed within --return-window seconds by YOU returning
       your team's flag ("<you> returns the red flag!", Botpack CTFMessage switch 1);
    3. the same followed within --capture-window seconds by YOU capturing (switch 0);
    4. a Multi Kill or higher whose streak includes killing the enemy flag carrier."""
    def hit(m, pattern):
        return any(c and re.search(pattern, c, re.I) for c in (m.get("call"), m.get("alt_call")))
    ev = [(m["t"], [m["call"]], m["t"]) for m in messages
          if m["t"] >= 0 and m["own"] and m["call"] and hit(m, args.clip_on)]
    rw, cw = getattr(args, "return_window", 15.0), getattr(args, "capture_window", 20.0)
    ctf = [m for m in messages if m["t"] >= 0 and m.get("recorder") and m["class"].lower().endswith(".ctfmessage")]
    returns = [m["t"] for m in ctf if int(m["switch"]) == 1]
    captures = [m["t"] for m in ctf if int(m["switch"]) == 0]
    fck = set() if getattr(args, "no_carrier_kills", False) else carrier_kill_times(messages)
    for m in messages:
        if not (m["t"] >= 0 and m["own"] and m["call"] and hit(m, "^(" + "|".join(MULTI_PLUS) + ")$")):
            continue
        for tag, times, window in (("flagreturn", returns, rw), ("capture", captures, cw)):
            if window > 0:
                r = next((x for x in times if 0 <= x - m["t"] <= window), None)
                if r is not None:
                    ev.append((m["t"], [m["call"], tag], r))
        chain = m.get("chain") or []
        if fck and any(round(k, 3) in {round(x, 3) for x in fck} for k, _v in chain):
            ev.append((m["t"], [m["call"], "fckill"], m["t"]))
    # one streak gives several multi kill messages: keep one combo per return / capture / streak,
    # named after its highest (= latest) multi kill
    ev.sort(key=lambda e: e[0])
    out: list[tuple[float, list[str], float]] = []
    key_of = {}
    for t, names, until in ev:
        tag = next((n for n in names if n in COMBOS), None)
        if tag:
            m = next(x for x in messages if x["t"] == t and x.get("call") == names[0])
            key = (tag, until if tag != "fckill" else round((m.get("chain") or [[t]])[0][0], 3))
            if key in key_of:
                i = key_of[key]
                out[i] = (out[i][0], [names[0], tag], max(out[i][2], until))
                continue
            key_of[key] = len(out)
        out.append((t, names, until))
    return out


def plan_parts(messages: list[dict], args) -> list[tuple[float, float, list[str], float]]:
    """Parts of the demo to record: from a few seconds before the kill streak that leads to a
    wanted call until args.part_after seconds after the last kill of that streak.
    Returns [(start, end, call names, demo time of the first call)]."""
    kills = sorted(m["t"] for m in messages if m["t"] >= 0 and (
        ("killermessage" in m["class"].lower() and m.get("recorder"))
        or (m["own"] and m["call"])))
    parts: list[list] = []
    for t, names, until in wanted_events(messages, args):
        first = last = t
        for k in reversed([k for k in kills if k <= t]):
            if first - k <= 4.0:
                first = k
        for k in [k for k in kills if k >= t]:
            if k - last <= 4.0:
                last = k
        a = max(0.0, min(first - 3.0, t - args.part_before))
        b = max(last, until) + args.part_after
        if parts and a <= parts[-1][1] + 3.0:
            parts[-1][1] = max(parts[-1][1], b)
            parts[-1][2] += names
        else:
            parts.append([a, b, list(names), t])
    return [(round(a, 2), round(b, 2), order_names(n), t0) for a, b, n, t0 in parts]


NAME_ORDER = ["doublekill", "multikill", "megakill", "ultrakill", "monsterkill", "ludicrouskill", "holyshit",
              "killingspree", "rampage", "dominating", "unstoppable", "godlike", "whickedsick",
              "fckill", "flagreturn", "capture"]


def order_names(names: list[str]) -> list[str]:
    """Clip label: the highest multi kill, the highest spree, then 'flagreturn' (and anything else)."""
    u = list(dict.fromkeys(names))
    kills = [n for n in u if n in NAME_ORDER[:7]]
    sprees = [n for n in u if n in NAME_ORDER[7:13]]
    rest = [n for n in u if n not in NAME_ORDER[:13]]
    out = ([max(kills, key=NAME_ORDER.index)] if kills else []) + \
          ([max(sprees, key=NAME_ORDER.index)] if sprees else []) + rest
    return sorted(out, key=lambda n: NAME_ORDER.index(n) if n in NAME_ORDER else 99)


DISPLAY = {"doublekill": "Double Kill", "multikill": "Multi Kill", "megakill": "Mega Kill", "ultrakill": "Ultra Kill",
           "monsterkill": "Monster Kill", "ludicrouskill": "Ludicrous Kill", "holyshit": "Holy Shit",
           "killingspree": "Killing Spree", "rampage": "Rampage", "dominating": "Dominating",
           "unstoppable": "Unstoppable", "godlike": "Godlike", "whickedsick": "Wicked Sick", "wickedsick": "Wicked Sick",
           "fckill": "Flag Carrier Kill", "flagreturn": "Flag Return", "capture": "Capture",
           "firstblood": "First Blood", "headshot": "Headshot"}
# which call names the clip's folder: the special combos first, then the rarest call
CATEGORY_ORDER = ["capture", "flagreturn", "fckill", "holyshit", "ludicrouskill", "whickedsick", "wickedsick",
                  "godlike", "monsterkill", "unstoppable", "ultrakill", "dominating", "megakill", "rampage",
                  "multikill", "killingspree", "doublekill"]


def display(name: str) -> str:
    return DISPLAY.get(name, name)


def clip_category(names: list[str]) -> str:
    best = min(names, key=lambda n: CATEGORY_ORDER.index(n) if n in CATEGORY_ORDER else 99, default="other")
    return display(best)


def safe_name(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().rstrip(".")


def clip_dest(root: Path, names: list[str], title: str, t_call: float, ext: str) -> Path:
    """<root>/<call type>/<title> - 12m30s Monster Kill + Flag Return.<ext>"""
    label = " + ".join(dict.fromkeys(display(n) for n in names))
    return root / safe_name(clip_category(names)) / f"{safe_name(title)} - {stamp_of(t_call)} {safe_name(label)}.{ext}"


_MAP_CACHE: dict[str, str | None] = {}


def demo_map(demo: Path, args) -> str | None:
    """Map of a demo: from udemo's file name, else from its scan (hook 16+), else from the packages
    the demo needs (the .unr one)."""
    m = map_from_filename(demo.name)
    if m:
        return m
    r = load_scan(demo, args) or {}
    if r.get("map"):
        return r["map"]
    if demo.name not in _MAP_CACHE:
        try:
            reqs = demo_packages(demo) or []
        except OSError:
            reqs = []
        _MAP_CACHE[demo.name] = next((Path(x["fname"]).stem for x in reqs if x["fname"].lower().endswith(".unr")), None)
    return _MAP_CACHE[demo.name]


def demo_title(demo: Path, args) -> str:
    """'2026-11-14 00.56 Klondike-PG1' (start and map of the demo), else the demo's own name."""
    r = load_scan(demo, args) or {}
    st, _exact = demo_start_exact(demo, r.get("total") or scan_total(demo))
    mp = demo_map(demo, args)
    if mp:
        mp = re.sub(r"^(CTF|DM|DOM|AS|TDM|CTF4|BT)-", "", mp, flags=re.I)
    if st is None:
        return demo.stem
    return dt.datetime.fromtimestamp(st).strftime("%Y-%m-%d %H.%M") + (f" {mp}" if mp else f" {demo.stem}")


def clip_dirs(out: Path) -> dict[str, Path]:
    """Where finished videos go. Killcam '99: the Clips folder (Demos, Recordings, Rejected), with
    the bookkeeping in the work folder <out>. The bare converter: everything under <out>."""
    if kc_config:
        b = kc_config.clips()
        return {"base": b, "clips": b / "Demos", "obs_clips": b / "Recordings", "rejected": b / "Rejected",
                "ledgers": out}
    return {"base": out, "clips": out / "clips", "obs_clips": out / "obs_clips", "rejected": out / "rejected",
            "ledgers": out / "clips"}


def ledger_dir(args) -> Path:
    """Bookkeeping next to the clips (events.txt, check.txt, parts_done.txt): never in the Clips folder."""
    d = clip_dirs(args.out)["ledgers"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def index_file(args) -> Path:
    return args.out / "clip_index.json"


def add_to_index(args, clip: Path, **info) -> None:
    """Every clip made is listed in <out>/clip_index.json; the review page reads it."""
    import json
    f = index_file(args)
    try:
        items = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        items = []
    base = clip_dirs(args.out)["base"]
    rel = str(clip.resolve().relative_to(base.resolve())) if inside(clip, base) else str(clip)
    items = [x for x in items if x.get("file") != rel]
    items.append({"file": rel, "created": time.time(), "run": RUN_ID, "status": "new", **info})
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def load_scan(demo: Path, args) -> dict | None:
    """The saved scan of a demo, or None."""
    import json
    f = args.out / "scans" / (demo.stem + ".json")
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def parts_ledger(args) -> Path:
    return clip_dirs(args.out)["ledgers"] / "parts_done.txt"


_CLIP_NAMES: dict = {"t": 0.0, "root": None, "names": set()}


def existing_clip_names(args) -> set[str]:
    """File names of every clip that still exists (in the clip folders or among the rejected ones).
    Looked up at most every few seconds: part_done asks for every part of every demo."""
    root = args.out
    if _CLIP_NAMES["root"] != root or time.time() - _CLIP_NAMES["t"] > 3:
        names = set()
        for sub in ("clips", "rejected"):
            d = clip_dirs(root)[sub]
            if d.is_dir():
                names |= {f.name.lower() for f in d.rglob("*") if f.is_file()}
        _CLIP_NAMES.update(t=time.time(), root=root, names=names)
    return _CLIP_NAMES["names"]


def part_done(demo: Path, part, args) -> bool:
    """A part counts as done when parts_done.txt lists a recorded part of the same demo that
    covers most of it (labels may change when detection improves; the footage is the same) AND
    its clip still exists. A clip you deleted is made again next time; one you rejected in the
    review page (moved to 'rejected') is not."""
    f = parts_ledger(args)
    if not f.exists():
        return False
    a, b = part[0], part[1]
    have = None
    for line in f.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) >= 3 and cols[0] == demo.name:
            try:
                da, db = float(cols[1]), float(cols[2])
            except ValueError:
                continue
            if min(b, db) - max(a, da) >= 0.8 * (b - a):
                if len(cols) < 5 or not cols[4].strip():
                    return True  # old ledger line without a file name: trust it
                if have is None:
                    have = existing_clip_names(args)
                if cols[4].strip().lower() in have:
                    return True
    return False


def part_clip_path(demo: Path, part, args) -> Path:
    _a, _b, names, t_call = part
    return clip_dest(clip_dirs(args.out)["clips"], names, demo_title(demo, args), t_call, args.format)


def scan_first(todo: list[Path], args, ut_dir: Path) -> list[Path] | None:
    """Fast message scan of every demo, then keep only the demos that contain a wanted call."""
    import json
    if not IS_WINDOWS:
        say("PROBLEM: This tool has to run on Windows (it drives the UT window).")
        return None
    if not SANDBOX or not hook_built(ut_system_dir(ut_dir)):
        say("PROBLEM: finding kills needs the UT2VidHook add-on in the game folder (run the setup first).")
        return None
    say(f"Scanning {len(todo)} demo(s) first (fast, no recording) ...")
    args.reuse_scans = True
    run_scans(todo, args, ut_dir)
    keep = []
    for d in todo:
        f = args.out / "scans" / (d.stem + ".json")
        r = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        if not r or not r.get("end") or not r.get("hooked", True):
            say(f"  {d.name}: scan incomplete, recording it anyway")
            keep.append(d)
            continue
        player = demo_player(d.name)
        spd, _src = scan_speed(r, args)
        args.speeds = getattr(args, "speeds", {})
        args.speeds[d.name] = spd
        refresh_calls(r["messages"], player, spd)
        bogus = [m for m in r["messages"] if m.get("bogus")]
        if bogus:
            say(f"  {d.name}: ignored {len(bogus)} impossible multi kill message(s), e.g. "
                f"{fmt_dur(bogus[0]['t'])} {bogus[0]['bogus']}")
        calls = [(t, "+".join(n)) for t, n, _ in wanted_events(r["messages"], args)]
        chosen = (getattr(args, "moments_map", None) or {}).get(d.name)
        if calls and chosen is not None and not args.whole_demo:
            # only the moments picked in the Demobuild window; picked means 'record it', also again
            parts = [p for p in plan_parts(r["messages"], args) if any(abs(p[3] - t) < 0.6 for t in chosen)]
            if not parts:
                say(f"  {d.name}: the picked moment(s) are not in the scan any more (rescanned or settings changed?)")
                continue
            keep.append(d)
            args.parts[d.name] = parts
            say(f"  {d.name}: {len(parts)} picked moment(s): " + ", ".join(
                f"{fmt_dur(a)}-{fmt_dur(b)} ({'+'.join(n)})" for a, b, n, _ in parts))
            continue
        if calls:
            parts = [] if args.whole_demo else plan_parts(r["messages"], args)
            have = [p for p in parts if part_done(d, p, args)]
            parts = [p for p in parts if p not in have]
            if not args.whole_demo and not parts:
                say(f"  {d.name}: all {len(have)} part(s) already clipped")
                continue
            say(f"  {d.name}: " + ", ".join(f"{fmt_dur(t)} {c}" for t, c in calls) + "  -> record"
                + (f" ({len(have)} part(s) already clipped)" if have else ""))
            keep.append(d)
            if not args.whole_demo:
                args.parts[d.name] = parts
                say("      parts to record: " + ", ".join(f"{fmt_dur(a)}-{fmt_dur(b)} ({'+'.join(n)})"
                                                         for a, b, n, _ in parts))
        else:
            say(f"  {d.name}: no wanted calls of yours, skipped")
    return keep


def auto_scan_jobs() -> int:
    """How many UT instances scan side by side when --scan-jobs is not given. UT99 runs its game
    on one thread, so every instance needs about one CPU core; two threads are left for Windows,
    ffmpeg and you, and every instance needs about 0.5 GB of free memory. At most 4."""
    threads = os.cpu_count() or 2
    jobs = min(4, max(1, threads // 2 - 1))
    if IS_WINDOWS:
        try:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = MS()
            ms.dwLength = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                jobs = min(jobs, max(1, int((ms.ullAvailPhys / 2**30 - 2) / 0.5)))
        except Exception:
            pass
    return jobs


def run_scans(todo: list[Path], args, ut_dir: Path) -> int:
    """Scan demos, several UT instances at a time (--scan-jobs, default: what the PC can carry).
    Every instance plays from the same game folder with its own demo copy, exec file, log,
    ini and user ini; nothing else is written while a demo plays."""
    import json
    from concurrent.futures import ThreadPoolExecutor, as_completed
    sysdir = ut_system_dir(ut_dir)
    if not (sysdir / f"{HOOK_CONSOLE.split('.')[0]}.u").exists():
        say("PROBLEM: UT2VidHook.u is missing in the build. Run the Killcam '99 setup first.")
        return 1
    ut_exe = sysdir / "UnrealTournament.exe"
    win = Win()
    out = args.out / "scans"
    out.mkdir(parents=True, exist_ok=True)
    pending, ok = [], 0
    for d in todo:
        prev = out / (d.stem + ".json")
        if getattr(args, "reuse_scans", False) and prev.exists():
            try:
                r = json.loads(prev.read_text(encoding="utf-8"))
                done_before = r.get("end") and r.get("hooked")
            except ValueError:
                done_before = False
            if done_before:
                say(f"Scan: {d.name}  (already scanned)")
                ok += 1
                continue
        pending.append(d)
    if not pending:
        say(f"Scans finished: {ok}/{len(todo)}. Results in {out}")
        return 0
    jobs = args.scan_jobs if getattr(args, "scan_jobs", 0) and args.scan_jobs > 0 else auto_scan_jobs()
    jobs = max(1, min(jobs, len(pending), 8))
    args._jobs = jobs
    args.scan_res = (640, 360)
    stop_leftover_ut(sysdir.parent)  # once, before any instance starts (it closes every sandbox UT)
    text = patch_ini((sysdir / "UnrealTournament.ini").read_text(encoding="latin-1"), *args.scan_res, args.renderer)
    text = hook_ini(text, mode=1, progress=60, speed=args.scan_speed)
    user = sysdir / "User.ini"
    for slot in range(jobs):
        (sysdir / f"ut2vid_scan{slot}.ini").write_text(text, encoding="latin-1")
        if user.exists():
            shutil.copyfile(user, sysdir / f"ut2vid_scanuser{slot}.ini")
    args.scan_ini = "ut2vid_scan{slot}.ini"
    args.user_ini_path = "ut2vid_scanuser{slot}.ini" if user.exists() else None
    # UT 469 allows one running copy per program name: a second UnrealTournament.exe hands its
    # command line to the one already running and quits (that mixed up demos between scans).
    # Every instance therefore runs from its own renamed copy of the program file.
    exes = {}
    for slot in range(jobs):
        exe = sandbox_exe(sysdir, f"s{slot}")
        if exe is None:
            break
        exes[slot] = exe
    if not exes:
        exes = {0: ut_exe}
    if len(exes) < jobs:
        say(f"  could only prepare {len(exes)} scan instance(s); scanning with fewer at a time")
        jobs = args._jobs = len(exes)
    say(f"Scan speed: {args.scan_speed:g}x (udemo slomo, time based; every message is still read); "
        f"{len(pending)} demo(s), {jobs} at a time" + ("" if getattr(args, "scan_jobs", 0) else " (auto, see --scan-jobs)"))
    # longest demos first, so the last one to finish is a short one
    pending.sort(key=lambda d: -(estimate_duration(d) or d.stat().st_size / 80_000))
    slots = list(range(jobs))
    slot_lock = threading.Lock()
    args._start_gate = threading.Lock() if jobs > 1 else None  # games load one at a time (scan_one)
    t_all = time.time()

    def work(i: int, d: Path):
        with slot_lock:
            slot = slots.pop(0)
        lines: list[str] = []
        emit = say if jobs == 1 else lines.append
        try:
            res = scan_one(d, args, exes[slot], sysdir, win, slot, emit)
            if res is None or not res.get("start") or (res.get("stalled") and not res.get("end")):
                emit("  trying once more ...")
                time.sleep(3)
                res = scan_one(d, args, exes[slot], sysdir, win, slot, emit) or res
            if res and res.get("start"):
                (out / (d.stem + ".json")).write_text(json.dumps(res, indent=1), encoding="utf-8")
            return d, res, lines
        finally:
            for f in (sysdir / f"ut2vid_tmp_s{slot}.dem",):
                for _ in range(10):
                    try:
                        f.unlink()
                        break
                    except FileNotFoundError:
                        break
                    except OSError:
                        time.sleep(0.5)
            with slot_lock:
                slots.append(slot)

    n = 0
    demo_secs = 0.0
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(work, i, d) for i, d in enumerate(pending)]
        try:
            for fut in as_completed(futs):
                n += 1
                try:
                    d, res, lines = fut.result()
                except Exception as e:
                    say(f"=== [{n}/{len(pending)}] scan failed: {e}")
                    continue
                if res and res.get("start"):
                    ok += 1
                    demo_secs += res.get("total") or 0
                if jobs > 1:
                    with SAY_LOCK:  # one demo's report as one block
                        say(f"=== [{n}/{len(pending)}] ===")
                        for l in lines:
                            say(l)
                        took = time.time() - t_all
                        if n < len(pending) and demo_secs:
                            say(f"  together: {fmt_dur(demo_secs)} of demo in {fmt_dur(took)} "
                                f"({demo_secs / took:.0f}x real time); {len(pending) - n} to go")
        except KeyboardInterrupt:
            say("Stopping the scans ...")
            for f in futs:
                f.cancel()
            stop_leftover_ut(sysdir.parent)
            raise
    # anything that failed side by side gets one more try alone (one instance, nothing else running)
    failed = [d for d in pending if not ((out / (d.stem + ".json")).exists()
                                         and (out / (d.stem + ".json")).stat().st_mtime >= t_all)]
    if failed and jobs > 1:
        say(f"{len(failed)} scan(s) failed side by side; trying those once more, one at a time ...")
        args._jobs = 1
        for d in failed:
            res = scan_one(d, args, exes[0], sysdir, win, 0)
            if res and res.get("start"):
                (out / (d.stem + ".json")).write_text(json.dumps(res, indent=1), encoding="utf-8")
                ok += 1
                demo_secs += res.get("total") or 0
    took = time.time() - t_all
    say(f"Scans finished: {ok}/{len(todo)} in {fmt_dur(took)}"
        + (f" ({demo_secs / took:.0f}x real time with {jobs} at a time)" if demo_secs and took > 0 else "")
        + f". Results in {out}")
    return 0 if ok == len(todo) else 2


def audio_calls_from_logs(paths: list[Path]) -> dict[str, list[tuple[float, str]]]:
    """'calls heard' lines written by the audio detector, per demo file name."""
    def secs(s):
        p = [int(x) for x in s.split(":")]
        return p[0] * 3600 + p[1] * 60 + p[2]
    out: dict[str, list[tuple[float, str]]] = {}
    for p in paths:
        if not p.exists():
            continue
        demo = None
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.search(r"\] Demo: (.+\.dem)\s*$", line)
            if m:
                demo = m.group(1)
            m = re.search(r"calls heard: (.*)$", line)
            if m and demo:
                out[demo] = [(secs(a), b) for a, b in re.findall(r"(\d+:\d\d:\d\d) (\w+)", m.group(1))]
    return out


def validate(args) -> int:
    """Compare message scans with what the audio detector heard on the same demos."""
    import json
    from collections import Counter
    logs = [Path(p) for p in args.validate] or [Path(__file__).resolve().parent.parent / "ut2vid_log.txt",
                                                Path(__file__).resolve().parent / "ut2vid_log.txt"]
    heard = audio_calls_from_logs(logs)
    scans = {}
    for f in (args.out / "scans").glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        scans[r["demo"]] = r
    both = sorted(set(heard) & set(scans))
    if not both:
        say(f"Nothing to compare: {len(heard)} demo(s) with audio results, {len(scans)} scanned. "
            "Scan demos that were already converted with clips.")
        return 1
    trig = re.compile(args.clip_on, re.I)
    worse = 0
    for name in both:
        a = heard[name]
        s = [(m["t"], m["call"]) for m in refresh_calls(scans[name]["messages"], demo_player(name))
             if m["call"] and m["own"]]
        # the video starts a little after the demo time zero: find that offset
        offs = Counter(round(ta - ts) for ta, ca in a for ts, cs in s if ca == cs)
        off = offs.most_common(1)[0][0] if offs else 0
        used, missing_in_scan = set(), []
        for ta, ca in a:
            hit = next((i for i, (ts, cs) in enumerate(s) if i not in used and abs(ts + off - ta) <= 2.5), None)
            if hit is None:
                missing_in_scan.append((ta, ca))
            else:
                used.add(hit)
        extra = [s[i] for i in range(len(s)) if i not in used]
        miss_trig = [x for x in missing_in_scan if trig.search(x[1])]
        worse += len(miss_trig)
        say(f"{name}")
        say(f"  audio heard {len(a)} call(s), scan found {len(s)}; offset {off:+d}s")
        for ta, ca in missing_in_scan:
            say(f"    only in audio: {fmt_dur(ta)} {ca}" + ("   <-- trigger call missed by scan!" if trig.search(ca) else ""))
        for ts, cs in extra:
            say(f"    only in scan:  {fmt_dur(ts + off)} {cs}" + ("   (audio missed this one)" if trig.search(cs) else ""))
    say("RESULT: " + ("the scan found every trigger call the audio found." if worse == 0
                      else f"the scan missed {worse} trigger call(s) the audio found. Do NOT switch yet."))
    return 0 if worse == 0 else 2


# --------------------------------------------------------------------------------------
# Separation audit: the original UT folders must not change while Demobuild runs
# --------------------------------------------------------------------------------------

def original_roots() -> list[Path]:
    roots = desktop_installs()
    src = load_settings().get("source_folder")  # the folder the copy was made from
    if src and Path(src).is_dir() and not any(inside(Path(src), r) for r in roots):
        roots.append(Path(src))
    docs = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents" / "UnrealTournament"
    if docs.is_dir():
        roots.append(docs)  # 469 can keep settings there; Killcam '99 must not touch it either
    return roots


def fingerprint(roots: list[Path]) -> dict[str, tuple[int, int]]:
    fp = {}
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                p = os.path.join(dirpath, fn)
                try:
                    st = os.stat(p)
                    fp[p] = (st.st_size, int(st.st_mtime))
                except OSError:
                    pass
    return fp


def audit_report(before: dict, after: dict) -> list[str]:
    changed = [p for p in after if p in before and after[p] != before[p]]
    added = [p for p in after if p not in before]
    removed = [p for p in before if p not in after]
    return [f"changed: {p}" for p in changed] + [f"added: {p}" for p in added] + [f"removed: {p}" for p in removed]


# --------------------------------------------------------------------------------------
# OBS link: scan existing gameplay recordings for the same announcer calls
# --------------------------------------------------------------------------------------

VIDEO_EXTS = {".mkv", ".mp4", ".flv", ".mov", ".ts", ".m4v"}


def stamp_of(t: float) -> str:
    hh, rest = divmod(int(max(0, t)), 3600)
    mm, ss = divmod(rest, 60)
    return (f"{hh}h" if hh else "") + f"{mm:02d}m{ss:02d}s"


def recording_start(f: Path, dur: float) -> tuple[float, bool]:
    """Wall clock start of a screen recording: from an OBS/Streamlabs style name
    ('2026-01-17 00-12-33.mkv') if present (exact), else file time minus length (rough)."""
    m = re.search(r"(\d{4})-(\d\d)-(\d\d)[ _T](\d\d)[-.](\d\d)[-.](\d\d)", f.stem)
    if m:
        try:
            return dt.datetime(*map(int, m.groups())).timestamp(), True
        except ValueError:
            pass
    return f.stat().st_mtime - dur, False


def align_to_demo(heard: list, own: list, near: float | None = None,
                  tol: float = 6.0) -> tuple[float, int, list] | None:
    """Find the shift that lines up the calls heard in a recording with the demo's own calls.
    heard/own: [(time, call)]. near: the shift the clocks predict (only shifts within tol of it are
    tried). Returns (offset so that recording_time = demo_time + offset, number of calls that line
    up, the matched pairs)."""
    from collections import Counter
    cands = Counter(round((th - td) * 2) / 2 for th, nh in heard for td, nd in own if nh == nd)
    best = None
    for off, _ in cands.most_common(40 if near is not None else 8):
        if near is not None and abs(off - near) > tol:
            continue
        pairs = []
        for th, nh in heard:
            close = [td for td, nd in own if nd == nh and abs(th - (td + off)) < 0.8]
            if close:
                td = min(close, key=lambda x: abs(th - (x + off)))
                pairs.append((th, td))
        if pairs:
            fine = sorted(th - td for th, td in pairs)[len(pairs) // 2]
            if best is None or len(pairs) > best[1]:
                best = (fine, len(pairs), pairs)
    return best


def find_demo_file(name: str, args) -> Path | None:
    """A demo file by name in the demo folder(s) (and one level below) and the Desktop installs."""
    for d in demo_search_folders(args):
        for f in (d / name, *d.glob(f"*/{glob_escape(name)}")):
            if f.is_file():
                return f
    return None


def glob_escape(name: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", name)


def demo_search_folders(args) -> list[Path]:
    folders = [Path(p) for p in (args.demos or [])]
    folders = [p if p.is_dir() else p.parent for p in folders]
    for inst in desktop_installs():
        folders.append(inst / "System")
    return [d for d in dict.fromkeys(folders) if d.is_dir()]


def scan_demo_start(r: dict, args) -> tuple[float | None, bool]:
    """Start of a scanned demo: saved with the scan (new scans), else from the demo file's time."""
    if r.get("demo_start") is not None:
        return r["demo_start"], bool(r.get("demo_start_exact"))
    f = find_demo_file(r.get("demo", ""), args)
    if f is not None:
        return demo_start_exact(f, r.get("total"))
    return demo_start(r.get("demo", "")), False


def link_demos(heard: list, rec_start: float, exact_start: bool, dur: float, args) -> list[dict]:
    """Demos (from earlier scans) that were recorded during this screen recording, each with the
    time shift between the two. A recording can hold several maps, so several demos can link.
    When both start times are known to the second (OBS file name, demo file time) the clocks
    predict the shift: then 2 matching calls confirm it, and a demo during which no call was heard
    at all is still linked on the clocks alone ('time_only', clips get some extra margin)."""
    import json
    scans = args.out / "scans"
    if not scans.is_dir():
        return []
    found, free = [], list(heard)
    cands = []
    for f in sorted(scans.glob("*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not r.get("end"):
            continue
        ds, ds_exact = scan_demo_start(r, args)
        in_window = ds is not None and rec_start - 3600 <= ds <= rec_start + dur + 120
        if ds is not None and not in_window and exact_start:
            continue  # recorded at another time
        near = ds - rec_start if (exact_start and ds_exact and ds is not None) else None
        cands.append((r, in_window, near))
    names_of = dict(heard)
    for _ in range(6):
        best = None
        for r, in_window, near in cands:
            if any(x["r"] is r for x in found):
                continue
            msgs = refresh_calls(r["messages"], demo_player(r["demo"]), scan_speed(r, args)[0])
            own = [(m["t"], m["call"]) for m in msgs if m["own"] and m["call"]]
            total = r.get("total") or max((t for t, _ in own), default=0)
            got = align_to_demo(free, own, near) if free else None
            confirmed = False
            if got:
                off, n, pairs = got
                # Double Kills happen all the time, so they line up by chance more easily: count
                # every other call double. Also most calls heard while this demo ran must line up.
                in_span = [h for h in free if off <= h[0] <= off + total + 5]
                weight = sum(1 if names_of.get(th) == "doublekill" else 2 for th, _ in pairs)
                need, share = (2, 0.4) if near is not None else ((4 if in_window else 6), 0.6)
                if weight >= need and n >= share * max(1, len(in_span)):
                    confirmed = True
                    if best is None or weight > best[1]:
                        best = (off, weight, pairs, r, msgs, near, False)
            # Both start times known to the second: the clocks alone are trusted when the sound
            # does not confirm them (announcer too quiet or not recorded; then whatever was
            # 'heard' is game noise that only resembles a call and must not block the link).
            if (not confirmed and near is not None and best is None
                    and 0 < total and near < dur and near + total > 0):
                best = (near, 0, [], r, msgs, near, True)
        if not best:
            break
        off, _w, pairs, r, msgs, near, time_only = best
        found.append({"r": r, "offset": off, "matched": len(pairs), "messages": msgs,
                      "clock_offset": near, "time_only": time_only})
        used = {th for th, _ in pairs}
        free = [h for h in free if h[0] not in used]
    return found


def demos_recorded_during(rec_start: float, dur: float, args) -> list[Path]:
    """Demos that ran during a screen recording: from the demo folder(s) (and one level below) and
    the System folders of the UT installs on the Desktop (those are only READ). Named demos by the
    start minute in their name; renamed ones by their file time (UT writes a demo until it ends)."""
    seen, out = set(), []
    rec_end = rec_start + dur
    for d in demo_search_folders(args):
        for f in [*d.glob("*.dem"), *d.glob("*/*.dem")]:
            if f.name.startswith("ut2vid_tmp") or f.name in seen:
                continue
            ds = demo_start(f.name)
            if ds is not None:
                hit = rec_start - 90 <= ds <= rec_end + 60
            else:
                try:
                    mt = f.stat().st_mtime
                except OSError:
                    continue
                tot = scan_total(f)
                hit = (rec_start - 90 <= mt - tot <= rec_end + 60) if tot else (rec_start <= mt <= rec_end + 45 * 60)
            if hit:
                seen.add(f.name)
                out.append(f)
    return sorted(out)


def track_report(ffmpeg: str, src: Path, track: int, templates: dict, debug_dir: Path | None) -> str:
    """How loud a sound track is and which announcer samples it resembles most (also below the
    detection threshold). With --obs-debug the track is also saved as a small 16 kHz WAV."""
    import numpy as np
    r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(src), "-map", f"0:a:{track}",
                        "-ac", "1", "-ar", str(KILL_SR), "-f", "s16le", "-"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    sig = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768
    if len(sig) < KILL_SR:
        return "no sound"
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        with wave.open(str(debug_dir / f"{src.stem}.track{track + 1}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(KILL_SR)
            w.writeframes(r.stdout)
    rms = float(np.sqrt(np.mean(sig[: KILL_SR * 600] ** 2))) + 1e-9
    level = 20 * np.log10(rms)
    det = KillDetector(sig[: KILL_SR * 1200])
    best = sorted(((float(det.zscores(t).max()), n) for n, t in templates.items()
                   if not n.startswith("cd")), reverse=True)[:4]
    return f"level {level:.0f} dBFS, closest announcer samples: " + ", ".join(f"{n} {z:.1f}" for z, n in best)


def cut_copy(ffmpeg: str, src: Path, a: float, length: float, dst: Path) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{a:.3f}", "-i", str(src),
                        "-t", f"{length:.3f}", "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero", str(dst)],
                       capture_output=True, text=True, errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        say(f"  clip failed: {r.stderr.strip()[-300:]}")
    return r.returncode == 0


def obs_ledger(args) -> dict[str, tuple[str, float]]:
    """obs_processed.txt: '<size>|<mtime>|<path>[\t<status>\t<when>]' per recording; the last line
    of a recording wins. status 'retry' = a demo ran during it but could not be linked yet."""
    f = args.out / "obs_processed.txt"
    out: dict[str, tuple[str, float]] = {}
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            cols = line.split("\t")
            if cols and cols[0]:
                out[cols[0]] = (cols[1] if len(cols) > 1 else "done", float(cols[2]) if len(cols) > 2 else 0.0)
    return out


def obs_mode(args, ut_dir: Path | None) -> int:
    """Find Mega Kill+/Unstoppable+ calls in screen recordings (OBS, ReLive, ...) and cut clips.
    The recordings are only read; clips and bookkeeping go to <out>/obs_clips."""
    src = Path(args.obs) if args.obs else Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Videos"
    if not src.exists() and not getattr(args, "obs_files", None):
        say(f"PROBLEM: folder not found: {src}")
        return 1
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        say("PROBLEM: ffmpeg not found  ->  winget install Gyan.FFmpeg")
        return 1
    try:
        import numpy  # noqa: F401
    except ImportError:
        say("PROBLEM: numpy missing  ->  py -m pip install numpy")
        return 1
    if not ut_dir:
        say("PROBLEM: no UT folder found to take the announcer sounds from (use --ut).")
        return 1
    templates = announcer_templates(ut_dir)
    if not any(re.search(args.clip_on, n, re.I) for n in templates):
        say(f"PROBLEM: no announcer sounds matching '{args.clip_on}' in {ut_dir / 'Sounds'}")
        return 1
    out_dir = clip_dirs(args.out)["obs_clips"]
    done_file = args.out / "obs_processed.txt"
    ledger = obs_ledger(args)
    newest_scan = max((f.stat().st_mtime for f in (args.out / "scans").glob("*.json")), default=0.0) \
        if (args.out / "scans").is_dir() else 0.0
    explicit = [Path(x) for x in getattr(args, "obs_files", [])]
    if src.is_file():
        explicit.append(src)
    if explicit:
        files = explicit
    else:
        files = sorted(p for p in src.rglob("*")
                       if p.is_file() and p.suffix.lower() in VIDEO_EXTS and not inside(p, args.out))
    if args.only:
        files = [p for p in files if args.only.lower() in p.name.lower()]
    enc = clip_encoder_args(pick_encoder(ffmpeg, args.encoder), args.clip_quality) if args.obs_reencode else []
    say(f"OBS link: {len(files)} recording(s)" + ("" if explicit else f" in {src}"))
    n_done = n_clips = 0
    for f in files:
        st = f.stat()
        key = f"{st.st_size}|{int(st.st_mtime)}|{f}"
        status, when = ledger.get(key, (None, 0.0))
        if status and not args.overwrite and not explicit:
            if status != "retry":
                continue
            if newest_scan <= when:
                continue  # nothing new to link it with
            say(f"  {f.name}: new scans since last time, trying to link it again")
        if time.time() - st.st_mtime < 120:
            say(f"  skipped (still being written?): {f.name}")
            continue
        if args.limit and n_done >= args.limit:
            break
        tracks = audio_track_count(ffmpeg, f)
        if not tracks:
            say(f"  skipped (no sound): {f.name}")
            continue
        which = [args.obs_track] if args.obs_track is not None else list(range(tracks))
        dur = media_duration(ffmpeg, f) or 0.0
        say(f"Recording: {f.name}  ({fmt_dur(dur)}, sound track(s) {', '.join(str(t + 1) for t in which)})")
        per_track = {}
        for tr in which:
            if tr >= tracks:
                continue
            h, heard = detect_calls(ffmpeg, f, templates, args.clip_on, track=tr, z_min=4.5)
            per_track[tr] = (h, heard)
            if heard:
                say(f"    track {tr + 1} calls heard: " + ", ".join(f"{fmt_dur(t)} {n}" for t, n, _ in heard))
            else:
                say(f"    track {tr + 1}: no announcer calls heard ("
                    + track_report(ffmpeg, f, tr, templates, args.out / "obs_debug" if args.obs_debug else None) + ")")
            if heard and args.obs_debug:
                track_report(ffmpeg, f, tr, templates, args.out / "obs_debug")
        # 1. Was a demo recorded during this recording (and scanned)? Then its exact kill list is used.
        rec_start, exact = recording_start(f, dur)
        during = demos_recorded_during(rec_start, dur, args)
        if during:
            say("    demo(s) recorded during this recording: " + ", ".join(d.name for d in during))
            unscanned = [d for d in during if not (args.out / "scans" / (d.stem + ".json")).exists()]
            if unscanned and SANDBOX and IS_WINDOWS and ut_dir and hook_built(ut_system_dir(ut_dir)):
                say("    checking the packages they need ...")
                lacking = prepare_packages(unscanned, args, ut_dir)
                for d, reqs in lacking.items():
                    say(f"    {d.name} still misses: {', '.join(r['pkg'] for r in reqs)}")
                if not args.force:
                    unscanned = [d for d in unscanned if d not in lacking]
                if unscanned:
                    say("    scanning them first (fast, the demo files are only read) ...")
                    args.reuse_scans = True
                    run_scans(unscanned, args, ut_dir)
        # every track's calls together (the same call heard on two tracks counts once)
        merged: list[tuple[float, str]] = []
        for _h, hd in per_track.values():
            for t, n, _z in hd:
                if not any(n == n2 and abs(t - t2) < 1.0 for t2, n2 in merged):
                    merged.append((t, n))
        merged.sort()
        links = link_demos(merged, rec_start, exact, dur, args)
        ext = "mp4" if f.suffix.lower() in (".mp4", ".mov", ".m4v", ".flv") else "mkv"
        if args.obs_reencode:
            ext = args.format
        if links:
            clips = []
            for L in links:
                r, off = L["r"], L["offset"]
                pad = 3.0 if L["time_only"] else 0.0
                if L["time_only"]:
                    say(f"    linked to demo {r['demo']} by the clocks only (shift {off:+.1f}s, the announcer "
                        "calls in the sound did not confirm it); clips get 3 s extra on both sides")
                else:
                    say(f"    linked to demo {r['demo']}: shift {off:+.1f}s, {L['matched']} calls line up; "
                        "using the demo's exact kill list"
                        + (f" (the clocks said {L['clock_offset']:+.1f}s)" if L["clock_offset"] is not None else ""))
                title = f.stem
                demo_file = find_demo_file(r["demo"], args)
                mp = demo_map(demo_file, args) if demo_file else map_from_filename(r["demo"])
                if mp:
                    title += " " + re.sub(r"^(CTF|DM|DOM|AS|TDM|CTF4|BT)-", "", mp, flags=re.I)
                for a, b, names, t_call in plan_parts(L["messages"], args):
                    va, vb = a + off - pad, b + off + pad
                    if vb <= 0 or va >= dur:
                        continue
                    va, vb = max(0.0, va), min(dur, vb)
                    dst = clip_dest(out_dir, names, title, t_call + off, ext)
                    if dst.exists() and not args.overwrite:
                        continue
                    say(f"    {fmt_dur(t_call + off)}  {'+'.join(names)}  (demo {fmt_dur(t_call)})")
                    ok_cut = (cut_span(ffmpeg, f, va, vb - va, dst, enc, None, 0.0, ext, cover_marker=False)
                              if args.obs_reencode
                              else cut_copy(ffmpeg, f, va, vb - va, dst))
                    if ok_cut:
                        clips.append(dst)
                        add_to_index(args, dst, source="obs", origin=f.name, category=clip_category(names),
                                     labels=[display(x) for x in names], t_call=t_call + off,
                                     check=("timed by the clocks only" if L["time_only"]
                                            else f"linked to {r['demo']}, {L['matched']} calls line up"),
                                     warn=L["time_only"], timing="clock" if L["time_only"] else "demo")
            say(f"  {len(clips)} clip(s) saved" + (f" in {out_dir}" if clips else "")
                + ("" if clips else "  (the linked demo has nothing that makes a clip)"))
            n_clips += len(clips)
            n_done += 1
            with open(done_file, "a", encoding="utf-8") as fh:
                fh.write(f"{key}\tdone\t{time.time():.0f}\n")
            continue
        if during:
            say("    could not line the recording up with " + ("that demo" if len(during) == 1 else "those demos")
                + " yet; it is tried again automatically after new scans. Clips can also be made from the "
                  "demo itself (option 5).")
        hits: list = []
        for tr, (h, _heard) in per_track.items():
            for t, n, z in h:
                if z < 5.5:
                    continue  # 4.5 was only for lining up with a demo
                # cross-check: another track that clearly hears a different call here, and not
                # this one, means this track mistook that call (e.g. 'dominating' for 'ultrakill')
                contradicted = any(
                    any(abs(t - t2) < 1.5 and n2 != n and z2 >= z for t2, n2, z2 in heard_b)
                    and not any(abs(t - t2) < 2.0 and n2 == n for t2, n2, _ in heard_b)
                    for tb, (_hb, heard_b) in per_track.items() if tb != tr)
                if contradicted:
                    continue
                if not any(abs(t - t2) < 2.0 for t2, _, _ in hits):
                    hits.append((t, n, z))
        for t, n, z in sorted(hits):
            say(f"    {fmt_dur(t)}  {n}  (score {z:.0f})")
        clips = make_clips(ffmpeg, f, f.stem, f.name, hits, args, enc, out_dir, ext, copy=not args.obs_reencode,
                           source="obs")
        say(f"  {len(clips)} clip(s) saved" + (f" in {out_dir}" if clips else ""))
        n_clips += len(clips)
        n_done += 1
        with open(done_file, "a", encoding="utf-8") as fh:
            fh.write(f"{key}\t{'retry' if during else 'done'}\t{time.time():.0f}\n")
    say(f"OBS link finished: {n_done} recording(s) scanned, {n_clips} clip(s).")
    if n_clips:
        offer_review(args)
    return 0


def clips_done_file(args) -> Path:
    # Demobuild: "done.txt" (an older "processed.txt" also listed demos that were only skipped)
    return clip_dirs(args.out)["ledgers"] / ("done.txt" if SANDBOX else "processed.txt")


def is_done(d: Path, args) -> bool:
    if SANDBOX and args.clips_only and getattr(args, "scan_first", False) and not getattr(args, "whole_demo", False):
        return False  # decided per part: a part is done when its clip exists
    if getattr(args, "scan", False):
        return (args.out / "scans" / (d.stem + ".json")).exists()
    if args.clips_only:
        f = clips_done_file(args)
        return f.exists() and d.name in f.read_text(encoding="utf-8").splitlines()
    return (args.out / (d.stem + "." + args.format)).exists()


def mux(ffmpeg: str, video: Path, audio: Path | None, offset: float, out: Path, fmt: str) -> None:
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video)]
    if audio is not None:
        if offset >= 0:          # audio started after the video: delay it
            cmd += ["-itsoffset", f"{offset:.3f}", "-i", str(audio)]
        else:                    # audio started first: skip its head
            cmd += ["-ss", f"{-offset:.3f}", "-i", str(audio)]
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ac", "2"]
    else:
        cmd += ["-map", "0:v:0", "-c:v", "copy"]
    if fmt == "mp4":
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(out))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed: {r.stderr.strip()[-800:]}")


# --------------------------------------------------------------------------------------
# Demo end detection
# --------------------------------------------------------------------------------------

def file_is_locked(p: Path) -> bool:
    """UT keeps the demo open while playing it; Windows then refuses a rename."""
    if not p.exists():
        return False
    probe = p.with_name(p.name + ".probe")
    try:
        os.replace(p, probe)
        os.replace(probe, p)
        return False
    except PermissionError:
        return True
    except OSError:
        return True


class LogWatcher:
    def __init__(self, paths: list[Path]) -> None:
        self.paths = paths
        self.pos: dict[Path, int] = {}
        self.lines: list[str] = []

    def poll(self) -> list[str]:
        new: list[str] = []
        for p in self.paths:
            try:
                size = p.stat().st_size
            except OSError:
                continue
            start = self.pos.get(p, 0)
            if size < start:
                start = 0
            if size > start:
                with open(p, "rb") as f:
                    f.seek(start)
                    data = f.read(size - start)
                self.pos[p] = size
                for raw in data.decode("latin-1", "replace").splitlines():
                    if raw.strip():
                        new.append(raw.strip())
        self.lines += new
        self.lines = self.lines[-400:]
        return new


def shutdown_ut(ut: subprocess.Popen, win: "Win", hwnd: int | None) -> None:
    """Close UT politely (avoids 'did not shut down properly' prompts), then force it."""
    if ut.poll() is not None:
        return
    if hwnd:
        try:
            win.close(hwnd)
            ut.wait(timeout=15)
            return
        except Exception:
            pass
    ut.kill()
    try:
        ut.wait(timeout=15)
    except Exception:
        pass


# --------------------------------------------------------------------------------------
# Main per-demo routine
# --------------------------------------------------------------------------------------

MARKER = 16  # size of the add-on's corner square in pixels (UT2VidConsole.UVDrawMarker)


def marker_frames(ffmpeg: str, video: Path) -> list[tuple[float, float, float, float]]:
    """[(time, Y, U, V)] of the add-on's corner square for every frame of the recording."""
    cmd = [ffmpeg, "-hide_banner", "-nostats", "-i", str(video), "-an", "-sn",
           "-vf", f"crop={MARKER // 2}:{MARKER // 2}:{MARKER // 4}:{MARKER // 4},showinfo", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        return []
    out = []
    for line in r.stderr.splitlines():
        m = re.search(r"pts_time:\s*([-\d.]+).*?mean:\[(\d+) (\d+) (\d+)\]", line)
        if m:
            out.append(tuple(float(x) for x in m.groups()))
    return out


def marker_runs(ffmpeg: str, video: Path, version: int = 16,
                frames: list | None = None) -> list[tuple[float, float, bool]]:
    """Video stretches that are parts, from the add-on's corner square: [(start, end, closed)].
    Hook 16+: the square is magenta whenever NO part plays, so a part is a stretch without it
    between two stretches with it (closed=False: the video ended before the square came back).
    Older hooks: the square is green during a part. Frame exact, unlike log timing."""
    frames = frames if frames is not None else marker_frames(ffmpeg, video)
    if not frames:
        return []
    if version >= 16:
        flag = [(t, u > 160 and v > 160) for t, _y, u, v in frames]       # magenta: U and V high
    else:
        flag = [(t, y > 80 and u < 115 and v < 105) for t, y, u, v in frames]  # green
    # ignore single odd frames (a frame that is half drawn, a HUD line passing the corner)
    clean = []
    for i, (t, f) in enumerate(flag):
        prev_f = flag[i - 1][1] if i else f
        next_f = flag[i + 1][1] if i + 1 < len(flag) else f
        clean.append((t, prev_f if prev_f == next_f and prev_f != f else f))
    step = 1 / 60
    runs: list[list] = []
    want = (lambda f: not f) if version >= 16 else (lambda f: f)
    seen_marker = version < 16
    for i, (t, f) in enumerate(clean):
        if i + 1 < len(clean):
            step = max(0.001, clean[i + 1][0] - t)
        if version >= 16 and f:
            seen_marker = True
            if runs and not runs[-1][2]:
                runs[-1][2] = True  # the square came back: this part is closed
            continue
        if not seen_marker or not want(f):
            continue
        if runs and not runs[-1][2]:
            runs[-1][1] = t + step
        elif version < 16 and runs and t - runs[-1][1] <= 0.25:
            runs[-1][1] = t + step
        else:
            runs.append([t, t + step, version < 16])
    return [(a, b, c) for a, b, c in runs if b - a >= 1.0]


def match_runs(runs: list[tuple[float, float, bool]], durations: list[float]) -> list[tuple[float, float] | None]:
    """Pair video stretches with parts, in order, by length (a part of d demo seconds is d seconds
    of video at 1x). A part without a fitting stretch gets None (then only that part uses log timing).
    An unclosed last stretch (video ended) is cut to the part's length."""
    out: list[tuple[float, float] | None] = [None] * len(durations)
    j = 0
    for i, d in enumerate(durations):
        for k in range(j, len(runs)):
            a, b, closed = runs[k]
            length = b - a
            if not closed and length > d:
                b, length = a + d, d
            if abs(length - d) <= max(1.5, 0.1 * d):
                out[i], j = (a, b), k + 1
                break
    return out


def smooth_fps(ffmpeg: str, clip: Path) -> float | None:
    """Distinct frames per second in a clip (frames that repeat the previous one are not counted).
    Low values mean UT itself drew few frames while recording: the clip looks choppy."""
    dur = media_duration(ffmpeg, clip)
    if not dur:
        return None
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(clip), "-an", "-vf", "mpdecimate", "-f", "null", "-"],
                       capture_output=True, text=True, errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    m = re.findall(r"frame=\s*(\d+)", r.stderr)
    return int(m[-1]) / dur if m else None


def check_clip(ffmpeg: str, clip: Path, tpl: dict, expected: list[tuple[float, str]]) -> tuple[int, int, list]:
    """Listen for the announcer calls the demo says are in the clip, each only around the moment it
    should play (+-1.5 s). Returns (heard, checkable, [(expected time, call, found time or None)])."""
    import numpy as np
    exp = [(t, c) for t, c in expected if c in tpl]
    if not exp:
        return 0, 0, []
    r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(clip), "-map", "0:a:0", "-ac", "1",
                        "-ar", str(KILL_SR), "-f", "s16le", "-"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    sig = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768
    if len(sig) < KILL_SR * 2:
        return 0, len(exp), [(t, c, None) for t, c in exp]
    det = KillDetector(sig)
    res, heard = [], 0
    for t, c in exp:
        z = det.zscores(tpl[c])
        j0, j1 = max(0, int((t - 1.5) * KILL_SR / KILL_HOP)), int((t + 1.5) * KILL_SR / KILL_HOP)
        seg = z[j0:j1]
        if len(seg) and float(seg.max()) >= 3.5:
            heard += 1
            res.append((t, c, (j0 + int(seg.argmax())) * KILL_HOP / KILL_SR))
        else:
            res.append((t, c, None))
    return heard, len(exp), res


def cut_parts(ffmpeg: str, video: Path, audio: Path | None, audio_offset: float, parts, seen,
              video_epoch: float, demo: Path, args, enc_args, tpl: dict | None = None) -> list[Path]:
    """Cut each recorded part out of the recording. Where each part is in the video comes from the
    add-on's corner marker (green while a part plays). Only if that cannot be read, the log is used:
    'SEGMENT START n t=..' / 'SEGMENT END n t=..' with the smallest 'wall clock minus demo time'
    (log lines can arrive seconds late, so that is a few seconds off at worst)."""
    clip_dir = clip_dirs(args.out)["clips"]
    out = []
    player = demo_player(demo.name)
    events = []
    version = max([int(m.group(1)) for _w, l in seen for m in [re.search(r"SCAN START .*version=(\d+)", l)] if m]
                  or [15])
    # 1. what the log says about each part: demo start/end, log-timed video position, live messages
    info: dict[int, dict] = {}
    for n in range(len(parts)):
        i_start = next((i for i, (_w, l) in enumerate(seen) if f"UT2VID SEGMENT START n={n} " in l), None)
        if i_start is None:
            continue
        i_end = next((i for i, (_w, l) in enumerate(seen) if i > i_start and
                      (f"UT2VID SEGMENT END n={n} " in l or "UT2VID SEEK " in l or "SCAN END" in l)), len(seen))
        t_s = float(re.search(r" t=([-\d.]+)", seen[i_start][1]).group(1))
        anchors, t_e, live = [], t_s, []
        for w, l in seen[i_start:i_end + 1]:
            m = re.search(r"UT2VID (?:MSG|PROGRESS|SEGMENT (?:START|END) n=\d+) t=([-\d.]+)", l)
            if m and float(m.group(1)) >= t_s - 0.01:
                t = float(m.group(1))
                anchors.append((t, w - t))
                t_e = max(t_e, t)
            if "UT2VID MSG" in l:
                live += parse_scan_log(l, player)["messages"]
        if anchors:
            info[n] = {"t_s": t_s, "t_e": t_e, "anchors": anchors, "live": live}
    # 2. where each part is in the video: the corner marker, matched per part
    started = sorted(info)
    runs = marker_runs(ffmpeg, video, version)
    matched = match_runs(runs, [info[n]["t_e"] - info[n]["t_s"] for n in started])
    pos = {n: r for n, r in zip(started, matched) if r}
    if started and len(pos) == len(started):
        say(f"  corner marker found for all {len(started)} part(s): frame exact cuts")
    elif started:
        say(f"  WARNING: corner marker matched {len(pos)} of {len(started)} part(s) ({len(runs)} stretch(es) seen); "
            "the others use log timing (can be a few seconds off)")
    for n, (a, b, names, t_call) in enumerate(parts):
        if n not in info:
            if not any(f"UT2VID SEGMENT START n={n} " in l for _w, l in seen):
                say(f"  part {n + 1}: the jump to {fmt_dur(a)} did not happen (see the UT log); skipped")
            continue
        t_s, t_e, anchors, live = info[n]["t_s"], info[n]["t_e"], info[n]["anchors"], info[n]["live"]
        live = [x for x in refresh_calls(live, player, getattr(args, "speeds", {}).get(demo.name))
                if x["own"] and x["call"]]
        if n in pos:
            va, vb = pos[n]
            if version >= 16:
                va, vb = va + 0.02, vb - 0.02   # stay clear of the frames where the square comes and goes
            length = vb - va
            if abs(length - (t_e - t_s)) > 1.5:
                say(f"  part {n + 1}: NOTE {length:.1f}s of video for {t_e - t_s:.1f}s of demo "
                    f"(playback {(t_e - t_s) / max(length, 0.1):.2f}x)")
        else:
            va = t_s + min(o for _t, o in anchors) - video_epoch
            length = t_e - t_s
        if va < 0:
            length += va
            va = 0.0
        if length < 3:
            say(f"  part {n + 1}: too short to keep ({length:.1f}s)")
            continue
        got = [x["call"] for x in live if any(c and re.search(args.clip_on, c, re.I) for c in (x["call"], x.get("alt_call")))
               or x["call"] in MULTI_PLUS]
        label = "+".join(dict.fromkeys(names))
        say(f"  part {n + 1}: demo {fmt_dur(t_s)}-{fmt_dur(t_e)} -> {label}"
            + (f"  (seen while recording: {', '.join(got)})" if got else "  (call not seen again while recording)"))
        dst = part_clip_path(demo, (a, b, names, t_call), args)
        if cut_span(ffmpeg, video, va, length, dst, enc_args, audio, audio_offset, args.format,
                    cover_marker=version < 16 or n not in pos):
            out.append(dst)
            with open(parts_ledger(args), "a", encoding="utf-8") as fl:
                fl.write(f"{demo.name}\t{t_s:.2f}\t{t_e:.2f}\t{label}\t{dst.name}\n")
            # quality check: are the announcer calls where they belong, and is the picture smooth?
            verdict = []
            if tpl:
                heard, total, detail = check_clip(ffmpeg, dst, tpl, [(x["t"] - t_s, x["call"]) for x in live])
                if total:
                    verdict.append(f"calls heard at the right moment {heard}/{total}")
                    if heard * 2 < total:
                        verdict.append("CHECK: most calls not heard where expected, the cut may be off")
            fps = smooth_fps(ffmpeg, dst)
            if fps is not None:
                verdict.append(f"{fps:.0f} distinct fps")
                if fps < 40:
                    verdict.append("CHECK: choppy (UT drew few frames)")
            if verdict:
                say(f"    check: {'; '.join(verdict)}")
                with open(ledger_dir(args) / "check.txt", "a", encoding="utf-8") as fc:
                    fc.write(f"{dst.name}\t{'; '.join(verdict)}\n")
            add_to_index(args, dst, source="demo", origin=demo.name, category=clip_category(names),
                         labels=[display(x) for x in names], t_call=t_call, part=[t_s, t_e],
                         check="; ".join(verdict), warn=any(v.startswith("CHECK") for v in verdict),
                         timing="marker" if n in pos else "log")
            events.append(f"{demo.name}\t{fmt_dur(t_call)}\t{label}\tgame message, part {fmt_dur(t_s)}-{fmt_dur(t_e)}")
    if events:
        clip_dir.mkdir(parents=True, exist_ok=True)
        with open(ledger_dir(args) / "events.txt", "a", encoding="utf-8") as f:
            f.write("\n".join(events) + "\n")
    return out


def cut_span(ffmpeg: str, video: Path, a: float, length: float, dst: Path, enc_args, audio: Path | None,
             audio_offset: float, ext: str, cover_marker: bool = True) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{a:.3f}", "-i", str(video)]
    if audio is not None:
        a_aud = a - audio_offset
        if a_aud >= 0:
            cmd += ["-ss", f"{a_aud:.3f}", "-i", str(audio)]
        else:
            cmd += ["-itsoffset", f"{-a_aud:.3f}", "-i", str(audio)]
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a?"]
    # cover the add-on's corner marker
    cmd += ["-t", f"{length:.3f}"]
    if cover_marker:
        cmd += ["-vf", f"drawbox=x=0:y=0:w={MARKER + 4}:h={MARKER + 4}:color=black:t=fill"]
    cmd += [*enc_args, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
    if audio is not None:
        cmd += ["-ac", "2"]
    if ext == "mp4":
        cmd += ["-movflags", "+faststart"]
    r = subprocess.run(cmd + [str(dst)], capture_output=True, text=True, errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        say(f"  clip failed: {r.stderr.strip()[-300:]}")
    return r.returncode == 0


def choose_hits(ffmpeg: str, media: Path, tpl: dict, args, offset: float, seen, video_epoch: float, demo: Path):
    """Clip moments. With the UT2VidHook add-on the game's own HUD messages decide (exact, no
    look-alikes); the sound detection still runs and anything it hears that has no game message
    is listed (and clipped too with --also-audio). Without the add-on: the sound detection."""
    say("  looking for Mega Kill and higher, Unstoppable, Godlike, Wicked Sick ...")
    heard = find_kills(ffmpeg, media, tpl, args.clip_on, offset=offset) if media is not None else []
    if not args.hook:
        return heard
    spd = getattr(args, "speeds", {}).get(demo.name)
    if spd is None:  # whole-demo recording: the speed the scan measured, else the usual one
        r = load_scan(demo, args)
        spd = scan_speed(r, args)[0] if r else default_game_speed(args)
    wanted, calls, msgs, ok = hook_calls(seen, video_epoch, args.clip_on, demo_player(demo.name),
                                         getattr(args, "return_window", 15.0), spd,
                                         getattr(args, "capture_window", 20.0))
    if not ok:
        say("    the add-on wrote no messages; using the sound detection only")
        return heard
    say("    game messages: " + (", ".join(f"{fmt_dur(t)} {c}" for t, c, _ in calls) or "no announcer calls for you"))
    with_msg = [t for t, m in msgs if m["call"]]
    extra = [h for h in heard if not any(abs(h[0] - t) < 3.0 for t in with_msg)]
    for t, n, z in extra:
        say(f"    heard {n} at {fmt_dur(t)} (score {z:.0f}) but the game showed no such message: "
            + ("clipped anyway (--also-audio)" if args.also_audio else "not clipped"))
    for t, n, _ in wanted:
        if not any(abs(t - h[0]) < 3.0 for h in heard):
            say(f"    {fmt_dur(t)} {n}: from the game message (the sound detection missed it)")
    return sorted(wanted + (extra if args.also_audio else []))


def convert_one(demo: Path, args, ut_exe: Path, sysdir: Path, extra_dirs: list[Path],
                ffmpeg: str, enc_args: list[str], win: Win, res: tuple[int, int]) -> bool:
    out_dir: Path = args.out
    final = out_dir / (demo.stem + "." + args.format)
    work = out_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)
    vid_tmp, wav_tmp = work / (demo.stem + ".video.mkv"), work / (demo.stem + ".audio.wav")

    est = estimate_duration(demo)
    max_len = args.max_minutes * 60 if args.max_minutes else ((est * 1.25 + 180) if est else 60 * 60)
    mapname = map_from_filename(demo.name)
    parts = args.parts.get(demo.name) if args.hook else None
    if parts and len(parts) > 30:
        say(f"  {len(parts)} parts: recording the first 30 now, the rest on the next run")
        parts = parts[:30]
    if parts:
        max_len = sum(b - a for a, b, _, _ in parts) + 60 + 45 * len(parts)
    say(f"Demo: {demo.name}")
    say(f"  map {mapname or '?'}, estimated length {fmt_dur(est)}, hard stop after {fmt_dur(max_len)}")
    if parts:
        say(f"  recording only {len(parts)} part(s), {fmt_dur(sum(b - a for a, b, _, _ in parts))} in total: "
            + ", ".join(f"{fmt_dur(a)}-{fmt_dur(b)}" for a, b, _, _ in parts))
    stop_leftover_ut(sysdir.parent)
    if args.hook and args.ini_target is not None:
        text = args.ini_base
        if parts:
            for k, v in (("UVMode", "3"), ("UVProgressEvery", "1"), ("UVWait", "6"), ("UVSettle", f"{args.settle:g}"),
                         ("UVSegments", ",".join(f"{a:.2f}:{b:.2f}" for a, b, _, _ in parts))):
                text = set_ini_value(text, HOOK_CONSOLE, k, v)
        args.ini_target.write_text(text, encoding="latin-1")

    # 1. stage demo + exec file + log locations
    demo_copies = []
    for d in [sysdir] + extra_dirs:
        try:
            shutil.copyfile(demo, d / TMP_DEMO)
            demo_copies.append(d / TMP_DEMO)
        except OSError as e:
            say(f"  note: could not copy demo into {d}: {e}")
    if not demo_copies:
        say("  ERROR: could not place the demo in UT's System folder (permissions?).")
        return False
    (sysdir / EXEC_FILE).write_text(f"DEMOPLAY {TMP_DEMO}\r\n", encoding="ascii")
    log_paths = [d / LOG_FILE for d in [sysdir] + extra_dirs]
    for lp in log_paths:
        try:
            lp.unlink()
        except OSError:
            pass

    rec_exe = (sandbox_exe(sysdir, "rec") if SANDBOX else None) or ut_exe
    cmd = [str(rec_exe), "Entry", f"exec={EXEC_FILE}", f"log={LOG_FILE}"]
    if args.ini_path:
        cmd.append(f"ini={args.ini_path}")
    if args.user_ini_path:
        cmd.append(f"userini={args.user_ini_path}")
    cmd += args.ut_args

    ut = None
    hwnd = None
    vcap: VideoCapture | None = None
    acap: LoopbackRecorder | None = None
    ok = False
    watcher = LogWatcher(log_paths)
    try:
        say("  starting Unreal Tournament")
        prev_fg = win.foreground() if args.background else 0
        ut = subprocess.Popen(cmd, cwd=str(sysdir))
        boost_process(ut.pid)

        # 2. wait for the game window and turn it into a borderless window at (0,0)
        t0w = time.time()
        while time.time() - t0w < 90 and ut.poll() is None:
            hwnd = win.game_window(ut.pid)
            if hwnd:
                break
            if time.time() - t0w > 25:  # fallback: largest window of the UT process
                wins = [h for h in win.windows_of_pid(ut.pid) if win.client_rect_on_screen(h)[2] >= 320]
                if wins:
                    hwnd = max(wins, key=lambda h: win.client_rect_on_screen(h)[2] * win.client_rect_on_screen(h)[3])
                    say(f"  using window class '{win.class_name(hwnd)}' "
                        f"(others: {', '.join(win.class_name(h) for h in win.windows_of_pid(ut.pid))})")
                    break
            time.sleep(0.5)
        if hwnd is None:
            say("  ERROR: UT window did not appear (or UT exited). Check the UT log.")
            return False
        time.sleep(2)
        win.make_borderless_at_origin(hwnd, *res, background=args.background)
        if args.background and prev_fg:
            win.u32.SetForegroundWindow(prev_fg)  # hand focus back to what the user was doing
        time.sleep(1)

        # 3. wait for the demo to start playing
        started, t_start_wait, last_probe = False, time.time(), 0.0
        while time.time() - t_start_wait < args.start_timeout and ut.poll() is None:
            new = watcher.poll()
            if any(re.search(p, l) for l in new for p in FAIL_PATTERNS):
                for l in watcher.lines[-12:]:
                    say(f"    log| {l}")
                say("  ERROR: UT reported a problem loading this demo (see log lines above).")
                return False
            if time.time() - last_probe > 2:
                last_probe = time.time()
                if any(file_is_locked(c) for c in demo_copies):
                    started = True
            if mapname and any(re.search(r"LoadMap:\s*" + re.escape(mapname), l, re.I) for l in new):
                started = True
            if started:
                break
            time.sleep(0.5)
        if not started:
            say("  WARNING: could not confirm playback started; recording anyway.")
        time.sleep(args.start_delay)
        seen = [(time.time(), l) for l in watcher.poll() if "UT2VID " in l]  # rest: before the recording
        hwnd = win.game_window(ut.pid) or hwnd
        win.make_borderless_at_origin(hwnd, *res, background=args.background)
        if args.background and prev_fg:
            win.u32.SetForegroundWindow(prev_fg)
        time.sleep(0.5)
        rect = win.client_rect_on_screen(hwnd)
        if rect[2] < 320 or rect[3] < 200:
            say(f"  ERROR: the UT window is {rect[2]}x{rect[3]}, nothing sensible to record.")
            return False
        say(f"  recording {rect[2]}x{rect[3]} at ({rect[0]},{rect[1]}), {args.fps} fps")

        # 4. start capture
        if not args.no_audio:
            acap = LoopbackRecorder(wav_tmp, args.audio_device)
            acap.start()
            say(f"  sound from: {acap.device_name}")
        vcap = VideoCapture(ffmpeg, vid_tmp, rect, args.fps, enc_args,
                            hwnd=hwnd if args.window_capture else None)
        vcap.start()
        t_rec = time.time()

        # 5. wait for the end
        held_since = time.time() if any(file_is_locked(c) for c in demo_copies) else None
        reason = None
        last_status = 0.0
        last_check, pend = 0.0, []
        while reason is None:
            time.sleep(0.25)  # the add-on's log lines are timed by when they show up here
            if args.hook:
                fresh = watcher.poll()
                now = time.time()
                seen += [(now, l) for l in fresh if "UT2VID " in l]
                pend += fresh
                if any("UT2VID SCAN END" in l for l in fresh) and now - t_rec > 10:
                    reason = "the add-on saw the demo end"
                    break
                if any("UT2VID SEGMENTS DONE" in l for l in fresh):
                    reason = "all parts recorded"
                    break
            if time.time() - last_check < 1:
                continue
            last_check = time.time()
            new, pend = pend, []
            el = time.time() - t_rec
            if ut.poll() is not None:
                reason = "UT exited"
            elif not vcap.running():
                reason = "ffmpeg stopped unexpectedly"
            elif el > max_len:
                reason = "time limit reached"
            else:
                if not args.hook:
                    new = watcher.poll()
                if any(re.search(p, l) for l in new for p in END_PATTERNS) and el > 10:
                    reason = "log shows level change"
                locked = any(file_is_locked(c) for c in demo_copies)
                if locked and held_since is None:
                    held_since = time.time()
                if held_since and not locked and time.time() - held_since > 30:
                    reason = "UT released the demo file"
            if time.time() - last_status > 60:
                last_status = time.time()
                say(f"  ... {fmt_dur(el)} recorded" + (f" of ~{fmt_dur(est)}" if est else ""))
        rec_secs = time.time() - t_rec
        say(f"  end detected: {reason} after {fmt_dur(rec_secs)}")
        stopped_early = reason in ("UT exited", "ffmpeg stopped unexpectedly") and not parts and \
            bool(est) and rec_secs < 0.8 * est
        time.sleep(args.tail)
        seen += [(time.time(), l) for l in watcher.poll() if "UT2VID " in l]
        video_epoch = vcap.start_epoch or t_rec

        # 6. stop everything
        vcap.stop()
        if acap:
            acap.stop()
        shutdown_ut(ut, win, hwnd)
        if not vid_tmp.exists() or vid_tmp.stat().st_size < 10_000:
            say("  ERROR: no video was produced. ffmpeg said:")
            for l in vcap.stderr_tail:
                say(f"    ffmpeg| {l}")
            return False
        audio = None
        offset = 0.0
        if acap and acap.error is None and wav_tmp.exists():
            audio = wav_tmp
            if vcap.start_epoch and acap.start_epoch:
                offset = acap.start_epoch - vcap.start_epoch + args.av_offset / 1000
            else:
                offset = args.av_offset / 1000
        elif acap and acap.error:
            say(f"  WARNING: {acap.error}  (video will have no sound)")
        say(f"  muxing (audio offset {offset:+.3f}s) -> {final.name}")
        if parts and (args.clips_only or args.clips):
            clips = cut_parts(ffmpeg, vid_tmp, audio, offset, parts, seen, video_epoch, demo, args,
                              clip_encoder_args(enc_args, args.clip_quality),
                              demo_templates(args.templates, sysdir.parent, demo) if args.templates else None)
            say(f"  {len(clips)} of {len(parts)} part(s) saved" + (f" in {clips[0].parent}" if clips else ""))
            ok = True
            if len(clips) == len(parts):
                f = clips_done_file(args)
                f.parent.mkdir(parents=True, exist_ok=True)
                with open(f, "a", encoding="utf-8") as fh:
                    fh.write(demo.name + "\n")
            else:
                say("  not every part made it; this demo is tried again on the next run")
            if not args.keep_work:
                for f in (vid_tmp, wav_tmp):
                    try:
                        f.unlink()
                    except OSError:
                        pass
            say("  done (parts only)")
            return True
        if args.clips_only and audio is not None:
            # Only clips wanted: detect on the recorded sound and cut straight from the
            # recording, skipping the minutes-long join of the full video.
            tpl = demo_templates(args.templates, sysdir.parent, demo)
            hits = choose_hits(ffmpeg, wav_tmp, tpl, args, offset, seen, video_epoch, demo)
            for t, name, z in hits:
                say(f"    {fmt_dur(t)}  {name}  " + ("(game message)" if z < 0 else f"(score {z:.0f})"))
            clips = make_clips(ffmpeg, vid_tmp, demo.stem, demo.name, hits, args,
                               clip_encoder_args(enc_args, args.clip_quality), clip_dirs(args.out)["clips"],
                               args.format, audio=wav_tmp, audio_offset=offset)
            say(f"  {len(clips)} clip(s) saved" + (f" in {clips[0].parent}" if clips else ""))
            ok = True
            if stopped_early:
                say("  the recording stopped early; this demo is tried again on the next run")
            else:
                f = clips_done_file(args)
                f.parent.mkdir(parents=True, exist_ok=True)
                with open(f, "a", encoding="utf-8") as fh:
                    fh.write(demo.name + "\n")
            if not args.keep_work:
                for f in (vid_tmp, wav_tmp):
                    try:
                        f.unlink()
                    except OSError:
                        pass
            say("  done (clips only)")
            return True
        mux(ffmpeg, vid_tmp, audio, offset, final, args.format)
        ok = True
        if not args.keep_work:
            for f in (vid_tmp, wav_tmp):
                try:
                    f.unlink()
                except OSError:
                    pass
        if args.clips or args.clips_only:
            if audio is None and not args.hook:
                say("  no sound recorded, so kills cannot be detected")
            else:
                tpl = demo_templates(args.templates, sysdir.parent, demo)
                hits = choose_hits(ffmpeg, final if audio is not None else None, tpl, args, 0.0, seen, video_epoch, demo)
                for t, name, z in hits:
                    say(f"    {fmt_dur(t)}  {name}  " + ("(game message)" if z < 0 else f"(score {z:.0f})"))
                clips = make_clips(ffmpeg, final, demo.stem, demo.name, hits, args,
                                   clip_encoder_args(enc_args, args.clip_quality), clip_dirs(args.out)["clips"], args.format)
                say(f"  {len(clips)} clip(s) saved" + (f" in {clips[0].parent}" if clips else ""))
            if args.clips_only:
                f = clips_done_file(args)
                f.parent.mkdir(parents=True, exist_ok=True)
                with open(f, "a", encoding="utf-8") as fh:
                    fh.write(demo.name + "\n")
                try:
                    final.unlink()  # full video not wanted
                except OSError:
                    pass
                say("  done (clips only, full video removed)")
                return True
        say(f"  done: {final}")
        return True
    finally:
        if vcap and vcap.running():
            vcap.stop()
        if acap and acap.thread.is_alive():
            acap.stop()
        if ut and ut.poll() is None:
            shutdown_ut(ut, win, hwnd)
        for c in demo_copies:
            for _ in range(10):
                try:
                    c.unlink()
                    break
                except OSError:
                    time.sleep(0.5)
        if not ok:
            for l in watcher.lines[-8:]:
                say(f"    log| {l}")


# --------------------------------------------------------------------------------------

def parse_selection(text: str, count: int) -> list[int] | None:
    """'1 3 5-7' / '2,4' / 'all' -> zero-based indexes, None when invalid."""
    text = text.strip().lower()
    if text in ("all", "a", "*"):
        return list(range(count))
    picked: list[int] = []
    for part in re.split(r"[\s,;]+", text):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            return None
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        if lo < 1 or hi > count or lo > hi:
            return None
        picked += [i - 1 for i in range(lo, hi + 1) if i - 1 not in picked]
    return picked or None


REVIEW_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Kill clips review</title>
<style>
:root{--bg:#111318;--card:#1b1e26;--line:#2a2f3a;--txt:#e8e8ea;--dim:#9aa0ab;--acc:#e0a526;--bad:#e5534b;--ok:#3fb950}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.4 system-ui,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:2;background:#0c0e12ee;border-bottom:1px solid var(--line);padding:12px 20px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
h1{font-size:17px;margin:0 16px 0 0}button,select{background:var(--card);color:var(--txt);border:1px solid var(--line);border-radius:6px;padding:6px 10px;font:inherit;cursor:pointer}
button.on{border-color:var(--acc);color:var(--acc)}#count{color:var(--dim);margin-left:auto}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:14px;padding:16px 20px}
.c{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.c.kept{border-color:var(--ok)}.c.rejected{opacity:.45}
video{width:100%;aspect-ratio:16/9;background:#000;display:block}
.b{padding:10px 12px;display:flex;flex-direction:column;gap:4px}.t{font-weight:600}.cat{color:var(--acc);font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.m{color:var(--dim);font-size:12px;word-break:break-all}.w{color:var(--bad);font-size:12px}.q{color:var(--dim);font-size:12px}
.a{display:flex;gap:8px;padding:0 12px 12px}.a button{flex:1}.keep:hover{border-color:var(--ok)}.rej:hover{border-color:var(--bad)}
.empty{padding:40px;color:var(--dim)}
</style></head><body>
<header><h1>Kill clips</h1><span id="filters"></span>
<select id="when"><option value="new">This run</option><option value="all">All clips</option></select>
<select id="state"><option value="open">Not rejected</option><option value="all">Incl. rejected</option><option value="warn">Only with a warning</option></select>
<span id="count"></span></header><main id="grid"></main>
<script>
const TOKEN="__TOKEN__", RUN="__RUN__"; let items=__ITEMS__; let cat="All";
const el=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e};
function post(p,b){return fetch(p,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...b,token:TOKEN})}).then(r=>r.json())}
function shown(){const w=document.getElementById("when").value,s=document.getElementById("state").value;
 return items.filter(x=>(w=="all"||x.run==RUN)&&(cat=="All"||x.category==cat)&&(s=="all"||(s=="warn"?x.warn&&x.status!="rejected":x.status!="rejected")))}
function filters(){const f=document.getElementById("filters");f.innerHTML="";const cats=["All",...new Set(items.map(x=>x.category))].sort((a,b)=>a=="All"?-1:a.localeCompare(b));
 for(const c of cats){const b=el("button",c==cat?"on":"",c);b.onclick=()=>{cat=c;draw()};f.append(b)}}
function draw(){filters();const g=document.getElementById("grid");g.innerHTML="";const list=shown();
 document.getElementById("count").textContent=list.length+" clip(s)";
 if(!list.length){g.append(el("div","empty","Nothing here. Try 'All clips' or another filter."));return}
 for(const x of list){const c=el("div","c "+(x.status||""));const v=el("video");v.controls=true;v.preload="metadata";v.src="/media/"+x.id;
  const b=el("div","b");b.append(el("div","cat",x.category),el("div","t",(x.labels||[]).join(" + ")),el("div","m",x.origin+" @ "+x.stamp+"  ("+x.source+")"));
  if(x.check)b.append(el("div",x.warn?"w":"q",x.check));
  const a=el("div","a");const k=el("button","keep",x.status=="kept"?"Kept":"Keep");const r=el("button","rej",x.status=="rejected"?"Restore":"Reject");const o=el("button","",x.playable?"Folder":"Open");
  k.onclick=()=>post("/api/status",{id:x.id,status:"kept"}).then(j=>{if(j.ok){x.status="kept";draw()}});
  r.onclick=()=>post("/api/status",{id:x.id,status:x.status=="rejected"?"new":"rejected"}).then(j=>{if(j.ok){x.status=j.status;draw()}else alert(j.error)});
  o.onclick=()=>post("/api/open",{id:x.id,play:!x.playable});a.append(k,r,o);c.append(v,b,a);g.append(c)}}
document.getElementById("when").onchange=draw;document.getElementById("state").onchange=draw;
if(!items.some(x=>x.run==RUN))document.getElementById("when").value="all";draw();
</script></body></html>"""


class ClipStore:
    """The clips listed in <out>/clip_index.json, for the review page and the GUI: where each clip
    is, keep / reject (rejected clips move to <out>/rejected, 'new' moves them back), open."""

    def __init__(self, out: Path) -> None:
        import json
        self.out = out.resolve()
        dirs = clip_dirs(out)
        self.base, self.rej = dirs["base"].resolve(), dirs["rejected"].resolve()
        self.idx = index_file(types_ns(out=out))
        self.lock = threading.Lock()
        try:
            items = json.loads(self.idx.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            items = []
        self.items = [x for x in items if self.path_of(x).exists() or self.rejected_path(x).exists()]
        if len(self.items) < len(items):  # clips deleted outside the app: forget them for good
            try:  # read again just before writing, so a clip a running job just added is kept
                fresh = json.loads(self.idx.read_text(encoding="utf-8"))
                fresh = [x for x in fresh if self.path_of(x).exists() or self.rejected_path(x).exists()]
                tmp = self.idx.with_suffix(".tmp")
                tmp.write_text(json.dumps(fresh, indent=1), encoding="utf-8")
                os.replace(tmp, self.idx)
            except (OSError, ValueError):
                pass
        for i, x in enumerate(self.items):
            x["id"] = i
            x["stamp"] = stamp_of(x.get("t_call") or 0)
            x["playable"] = Path(x["file"]).suffix.lower() in (".mp4", ".m4v", ".mov", ".webm")

    def path_of(self, x) -> Path:
        p = Path(x["file"])
        return p if p.is_absolute() else self.base / p

    def rejected_path(self, x) -> Path:
        p = Path(x["file"])
        return self.rej / (p.name if p.is_absolute() else p)

    def file_of(self, i: int) -> Path:
        x = self.items[i]
        return self.path_of(x) if self.path_of(x).exists() else self.rejected_path(x)

    def save(self) -> None:
        import json
        keep = [{k: v for k, v in x.items() if k not in ("id", "stamp", "playable")} for x in self.items]
        tmp = self.idx.with_suffix(".tmp")
        tmp.write_text(json.dumps(keep, indent=1), encoding="utf-8")
        os.replace(tmp, self.idx)

    def set_status(self, i: int, want) -> tuple[bool, str]:
        if want not in ("new", "kept", "rejected") or not 0 <= i < len(self.items):
            return False, "bad request"
        with self.lock:
            x = self.items[i]
            src, dst = (self.path_of(x), self.rejected_path(x)) if want == "rejected" else \
                (self.rejected_path(x), self.path_of(x))
            if want != "kept" and src.exists() and src != dst:
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(src, dst)
                except OSError as e:
                    return False, f"could not move the clip (is it open in a player?): {e}"
            x["status"] = want
            self.save()
        return True, want

    def open(self, i: int, play: bool) -> None:
        f = self.file_of(i)
        try:
            if IS_WINDOWS and play:
                os.startfile(str(f))  # noqa: the default video player
            elif IS_WINDOWS:
                subprocess.Popen(["explorer", "/select,", str(f)])
        except OSError:
            pass


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


def review_server(args, wait: bool = True) -> int:
    """Local review page (http://127.0.0.1 only) for the clips in clip_index.json: watch them, keep
    them, or reject them (rejected clips are moved to <out>/rejected, Restore puts them back)."""
    import hmac
    import json
    import secrets
    import webbrowser
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    store = ClipStore(args.out)
    items = store.items
    token = secrets.token_hex(16)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not local_request_ok(self.headers):
                self.send_error(403)
                return
            if self.path in ("/", "/index.html"):
                page = (REVIEW_HTML.replace("__TOKEN__", token).replace("__RUN__", RUN_ID)
                        .replace("__ITEMS__", json.dumps(items).replace("</", "<\\/")))
                data = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            m = re.fullmatch(r"/media/(\d+)", self.path)
            if not m or int(m.group(1)) >= len(items):
                self.send_error(404)
                return
            f = store.file_of(int(m.group(1)))
            try:
                size = f.stat().st_size
            except OSError:
                self.send_error(404)
                return
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
            ctype = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/mp4", ".webm": "video/webm",
                     ".mkv": "video/x-matroska"}.get(f.suffix.lower(), "application/octet-stream")
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            try:
                with open(f, "rb") as fh:
                    fh.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = fh.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (ConnectionError, OSError):
                pass

        def do_POST(self):
            if not local_request_ok(self.headers):
                self.send_error(403)
                return
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 1 << 20)) or b"{}")
            except ValueError:
                body = {}
            if not hmac.compare_digest(str(body.get("token", "")), token) or not isinstance(body.get("id"), int) or not 0 <= body["id"] < len(items):
                self._json({"ok": False, "error": "refused"}, 403)
                return
            if self.path == "/api/status":
                ok, msg = store.set_status(body["id"], body.get("status"))
                self._json({"ok": ok, "status": msg} if ok else {"ok": False, "error": msg})
                return
            if self.path == "/api/open":
                store.open(body["id"], bool(body.get("play")))
                self._json({"ok": True})
                return
            self._json({"ok": False, "error": "unknown"}, 404)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    if not wait:
        return srv  # tests
    say(f"Review page: {url}  ({len(items)} clip(s); rejected clips go to {args.out / 'rejected'})")
    webbrowser.open(url)
    try:
        input("  Press Enter here when you are done reviewing ... ")
    except (EOFError, KeyboardInterrupt):
        pass
    srv.shutdown()
    return 0


def watch_demo(demo: Path, args, ut_dir: Path | None) -> int:
    """Play a demo in the game set up in Killcam '99, windowed, at 1x with sound (udemo's own default from the
    console plays some demos in slow motion). With --at: only around that moment, then UT closes."""
    if not (SANDBOX and ut_dir and IS_WINDOWS):
        say("PROBLEM: watching needs the game set up in Killcam '99, on Windows.")
        return 1
    if not demo.is_file():
        say(f"PROBLEM: demo not found: {demo}")
        return 1
    sysdir = ut_system_dir(ut_dir)
    shutil.copyfile(demo, sysdir / "ut2vid_tmp_watch.dem")
    (sysdir / "ut2vid_exec_watch.txt").write_text("DEMOPLAY ut2vid_tmp_watch.dem\r\n", encoding="ascii")
    w, h = Win().screen_size()
    w, h = max(1024, int(w * 0.75)) // 2 * 2, max(576, int(h * 0.75)) // 2 * 2
    text = patch_ini((sysdir / "UnrealTournament.ini").read_text(encoding="latin-1"), w, h, args.renderer)
    if hook_built(sysdir):
        text = hook_ini(text, mode=2, progress=60)
        if args.at is not None:
            a, b = max(0.0, args.at - 10), args.at + 12
            for k, v in (("UVMode", "3"), ("UVWait", "0.5"), ("UVSettle", "1"), ("UVSegments", f"{a:.2f}:{b:.2f}")):
                text = set_ini_value(text, HOOK_CONSOLE, k, v)
    (sysdir / "ut2vid_watch.ini").write_text(text, encoding="latin-1")
    cmd = [str(sandbox_exe(sysdir, "watch") or sysdir / "UnrealTournament.exe"), "Entry",
           "exec=ut2vid_exec_watch.txt", "log=ut2vid_watch.log",
           "ini=ut2vid_watch.ini"]
    subprocess.Popen(cmd, cwd=str(sysdir))
    say(f"Watching {demo.name}" + (f" around {fmt_dur(args.at)}" if args.at is not None else "")
        + ". Close the game window when you are done.")
    return 0


def offer_review(args) -> None:
    """After a batch that made clips: open the review page (only when someone is at the keyboard)."""
    if getattr(args, "no_review", False) or not sys.stdin or not sys.stdin.isatty():
        return
    review_server(args)


def settings_file() -> Path:
    if kc_config:
        return kc_config.settings_file()
    return (SANDBOX or Path(__file__).resolve().parent) / "settings.json"


def load_settings() -> dict:
    import json
    try:
        return json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(**kv) -> None:
    import json
    st = load_settings()
    st.update(kv)
    try:
        settings_file().write_text(json.dumps(st, indent=1), encoding="utf-8")
    except OSError:
        pass


def pick_folder(title: str, initial: Path | None) -> Path | None:
    """Explorer folder dialog (tkinter, part of Python; else PowerShell's), typed path as last resort.
    None when cancelled."""
    init = str(initial) if initial and initial.is_dir() else str(Path.home())
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        got = filedialog.askdirectory(title=title, initialdir=init, mustexist=True, parent=root)
        root.destroy()
        return Path(got) if got else None
    except Exception:
        pass
    if IS_WINDOWS:
        ps = ("Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; "
              f"$d.Description = '{title.replace(chr(39), chr(39) * 2)}'; $d.SelectedPath = '{init.replace(chr(39), chr(39) * 2)}'; "
              "$d.ShowNewFolderButton = $false; if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, text=True,
                               timeout=3600)
            if r.returncode == 0:
                return Path(r.stdout.strip()) if r.stdout.strip() else None
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        ans = input(f"{title} (Enter = {init}): ").strip().strip('"')
    except EOFError:
        return None
    return Path(ans or init)


def demo_overview(d: Path, args) -> tuple[str, str]:
    """(what the scan found worth a clip, status) for the demo picker."""
    r = load_scan(d, args)
    if not r or not r.get("end"):
        return "not scanned yet", ""
    refresh_calls(r["messages"], demo_player(d.name), scan_speed(r, args)[0])
    parts = plan_parts(r["messages"], args)
    if not parts:
        return "nothing", "nothing to clip"
    found = ", ".join(" + ".join(display(n) for n in names) for _a, _b, names, _t in parts)
    done = sum(1 for p in parts if part_done(d, p, args))
    return found, ("done" if done == len(parts) else f"{done} of {len(parts)} clipped" if done else "to do")


def pick_demos(playable: list[Path], args) -> list[Path]:
    """Choose demos: a sortable, searchable Windows grid (Out-GridView) with multi-select; the
    numbered console list when that is not available."""
    if not playable:
        say("No demo has all the files it needs, so there is nothing to pick.")
        return []
    rows = []
    for d in playable:
        st, _ex = demo_start_exact(d, scan_total(d))
        found, status = demo_overview(d, args)
        rows.append({"d": d, "when": dt.datetime.fromtimestamp(st).strftime("%Y-%m-%d %H:%M") if st else "?",
                     "map": demo_map(d, args) or "?", "len": fmt_dur(estimate_duration(d)), "found": found,
                     "status": status})
    rows.sort(key=lambda x: x["when"])
    if IS_WINDOWS and not getattr(args, "console_pick", False):
        chosen = grid_pick(rows)
        if chosen is not None:
            if chosen:
                say(f"Selected {len(chosen)} demo(s), about "
                    f"{fmt_dur(sum(estimate_duration(d) or 0 for d in chosen))} of playback.")
            return chosen
    print()
    print(f"  {'#':>3}  {'Recorded':<16}  {'Map':<24}  {'Length':>7}  {'Status':<14}  Found")
    print(f"  {'-' * 3}  {'-' * 16}  {'-' * 24}  {'-' * 7}  {'-' * 14}  -----")
    for i, x in enumerate(rows, 1):
        print(f"  {i:>3}  {x['when']:<16}  {x['map'][:24]:<24}  {x['len']:>7}  {x['status'][:14]:<14}  {x['found'][:60]}")
    print()
    while True:
        try:
            ans = input("Which demos? (e.g. 3  or  1,4  or  2-6  or  all; Enter = cancel): ")
        except EOFError:
            return []
        if not ans.strip():
            return []
        sel = parse_selection(ans, len(rows))
        if sel is not None:
            chosen = [rows[i]["d"] for i in sel]
            say(f"Selected {len(chosen)} demo(s), about {fmt_dur(sum(estimate_duration(d) or 0 for d in chosen))} of playback.")
            return chosen
        print("  Not understood, try again.")


def grid_pick(rows: list[dict]) -> list[Path] | None:
    """Out-GridView picker. Returns the chosen demos ([] = cancelled), None if the grid cannot open."""
    import csv
    import tempfile
    tmp = Path(tempfile.gettempdir()) / "ut2vid_pick.csv"
    try:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Nr", "Recorded", "Map", "Length", "Status", "Worth a clip (from the scan)", "File"])
            for i, x in enumerate(rows, 1):
                w.writerow([f"{i:03d}", x["when"], x["map"], x["len"], x["status"], x["found"], x["d"].name])
        ps = (f"$rows = Import-Csv -LiteralPath '{str(tmp).replace(chr(39), chr(39) * 2)}' -Encoding UTF8; "
              "$sel = $rows | Out-GridView -Title 'Pick demos: click, Ctrl+click or Shift+click, type to filter, then OK' "
              "-OutputMode Multiple; $sel | ForEach-Object { $_.Nr }")
        print("  The demo list opened in a separate window (it may be behind this one) ...")
        r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, text=True,
                           timeout=6 * 3600)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    if r.returncode != 0 or "is not recognized" in r.stderr or "Out-GridView" in r.stderr:
        return None
    nums = [int(x) for x in re.findall(r"\d+", r.stdout)]
    return [rows[n - 1]["d"] for n in nums if 1 <= n <= len(rows)]


def main() -> int:
    """Runs the tool. With a separate copy it also checks that no original UT folder changed
    meanwhile; with the player's own folder it removes its temporary files afterwards."""
    copy_mode = bool(kc_config and kc_config.setup_done() and kc_config.mode() == "copy")
    base = fingerprint(original_roots()) if copy_mode and IS_WINDOWS else None
    try:
        return _main()
    finally:
        if kc_config and kc_config.mode() == "direct" and kc_config.game():
            kc_config.clean_temp(kc_config.system_dir(kc_config.game()))
            u = user_system_dir()
            if u:
                kc_config.clean_temp(u)
        if base is not None:
            diff = audit_report(base, fingerprint(original_roots()))
            if diff:
                say(f"SEPARATION CHECK: {len(diff)} file(s) in your original UT folders changed during this run.")
                say("  (If you played UT yourself meanwhile, that explains it.) First ones:")
                for d in diff[:10]:
                    say(f"    {d}")
            else:
                say("SEPARATION CHECK: original UT folders unchanged.")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Convert UT99 .dem demos to video by playing them in UT and recording.")
    ap.add_argument("demos", nargs="*", help="demo files or folders (default: the folder this script is in)")
    ap.add_argument("--ut", help="UT install folder (auto-detected if omitted)")
    ap.add_argument("--out", type=Path, help="output folder (default: <demo folder>\\videos)")
    ap.add_argument("--format", choices=["mp4", "mkv"], default="mp4")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--res", help="game resolution WxH (default: primary screen size)")
    ap.add_argument("--encoder", choices=["auto", "nvenc", "amf", "qsv", "x264"], default="auto")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--audio-device", help="record sound from the output device whose name contains this text")
    ap.add_argument("--list-audio", action="store_true", help="list output devices that can be recorded, then exit")
    ap.add_argument("--renderer", choices=["keep", *RENDERERS], default="keep",
                    help="renderer for the capture run (try d3d9 or opengl if the video is black)")
    ap.add_argument("--force", action="store_true", help="also try demos that miss packages")
    ap.add_argument("--no-import", action="store_true", help="do not copy packages from other UT folders")
    ap.add_argument("--no-download", action="store_true", help="do not look for missing packages online")
    ap.add_argument("--import-from", action="append", default=[], help="extra UT folder to take packages from")
    ap.add_argument("--redirect", action="append", default=[], help="extra download URL that hosts .uz files")
    ap.add_argument("--github", action="append", default=[], metavar="PKG=owner/repo",
                    help="also search this GitHub repo's releases for package PKG")
    ap.add_argument("--prepare-only", action="store_true", help="only gather packages, do not record")
    ap.add_argument("--pick", action="store_true", help="list the demos that can be played and choose which to record")
    ap.add_argument("--obs", nargs="?", const="", default=None, metavar="FOLDER",
                    help="read the HUD messages of stream recordings (OBS / Streamlabs) in FOLDER (default: your Videos "
                         "folder) and cut the same clips as for demos; no demo and no sound needed (see ut_stream.py)")
    ap.add_argument("--obs-track", type=int, default=None,
                    help="only use this sound track of the recordings (1 = first); default: all tracks")
    ap.add_argument("--obs-debug", action="store_true",
                    help="also save every sound track as a small WAV in <out>/obs_debug (to find out why nothing is heard)")
    ap.add_argument("--obs-legacy", action="store_true",
                    help="use the old method for recordings (announcer sound + link to a demo) instead of reading the screen")
    ap.add_argument("--player", help="your player name as the game shows it (default: the name your demo files start with)")
    ap.add_argument("--stream-fps", type=float, default=6.0,
                    help="how many frames per second of a recording are read for HUD messages (default 6)")
    ap.add_argument("--stream-area", metavar="X,Y,W,H",
                    help="where the HUD messages are in a 1920x1080 picture (default: centred, 1000x125 at y=240)")
    ap.add_argument("--stream-clock", metavar="X,Y,W,H",
                    help="where the HUD's match clock is in a 1920x1080 picture (default 722,1038,104,42); "
                         "what happens while it stands still (warm-up, after the match) is not counted")
    ap.add_argument("--include-warmup", action="store_true",
                    help="recordings: also count and clip what happens while the match clock stands still")
    ap.add_argument("--stream-compare", action="store_true",
                    help="also compare what was read from the screen with the scanned demo(s) of the same match")
    ap.add_argument("--rescan", action="store_true", help="read recordings again even when a saved reading exists")
    ap.add_argument("--obs-reencode", action="store_true",
                    help="re-encode OBS clips (exact cut points) instead of fast copying (starts on a key frame)")
    ap.add_argument("--scan", action="store_true",
                    help="find kill/spree messages with the UT2VidHook add-on (fast, no recording; Killcam '99 only)")
    ap.add_argument("--validate", nargs="*", default=None, metavar="LOG",
                    help="compare scans with the calls the audio detector heard (default: the ut2vid_log.txt files)")
    ap.add_argument("--clips", action="store_true", help="also cut clips around Mega Kill and higher / Unstoppable and higher")
    ap.add_argument("--clips-only", action="store_true", help="only keep the clips, delete the full videos")
    ap.add_argument("--clip-before", type=float, default=15.0, help="seconds before the announcement (default 15)")
    ap.add_argument("--clip-quality", choices=["high", "normal", "small"], default="normal",
                    help="clip size/quality: high = like the recording, normal = about half the size (default)")
    ap.add_argument("--announcer-volume", type=int, default=4,
                    help="announcer volume (0-4) used while recording; 4 makes the calls easy to detect, 0 = keep yours")
    ap.add_argument("--clip-after", type=float, default=30.0, help="seconds after the announcement (default 30)")
    ap.add_argument("--clip-on", default=r"megakill|ultrakill|monsterkill|ludicrouskill|holyshit|rampage|dominating|unstoppable|godlike|whickedsick|wickedsick",
                    help="announcer sounds that trigger a clip (regular expression)")
    ap.add_argument("--background", action="store_true",
                    help="keep UT behind your other windows and write a log file (default when ffmpeg 8.1+ is found)")
    ap.add_argument("--foreground", action="store_true",
                    help="old behaviour: UT on top, screen capture, hands off the PC")
    ap.add_argument("--retry-online", action="store_true",
                    help="look online again for packages that were not found during the last 7 days")
    ap.add_argument("--only", help="only demos whose name contains this text")
    ap.add_argument("--limit", type=int, help="convert at most this many demos")
    ap.add_argument("--overwrite", action="store_true", help="redo demos that already have a video")
    ap.add_argument("--max-minutes", type=float, help="hard stop per demo (default: estimated length + 25%% + 3 min)")
    ap.add_argument("--start-timeout", type=float, default=120, help="seconds to wait for playback to start")
    ap.add_argument("--start-delay", type=float, default=1.0, help="extra seconds before recording starts")
    ap.add_argument("--tail", type=float, default=2.0, help="seconds to keep recording after the end")
    ap.add_argument("--av-offset", type=float, default=0.0, help="extra audio delay in ms (fine tuning)")
    ap.add_argument("--keep-work", action="store_true", help="keep the separate video/audio files")
    ap.add_argument("--no-hook", action="store_true",
                    help="Killcam '99: do not use the UT2VidHook game messages for clips, only the sound")
    ap.add_argument("--also-audio", action="store_true",
                    help="also clip calls the sound detection heard but the game showed no message for")
    ap.add_argument("--scan-speed", type=float, default=40.0,
                    help="Killcam '99 scans: demo speed (udemo slomo), default 40x real time")
    ap.add_argument("--scan-jobs", type=int, default=0,
                    help="Killcam '99 scans: how many UT instances scan side by side (default: auto, up to 4; 1 = one at a time)")
    ap.add_argument("--part-before", type=float, default=8.0,
                    help="seconds recorded before the kill streak that leads to a wanted call (default 8)")
    ap.add_argument("--part-after", type=float, default=10.0,
                    help="seconds recorded after the last kill of that streak (default 10)")
    ap.add_argument("--return-window", type=float, default=15.0,
                    help="clip a Multi Kill or higher followed by you returning your flag within this many "
                         "seconds (default 15, 0 = off)")
    ap.add_argument("--capture-window", type=float, default=20.0,
                    help="clip a Multi Kill or higher followed by you capturing within this many seconds "
                         "(default 20, 0 = off)")
    ap.add_argument("--settle", type=float, default=2.0,
                    help="parts: jump this many seconds early so picture and sound settle after the jump (default 2)")
    ap.add_argument("--whole-demo", action="store_true",
                    help="with --scan-first: record the whole demo instead of jumping to the kill parts")
    ap.add_argument("--scan-first", action="store_true",
                    help="Killcam '99: scan the demos fast first and only record those with a wanted call")
    ap.add_argument("--choose-folder", action="store_true",
                    help="with --obs: pick the recordings folder in an Explorer dialog (remembered)")
    ap.add_argument("--set-demo-folder", action="store_true",
                    help="Killcam '99: pick the folder with your demos in an Explorer dialog (remembered), then exit")
    ap.add_argument("--dropped-list", help=argparse.SUPPRESS)  # Killcam99.bat: files dropped on it
    ap.add_argument("--review", action="store_true", help="open the review page for the clips made so far")
    ap.add_argument("--no-review", action="store_true", help="do not open the review page after a batch")
    ap.add_argument("--console-pick", action="store_true", help="pick demos from a numbered list instead of a grid")
    ap.add_argument("--dry-run", action="store_true", help="check setup and list demos, convert nothing")
    ap.add_argument("--ut-args", nargs=argparse.REMAINDER, default=[], help="extra UT command line arguments (must be last)")
    ap.add_argument("--moments", metavar="FILE",
                    help="with --scan-first: record only these moments (JSON: {demo file name: [call times]})")
    ap.add_argument("--obs-file", action="append", default=[], metavar="FILE",
                    help="with --obs: only these recordings (can be given more than once)")
    ap.add_argument("--no-carrier-kills", action="store_true",
                    help="do not clip a Multi Kill+ streak just because it killed the flag carrier")
    ap.add_argument("--watch", metavar="DEMO", help="Killcam '99: just watch a demo in the game (1x, with sound)")
    ap.add_argument("--at", type=float, metavar="SECONDS",
                    help="with --watch: play only around this moment of the demo (10 s before to 12 s after)")
    ap.add_argument("--ask-folder", nargs=2, metavar=("TITLE", "START"), help=argparse.SUPPRESS)
    return ap


def _main() -> int:
    here = Path(__file__).resolve().parent
    ap = build_parser()
    args = ap.parse_args()
    if args.ask_folder:  # used by the GUI: a folder dialog, the answer on stdout
        got = pick_folder(args.ask_folder[0], Path(args.ask_folder[1]) if args.ask_folder[1] else None)
        print(f"FOLDER={got or ''}", flush=True)
        return 0
    args.window_capture = False
    args.templates = {}
    args.hook = False
    args.parts = {}
    args.ini_base = None
    args.ini_target = None
    for spec in args.github:
        if "=" in spec:
            k, v = spec.split("=", 1)
            GITHUB_REPOS[k.strip().lower()] = v.strip()

    global LOG_PATH, SANDBOX, GAME, GAME_MODE
    LOG_PATH = kc_config.LOG if kc_config else Path(__file__).resolve().parent / "ut2vid_log.txt"
    rotate_log(LOG_PATH)
    say("=== run started: " + " ".join(sys.argv[1:]) + " ===")
    if kc_config:
        # Killcam '99: only the configured game folder is ever written to; other UT folders are read only
        kc_config.migrate()
        SANDBOX = here
        GAME, GAME_MODE = kc_config.game(), kc_config.mode()
        built = kc_config.setup_done()
        if args.obs is not None:
            # the OBS link only READS announcer sounds; fall back to an original install if needed
            args.ut = args.ut or (str(GAME) if GAME else None)
        elif not built and not args.list_audio:
            say("PROBLEM: the game is not set up yet. Open Killcam '99 and finish the setup first.")
            return 1
        else:
            args.ut = str(GAME)
        args.out = args.out or kc_config.out()
        if args.set_demo_folder:
            cur = load_settings().get("demo_folder") or str(here.parent)
            got = pick_folder("Folder with your UT demos", Path(cur))
            if got:
                save_settings(demo_folder=str(got))
                say(f"Demo folder: {got}")
            return 0
        if args.dropped_list:
            dropped = []
            for line in Path(args.dropped_list).read_text(encoding="utf-8-sig", errors="replace").splitlines():
                line = line.strip().strip('"').strip()
                if line:
                    dropped.append(Path(line))
            vids = [f for f in dropped if f.suffix.lower() in VIDEO_EXTS]
            dems = [f for f in dropped if f.suffix.lower() == ".dem" or f.is_dir()]
            other = [f for f in dropped if f not in vids and f not in dems]
            for f in other:
                say(f"Ignored (not a demo or a video): {f}")
            for f in dropped:
                if not f.exists():
                    say(f"NOT FOUND: {f}  (odd characters in the name? run it from the menu instead)")
            if vids:
                say(f"Dropped recording(s): {len(vids)} -> clips from OBS / Streamlabs")
                args.obs, args.obs_files = "", [f for f in vids if f.exists()]
                if not dems:
                    return obs_mode_entry(args, here, built)
                obs_mode_entry(args, here, built)
                args.obs = None
            if dems:
                say(f"Dropped demo(s): {len(dems)} -> scan, then kill clips")
                args.demos = [str(f) for f in dems if f.exists()]
                args.clips_only = args.scan_first = True
        if not args.demos:
            args.demos = [load_settings().get("demo_folder") or str(here.parent)]
        if not args.import_from:
            args.import_from = [str(p) for p in package_sources()]
    if args.obs is not None or args.obs_file:
        args.obs = args.obs or ""
        return obs_mode_entry(args, here, SANDBOX is not None)
    if args.review:
        args.out = args.out or (kc_config.out() if kc_config else here / "videos")
        return review_server(args)
    if args.watch:
        return watch_demo(Path(args.watch), args, find_ut_dir(args.ut))
    if args.list_audio:
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            say("pyaudiowpatch is not installed  ->  py -m pip install pyaudiowpatch")
            return 1
        pa = pyaudio.PyAudio()
        default = pa.get_device_info_by_index(pa.get_host_api_info_by_type(pyaudio.paWASAPI)["defaultOutputDevice"])
        print(f"Windows default output: {default['name']}")
        for d in pa.get_loopback_device_info_generator():
            print(f"  {d['name']}")
        pa.terminate()
        return 0

    # collect demos
    srcs = [Path(p) for p in args.demos] or [here]
    demos: list[Path] = []
    removed = {n.lower() for n in load_settings().get("hidden_demos") or []}  # 'Remove from list' in the app
    for s in srcs:
        if s.is_dir():
            demos += sorted(p for p in s.iterdir() if p.suffix.lower() == ".dem"
                             and not p.name.startswith("ut2vid_tmp") and p.name.lower() not in removed)
        elif s.suffix.lower() == ".dem":
            demos.append(s)
    if args.only:
        demos = [d for d in demos if args.only.lower() in d.name.lower()]
    if not demos:
        say("No .dem files found.")
        return 1
    args.out = args.out or (demos[0].parent / "videos")
    args.out.mkdir(parents=True, exist_ok=True)
    global SCAN_DIR
    SCAN_DIR = args.out / "scans"
    if args.validate is not None:
        return validate(args)
    todo = [d for d in demos if args.overwrite or args.pick or not is_done(d, args)]
    if args.limit:
        todo = todo[: args.limit]

    ut_dir = find_ut_dir(args.ut)
    if SANDBOX and (not ut_dir or not GAME or not inside(ut_dir, GAME)):
        say(f"SAFETY STOP: UT folder {ut_dir} is not the game folder set up in Killcam '99 ({GAME}).")
        return 1
    if SANDBOX and GAME_MODE == "copy":
        for r in original_roots():
            if inside(args.out, r):
                say(f"SAFETY STOP: output folder {args.out} is inside an original UT folder ({r}).")
                return 1
    missing: dict[Path, list[dict]] = {}
    if ut_dir and todo:
        say("Checking which packages (maps, mods, textures) each demo needs ...")
        missing = prepare_packages(todo, args, ut_dir)
        if missing:
            counter: dict[str, int] = {}
            for reqs in missing.values():
                for r in reqs:
                    counter[r["pkg"]] = counter.get(r["pkg"], 0) + 1
            say(f"{len(missing)} demo(s) still miss packages (exact version needed): "
                + ", ".join(f"{k} ({v}x)" for k, v in sorted(counter.items(), key=lambda kv: -kv[1])))
            report = args.out / "missing_packages.txt"
            with open(report, "w", encoding="utf-8") as f:
                for d, reqs in missing.items():
                    f.write(f"{d.name}\n")
                    for r in reqs:
                        f.write(f"    {r['pkg']:<32} {', '.join(candidate_filenames(r)):<40} GUID {r['guid']}  size {r['size']}\n")
            say(f"  details: {report}")
            if not args.force:
                say("  these demos are skipped (add --force to try them anyway)")
                todo = [d for d in todo if d not in missing]

    if args.pick:
        todo = pick_demos(todo, args)
        if not todo:
            return 0
    if args.prepare_only:
        say(f"Prepared. {len(todo)} demo(s) have everything they need.")
        return 0
    if args.scan:
        if not IS_WINDOWS:
            say("PROBLEM: This tool has to run on Windows (it drives the UT window).")
            return 1
        return run_scans(todo, args, ut_dir)
    if args.moments:
        import json
        try:
            args.moments_map = json.loads(Path(args.moments).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            say(f"PROBLEM: could not read the picked moments ({e})")
            return 1
    if args.scan_first and todo and not args.dry_run:
        todo = scan_first(todo, args, ut_dir)
        if todo is None:
            return 1
        if not todo:
            say("No demo has a Mega Kill or higher / Unstoppable or higher of yours. Nothing to record.")
            return 0
    total_est = sum(estimate_duration(d) or 0 for d in todo)
    say(f"{len(demos)} demo(s) found, {len(todo)} to convert, roughly {fmt_dur(total_est)} of playback.")

    ffmpeg = find_ffmpeg()
    if not args.dry_run and IS_WINDOWS:
        need_audio = False
        if not args.no_audio:
            try:
                import pyaudiowpatch  # noqa: F401
            except ImportError:
                need_audio = True
        need_numpy = False
        if args.clips or args.clips_only:
            try:
                import numpy  # noqa: F401
            except ImportError:
                need_numpy = True
        offer_install(not ffmpeg, need_audio, need_numpy)
        ffmpeg = ffmpeg or find_ffmpeg()
    problems = []
    if not IS_WINDOWS:
        problems.append("This tool has to run on Windows (it drives the UT window).")
    if not ffmpeg:
        problems.append("ffmpeg not found on PATH  ->  winget install Gyan.FFmpeg  (then open a new terminal)")
    if not ut_dir:
        problems.append("Unreal Tournament not found  ->  pass --ut \"C:\\path\\to\\UnrealTournament\"")
    if not args.no_audio:
        try:
            import pyaudiowpatch  # noqa: F401
        except ImportError:
            problems.append("pyaudiowpatch missing  ->  py -m pip install pyaudiowpatch   (or use --no-audio)")
    if args.clips or args.clips_only:
        if args.no_audio:
            problems.append("clips need the game sound to find the kills; remove --no-audio")
        try:
            import numpy  # noqa: F401
        except ImportError:
            problems.append("numpy missing (needed for clips)  ->  py -m pip install numpy")

    if args.dry_run:
        for d in todo:
            pk = count_packets(d)
            say(f"  {fmt_dur(estimate_duration(d)):>8}  {'ok ' if pk else 'BAD'}  {d.name}")
        for d, reqs in missing.items():
            say(f"  skipped (missing {', '.join(r['pkg'] for r in reqs)}): {d.name}")
        say(f"UT: {ut_dir or 'not found'}   ffmpeg: {ffmpeg or 'not found'}")
        for p in problems:
            say(f"PROBLEM: {p}")
        return 0 if not problems else 1
    if problems:
        for p in problems:
            say(f"PROBLEM: {p}")
        return 1

    sysdir = ut_system_dir(ut_dir)
    ut_exe = sysdir / "UnrealTournament.exe"
    # a separate copy has its own settings; the player's own UT may keep them in Documents\UnrealTournament
    udir = None if (SANDBOX and GAME_MODE == "copy") else user_system_dir()
    extra_dirs = [udir] if udir and udir.resolve() != sysdir.resolve() else []
    win = Win()
    res = tuple(map(int, args.res.lower().split("x"))) if args.res else win.screen_size()

    # windowed-mode ini copy, so the user's own settings are never touched
    args.ini_path = None
    args.user_ini_path = None
    # copy of User.ini for the capture run: louder announcer (needed to find the kill calls)
    src_user = next((p for p in [udir / "User.ini" if udir else None, sysdir / "User.ini"] if p and p.exists()), None)
    if src_user and args.announcer_volume > 0:
        utext = set_ini_value(src_user.read_text(encoding="latin-1"), "Botpack.TournamentPlayer",
                              "AnnouncerVolume", str(args.announcer_volume))
        for target in [sysdir / USER_INI_FILE] + [d / USER_INI_FILE for d in extra_dirs]:
            try:
                target.write_text(utext, encoding="latin-1")
                args.user_ini_path = USER_INI_FILE if target.parent == sysdir else str(target)
                break
            except OSError:
                continue
    src_ini = next((p for p in [udir / "UnrealTournament.ini" if udir else None,
                                sysdir / "UnrealTournament.ini", ut_dir / "System" / "UnrealTournament.ini"]
                    if p and p.exists()), None)
    args.hook = bool(SANDBOX and (args.clips or args.clips_only) and not args.no_hook and hook_built(sysdir))
    if src_ini:
        patched = patch_ini(src_ini.read_text(encoding="latin-1"), *res, args.renderer)
        if args.hook:
            patched = hook_ini(patched, mode=2, progress=5)
        for target in [sysdir / INI_FILE] + [d / INI_FILE for d in extra_dirs]:
            try:
                target.write_text(patched, encoding="latin-1")
                args.ini_path = INI_FILE if target.parent == sysdir else str(target)
                args.ini_base, args.ini_target = patched, target
                break
            except OSError:
                continue
    if not args.ini_path:
        say("WARNING: could not prepare a windowed ini; set UT to windowed mode yourself if capture is black.")

    say(f"UT: {ut_exe}")
    say(f"Game resolution {res[0]}x{res[1]}, output {args.format.upper()} at {args.fps} fps into {args.out}")
    enc_args = pick_encoder(ffmpeg, args.encoder)
    say(f"Video encoder: {enc_args[1]}")
    if args.clips or args.clips_only:
        args.templates = announcer_templates(ut_dir)
        trig = sorted(n for n in args.templates if re.search(args.clip_on, n, re.I))
        if not trig:
            say(f"PROBLEM: no announcer sound matching '{args.clip_on}' found in {ut_dir / 'Sounds'}")
            return 1
        say(f"Clips: {args.clip_before:g}s before to {args.clip_after:g}s after: {', '.join(trig)}"
            + ("  (full videos are deleted afterwards)" if args.clips_only else ""))
    if args.hook:
        say("Clips are placed by the game's own HUD messages (UT2VidHook add-on); the sound detection "
            "double-checks" + (" and its extra finds are clipped too." if args.also_audio else "."))
    if not args.foreground:
        args.window_capture = has_gfxcapture(ffmpeg)
        args.background = args.window_capture or args.background
    if args.background:
        if args.window_capture:
            say("Background mode: UT stays behind your windows and is recorded directly (window capture).")
            say("  Don't minimise the UT window. Every sound your PC plays ends up in the recording,")
            say("  unless UT outputs to its own device (see --audio-device).")
        else:
            say("Background mode needs window capture, which your ffmpeg lacks (needs 8.1+: menu option 7).")
            say("  Falling back to screen capture: the UT window has to stay visible.")
            args.background = False
    else:
        say("Hands off the PC while this runs; press Ctrl+C to abort.")

    done = failed = 0
    try:
        for i, d in enumerate(todo, 1):
            say(f"=== [{i}/{len(todo)}] ===")
            try:
                if convert_one(d, args, ut_exe, sysdir, extra_dirs, ffmpeg, enc_args, win, res):
                    done += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                say(f"  ERROR: {e}")
            time.sleep(2)
    except KeyboardInterrupt:
        say("Aborted by user.")
    say(f"Finished: {done} converted, {failed} failed. Videos are in {args.out}")
    if new_clips_this_run(args):
        offer_review(args)
    return 0 if failed == 0 else 2


def new_clips_this_run(args) -> int:
    import json
    try:
        return sum(1 for x in json.loads(index_file(args).read_text(encoding="utf-8")) if x.get("run") == RUN_ID)
    except (OSError, ValueError):
        return 0


def obs_mode_entry(args, here: Path, built) -> int:
    """--obs: recordings folder (Explorer dialog with --choose-folder, remembered), then obs_mode."""
    global SCAN_DIR
    if args.obs_track is not None and not getattr(args, "_track_fixed", False):
        args.obs_track -= 1
        args._track_fixed = True
    args.out = args.out or (kc_config.out() if kc_config else here / "videos")
    args.out.mkdir(parents=True, exist_ok=True)
    SCAN_DIR = args.out / "scans"
    if not args.demos:
        args.demos = [load_settings().get("demo_folder") or str(here.parent)] if SANDBOX else []
    if args.obs_file:
        args.obs_files = [Path(x) for x in args.obs_file]
    if not getattr(args, "obs_files", None):
        default = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Videos"
        remembered = Path(load_settings().get("obs_folder") or default)
        if args.choose_folder:
            got = pick_folder("Folder with your OBS / Streamlabs recordings", remembered)
            if not got:
                say("No folder chosen.")
                return 1
            save_settings(obs_folder=str(got))
            args.obs = str(got)
        elif not args.obs:
            args.obs = str(remembered)
    if not args.obs_legacy:
        # default: read the HUD messages from the picture (no demo, no sound needed)
        import ut_stream
        return ut_stream.stream_mode(args, None)
    return obs_mode(args, find_ut_dir(args.ut))


if __name__ == "__main__":
    sys.exit(main())
