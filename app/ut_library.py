"""Killcam '99 packages: which UT package versions you have, where they are, and what demos need.

A demo needs the exact versions (GUIDs) of the maps, textures, sounds, music and code packages
the server used. This module keeps an INDEX of every package version in these places, in the
order the converter looks in them:

    1  the game folder (the copy, or your own UT folder)
    2  the base pack that ships with Killcam '99    packs\\base\\Cache\\<GUID>.uxx + cache.ini
    3  your package folders (Packages page)          only read, never copied
    4  packages found online                         packs\\downloads\\Cache\\<GUID>.uxx + cache.ini

Nothing is copied to build the index. When a demo needs a package, the converter copies that
one version into the game folder's Cache (UT's own format) and nothing else.

    library\\catalog.json     the index (see load_catalog)
    library\\UT_files.csv     the same as a list you can open in Excel

Stock (retail) UT files are recognised from the game's System\\Manifest.ini and are never put in
a pack: players install UT itself with the OldUnreal installer.

    py ut_library.py build      refresh the index (game folder, packs, your package folders)
    py ut_library.py basepack   DEST    make the base pack to ship (what the demos need)
    py ut_library.py fetch      [--guid G ...] [--retry]  look online for missing versions
    py ut_library.py stats
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import struct
import sys
import time
from pathlib import Path

import kc_config as cfg

HERE = cfg.APP
LIB = cfg.DATA / "library"
CATALOG = LIB / "catalog.json"
CSV = LIB / "UT_files.csv"
ONLINE = LIB / "online_search.json"
PKG_EXTS = {".u": "code", ".unr": "map", ".utx": "textures", ".uax": "sounds", ".umx": "music"}
SUBDIRS = ("System", "System64", "Maps", "Textures", "Sounds", "Music")
SKIP = re.compile(r"^(ut2vid|UT2VidHook)", re.I)   # our own add-on and temporary files
VERSION = 2   # 2: an index of where packages are (1 copied everything into library\Cache)
KIND_LABEL = {"game": "Game folder", "base": "Base pack", "folder": "Your folder", "download": "Found online"}


def say(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def guard(p: Path) -> Path:
    """Writes go to the index folder and the packs only; everything else is read."""
    if not (inside(p, LIB) or inside(p, cfg.PACKS)):
        raise SystemExit(f"SAFETY STOP: refused to write outside {LIB} and {cfg.PACKS}: {p}")
    return p


# --------------------------------------------------------------------------------------
# Reading Unreal packages (header, names, imports): enough to know what a file is and needs
# --------------------------------------------------------------------------------------

def _index(b: bytes, pos: int) -> tuple[int, int]:
    """Unreal's compact index (1 to 5 bytes)."""
    b0 = b[pos]
    pos += 1
    val = b0 & 0x3F
    if b0 & 0x40:
        shift = 6
        while True:
            bx = b[pos]
            pos += 1
            val |= (bx & 0x7F) << shift
            shift += 7
            if not bx & 0x80 or shift > 27:
                break
    return (-val if b0 & 0x80 else val), pos


def read_package(path: Path, deep: bool = True) -> dict | None:
    """Header facts of a UT package: GUID (as UT and demos write it), file version, licensee,
    and (deep) the packages it imports. None if it is not a package."""
    try:
        with open(path, "rb") as f:
            h = f.read(64)
            if len(h) < 36:
                return None
            tag, ver, lic, flags, ncount, noff, ecount, eoff, icount, ioff = struct.unpack_from("<IHHIIIIIII", h, 0)
            if tag != 0x9E2A83C1:
                return None
            if ver >= 68:
                guid = "".join(f"{x:08X}" for x in struct.unpack_from("<4I", h, 36))
            else:  # old packages keep it as the last 'heritage' entry
                hcount, hoff = struct.unpack_from("<II", h, 36)
                if not 1 <= hcount <= 10000:
                    return None
                f.seek(hoff + 16 * (hcount - 1))
                guid = "".join(f"{x:08X}" for x in struct.unpack("<4I", f.read(16)))
            info = {"guid": guid, "pkg_ver": ver, "licensee": lic, "imports": []}
            if not deep or not (0 < ncount < 2_000_000 and 0 <= icount < 2_000_000):
                return info
            size = path.stat().st_size
            f.seek(noff)
            names_raw = f.read(min(size - noff, 64 * ncount + 64))
            names, pos = [], 0
            for _ in range(ncount):
                if ver >= 64:
                    n, pos = _index(names_raw, pos)
                    s = names_raw[pos:pos + max(0, n)]
                    pos += max(0, n)
                else:
                    end = names_raw.index(b"\0", pos)
                    s = names_raw[pos:end + 1]
                    pos = end + 1
                names.append(s.rstrip(b"\0").decode("latin-1"))
                pos += 4  # flags
            f.seek(ioff)
            raw = f.read(min(size - ioff, 32 * icount + 32))
            pos, deps = 0, []
            for _ in range(icount):
                _cp, pos = _index(raw, pos)
                cname, pos = _index(raw, pos)
                (outer,) = struct.unpack_from("<i", raw, pos)
                pos += 4
                oname, pos = _index(raw, pos)
                if outer == 0 and 0 <= cname < len(names) and names[cname].lower() == "package" \
                        and 0 <= oname < len(names):
                    deps.append(names[oname])
            info["imports"] = sorted(set(deps), key=str.lower)
            return info
    except (OSError, struct.error, ValueError, IndexError):
        return None


