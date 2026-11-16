#!/usr/bin/env python3
"""
ut_stream.py - clips from stream recordings (OBS / Streamlabs) by READING THE SCREEN.

A stream recording shows the same HUD messages the game sends to a demo:

    You killed nanstuko                      <- kill line   (cyan)
    DiAteR^ returns the red flag!            <- info line   (cyan: flag events, killing sprees)
    Multi Kill!                              <- multi kill  (red)

This module reads those three lines from the video and turns them into the very same message
list a demo scan produces (time, class, switch, text, own ...). From there on the clips are
planned by the demo pipeline's own rules (ut99_dem2video.plan_parts), so a recording gets the
same clips, with the same lead-in and run-out, as the demo of that match would.

No demo is needed and none is used. Sound is not used either. Only --stream-compare looks at
demo scans, and only to report how well the screen reading agrees with them (trial phase).

Stages (each one is a plain function, results are cached in <out>/stream_scans):
    1. frames    ffmpeg cuts the message area out of the video, a few frames per second
    2. reading   the text colour is separated from the background, Windows' built-in text
                 recognition (Windows.Media.Ocr) reads many frames at once
    3. tracking  readings of the same message in consecutive frames become one message
    4. messages  -> demo-scan style message list (kills, multi kills, sprees, flag events)
    5. clips     plan_parts() + the same cutting as for demos
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path


def _core():
    """The demo tool's module. When it is the running script it is '__main__' (importing it by
    name would create a second copy with its own settings)."""
    m = sys.modules.get("__main__")
    if m is not None and hasattr(m, "plan_parts") and hasattr(m, "clip_dest"):
        return m
    import ut99_dem2video
    return ut99_dem2video


core = _core()
say = core.say

SCAN_VERSION = 6
# Message area for a 1920x1080 picture (x is centred): wide enough for long names, high enough
# for the kill line, the info line and the largest multi kill text. Other sizes are scaled.
AREA_W, AREA_H, AREA_Y = 1000, 125, 240
ZOOM = 1.5          # the area is enlarged this much for reading (measured: 1.0 misreads more, 2.0 is 3x slower)
PIC_W, PIC_H = int(AREA_W * ZOOM), int(AREA_H * ZOOM) // 2 * 2
# The match clock of the HUD (bottom, left of the middle) for a 1920x1080 picture. It stands
# still during warm-up and after the match; only what happens while it runs is counted.
CLOCK_X, CLOCK_Y, CLOCK_W, CLOCK_H = 722, 1038, 104, 42
GAP = 14            # white rows between the frames stacked into one picture for the text reader
BATCH = 24          # frames per picture
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --------------------------------------------------------------------------------------
# 2. reading: Windows' own text recognition, kept running as a helper process
# --------------------------------------------------------------------------------------

PS_OCR = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(); $t.Result }
$eng = $null
try { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('en-US')) } catch {}
if (-not $eng) { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $eng) { [Console]::Out.WriteLine('##NOENGINE'); exit 3 }
[Console]::Out.WriteLine('##READY ' + $eng.RecognizerLanguage.LanguageTag + ' ' + [Windows.Media.Ocr.OcrEngine]::MaxImageDimension)
[Console]::Out.Flush()
while ($true) {
    $path = [Console]::In.ReadLine()
    if ($null -eq $path -or $path -eq '') { break }
    try {
        $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
        $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $res = Await ($eng.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
        foreach ($line in $res.Lines) {
            $x0 = 1e9; $y0 = 1e9; $x1 = 0; $y1 = 0
            foreach ($w in $line.Words) {
                $r = $w.BoundingRect
                if ($r.X -lt $x0) { $x0 = $r.X }; if ($r.Y -lt $y0) { $y0 = $r.Y }
                if ($r.X + $r.Width -gt $x1) { $x1 = $r.X + $r.Width }
                if ($r.Y + $r.Height -gt $y1) { $y1 = $r.Y + $r.Height }
            }
            [Console]::Out.WriteLine(('{0:F0}' -f $x0) + "`t" + ('{0:F0}' -f $y0) + "`t" + ('{0:F0}' -f ($x1 - $x0)) + "`t" + ('{0:F0}' -f ($y1 - $y0)) + "`t" + ($line.Text -replace "[`t`r`n]", ' '))
        }
        $stream.Dispose()
    } catch { [Console]::Out.WriteLine('##ERROR ' + ($_.Exception.Message -replace "[`r`n]", ' ')) }
    [Console]::Out.WriteLine('##END')
    [Console]::Out.Flush()
}
'''


class TextReader:
    """Windows.Media.Ocr behind a small PowerShell helper: a picture file in, text lines with
    their place in the picture out. Nothing has to be installed (part of Windows 10/11)."""

    def __init__(self, work: Path):
        work.mkdir(parents=True, exist_ok=True)
        self.script = work / "ut_stream_ocr.ps1"
        self.script.write_text(PS_OCR, encoding="utf-8-sig")
        self.p = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(self.script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        first = self.p.stdout.readline().strip()
        if not first.startswith("##READY"):
            err = (self.p.stderr.read() or "").strip()[-400:]
            raise RuntimeError("Windows text recognition could not be started"
                               + (" (no recognition language installed: Settings > Time & language > "
                                  "Language > add English)" if "NOENGINE" in first else f": {first} {err}"))
        parts = first.split()
        self.language = parts[1] if len(parts) > 1 else "?"
        self.max_dim = int(float(parts[2])) if len(parts) > 2 else 2600

    def read(self, picture: Path) -> list[tuple[float, float, float, float, str]]:
        self.p.stdin.write(str(picture) + "\n")
        self.p.stdin.flush()
        out = []
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("the text recognition helper stopped: " + (self.p.stderr.read() or "")[-300:])
            line = line.rstrip("\r\n")
            if line == "##END":
                return out
            if line.startswith("##ERROR"):
                say(f"    note: text recognition: {line[8:]}")
                continue
            c = line.split("\t", 4)
            if len(c) == 5:
                out.append((float(c[0]), float(c[1]), float(c[2]), float(c[3]), c[4]))

    def close(self) -> None:
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def write_bmp(path: Path, rgb) -> None:
    """RGB picture (height x width x 3) as a 24-bit BMP (no imaging library needed)."""
    import struct
    import numpy as np
    h, w = rgb.shape[:2]
    row = (w * 3 + 3) & ~3
    data = np.zeros((h, row), np.uint8)
    data[:, :w * 3] = rgb[::-1, :, ::-1].reshape(h, w * 3)
    with open(path, "wb") as f:
        f.write(b"BM" + struct.pack("<IHHI", 54 + row * h, 0, 0, 54))
        f.write(struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, row * h, 2835, 2835, 0, 0))
        f.write(data.tobytes())


# --------------------------------------------------------------------------------------
# 1. frames: the message area of the video, a few times per second
# --------------------------------------------------------------------------------------

def video_info(ffmpeg: str, src: Path) -> tuple[int, int, float]:
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(src)], capture_output=True, text=True,
                       errors="replace", creationflags=NO_WINDOW)
    m = re.search(r"Stream #\d+:\d+.*?: Video:.*?\b(\d{3,5})x(\d{3,5})\b", r.stderr)
    d = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0.0
    return (int(m.group(1)), int(m.group(2)), dur) if m else (0, 0, dur)


def message_area(width: int, height: int, custom: str | None = None) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the message area in the video's own pixels. custom: 'x,y,w,h' for 1920x1080
    (for a HUD that sits elsewhere, e.g. the game shown smaller inside the stream picture)."""
    s = height / 1080.0
    if custom:
        x, y, w, h = (float(v) for v in custom.split(","))
        box = (x * s, y * s, w * s, h * s)
    else:
        box = (width / 2 - AREA_W * s / 2, AREA_Y * s, AREA_W * s, AREA_H * s)
    x, y, w, h = (int(round(v / 2)) * 2 for v in box)
    x, y = max(0, x), max(0, y)
    return x, y, min(w, width - x), min(h, height - y)