# --------------------------------------------------------------------------------------
# Where UT files are
# --------------------------------------------------------------------------------------

def is_ut_root(p: Path) -> bool:
    try:
        names = {x.name.lower() for x in p.iterdir() if x.is_dir()}
    except OSError:
        return False
    return "system" in names and bool({"maps", "cache", "textures"} & names)


def find_roots(bases: list[Path], depth: int = 4) -> list[Path]:
    out = []
    for base in bases:
        if not base.is_dir():
            continue
        if is_ut_root(base):
            out.append(base)
            continue
        for dirpath, dirnames, _ in os.walk(base):
            here = Path(dirpath)
            if len(here.relative_to(base).parts) >= depth:
                dirnames[:] = []
                continue
            if is_ut_root(here):
                out.append(here)
                dirnames[:] = []
    seen, uniq = set(), []
    for r in out:
        k = str(r.resolve()).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def cache_entries(root: Path) -> list[tuple[Path, str]]:
    """(file, real file name) of every package in a UT cache folder (Cache, Cache1, ...)."""
    out = []
    for sub in sorted(root.glob("Cache*")):
        ci = sub / "cache.ini"
        if not (sub.is_dir() and ci.exists()):
            continue
        for line in ci.read_text(encoding="latin-1", errors="replace").splitlines():
            m = re.match(r"\s*([0-9A-Fa-f]{32})\s*=\s*(.+?)\s*$", line)
            if m:
                f = sub / f"{m.group(1).upper()}.uxx"
                if f.exists():
                    out.append((f, m.group(2)))
    return out


def folder_entries(root: Path) -> list[tuple[Path, str]]:
    out = []
    for sub in SUBDIRS:
        d = root / sub
        if d.is_dir():
            for p in d.iterdir():
                if p.is_file() and p.suffix.lower() in PKG_EXTS and not SKIP.match(p.name):
                    out.append((p, p.name))
    return out


def loose_entries(folder: Path) -> list[tuple[Path, str]]:
    """Package files anywhere below a folder that is not a UT install (a maps collection)."""
    out = []
    for dirpath, _dirs, files in os.walk(folder):
        for fn in files:
            if Path(fn).suffix.lower() in PKG_EXTS and not SKIP.match(fn):
                out.append((Path(dirpath) / fn, fn))
    return out


def stock_names(roots: list[Path]) -> set[str]:
    """Retail file names ('maps\\ctf-face.unr' style, lower case) from the installers' Manifest.ini:
    every File= line of every product group ([Setup] Group=...)."""
    out = set()
    for r in roots:
        m = r / "System" / "Manifest.ini"
        if not m.exists():
            continue
        groups, cur = set(), None
        lines = m.read_text(encoding="latin-1", errors="replace").splitlines()
        for line in lines:
            g = re.match(r"\s*Group=(\S+)", line)
            if g and cur == "setup":
                groups.add(g.group(1).lower())
            s = re.match(r"\s*\[(.+)\]\s*$", line)
            if s:
                cur = s.group(1).lower()
        cur = None
        for line in lines:
            s = re.match(r"\s*\[(.+)\]\s*$", line)
            if s:
                cur = s.group(1).lower()
                continue
            f = re.match(r"\s*File=(?:\(Src=)?([^,)\s]+)", line)
            if f and cur in groups:
                out.add(Path(f.group(1).replace("\\", "/")).name.lower())
    return out

# --------------------------------------------------------------------------------------
# Catalog (the index)
# --------------------------------------------------------------------------------------

def removed_demos() -> set[str]:
    """Demos the player took off the list ('Remove from list'): they no longer count anywhere."""
    return {n.lower() for n in cfg.load().get("hidden_demos") or []}


def load_catalog(raw: bool = False) -> dict:
    """packages[GUID] = {file, name, type, size, pkg_ver, licensee, imports, cache_origin, sources[], stock}
    sources = every file that holds this exact version; roots = the places that were read;
    demos[file name] = {key, path, requires[GUID], names{GUID: pkg}, reqs{GUID: {pkg, fname, size, flags, gen}}}"""
    try:
        cat = json.loads(CATALOG.read_text(encoding="utf-8"))
        if cat.get("version") == VERSION:
            if not raw:
                gone = removed_demos()
                if gone:
                    cat["demos"] = {n: d for n, d in cat.get("demos", {}).items() if n.lower() not in gone}
            return cat
    except (OSError, ValueError):
        pass
    return {"version": VERSION, "packages": {}, "seen": {}, "demos": {}, "stock": [], "roots": []}