def clock_area(width: int, height: int, custom: str | None = None) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the HUD's match clock in the video's own pixels. custom: 'x,y,w,h' for 1920x1080."""
    s = height / 1080.0
    if custom:
        x, y, w, h = (float(v) * s for v in custom.split(","))
    else:
        x, y, w, h = width / 2 + (CLOCK_X - 960) * s, CLOCK_Y * s, CLOCK_W * s, CLOCK_H * s
    x, y, w, h = (int(round(v / 2)) * 2 for v in (x, y, w, h))
    x, y = max(0, x), max(0, y)
    return x, y, max(2, min(w, width - x)), max(2, min(h, height - y))


def frames(ffmpeg: str, src: Path, area: tuple[int, int, int, int], fps: float, start: float = 0.0,
           length: float | None = None, clock: tuple[int, int, int, int] | None = None):
    """Yields (time in the recording, RGB picture of the message area (PIC_W x PIC_H),
    grey picture of the match clock (CLOCK_W x CLOCK_H) or None). One pass over the video."""
    import numpy as np
    x, y, w, h = area
    if clock:
        cx, cy, cw, ch = clock
        vf = (f"[0:v]fps={fps:g},split=2[a][b];"
              f"[a]crop={w}:{h}:{x}:{y},scale={PIC_W}:{PIC_H}:flags=lanczos[m];"
              f"[b]crop={cw}:{ch}:{cx}:{cy},scale={CLOCK_W}:{CLOCK_H}:flags=bilinear,pad={PIC_W}:{CLOCK_H}:0:0[c];"
              f"[m][c]vstack=inputs=2[o]")
        graph = ["-filter_complex", vf, "-map", "[o]"]
        rows = PIC_H + CLOCK_H
    else:
        graph = ["-map", "0:v:0", "-vf", f"crop={w}:{h}:{x}:{y},fps={fps:g},scale={PIC_W}:{PIC_H}:flags=lanczos"]
        rows = PIC_H
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if length:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-an", *graph, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    size = PIC_W * rows * 3
    buf = bytearray(size)
    view = memoryview(buf)
    i = 0
    try:
        while True:
            got = 0
            while got < size:
                n = p.stdout.readinto(view[got:])
                if not n:
                    break
                got += n
            if got < size:
                break
            pic = np.frombuffer(bytes(buf), np.uint8).reshape(rows, PIC_W, 3)
            yield (start + i / fps, pic[:PIC_H],
                   pic[PIC_H:, :CLOCK_W].min(axis=2).astype(np.float32) if clock else None)   # digits are white
            i += 1
    finally:
        p.kill()
        p.wait()


class ClockWatch:
    """Second by second: did the last digit of the match clock change? Kept as one character
    per second of the recording: '#' changed, '_' the same as the second before, '.' clock not
    on screen (scoreboard, menu, loading). The digit is taken from all frames of a second
    together (a pixel counts when most frames have it), which removes the flicker a moving
    background causes. Measured on real recordings: a running clock gives about 3 '#' out of
    4, a clock that stands still (warm-up, after the match) about 1 out of 10."""

    def __init__(self):
        self.seconds: list[str] = []
        self.now = -1
        self.masks: list = []
        self.frames = 0
        self.prev = None

    def _close(self) -> None:
        import numpy as np
        if self.now < 0:
            return
        while len(self.seconds) < self.now:
            self.seconds.append(".")
        if len(self.masks) * 3 < self.frames * 2 or not self.masks:
            self.seconds.append(".")
        else:
            most = np.sum(self.masks, axis=0) * 2 > len(self.masks)
            if self.prev is None:
                self.seconds.append("_")
            else:
                diff = int((most ^ self.prev).sum())
                self.seconds.append("#" if diff >= 0.2 * max(1, int(most.sum()), int(self.prev.sum())) else "_")
            self.prev = most
        self.masks, self.frames = [], 0

    def look(self, t: float, white) -> None:
        sec = int(t)
        if sec != self.now:
            self._close()
            self.now = sec
        self.frames += 1
        m = stand_out(white, 6) > 20
        if 0.06 * m.size <= int(m.sum()) <= 0.21 * m.size:     # the digits fill 10-15% of the box
            self.masks.append(m[:, m.shape[1] * 3 // 4:])

    def result(self) -> dict:
        self._close()
        self.now = -1
        return {"seconds": "".join(self.seconds)}


def standstill(clock: dict | None, window: int = 10) -> list[tuple[float, float]]:
    """The stretches in which the match clock stood still: warm-up before a match and the time
    after its end. A second counts as 'still' when under 30% of the seconds around it (10 on
    each side, those with the clock on screen) show a change. Short stalls inside a match (the
    clock sometimes hangs a few seconds and then jumps) stay far above that."""
    sec = (clock or {}).get("seconds") or ""
    if "#" not in sec and "_" not in sec:
        return []
    still: list[bool | None] = []
    for i in range(len(sec)):
        part = sec[max(0, i - window): i + window + 1]
        seen = len(part) - part.count(".")
        still.append(None if seen < 8 else part.count("#") < 0.3 * seen)
    last = None
    for i, v in enumerate(still):          # clock hidden: as it was before (before it first shows: still)
        if v is None:
            still[i] = True if last is None else last
        else:
            last = v
    out: list[tuple[float, float]] = []
    i = 0
    while i < len(still):
        if not still[i]:
            i += 1
            continue
        j = i
        while j < len(still) and still[j]:
            j += 1
        # sharpen the edges: the match runs from the first second after which the clock keeps changing
        a, b = i, j
        for k in range(max(0, j - window), min(len(sec), j + window)):
            if sec[k:k + 4].count("#") >= 3:
                b = k
                break
        # ... and it started with the first change shortly before that (rather count a second
        # of warm-up than lose a kill made in the first second of the match)
        first = sec.find("#", max(a, b - 6), b)
        if first >= 0:
            b = first
        if i > 0:
            for k in range(min(len(sec), i + window), max(0, i - window), -1):
                if sec[max(0, k - 4):k].count("#") >= 3:
                    a = k
                    break
        if b > a:
            a2, b2 = (0.0 if i == 0 else float(a)), (float(len(sec)) if j >= len(still) else float(b))
            if out and a2 - out[-1][1] < 20:      # under 20 s of 'running' in between is not a match
                out[-1] = (out[-1][0], b2)
            else:
                out.append((a2, b2))
        i = j
    return out


def text_layers(rgb):
    """How strongly each pixel has one of the HUD's two text colours: cyan (kill line, info
    line) and red (multi kills)."""
    import numpy as np
    a = rgb.astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    cyan = np.clip(np.minimum(b - r, (g + b) / 2 - r), 0, None)
    red = np.clip(r - np.maximum(g, b), 0, None)
    return cyan, red


def stand_out(score, k: int = 9):
    """The same, minus the average around each pixel: a blue wall or a red banner behind the
    text is flat colour and drops out, thin strokes of that colour (letters) remain."""
    import numpy as np
    p = np.pad(score, k, mode="edge")
    ii = np.pad(p.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    w = 2 * k + 1
    box = (ii[w:, w:] - ii[:-w, w:] - ii[w:, :-w] + ii[:-w, :-w]) / (w * w)
    return np.clip(score - box, 0, None)


def may_hold_text(strokes) -> bool:
    """Cheap test before the (slow) reading: enough thin strokes of a text colour in the middle
    part of the area, where every HUD message is centred. Measured on real recordings: frames
    with a readable message have 160+ such pixels (at zoom 1), 3 out of 4 frames without have
    under 25."""
    w = strokes.shape[1]
    mid = strokes[:, w // 7: w - w // 7]
    return int((mid > 30).sum()) >= 110 * ZOOM * ZOOM / 4      # strokes come at half size


def red_print(strokes):
    """The red strokes as dark text on white (a faint multi kill text over a bright wall is
    read from this when the plain picture does not give it)."""
    import numpy as np
    g = (255 - np.clip(strokes * 2.5, 0, 255)).astype(np.uint8)
    return np.repeat(g[..., None], 3, axis=2)


# --------------------------------------------------------------------------------------
# what a line of text means
# --------------------------------------------------------------------------------------

def letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def alike(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def name_key(name: str) -> str:
    """A name reduced to what the text reader can tell apart: letters and digits only, and the
    look-alikes it mixes up made equal ('iMpure' is also read as 'ilVlpure', 'l' as 'I' or '1',
    'o' as '0', 'rn' as 'm')."""
    k = re.sub(r"[^a-z0-9]", "", name.lower())
    k = k.replace("1", "i").replace("l", "i").replace("0", "o").replace("5", "s")
    return k.replace("ivi", "m").replace("rn", "m").replace("vv", "w")


MULTI_WORDS = ["doublekill", "multikill", "triplekill", "megakill", "ultrakill", "monsterkill",
               "ludicrouskill", "holyshit"]
SPREE_TAILS = [("isonakillingspree", "killingspree"), ("isonarampage", "rampage"), ("isdominating", "dominating"),
               ("isunstoppable", "unstoppable"), ("isgodlike", "godlike"), ("iswickedsick", "whickedsick"),
               ("iswhickedsick", "whickedsick")]
# Botpack.CTFMessage: switch 0 captured, 1 returns, 2 dropped, 4 has (the switch a demo scan shows)
FLAG_TAILS = [("returnsthe", 1), ("droppedthe", 2), ("capturedthe", 0), ("hasthe", 4)]


def read_multi(text: str) -> str | None:
    """Red line -> the multi kill it announces (the demo tool's call names), else None."""
    t = letters(text)
    if len(t) < 6:
        return None
    best = max(MULTI_WORDS, key=lambda w: alike(t, w))
    if alike(t, best) < 0.74:
        return None
    return core.msg_call("Botpack.MultiKillMessage", 0, best)


def read_info(text: str) -> tuple[str, str, object] | None:
    """Cyan line -> (kind, player name, detail):
    ('kill', victim, None)  ('death', killer, None)  ('spree', who, call)  ('flag', who, switch)."""
    words = text.replace("|", "I").split()
    if len(words) < 2:
        return None
    low = [letters(w) for w in words]
    if len(words) >= 3 and alike(low[0] + low[1], "youkilled") >= 0.78:
        name = "".join(words[2:]).rstrip("!.,")
        return ("kill", name, None) if name else None
    if len(words) >= 5 and alike("".join(low[:4]), "youwerekilledby") >= 0.8:
        name = "".join(words[4:]).rstrip("!.,")
        return ("death", name, None) if name else None
    for i in range(1, len(words)):
        tail = "".join(low[i:])
        if low[i] in ("is", "ls", "js") or alike(low[i], "is") == 1.0:
            for phrase, call in SPREE_TAILS:
                if alike("is" + tail[len(low[i]):], phrase) >= 0.82:
                    return "spree", "".join(words[:i]), call
        for phrase, switch in FLAG_TAILS:
            head = "".join(low[i:i + 2])
            if alike(head, phrase) >= 0.8 and "flag" in tail[len(phrase) - 2:]:
                return "flag", "".join(words[:i]), switch
    return None


# --------------------------------------------------------------------------------------
# 2 + 3. reading every frame, then following each message from frame to frame
# --------------------------------------------------------------------------------------

def read_recording(ffmpeg: str, src: Path, area, fps: float, work: Path, dur: float,
                   start: float = 0.0, length: float | None = None, debug: Path | None = None,
                   clock=None) -> tuple[list[dict], dict]:
    """Every readable message line of every sampled frame:
    [{t, line: 'kill'|'info'|'multi', kind, name, detail, strength, text}].
    Per frame up to two strips go to the text reader: the plain picture (reads all three lines
    when the text is clear) and the red strokes alone (multi kill text that is faint)."""
    import numpy as np
    reader = TextReader(work)
    watch = ClockWatch()
    seen: list[dict] = []
    batch: list[tuple[float, str, object, object]] = []   # (time, 'plain'|'red', strip, colour scores)
    pics: list[Path] = []   # the helper may keep a picture open for a moment: a new file each time
    n_frames = n_read = n_pics = 0
    t_begin = last_note = time.time()
    rows = PIC_H + GAP

    def flush() -> None:
        nonlocal n_pics
        if not batch:
            return
        sheet = np.full((len(batch) * rows, PIC_W, 3), 255, np.uint8)
        for i, (_t, _c, strip, _sc) in enumerate(batch):
            sheet[i * rows:i * rows + PIC_H] = strip
        pic = work / f"ut_stream_frames_{os.getpid()}_{n_pics:05d}.bmp"
        for old in pics[:-1]:
            try:
                old.unlink()
                pics.remove(old)
            except OSError:
                pass
        pics.append(pic)
        write_bmp(pic, sheet)
        if debug is not None and n_pics < 40:
            debug.mkdir(parents=True, exist_ok=True)
            write_bmp(debug / f"{src.stem}.sheet{n_pics:03d}.bmp", sheet)
        n_pics += 1
        for x, y, w, h, text in reader.read(pic):
            i = int((y + h / 2) // rows)
            if not 0 <= i < len(batch):
                continue
            t, kind_of_strip, _strip, (cyan, red) = batch[i]
            y -= i * rows
            if abs(x + w / 2 - PIC_W / 2) > 90 * ZOOM:
                continue                      # every HUD message is centred
            sl = (slice(max(0, int(y)), int(y + h) + 1), slice(max(0, int(x)), int(x + w) + 1))
            call = read_multi(text)
            if call:
                box = red[sl]
                seen.append({"t": t, "line": "multi", "kind": "multi", "name": "", "detail": call,
                             "strength": float(np.percentile(box, 96)) if box.size else 0.0, "text": text})
                continue
            got = read_info(text) if kind_of_strip == "plain" else None
            if got:
                kind, name, detail = got
                box = cyan[sl]
                seen.append({"t": t, "line": "kill" if kind in ("kill", "death") else "info", "kind": kind,
                             "name": name, "detail": detail,
                             "strength": float(np.percentile(box, 96)) if box.size else 0.0, "text": text})
        batch.clear()

    try:
        for t, rgb, clock_pic in frames(ffmpeg, src, area, fps, start, length, clock):
            n_frames += 1
            if clock_pic is not None:
                watch.look(t, clock_pic)
            cyan, red = text_layers(rgb)
            red_strokes = stand_out(red[::2, ::2])
            has_red = may_hold_text(red_strokes)
            if has_red or may_hold_text(stand_out(cyan[::2, ::2])):
                batch.append((t, "plain", rgb, (cyan, red)))
                n_read += 1
            if has_red:
                batch.append((t, "red", red_print(stand_out(red, 18)), (cyan, red)))
            if len(batch) >= min(BATCH, max(2, reader.max_dim // rows - 1)):
                flush()
            if time.time() - last_note > 30:
                last_note = time.time()
                say(f"    ... {core.fmt_dur(t)} of {core.fmt_dur(dur)} read")
        flush()
    finally:
        reader.close()
        for old in pics:
            try:
                old.unlink()
            except OSError:
                pass
    say(f"    {n_frames} frames looked at, {n_read} of them read, "
        f"{len(seen)} message readings ({time.time() - t_begin:.0f} s)")
    return seen, watch.result()


SHOWN = 3.05   # a HUD message stays 3 seconds


def track(seen: list[dict], fps: float, you: str = "") -> list[dict]:
    """Readings of one message in consecutive frames -> one message with its first moment.
    The HUD has one kill line, one info line and one multi kill line; a new message replaces
    the old one. The same text read again while a message is on screen is taken as that same
    message. (Killing the same player twice within 3 seconds does happen with instant respawns;
    the kill line then does not change, but the multi kill text does: see add_streaks.)
    you: your player name if known; unclear readings that resemble it count as it."""
    step = 1.0 / fps
    settle_names(seen, you)
    # a name that was read only once or twice in the whole recording is a misreading
    weight = Counter(s["name"] for s in seen if s["name"])
    out: list[dict] = []
    recent: dict[str, list[dict]] = {"kill": [], "info": [], "multi": []}
    line_last: dict[str, dict] = {}
    for s in sorted(seen, key=lambda s: s["t"]):
        if s["name"] and (s["name"] == "?" or weight[s["name"]] < 3):
            continue
        line = recent[s["line"]]
        line[:] = [m for m in line if s["t"] - m["t_seen"] <= SHOWN or (m is line[-1] and s["t"] - m["last"] <= 1.0
                                                                       and s["line"] == "kill")]
        # the message now on this line, or an earlier one that was last read under a second ago
        # (the reader flickering between two readings of one message)
        hit = next((m for m in reversed(line) if m["kind"] == s["kind"] and m["detail"] == s["detail"]
                    and m["name"] == s["name"] and (m is line[-1] or s["t"] - m["last"] <= 1.0)), None)
        if hit is None and line and s["line"] == "kill":
            # Still the same text without a break, longer than a message lasts: the same player
            # was killed again and the line started over. It stays one display here (how many
            # kills it holds is worked out in add_streaks); cutting it at 3 seconds would
            # invent a kill at that moment.
            m = line_last.get("kill")
            if (m is not None and m["kind"] == s["kind"] and m["name"] == s["name"]
                    and s["t"] - m["last"] <= 1.0):
                hit = m
                line.append(m)
        if hit is not None:
            hit["last"], hit["n"] = s["t"], hit["n"] + 1
            hit["texts"][s["text"]] += 1
            # A message never comes back once a newer one has replaced it. So whatever was read
            # on this line in between was this same message, misread: drop those. (For multi
            # kills the level only goes up, so there a lower level in between is dropped too.)
            for m in line[line.index(hit) + 1:]:
                m["drop"] = True
            del line[line.index(hit) + 1:]
            continue
        m = {"t": max(0.0, s["t"] - step / 2), "t_seen": s["t"], "last": s["t"], "line": s["line"],
             "kind": s["kind"], "detail": s["detail"], "name": s["name"], "strength": round(s["strength"], 1),
             "n": 1, "texts": Counter({s["text"]: 1})}
        line.append(m)
        line_last[s["line"]] = m
        out.append(m)
    out = [m for m in out if not m.get("drop")]
    for m in out:
        m["text"] = m["texts"].most_common(1)[0][0]
        m["shown"] = round(m["last"] - m["t_seen"] + step, 2)
        m["until"] = round(m["last"], 3)
        for k in ("texts", "last", "t_seen"):
            m.pop(k)
        m["t"] = round(m["t"], 3)
    # a multi kill text read in a single frame only is kept when a kill of yours is right there
    kills = [m["t"] for m in out if m["kind"] == "kill"]
    out = [m for m in out if not (m["kind"] == "multi" and m["n"] < 2
                                  and not any(abs(k - m["t"]) <= 1.5 for k in kills))]
    out.sort(key=lambda m: m["t"])
    return out


def settle_names(events: list[dict], you: str = "") -> dict[str, str]:
    """One spelling per player: the text recognition reads a name slightly differently now and
    then ('scarz' / 'scar.'); every reading is mapped to the spelling seen most often."""
    for e in events:              # a reading that is only a piece of a name ('Di') is not a name
        if e["name"] and len(name_key(e["name"])) < 3:
            e["name"] = "?"
    count = Counter(e["name"] for e in events if e["name"] and e["name"] != "?")
    canon: list[str] = []
    mapping: dict[str, str] = {}
    if you:
        # Your own name is the hardest to read ('-]Clan[-Player^-': brackets, and it is in
        # the lines that matter most). A reading that shares a good part with it is it.
        yk = name_key(you)
        canon.append(you)
        for name in count:
            k = name_key(name)
            block = difflib.SequenceMatcher(None, k, yk).find_longest_match(0, len(k), 0, len(yk)).size
            if alike(k, yk) >= 0.6 or block >= max(5, len(yk) // 2):
                mapping[name] = you
        for e in events:
            if e["name"] in mapping:
                e["name"] = you
        count = Counter(e["name"] for e in events if e["name"] and e["name"] != "?")
    for name, _n in count.most_common():
        k = name_key(name)
        hit = next((c for c in canon if name_key(c) == k or alike(name_key(c), k) >= 0.8
                    or (len(k) >= 3 and name_key(c).startswith(k))), None)
        if hit is None:
            canon.append(name)
            hit = name
        mapping[name] = hit
    for e in events:
        if e["name"] and e["name"] != "?":
            e["name"] = mapping[e["name"]]
    return mapping


# --------------------------------------------------------------------------------------
# 4. messages in the demo-scan format
# --------------------------------------------------------------------------------------

def is_player(name: str, player: str) -> bool:
    a, b = name_key(name), name_key(player)
    return bool(a and b) and (a == b or alike(a, b) >= 0.72)


def to_messages(events: list[dict], player: str) -> list[dict]:
    """Tracked screen messages -> the message list the demo tool plans clips from. 'recorder'
    means 'about you' there: your kills, your multi kills, flag events with your name."""
    msgs: list[dict] = []
    for e in events:
        t, name = e["t"], e["name"]
        base = {"t": t, "where": "screen", "seen": e["n"], "shown": e["shown"], "until": e.get("until", t)}
        if e["kind"] == "kill":
            msgs.append({**base, "class": "Botpack.KillerMessagePlus", "switch": 0, "recorder": True,
                         "own": True, "who": player, "text": f"You killed {name}", "call": None})
        elif e["kind"] == "death":
            msgs.append({**base, "class": "Botpack.VictimMessage", "switch": 0, "recorder": False,
                         "own": False, "who": name, "text": f"You were killed by {name}!", "call": None})
        elif e["kind"] == "multi":
            msgs.append({**base, "class": "Botpack.MultiKillMessage", "switch": 0, "recorder": True,
                         "own": True, "who": player, "text": e["text"], "call": e["detail"]})
        elif e["kind"] == "spree":
            own = is_player(name, player)
            msgs.append({**base, "class": "Botpack.KillingSpreeMessage", "switch": 0, "recorder": own,
                         "own": own, "who": name, "text": e["text"], "call": e["detail"]})
        elif e["kind"] == "flag":
            own = is_player(name, player)
            msgs.append({**base, "class": "Botpack.CTFMessage", "switch": int(e["detail"]), "recorder": own,
                         "own": own, "who": name, "text": e["text"], "call": None})
    add_streaks(msgs)
    add_sprees(msgs, player)
    msgs.sort(key=lambda m: m["t"])
    return msgs


SPREES = ["killingspree", "rampage", "dominating", "unstoppable", "godlike"]


def add_sprees(msgs: list[dict], player: str) -> None:
    """The game announces a spree level every 5 kills without dying (5 = killing spree, 10 =
    rampage, 15 = dominating ...). The info line shows one message at a time, so a spree line
    can be pushed away by a flag message before it is read. A level that WAS read proves the
    levels below it: they happened 5, 10 ... of your kills earlier, and are added there."""
    kills = sorted(m["t"] for m in msgs if m["class"].endswith("KillerMessagePlus"))
    own = [m for m in msgs if m["class"].endswith("KillingSpreeMessage") and m["own"] and m["call"] in SPREES]
    for m in sorted(own, key=lambda m: m["t"]):
        at = [i for i, k in enumerate(kills) if k <= m["t"] + 0.6]
        if not at:
            continue
        i, level = at[-1], SPREES.index(m["call"])
        for lower in range(level - 1, -1, -1):
            j = i - 5 * (level - lower)
            if j < 0:
                break
            t = kills[j]
            if any(x["call"] == SPREES[lower] and abs(x["t"] - t) <= 8.0 for x in own):
                continue
            x = {"t": t, "where": "screen", "class": "Botpack.KillingSpreeMessage", "switch": 0, "recorder": True,
                 "own": True, "who": player, "text": SPREES[lower], "call": SPREES[lower], "seen": 0,
                 "shown": 0.0, "until": t, "inferred": f"implied by the {m['call']} read later"}
            msgs.append(x)
            own.append(x)


LEVELS = {"doublekill": 1, "multikill": 2, "megakill": 3, "ultrakill": 3, "monsterkill": 4,
          "ludicrouskill": 5, "holyshit": 6}


def add_streaks(msgs: list[dict], window: float = 3.0, sure: float = 2.6) -> None:
    """Tie every multi kill text to the kill that caused it and give it its streak (the kills
    that led to it: clips start before the first one, and a flag carrier among them makes it a
    carrier kill).

    A multi kill text appears in the same instant as a kill of yours. So it also PROVES a kill:
    - the kill line changed shortly before or after it: that kill (the text is often readable
      a moment later than the kill line);
    - the kill line still shows an older kill: the same player was killed again (instant
      respawn), the kill line looks the same, so that kill is added here;
    - no kill line readable at all: a kill of an unknown player is added.

    The other way round, a streak the kill line shows but whose red text could not be read
    (bright background) is added from the kill times; only gaps under `sure` seconds between
    clearly read kills of different players count there (the game's own limit is 3 game
    seconds, 2.7 s on a 110% server)."""
    def is_kill(m):
        return m["class"].endswith("KillerMessagePlus")

    multis = sorted((m for m in msgs if m["class"].endswith("MultiKillMessage")), key=lambda m: m["t"])
    taken: set[int] = set()
    for m in multis:
        kills = sorted((k for k in msgs if is_kill(k)), key=lambda k: k["t"])
        near = [k for k in kills if -1.3 <= k["t"] - m["t"] <= 0.8 and id(k) not in taken]
        if near:
            k = max(near, key=lambda k: k["t"])
        else:
            shown = [k for k in kills if k["t"] < m["t"] and k.get("until", k["t"]) >= m["t"] - 0.5]
            victim = shown[-1]["text"][11:] if shown else "?"
            k = {"t": m["t"], "where": "screen", "class": "Botpack.KillerMessagePlus", "switch": 0,
                 "recorder": True, "own": True, "who": m.get("who", ""), "text": f"You killed {victim}",
                 "call": None, "seen": 0, "shown": 0.0, "until": m["t"],
                 "inferred": "same player killed again" if shown else "kill line not readable"}
            msgs.append(k)
        taken.add(id(k))
        m["t"] = k["t"]
    # A kill message lasts 3 seconds. A kill line that stays longer than that after its last
    # known kill was started over once more: the same player killed again, more than 2.7 s
    # after the kill before (so without a multi kill text).
    lives = sorted(k["until"] - k["t"] for k in msgs if is_kill(k) and k.get("seen", 0) >= 3)
    life = min(3.0, max(1.5, lives[len(lives) // 2])) if lives else 3.0   # how long one stays readable
    for k in [k for k in msgs if is_kill(k) and k.get("seen", 0) >= 2]:
        again = [x["t"] for x in msgs if is_kill(x) and x is not k and x.get("inferred")
                 and k["t"] < x["t"] <= k["until"] + 0.5 and x["text"] == k["text"]]
        last = max([k["t"]] + again)
        if k["until"] - last > 3.3:
            msgs.append({"t": round(max(last + 2.7, k["until"] - life), 3), "where": "screen",
                         "class": "Botpack.KillerMessagePlus",
                         "switch": 0, "recorder": True, "own": True, "who": k.get("who", ""), "text": k["text"],
                         "call": None, "seen": 0, "shown": 0.0, "until": k["until"],
                         "inferred": "same player killed again (the kill line stayed longer than 3 s)"})
    kills = sorted(((k["t"], k["text"][11:]) for k in msgs if is_kill(k)))
    solid = {k["t"] for k in msgs if is_kill(k) and k.get("seen", 0) >= 2}
    used: set[float] = set()
    for m in multis:
        chain: list[list] = []
        for k in reversed([k for k in kills if k[0] <= m["t"]]):
            if chain and (chain[0][0] - k[0] > window + 0.4 or len(chain) > LEVELS.get(m["call"], 1)):
                break
            chain.insert(0, list(k))
        m["chain"] = chain
        used.update(k[0] for k in chain[1:])
        botpack = core.MULTIKILL_TABLES["multikillmessage"].get(len(chain) - 1)
        if botpack and botpack != m["call"]:
            m["alt_call"] = botpack
    scheme = core.MULTIKILL_TABLES["mmultikillmessage" if any(m["call"] == "megakill" for m in multis)
                                   else "multikillmessage"]
    level, chain = 0, []
    for i, (t, victim) in enumerate(kills):
        if (i and t - kills[i - 1][0] < sure and t in solid and kills[i - 1][0] in solid
                and victim != kills[i - 1][1]):
            level += 1
        else:
            level, chain = 0, []
        chain.append([t, victim])
        if level and t not in used and not any(abs(m["t"] - t) <= 1.2 for m in multis) and scheme.get(level):
            msgs.append({"t": t, "where": "screen", "class": "Botpack.MultiKillMessage", "switch": level,
                         "recorder": True, "own": True, "who": "", "text": scheme[level], "call": scheme[level],
                         "chain": [list(c) for c in chain], "inferred": "level from the kill times",
                         "seen": 0, "shown": 0.0, "until": t})


# --------------------------------------------------------------------------------------
# scan of one recording (cached)
# --------------------------------------------------------------------------------------

def scan_file(args, rec: Path) -> Path:
    return args.out / "stream_scans" / (rec.stem + ".json")


def find_player(events: list[dict], rec: Path, args) -> str:
    """Your player name, needed to tell YOUR sprees, flag returns and captures from the other
    players' (kills and multi kills are yours anyway: only you get those lines).
    1. --player;  2. read from the recording itself: 'X is on a killing spree!' appears in the
    same moment as one of your kills only when X is you;  3. the name the demo file closest in
    time to this recording starts with (your name at that time; the demo itself is not used)."""
    if getattr(args, "player", None):
        return args.player
    on_screen = Counter(e["name"] for e in events if e["kind"] in ("spree", "flag") and e["name"])
    kills = [e["t"] for e in events if e["kind"] == "kill"]
    votes = Counter(e["name"] for e in events if e["kind"] == "spree"
                    and any(abs(k - e["t"]) <= 0.6 for k in kills))
    enemies = {e["name"] for e in events if e["kind"] in ("kill", "death")}
    for name, n in votes.most_common():
        if name not in enemies and n >= 2:
            say(f"    your player name, read from the screen: {name}")
            return name
    guess = nearest_demo_player(rec, args)
    if guess:
        hit = next((n for n, _c in on_screen.most_common() if is_player(n, guess)), None)
        say(f"    your player name: {hit or guess} (from your demo files' names"
            + ("" if hit else "; not seen on screen in this recording") + ")")
        return hit or guess
    if votes:
        name = votes.most_common(1)[0][0]
        say(f"    your player name, read from the screen: {name}")
        return name
    say("    your player name is not known (use --player): your sprees and flag events are not recognised")
    return ""


def nearest_demo_player(rec: Path, args) -> str:
    try:
        when = core.recording_start(rec, 0.0)[0]
    except OSError:
        return ""
    best: tuple[float, str] | None = None
    names: set[str] = set()
    try:
        for d in core.demo_search_folders(args):
            names.update(f.name for f in d.glob("*.dem"))
            names.update(f.name for f in d.glob("*/*.dem"))
        scans = args.out / "scans"
        if scans.is_dir():
            names.update(f.name for f in scans.glob("*.json"))
    except OSError:
        pass
    for n in names:
        who, ds = core.demo_player(n), core.demo_start(n)
        if who and ds is not None and (best is None or abs(ds - when) < best[0]):
            best = (abs(ds - when), who)
    return best[1] if best else ""


def scan_recording(ffmpeg: str, rec: Path, args) -> dict | None:
    """Read one recording's screen messages (or load the saved reading)."""
    st = rec.stat()
    fps = float(getattr(args, "stream_fps", None) or 6.0)
    out = scan_file(args, rec)
    if out.exists() and not getattr(args, "rescan", False):
        try:
            r = json.loads(out.read_text(encoding="utf-8"))
            if (r.get("version") == SCAN_VERSION and r.get("size") == st.st_size
                    and r.get("mtime") == int(st.st_mtime) and r.get("fps") == fps
                    and r.get("area_custom") == getattr(args, "stream_area", None)
                    and r.get("clock_custom") == getattr(args, "stream_clock", None)):
                say(f"    screen reading from {out.name} (saved earlier)")
                return r
        except ValueError:
            pass
    w, h, dur = video_info(ffmpeg, rec)
    if not w:
        say("    skipped (no picture in this file)")
        return None
    area = message_area(w, h, getattr(args, "stream_area", None))
    say(f"    reading the screen: {w}x{h}, message area {area[2]}x{area[3]} at ({area[0]},{area[1]}), {fps:g} frames/s")
    work = args.out / "_work"
    debug = (args.out / "obs_debug") if getattr(args, "obs_debug", False) else None
    seen, clock = read_recording(ffmpeg, rec, area, fps, work, dur, debug=debug,
                                 clock=clock_area(w, h, getattr(args, "stream_clock", None)))
    for x in seen:
        x["t"], x["strength"] = round(x["t"], 3), round(x["strength"], 1)
    # the raw readings are what is saved: messages are worked out from them every time, so a
    # better rule later does not need the (slow) reading again
    r = {"version": SCAN_VERSION, "recording": rec.name, "size": st.st_size, "mtime": int(st.st_mtime),
         "fps": fps, "area": list(area), "area_custom": getattr(args, "stream_area", None),
         "clock_custom": getattr(args, "stream_clock", None),
         "duration": dur, "readings": seen, "clock": clock}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(r), encoding="utf-8")
    os.replace(tmp, out)
    return r


def events_of(r: dict, you: str = "") -> list[dict]:
    """Messages from the saved readings. Each reading's text is interpreted again, so better
    rules apply to recordings that were read earlier."""
    seen = []
    for x in r["readings"]:
        x = dict(x)
        call = read_multi(x["text"])
        got = None if call else read_info(x["text"])
        if call:
            x.update(line="multi", kind="multi", name="", detail=call)
        elif got and x["kind"] != "multi":
            x.update(line="kill" if got[0] in ("kill", "death") else "info", kind=got[0], name=got[1], detail=got[2])
        else:
            continue
        seen.append(x)
    return track(seen, r["fps"], you)


def match_only(events: list[dict], r: dict, args) -> list[dict]:
    """Leave out what happened while the match clock stood still: warm-up before the match and
    anything after its end. (--include-warmup keeps it.)"""
    still = standstill(r.get("clock"))
    clock = (r.get("clock") or {}).get("seconds") or ""
    if "#" not in clock and "_" not in clock:
        say("    note: the match clock was not found on screen, so warm-up cannot be told from the match "
            "(everything is counted; --stream-clock X,Y,W,H says where the clock is)")
        return events
    if getattr(args, "include_warmup", False) or not still:
        return events
    still = [(a, b) for a, b in still if b - a >= 8]
    if not still:
        return events
    kept = [e for e in events if not any(a <= e["t"] <= b for a, b in still)]
    kills = sum(1 for e in events if e["kind"] == "kill") - sum(1 for e in kept if e["kind"] == "kill")
    say("    match clock standing still (warm-up / after the match): "
        + ", ".join(f"{core.fmt_dur(a)}-{core.fmt_dur(b)}" for a, b in still)
        + f"; left out there: {len(events) - len(kept)} message(s), {kills} of them kills of yours")
    return kept


def describe(msgs: list[dict]) -> str:
    """Totals the way a scoreboard counts them: every streak once, under the highest level it
    reached (a Multi Kill is not also counted as a Double Kill, a Rampage not also as a
    Killing Spree)."""
    kills = sum(1 for m in msgs if m["class"].endswith("KillerMessagePlus"))
    mk = sorted((m for m in msgs if m["class"].endswith("MultiKillMessage")), key=lambda m: m["t"])
    multi: Counter = Counter()
    for m in mk:
        if not any(0 < n["t"] - m["t"] <= 3.3 and LEVELS.get(n["call"], 0) > LEVELS.get(m["call"], 0) for n in mk):
            multi[m["call"]] += 1
    sp = sorted((m for m in msgs if m["class"].endswith("KillingSpreeMessage") and m["own"] and m["call"] in SPREES),
                key=lambda m: m["t"])
    spree: Counter = Counter()
    for a, b in zip(sp, sp[1:] + [None]):
        if b is None or SPREES.index(b["call"]) != SPREES.index(a["call"]) + 1:
            spree[a["call"]] += 1
    flags = Counter({1: "flag returns", 0: "captures"}.get(m["switch"]) for m in msgs
                    if m["class"].endswith("CTFMessage") and m["own"] and m["switch"] in (0, 1))
    bits = [f"{kills} kills"]
    bits += [f"{n}x {core.display(c)}" for c, n in sorted(multi.items(), key=lambda kv: LEVELS.get(kv[0], 9))]
    bits += [f"{n}x {core.display(c)}" for c, n in sorted(spree.items(), key=lambda kv: SPREES.index(kv[0]))]
    bits += [f"{n} {c}" for c, n in flags.items()]
    return ", ".join(bits) + "  (each streak counted once, under its highest level)"


# --------------------------------------------------------------------------------------
# 5. clips
# --------------------------------------------------------------------------------------

def cut_clips(ffmpeg: str, rec: Path, msgs: list[dict], dur: float, args, enc, out_dir: Path) -> list[Path]:
    ext = "mp4" if rec.suffix.lower() in (".mp4", ".mov", ".m4v", ".flv") else "mkv"
    if args.obs_reencode:
        ext = args.format
    clips: list[Path] = []
    planned: set[str] = set()
    for a, b, names, t_call in core.plan_parts(msgs, args):
        if b <= 0 or a >= dur:
            continue
        a, b = max(0.0, a), min(dur, b) if dur else b
        dst = core.clip_dest(out_dir, names, rec.stem, t_call, ext)
        planned.add(dst.name)
        if dst.exists() and not args.overwrite:
            continue
        inferred = any(m.get("inferred") and m["class"].endswith("MultiKillMessage") and a <= m["t"] <= b
                       for m in msgs)
        say(f"    {core.fmt_dur(t_call)}  {'+'.join(names)}" + ("  (level from the kill times)" if inferred else ""))
        ok = (core.cut_span(ffmpeg, rec, a, b - a, dst, enc, None, 0.0, ext, cover_marker=False)
              if args.obs_reencode else core.cut_copy(ffmpeg, rec, a, b - a, dst))
        if ok:
            clips.append(dst)
            core.add_to_index(args, dst, source="obs", origin=rec.name, category=core.clip_category(names),
                              labels=[core.display(x) for x in names], t_call=t_call,
                              check=("multi kill level worked out from the kill times (its text was not readable)"
                                     if inferred else "read from the screen"),
                              warn=inferred, timing="screen")
    # clips of this recording from an earlier reading that the current one no longer gives:
    # they are kept (never deleted here), only pointed out
    try:
        old = [x for x in json.loads(core.index_file(args).read_text(encoding="utf-8"))
               if x.get("source") == "obs" and x.get("origin") == rec.name
               and Path(x["file"]).name not in planned and (args.out / x["file"]).exists()]
    except (OSError, ValueError):
        old = []
    for x in old:
        say(f"    note: an earlier clip is not found any more with the current reading and settings (kept): "
            f"{Path(x['file']).name}")
    return clips


def stream_mode(args, ut_dir: Path | None) -> int:
    """--obs: read the HUD messages of stream recordings and cut the clips. The recordings are
    only read; clips go to <out>/obs_clips, the readings to <out>/stream_scans."""
    src = Path(args.obs) if args.obs else Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Videos"
    explicit = [Path(x) for x in getattr(args, "obs_files", [])]
    if not src.exists() and not explicit:
        say(f"PROBLEM: folder not found: {src}")
        return 1
    ffmpeg = core.find_ffmpeg()
    if not ffmpeg:
        say("PROBLEM: ffmpeg not found  ->  winget install Gyan.FFmpeg")
        return 1
    try:
        import numpy  # noqa: F401
    except ImportError:
        say("PROBLEM: numpy missing  ->  py -m pip install numpy")
        return 1
    if os.name != "nt":
        say("PROBLEM: reading the screen uses Windows' text recognition (Windows 10/11 only).")
        return 1
    if src.is_file():
        explicit.append(src)
    files = explicit or sorted(p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in core.VIDEO_EXTS
                               and not core.inside(p, args.out))
    if args.only:
        files = [p for p in files if args.only.lower() in p.name.lower()]
    out_dir = core.clip_dirs(args.out)["obs_clips"]
    done_file = args.out / "obs_processed.txt"
    ledger = core.obs_ledger(args)
    enc = core.clip_encoder_args(core.pick_encoder(ffmpeg, args.encoder), args.clip_quality) if args.obs_reencode else []
    say(f"Stream recordings: {len(files)}" + ("" if explicit else f" in {src}"))
    n_done = n_clips = 0
    for f in files:
        st = f.stat()
        key = f"{st.st_size}|{int(st.st_mtime)}|{f}"
        status, _when = ledger.get(key, (None, 0.0))
        # 'retry' was the old sound-based method waiting for a demo: such recordings are read now
        if (status and status != "retry" and not args.overwrite and not explicit
                and not getattr(args, "rescan", False) and scan_file(args, f).exists()):
            continue
        if time.time() - st.st_mtime < 120:
            say(f"  skipped (still being written?): {f.name}")
            continue
        if args.limit and n_done >= args.limit:
            break
        say(f"Recording: {f.name}")
        try:
            r = scan_recording(ffmpeg, f, args)
        except RuntimeError as e:
            say(f"PROBLEM: {e}")
            return 1
        if r is None:
            continue
        player = find_player(events_of(r), f, args)
        events = events_of(r, player)        # again, now knowing which unclear names are yours
        events = match_only(events, r, args)
        msgs = to_messages(events, player)
        say(f"    on screen: {describe(msgs)}")
        if getattr(args, "stream_compare", False):
            compare_with_demos(f, r, msgs, args)
        clips = cut_clips(ffmpeg, f, msgs, r["duration"], args, enc, out_dir)
        say(f"  {len(clips)} clip(s) saved" + (f" in {out_dir}" if clips else ""))
        n_clips += len(clips)
        n_done += 1
        with open(done_file, "a", encoding="utf-8") as fh:
            fh.write(f"{key}\tdone\t{time.time():.0f}\n")
    say(f"Stream recordings finished: {n_done} read, {n_clips} clip(s).")
    if n_clips:
        core.offer_review(args)
    return 0


# --------------------------------------------------------------------------------------
# trial phase: how well does the screen reading agree with the demo of the same match?
# --------------------------------------------------------------------------------------

def _pairs(a: list[tuple[float, str]], b: list[tuple[float, str]], tol: float, same=None):
    """Greedy one-to-one matching of two event lists by time (and `same(label_a, label_b)`)."""
    left = list(b)
    hit, miss = [], []
    for t, x in a:
        cand = [(abs(t2 - t), i) for i, (t2, y) in enumerate(left) if abs(t2 - t) <= tol and (same is None or same(x, y))]
        if cand:
            _d, i = min(cand)
            hit.append(((t, x), left.pop(i)))
        else:
            miss.append((t, x))
    return hit, miss, left


def compare_with_demos(rec: Path, r: dict, msgs: list[dict], args) -> list[dict]:
    """For every scanned demo that ran during this recording: line the two up (clocks first, then
    the kill lines themselves) and count what the demo has, what the screen reading found, what
    it missed and what it has extra. Written to the log and <out>/stream_scans/<name>.compare.txt."""
    dur = r["duration"]
    rec_start, _exact = core.recording_start(rec, dur)
    scans = args.out / "scans"
    lines: list[str] = []
    results: list[dict] = []
    screen_kills = [(m["t"], m["text"][11:]) for m in msgs if m["class"].endswith("KillerMessagePlus")]
    for f in sorted(scans.glob("*.json")) if scans.is_dir() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not d.get("end"):
            continue
        ds, _ex = core.scan_demo_start(d, args)
        total = d.get("total") or 0
        if ds is None or ds + total < rec_start - 120 or ds > rec_start + dur + 120:
            continue
        dm = core.refresh_calls(d["messages"], core.demo_player(d["demo"]), core.scan_speed(d, args)[0])
        demo_kills = [(t, v or "") for t, k, v in core.own_kills_detail(dm) if k]
        clock = ds - rec_start
        # the kill lines give the exact shift: most common difference between same-victim kills
        diffs = Counter(round((ts - td) * 2) / 2 for ts, vs in screen_kills for td, vd in demo_kills
                        if abs(ts - td - clock) < 150 and is_player(vs, vd))
        if not diffs or diffs.most_common(1)[0][1] < 3:
            lines.append(f"  compare: {d['demo']} ran during this recording (by the clocks) but its kills "
                         "do not line up with the screen")
            continue
        rough = diffs.most_common(1)[0][0]
        near = sorted(ts - td for ts, vs in screen_kills for td, vd in demo_kills
                      if abs(ts - td - rough) <= 0.75 and is_player(vs, vd))
        shift = near[len(near) // 2]
        lo, hi = max(0.0, shift), min(dur, shift + total)

        def inside(t):
            return lo + 1.0 <= t + shift <= hi - 1.0

        def screen(pred):
            return [(m["t"], lab) for m in msgs for lab in [pred(m)] if lab is not None and lo <= m["t"] <= hi]

        def demo(pred):
            return [(m["t"] + shift, lab) for m in dm for lab in [pred(m)] if lab is not None and inside(m["t"])]

        rows = []

        def row(title, d_ev, s_ev, tol, same=None):
            hit, miss, extra = _pairs(d_ev, s_ev, tol, same)
            rows.append({"what": title, "demo": len(d_ev), "found": len(hit), "missed": miss, "extra": extra})

        same_name = lambda a, b: is_player(a, b)  # noqa: E731
        row("your kills", [(t + shift, v) for t, v in demo_kills if inside(t)],
            [(t, v) for t, v in screen_kills if lo <= t <= hi], 0.8, same_name)
        row("your multi kills",
            demo(lambda m: m["call"] if m.get("derived") and m.get("call") in LEVELS else None),
            screen(lambda m: m["call"] if m["class"].endswith("MultiKillMessage") else None), 1.2,
            lambda a, b: a == b)
        row("your sprees",
            demo(lambda m: m["call"] if m["own"] and m["class"].lower().endswith("killingspreemessage") and m["call"] else None),
            screen(lambda m: m["call"] if m["own"] and m["class"].endswith("KillingSpreeMessage") else None), 1.5,
            lambda a, b: a == b)
        for sw, title in ((1, "your flag returns"), (0, "your captures")):
            row(title,
                demo(lambda m: "x" if m.get("recorder") and m["class"].lower().endswith(".ctfmessage") and int(m["switch"]) == sw else None),
                screen(lambda m: "x" if m["own"] and m["class"].endswith("CTFMessage") and m["switch"] == sw else None), 1.5)
        row("flag drops (others)",
            demo(lambda m: m.get("who", "") if not m.get("recorder") and m["class"].lower().endswith(".ctfmessage") and int(m["switch"]) == 2 else None),
            screen(lambda m: m["who"] if not m["own"] and m["class"].endswith("CTFMessage") and m["switch"] == 2 else None),
            1.5, same_name)
        d_parts = [(a + shift, b + shift, n) for a, b, n, _t in core.plan_parts(dm, args) if inside((a + b) / 2)]
        s_parts = [(a, b, n) for a, b, n, _t in core.plan_parts(msgs, args) if lo <= (a + b) / 2 <= hi]
        both = [(p, q) for p in d_parts for q in s_parts if min(p[1], q[1]) - max(p[0], q[0]) > 2.0]
        lines.append(f"  compare with demo {d['demo']}: shift {shift:+.2f}s (clocks {clock:+.1f}s), "
                     f"{core.fmt_dur(hi - lo)} in common")
        for x in rows:
            if not x["demo"] and not x["extra"]:
                continue
            lines.append(f"    {x['what']:<20} demo {x['demo']:>3}   found {x['found']:>3}   missed {len(x['missed']):>3}"
                         f"   extra on screen {len(x['extra']):>3}")
            for t, lab in x["missed"][:12]:
                lines.append(f"        missed  {core.fmt_dur(t)}  {lab}")
            for t, lab in x["extra"][:12]:
                lines.append(f"        extra   {core.fmt_dur(t)}  {lab}")
        lines.append(f"    clips: the demo plans {len(d_parts)}, the screen reading {len(s_parts)}, "
                     f"{len({id(p) for p, _q in both})} of the demo's are covered")
        for p in d_parts:
            q = next((q for pp, q in both if pp is p), None)
            lines.append(f"        demo {core.fmt_dur(p[0])}-{core.fmt_dur(p[1])} {'+'.join(p[2])}  ->  "
                         + (f"screen {core.fmt_dur(q[0])}-{core.fmt_dur(q[1])} {'+'.join(q[2])}"
                            + ("" if q[2] == p[2] else "   (label differs)")
                            + ("" if abs(q[0] - p[0]) <= 1.5 and abs(q[1] - p[1]) <= 1.5 else "   (cut differs)")
                            if q else "NOT FOUND on screen"))
        for q in s_parts:
            if not any(qq is q for _p, qq in both):
                lines.append(f"        screen only: {core.fmt_dur(q[0])}-{core.fmt_dur(q[1])} {'+'.join(q[2])}")
        results.append({"demo": d["demo"], "shift": shift, "rows": rows, "demo_parts": d_parts, "screen_parts": s_parts})
    if not lines:
        lines.append("  compare: no scanned demo ran during this recording")
    for ln in lines:
        say(ln)
    try:
        out = scan_file(args, rec).with_suffix(".compare.txt")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    return results