def save_catalog(cat: dict) -> None:
    LIB.mkdir(parents=True, exist_ok=True)
    tmp = guard(LIB / "catalog.tmp")
    tmp.write_text(json.dumps(cat, indent=1), encoding="utf-8")
    os.replace(tmp, guard(CATALOG))


def classify(cat: dict) -> None:
    stock = set(cat.get("stock", []))
    for p in cat["packages"].values():
        p["stock"] = p["file"].lower() in stock and not p.get("cache_origin")


def write_csv(cat: dict) -> None:
    import csv
    demo_of: dict[str, list[str]] = {}
    for name, d in cat.get("demos", {}).items():
        for g in d.get("requires", []):
            demo_of.setdefault(g, []).append(name)
    rows = sorted(cat["packages"].items(), key=lambda kv: (kv[1]["type"], kv[1]["file"].lower()))
    tmp = guard(LIB / "UT_files.tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")  # ; opens straight into columns in a Dutch/European Excel
        w.writerow(["File", "Type", "Kind", "Size (MB)", "GUID", "Package version", "Needed by demos",
                    "Demos (first 3)", "Where", "Imports", "First location"])
        for g, p in rows:
            ds = demo_of.get(g, [])
            w.writerow([p["file"], p["type"], "stock (not shipped)" if p.get("stock") else "community",
                        f"{p['size'] / 1e6:.2f}".replace(".", ","), g, p.get("pkg_ver", ""), len(ds),
                        ", ".join(ds[:3]), ", ".join(KIND_LABEL[k] for k in where(cat, p)),
                        " ".join(p.get("imports", [])), (p.get("sources") or [""])[0]])
    os.replace(tmp, guard(CSV))


# --------------------------------------------------------------------------------------
# The places that are read
# --------------------------------------------------------------------------------------

def roots_to_read() -> list[dict]:
    """[{path, kind}] in lookup order: game folder, base pack, your folders, packages found online."""
    st = cfg.load()
    out = []
    g = cfg.game()
    if g:
        out.append({"path": str(g), "kind": "game"})
    if (cfg.BASE_PACK / "Cache" / "cache.ini").exists():
        out.append({"path": str(cfg.BASE_PACK), "kind": "base"})
    for f in st.get("library_sources") or []:
        out.append({"path": f, "kind": "folder"})
    if (cfg.DOWNLOADS / "Cache" / "cache.ini").exists():
        out.append({"path": str(cfg.DOWNLOADS), "kind": "download"})
    return out


def entries_of(root: Path) -> list[tuple[Path, str, bool]]:
    """(file, real file name, came from a cache folder) for every package in one place."""
    out = [(p, n, True) for p, n in cache_entries(root)]
    if (root / "cache.ini").exists():  # the folder itself is a cache folder
        out += [(p, n, True) for p, n in cache_entries(root.parent) if p.parent == root]
    if is_ut_root(root):
        out += [(p, n, False) for p, n in folder_entries(root)]
    elif not (root / "Cache" / "cache.ini").exists():
        out += [(p, n, False) for p, n in loose_entries(root)]
    return out


def root_of(cat: dict, path: str) -> dict | None:
    best = None
    for r in cat.get("roots", []):
        if path.lower().startswith(r["path"].lower().rstrip("\\/") + os.sep) and (best is None or len(r["path"]) > len(best["path"])):
            best = r
    return best


def where(cat: dict, p: dict) -> list[str]:
    """The kinds of place that hold this version, in lookup order."""
    ks = {(root_of(cat, s) or {}).get("kind") for s in p.get("sources", [])}
    return [k for k in ("game", "base", "folder", "download") if k in ks]


def demo_folders() -> list[Path]:
    st = cfg.load()
    d = Path(st.get("demo_folder") or HERE.parent)
    out = [d] + [x for x in d.iterdir() if x.is_dir() and not inside(x, HERE)] if d.is_dir() else []
    return [x for x in out if x.is_dir()]


def scan_demos(cat: dict) -> None:
    """Which package versions each of your demos needs (read from the demo files)."""
    sys.path.insert(0, str(HERE))
    try:
        import ut99_dem2video as core
    except Exception as e:
        say(f"  (demo requirements skipped: {e})")
        return
    demos = []
    for d in demo_folders():
        demos += [p for p in d.glob("*.dem") if not p.name.startswith("ut2vid_tmp")]
    known = cat.setdefault("demos", {})
    todo = [p for p in demos if (known.get(p.name) or {}).get("key") != f"{p.stat().st_size}|{int(p.stat().st_mtime)}"]
    if todo:
        say(f"Reading what {len(todo)} demo(s) need ...")
    for i, p in enumerate(todo, 1):
        try:
            reqs = core.demo_packages(p) or []
        except Exception:
            reqs = []
        known[p.name] = {"key": f"{p.stat().st_size}|{int(p.stat().st_mtime)}", "path": str(p),
                         "requires": [r["guid"] for r in reqs],
                         "names": {r["guid"]: r["pkg"] for r in reqs},
                         "reqs": {r["guid"]: {k: r.get(k) for k in ("pkg", "fname", "size", "flags", "gen")} for r in reqs}}
        if i % 10 == 0:
            say(f"  ... {i}/{len(todo)}")
    for name in [n for n, d in known.items() if not Path(d.get("path", "")).exists()]:
        del known[name]


# --------------------------------------------------------------------------------------
# Refresh the index
# --------------------------------------------------------------------------------------

def index_file(cat: dict, path: Path, fname: str, from_cache: bool) -> bool:
    """Add one file to the index. True when it is a version the index did not know yet."""
    pk, seen = cat["packages"], cat["seen"]
    try:
        st = path.stat()
    except OSError:
        return False
    ext = Path(fname).suffix.lower()
    if ext not in PKG_EXTS:
        return False
    key = str(path)
    prev = seen.get(key)
    if prev and prev[0] == st.st_size and prev[1] == int(st.st_mtime):
        g = prev[2]
        info = None
    else:
        info = read_package(path, deep=False)
        if not info:
            return False
        g = info["guid"]
        seen[key] = [st.st_size, int(st.st_mtime), g]
    p = pk.get(g)
    new = p is None
    if new:
        info = read_package(path) or {}
        p = pk[g] = {"file": fname, "name": Path(fname).stem, "type": PKG_EXTS[ext], "size": st.st_size,
                     "pkg_ver": info.get("pkg_ver"), "licensee": info.get("licensee"),
                     "imports": info.get("imports", []), "cache_origin": False, "sources": []}
    if from_cache:
        p["cache_origin"] = True
    if key not in p["sources"]:
        p["sources"].append(key)
    return new


def build(args) -> int:
    t0 = time.time()
    roots = roots_to_read()
    if not roots:
        say("Nothing to read yet: finish the setup first (the game folder is read), or add a package folder.")
        return 1
    old = load_catalog(raw=True)
    cat = {"version": VERSION, "packages": {}, "seen": old.get("seen", {}), "demos": old.get("demos", {}),
           "stock": [], "roots": roots}
    say("Refreshing the package index. Every folder is only read; nothing is copied.")
    for n, r in enumerate(roots, 1):
        root = Path(r["path"])
        say(f"=== [{n}/{len(roots)}] ===")
        if not root.is_dir():
            say(f"{KIND_LABEL[r['kind']]}: {root}  (NOT FOUND: skipped)")
            r["files"] = r["versions"] = 0
            continue
        say(f"{KIND_LABEL[r['kind']]}: {root}")
        if r["kind"] == "game":
            cat["stock"] = sorted(stock_names([root]))
        entries = entries_of(root)
        # 'came from a server' only counts for a real UT install's Cache (a pack or old library is just storage)
        install = is_ut_root(root)
        new = sum(index_file(cat, p, name, c and install) for p, name, c in entries)
        r["files"], r["versions"] = len(entries), len({cat["seen"][str(p)][2] for p, _n, _c in entries if str(p) in cat["seen"]})
        say(f"  {len(entries)} package file(s); {new} version(s) not in an earlier place")
    # forget memo entries of files that are gone
    cat["seen"] = {k: v for k, v in cat["seen"].items() if Path(k).exists()}
    scan_demos(cat)
    classify(cat)
    cat["built"] = time.time()
    save_catalog(cat)
    write_csv(cat)
    s = summary(cat)
    say(f"Index ready: {s['packages']} package versions ({s['gb']:.2f} GB) in {len(roots)} place(s), "
        f"{s['community']} community, {s['stock']} stock; {time.time() - t0:.0f}s.")
    if s["demos"]:
        say(f"Your {s['demos']} demo(s) need {s['needed']} package version(s); "
            + (f"{s['missing']} are in none of these places: {', '.join(s['missing_names'][:8])}"
               + (" ..." if len(s["missing_names"]) > 8 else "") if s["missing"] else "every one of them is available."))
    return 0


def summary(cat: dict | None = None) -> dict:
    cat = cat or load_catalog()
    pk = cat["packages"]
    need, names = set(), {}
    for d in cat.get("demos", {}).values():
        need |= set(d.get("requires", []))
        names.update(d.get("names", {}))
    missing = sorted(g for g in need if g not in pk and not _optional(cat, g))
    by_type: dict[str, int] = {}
    for p in pk.values():
        by_type[p["type"]] = by_type.get(p["type"], 0) + 1
    return {"packages": len(pk), "gb": sum(p["size"] for p in pk.values()) / 2**30,
            "community": sum(1 for p in pk.values() if not p.get("stock")),
            "stock": sum(1 for p in pk.values() if p.get("stock")),
            "by_type": by_type, "demos": len(cat.get("demos", {})), "needed": len(need),
            "missing": len(missing), "missing_names": sorted({Path(names.get(g, g)).stem for g in missing}),
            "built": cat.get("built")}


def _optional(cat: dict, g: str) -> bool:
    """A package the server marked client-optional: UT plays the demo without it."""
    for d in cat.get("demos", {}).values():
        r = (d.get("reqs") or {}).get(g)
        if r is not None:
            return bool((r.get("flags") or 0) & 0x02)
    return False


def locate(guid: str, cat: dict | None = None) -> Path | None:
    """A file that holds exactly this package version, in lookup order."""
    cat = cat or load_catalog()
    p = cat["packages"].get(guid.upper())
    if not p:
        return None
    for s in sorted(p.get("sources", []), key=lambda s: ["game", "base", "folder", "download"].index(
            (root_of(cat, s) or {}).get("kind", "download"))):
        if Path(s).exists():
            return Path(s)
    return None


# --------------------------------------------------------------------------------------
# Packages per demo, and what is missing (with everything known about it)
# --------------------------------------------------------------------------------------

def online_log() -> dict:
    try:
        return json.loads(ONLINE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def note_online(guid: str, found: bool, where_: str = "") -> None:
    log = online_log()
    log[guid] = {"checked": time.time(), "found": found, "where": where_}
    LIB.mkdir(parents=True, exist_ok=True)
    guard(ONLINE).write_text(json.dumps(log, indent=1), encoding="utf-8")


def _by_name(cat: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for g, p in cat["packages"].items():
        out.setdefault(p["name"].lower(), []).append(g)
    return out


def _other_versions(cat: dict, name: str, guid: str, by_name: dict) -> list[dict]:
    return [{"guid": g, "size": cat["packages"][g]["size"], "where": [KIND_LABEL[k] for k in where(cat, cat["packages"][g])]}
            for g in by_name.get(name.lower(), []) if g != guid]


def _req_row(cat: dict, g: str, r: dict, by_name: dict, online: dict) -> dict:
    p = cat["packages"].get(g)
    optional = bool((r.get("flags") or 0) & 0x02)
    fname = r.get("fname") or ""
    if fname.lower().endswith(".uxx"):  # the server sent its cache name: show the real file name instead
        pkg = r.get("pkg") or ""
        fname = pkg + (".unr" if re.match(r"(?i)(CTF|DM|DOM|AS|BT|TDM|CTF4|MH|JB|SB|RA|LMS|EOL)-", pkg) else ".u")
        known = cat["packages"].get(g) or next((cat["packages"][x] for x in by_name.get(pkg.lower(), [])), None)
        if known:
            fname = known["file"]
    row = {"guid": g, "pkg": r.get("pkg") or g, "fname": fname, "size": r.get("size") or 0,
           "gen": r.get("gen"), "optional": optional}
    if p:
        ks = where(cat, p)
        row.update(status=ks[0] if ks else "game", where=[KIND_LABEL[k] for k in ks], type=p["type"],
                   file=p["file"], stock=bool(p.get("stock")))
    else:
        row.update(status="optional" if optional else "missing", where=[], type=None, file=None,
                   other_versions=_other_versions(cat, row["pkg"], g, by_name), online=online.get(g))
    return row


def demo_report(demo: str) -> dict:
    """Every package version one demo needs, and where each is (or that it is missing)."""
    cat = load_catalog()
    d = cat.get("demos", {}).get(Path(demo).name)
    if not d:
        return {"demo": Path(demo).name, "known": False, "packages": []}
    by_name, online = _by_name(cat), online_log()
    reqs = d.get("reqs") or {g: {"pkg": n} for g, n in d.get("names", {}).items()}
    rows = [_req_row(cat, g, reqs.get(g, {}), by_name, online) for g in d.get("requires", [])]
    order = {"missing": 0, "optional": 1}
    rows.sort(key=lambda r: (order.get(r["status"], 2), r["pkg"].lower()))
    return {"demo": Path(demo).name, "known": True, "packages": rows,
            "missing": sum(r["status"] == "missing" for r in rows)}


def missing_detail(cat: dict | None = None) -> list[dict]:
    """Every missing version across all demos, grouped by version, with everything known about it."""
    cat = cat or load_catalog()
    by_name, online = _by_name(cat), online_log()
    out: dict[str, dict] = {}
    for name, d in cat.get("demos", {}).items():
        reqs = d.get("reqs") or {}
        for g in d.get("requires", []):
            if g in cat["packages"]:
                continue
            r = reqs.get(g) or {"pkg": d.get("names", {}).get(g, g)}
            if (r.get("flags") or 0) & 0x02:
                continue
            row = out.get(g) or _req_row(cat, g, r, by_name, online)
            row.setdefault("demos", []).append(name)
            out[g] = row
    return sorted(out.values(), key=lambda m: (m["pkg"].lower(), m["guid"]))


def missing_count(demo_name: str, cat: dict) -> int:
    d = cat.get("demos", {}).get(demo_name)
    if not d:
        return 0
    reqs = d.get("reqs") or {}
    return sum(1 for g in d.get("requires", []) if g not in cat["packages"]
               and not ((reqs.get(g) or {}).get("flags") or 0) & 0x02)


# --------------------------------------------------------------------------------------
# Packs: packages found online, and the base pack that ships
# --------------------------------------------------------------------------------------

def _pack_add(pack: Path, src: Path, guid: str, fname: str) -> Path:
    cache = guard(pack / "Cache")
    cache.mkdir(parents=True, exist_ok=True)
    dst = cache / f"{guid}.uxx"
    if not dst.exists():
        shutil.copy2(src, dst)
    ci = cache / "cache.ini"
    text = ci.read_text(encoding="latin-1") if ci.exists() else "[Cache]\r\n"
    if not re.search(rf"(?im)^\s*{guid}\s*=", text):
        text += f"{guid}={fname}\r\n"
        ci.write_text(text, encoding="latin-1", newline="")
    return dst


def add_package(src: Path, fname: str, origin: str = "online") -> bool:
    """Keep a package version found online in packs\\downloads (so it is never fetched again) and
    add it to the index. False if it is not a package."""
    info = read_package(src)
    ext = Path(fname).suffix.lower()
    if not info or ext not in PKG_EXTS:
        return False
    g = info["guid"]
    dst = _pack_add(cfg.DOWNLOADS, src, g, fname)
    cat = load_catalog(raw=True)
    if not any(r["kind"] == "download" for r in cat.get("roots", [])):
        cat.setdefault("roots", []).append({"path": str(cfg.DOWNLOADS), "kind": "download"})
    index_file(cat, dst, fname, True)
    cat["packages"][g]["stock"] = False
    save_catalog(cat)
    note_online(g, True, origin)
    try:
        write_csv(cat)
    except OSError:
        pass
    return True


def closure(cat: dict, start: set[str]) -> set[str]:
    """Add the community packages that the chosen ones import (by name, any version we have)."""
    by_name = _by_name(cat)
    out, todo = set(start), list(start)
    while todo:
        g = todo.pop()
        for dep in cat["packages"].get(g, {}).get("imports", []):
            for g2 in by_name.get(dep.lower(), []):
                if g2 not in out and not cat["packages"][g2].get("stock"):
                    out.add(g2)
                    todo.append(g2)
    return out


PACK_README = """Killcam '99 base pack ({when})

{count} Unreal Tournament package versions ({mb:.0f} MB): community maps, mods, textures, sounds
and music that demos need, in UT's own cache format (Cache\\<GUID>.uxx plus Cache\\cache.ini).
Killcam '99 copies a version from here into your game's Cache only when a demo needs it.

Not included: the retail game. Install Unreal Tournament with the OldUnreal installer.
"""


def make_base_pack(dest: Path, log=say) -> int:
    """The base pack to ship: every community version the demos need, plus what those import."""
    cat = load_catalog()
    pk = cat["packages"]
    need = set()
    for d in cat.get("demos", {}).values():
        need |= set(d.get("requires", []))
    chosen = closure(cat, {g for g in need if g in pk and not pk[g].get("stock")})
    chosen = {g for g in chosen if locate(g, cat)}
    if not chosen:
        log("Nothing to put in the base pack: refresh the index first.")
        return 1
    dest = Path(dest)
    if (dest / "Cache").exists():
        shutil.rmtree(dest / "Cache")
    (dest / "Cache").mkdir(parents=True)
    ordered = sorted(chosen, key=lambda g: pk[g]["file"].lower())
    for i, g in enumerate(ordered, 1):
        shutil.copy2(locate(g, cat), dest / "Cache" / f"{g}.uxx")
        if i % 25 == 0 or i == len(ordered):
            log(f"=== [{i}/{len(ordered)}] ===")
    (dest / "Cache" / "cache.ini").write_text("[Cache]\r\n" + "".join(f"{g}={pk[g]['file']}\r\n" for g in ordered),
                                              encoding="latin-1", newline="")
    when = dt.datetime.now()
    size = sum(pk[g]["size"] for g in ordered)
    (dest / "pack.json").write_text(json.dumps({"name": "base", "made": when.timestamp(), "count": len(ordered),
                                                "packages": {g: {k: pk[g].get(k) for k in ("file", "type", "size", "pkg_ver")}
                                                             for g in ordered}}, indent=1), encoding="utf-8")
    (dest / "README.txt").write_text(PACK_README.format(when=f"{when:%Y-%m-%d}", count=len(ordered), mb=size / 2**20)
                                     .replace("\n", "\r\n"), encoding="utf-8", newline="")
    log(f"Base pack ready: {len(ordered)} package versions, {size / 2**20:.0f} MB in {dest}")
    return 0


EXTRA_REDIRECTS = [
    # redirect folders of UT99 servers and file archives (name.ext.uz files); more can be added
    # with --redirect. The Wayback Machine is asked for older copies of every one of them.
    "https://deaod.de/ut99/", "http://pgaming.site.nfoservers.com/redirect/", "https://medor.no-ip.org/uz/",
    "http://uz.ut-files.com/", "http://files.emilstefanov.net/UT99/Redirect/", "http://uz.unrealadmin.org/",
    "http://redirect.ut-files.com/",
]


def missing_requirements(cat: dict) -> list[dict]:
    """Package versions your demos need that none of the places has, with what the demo
    says about them (name, server file name, exact size). Client-optional ones are left out."""
    sys.path.insert(0, str(HERE))
    import ut99_dem2video as core
    out: dict[str, dict] = {}
    for name, d in cat.get("demos", {}).items():
        miss = [g for g in d.get("requires", []) if g not in cat["packages"]]
        if not miss:
            continue
        reqs = d.get("reqs")
        if not reqs:
            try:
                reqs = {r["guid"]: r for r in core.demo_packages(Path(d["path"])) or []}
            except Exception:
                reqs = {}
        for g in miss:
            r = reqs.get(g)
            if r and not (r.get("flags") or 0) & 0x02:
                o = out.setdefault(g, {"guid": g, "pkg": r["pkg"], "fname": r["fname"], "size": r["size"],
                                       "flags": r.get("flags", 0), "demos": []})
                o["demos"].append(name)
    return sorted(out.values(), key=lambda r: r["pkg"].lower())


def _get(url: str, timeout: int = 60, tries: int = 1) -> bytes | None:
    """GET with a polite retry when a site says 'too many requests' (the Wayback Machine does)."""
    import urllib.error
    import urllib.request
    for i in range(tries):
        try:
            rq = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Killcam 99 package finder)"})
            with urllib.request.urlopen(rq, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i + 1 < tries:
                time.sleep(20 * (i + 1))
                continue
            return None
        except Exception:
            if i + 1 < tries:
                time.sleep(5)
                continue
            return None
    return None


def wayback_copies(base: str, names: list[str]) -> list[tuple[str, str, str]]:
    """[(timestamp, original url, digest)] of every archived copy (any date) of these files in one
    redirect folder. One exact-address question per file: the Wayback Machine answers those fast
    (folder-wide searches time out)."""
    import urllib.parse
    folder = base.split("://", 1)[1]
    out = []
    for n in names:
        url = ("http://web.archive.org/cdx/search/cdx?output=json&fl=timestamp,original,digest,statuscode"
               f"&collapse=digest&url={urllib.parse.quote(folder + n + '.uz')}")
        raw = _get(url, 60, tries=3)
        if raw is None:
            say(f"    (the Wayback Machine did not answer for {folder}{n}.uz)")
            continue
        try:
            rows = json.loads(raw or b"[]")[1:]
        except ValueError:
            rows = []
        out += [(ts, orig, dg) for ts, orig, dg, st in rows if st == "200"]
    return out


def fetch(args) -> int:
    """Look for the package versions your demos need but you do not have: on UT redirect servers
    (live), in the Wayback Machine (every archived copy of those files) and in the GitHub releases
    of known mods. A file is only kept when its GUID is exactly the one the demo needs."""
    import urllib.parse
    sys.path.insert(0, str(HERE))
    import ut99_dem2video as core
    cat = load_catalog()
    todo = missing_requirements(cat)
    if args.guid:
        want = {g.upper() for g in args.guid}
        todo = [r for r in todo if r["guid"] in want]
    if not todo:
        say("Nothing is missing: every package version your demos need is available.")
        return 0
    game = cfg.game()
    sysdir = cfg.system_dir(game) if game else None
    if not sysdir or not (sysdir / "UCC.exe").exists():
        say("PROBLEM: the game folder is needed to unpack .uz files (finish the setup first).")
        return 1
    work = cfg.out() / "_work" / "fetch"
    work.mkdir(parents=True, exist_ok=True)
    bases = list(dict.fromkeys(args.redirect + core.redirect_sources(sysdir, []) + EXTRA_REDIRECTS))
    bases = [b if b.endswith("/") else b + "/" for b in bases]
    say(f"Looking for {len(todo)} missing package version(s) on {len(bases)} redirect servers, "
        "in the Wayback Machine and in GitHub releases. Only exact versions (same GUID) are kept.")
    tried_digests: dict[str, str] = {}  # Wayback digest -> GUID inside
    found = 0
    # one Wayback question per redirect folder for every missing file at once (it answers slowly)
    all_names = sorted({f for r in todo for f in core.candidate_filenames(r)})
    say("Asking the Wayback Machine which old copies it has (this takes a minute or two) ...")
    copies: dict[str, list[tuple[str, str, str]]] = {}
    for base in bases:
        for ts, orig, dg in wayback_copies(base, all_names):
            copies.setdefault(urllib.parse.unquote(orig.rsplit("/", 1)[-1])[:-3].lower(), []).append((ts, orig, dg))
    say(f"  {sum(len(v) for v in copies.values())} archived copies found")

    def check(data: bytes | None, fname: str, req: dict, where: str) -> bool:
        nonlocal found
        if not data:
            return False
        out = core.unpack_uz(data, fname, work, sysdir, say)
        if out is None and data[:4] == b"\xc1\x83\x2a\x9e":  # a plain package, not compressed
            out = work / (fname + ".unpacked")
            out.write_bytes(data)
        if out is None:
            return False
        info = read_package(out, deep=False) or {}
        check.last = info.get("guid") or "?"
        ok = info.get("guid") == req["guid"]
        if ok:
            add_package(out, fname, where)
            say(f"  FOUND {req['pkg']} ({req['guid'][:8]}..) at {where}")
            found += 1
        else:
            say(f"    {where}: another version ({(info.get('guid') or '?')[:8]}..)")
        out.unlink(missing_ok=True)
        return ok

    for n, req in enumerate(todo, 1):
        say(f"=== [{n}/{len(todo)}] ===")
        say(f"{req['pkg']}  version {req['guid']}  ({req['size']:,} bytes, needed by {len(req['demos'])} demo(s))")
        names = core.candidate_filenames(req)
        hit = False
        # 1. redirect servers as they are now
        for fname in names:
            for base in bases:
                url = base + urllib.parse.quote(fname) + ".uz"
                if check(_get(url, 30), fname, req, url):
                    hit = True
                    break
            if hit:
                break
        # 2. every copy the Wayback Machine archived of those files (any date, any of the folders)
        if not hit:
            for fname in names:
                for ts, orig, digest in sorted(copies.get(fname.lower(), [])):
                    if digest in tried_digests and tried_digests[digest] != req["guid"]:
                        continue  # already looked inside: another version
                    say(f"    Wayback copy of {orig} from {ts[:4]}-{ts[4:6]}-{ts[6:8]}")
                    check.last = "?"
                    ok = check(_get(f"https://web.archive.org/web/{ts}id_/{orig}", 120, tries=3), fname, req,
                               f"web.archive.org ({orig} on {ts[:8]})")
                    tried_digests[digest] = check.last
                    if ok:
                        hit = True
                        break
                if hit:
                    break
        # 3. GitHub releases of mods that publish their packages there
        if not hit and req["pkg"].lower() in core.GITHUB_REPOS:
            repo = core.GITHUB_REPOS[req["pkg"].lower()]
            demo_time = None
            for dn in req["demos"]:
                demo_time = core.demo_start(dn) or demo_time
            got = core.github_package(req, repo, demo_time, work, say)
            if got:
                add_package(got[0], got[1], f"github.com/{repo}")
                say(f"  FOUND {req['pkg']} ({req['guid'][:8]}..) in the GitHub releases of {repo}")
                got[0].unlink(missing_ok=True)
                found += 1
                hit = True
        if not hit:
            say("  not found")
            note_online(req["guid"], False)
    left = len(todo) - found
    say(f"Done: {found} of {len(todo)} found (kept with the packages found online)"
        + (f"; {left} still missing (see Packages, Missing)." if left else "."))
    return 0


def table(_args) -> int:
    print(json.dumps(table_data()))
    return 0


def table_data() -> dict:
    """Compact data for the Packages page."""
    cat = load_catalog()
    demo_of: dict[str, int] = {}
    for d in cat.get("demos", {}).values():
        for g in d.get("requires", []):
            demo_of[g] = demo_of.get(g, 0) + 1
    kinds = ["game", "base", "folder", "download"]
    rows = [[p["file"], p["type"], 1 if p.get("stock") else 0, p["size"], g, demo_of.get(g, 0),
             "/".join(str(kinds.index(k)) for k in where(cat, p))]
            for g, p in cat["packages"].items()]
    base = {}
    try:
        base = json.loads((cfg.BASE_PACK / "pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {"summary": summary(cat), "rows": rows, "missing": missing_detail(cat), "roots": cat.get("roots", []),
            "kinds": [KIND_LABEL[k] for k in kinds], "index_exists": CATALOG.exists(),
            "base": {"count": base.get("count", 0), "made": base.get("made"), "folder": str(cfg.BASE_PACK)}}


def stats(_args) -> int:
    print(json.dumps(summary(), indent=1))
    return 0


def basepack(args) -> int:
    return make_base_pack(Path(args.dest))


def main() -> int:
    ap = argparse.ArgumentParser(description="Killcam '99 packages")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="refresh the index: game folder, packs and your package folders (only read)")
    b = sub.add_parser("basepack", help="make the base pack to ship (every community version the demos need)")
    b.add_argument("dest")
    sub.add_parser("stats", help="print the summary")
    sub.add_parser("table", help=argparse.SUPPRESS)
    fe = sub.add_parser("fetch", help="look online for the package versions your demos need but you do not have")
    fe.add_argument("--redirect", action="append", default=[], help="extra redirect folder (URL) to try")
    fe.add_argument("--guid", action="append", default=[], help="only this version (repeatable)")
    args = ap.parse_args()
    return {"build": build, "basepack": basepack, "stats": stats, "table": table, "fetch": fetch}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
