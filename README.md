<div align="center">

# Killcam '99

**Turns your Unreal Tournament (UT99) demos and gameplay recordings into kill clips, automatically.**

Multi Kills · Monster Kills · Ludicrous · Holy Shit · Godlike sprees · flag returns and captures

![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-2f6fc0)
![Game](https://img.shields.io/badge/game-Unreal%20Tournament%20%2B%20OldUnreal%20469-555)
![Python](https://img.shields.io/badge/python-3.12%20(bundled)-3776ab)
![License](https://img.shields.io/badge/license-MIT-2e8b3e)

</div>

---

## Contents

- [What Killcam '99 does](#what-killcam-99-does)
- [Highlights](#highlights)
- [Getting started](#getting-started)
  - [What you need](#what-you-need)
  - [Option A: download the ready-to-run release](#option-a-download-the-ready-to-run-release)
  - [Option B: run it from this repository](#option-b-run-it-from-this-repository)
  - [The first start: the setup wizard](#the-first-start-the-setup-wizard)
  - [Your first clips, step by step](#your-first-clips-step-by-step)
- [User guide](#user-guide)
  - [Demos](#demos)
  - [Recordings (OBS / Streamlabs)](#recordings-obs--streamlabs)
  - [Clips](#clips)
  - [Packages](#packages)
  - [Options](#options)
  - [Help, keys, console](#help-keys-console)
  - [Drag and drop, text menu, command line](#drag-and-drop-text-menu-command-line)
  - [Updating and uninstalling](#updating-and-uninstalling)
- [How it works](#how-it-works)
  - [The big picture](#the-big-picture)
  - [How a moment is recognised, in plain words](#how-a-moment-is-recognised-in-plain-words)
  - [Architecture diagram](#architecture-diagram)
  - [From demo to clip: the pipeline](#from-demo-to-clip-the-pipeline)
  - [The in-game add-on (UT2VidHook)](#the-in-game-add-on-ut2vidhook)
  - [Parallel scans](#parallel-scans)
  - [Recording a clip](#recording-a-clip)
  - [Clips from stream recordings (screen reading / OCR)](#clips-from-stream-recordings-screen-reading--ocr)
  - [Packages: exact versions by GUID](#packages-exact-versions-by-guid)
  - [The two setup modes](#the-two-setup-modes)
  - [The app: a local web window](#the-app-a-local-web-window)
  - [Folder layout and data files](#folder-layout-and-data-files)
- [Design decisions and crossroads](#design-decisions-and-crossroads)
- [Repository layout](#repository-layout)
- [Building a release](#building-a-release)
- [Developing](#developing)
- [Reference](#reference)
  - [settings.json](#settingsjson)
  - [Command line options](#command-line-options)
  - [Log messages worth knowing](#log-messages-worth-knowing)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Known limitations and roadmap](#known-limitations-and-roadmap)
- [Privacy: what goes online](#privacy-what-goes-online)
- [Contributing](#contributing)
- [License, third-party content and fair use](#license-third-party-content-and-fair-use)

---

## What Killcam '99 does

Unreal Tournament can record a **demo** of every match you play (`demorec` in the console, or automatically with
many server setups). A demo is not a video: it is a recording of the network traffic of the match, and only the
game engine itself can turn it back into pictures. That makes demos tiny and perfect, but useless for sharing
on YouTube, Discord or social media until someone sits through the whole match with a screen recorder running.

**Killcam '99 does that for you, and only for the moments that matter.** It:

1. **plays each demo in the background at about 40× speed** to find *your* big moments: the announcer calls
   (Multi Kill, Monster Kill, Godlike ...), your flag returns and captures, killing the enemy flag carrier;
2. **plays only those moments again at normal speed** and records picture and sound;
3. **cuts each moment into a clip** with a few seconds of build-up and aftermath, named after the match, the map,
   the time and what happened, and sorts it into a folder per kind of moment;
4. lets you **review** the clips in its own window: keep the good ones, reject the rest.

It does the same for gameplay you recorded with **OBS or Streamlabs**: it *reads the kill messages from the
picture* and cuts the clips out of the recording. No demo, no game, no sound analysis needed.

And because a demo only plays with the **exact version** of every map, mod and texture the server used, it also
manages those **packages**: it knows which versions every demo needs, finds them in your folders, in a shipped
base pack, or online, and tells you precisely (down to the GUID) what is still missing.

## Highlights

| | |
|---|---|
| **Only your moments** | Only *your own* announcer calls count; other players' sprees never make a clip. |
| **Fast** | Kill-finding runs at ~35–40× real time, several demos side by side. A 15-minute demo is searched in under 30 seconds. |
| **Background recording** | Uses ffmpeg's Windows Graphics Capture (`gfxcapture`, ffmpeg 8.1+): you can keep working while it records. |
| **OBS / Streamlabs** | Cuts clips straight from stream recordings by reading the on-screen kill messages with Windows' built-in text recognition (OCR). No demo, no game, no sound analysis. |
| **Pick your moments** | Demos *and* recordings list every moment worth a clip first; click the ones you want and only those are recorded or cut. Picking from a recording takes seconds, because its reading is saved. |
| **Free disk space** | Delete clips you do not want (one by one, or every rejected clip at once) and see how much space your clips take. Deleted clips are remembered and not made again. |
| **Exact packages** | GUID-exact package tracking, a 137-version base pack, your own folders, and online search (redirect servers, Wayback Machine, GitHub releases). |
| **Safe with your game** | Either a separate copy of UT (your folder is only read), or your own folder with a byte-for-byte undo. |
| **Self-contained** | Unzip and double-click. Python is bundled; ffmpeg is downloaded once by the setup. Nothing is installed on the PC. |
| **Plain app window** | A local, offline web UI in its own Edge app window: Demos, Recordings, Clips, Packages, Options, Help. |

---

## Getting started

### What you need

- **Windows 10 or 11**, 64-bit.
- **Unreal Tournament** (original or GOTY) with the **[OldUnreal 469 patch](https://www.oldunreal.com)**.
  The patch includes *udemo*, which Killcam '99 relies on. The OldUnreal site also offers a complete installer
  that downloads the game from archive.org with Epic's consent.
- **Disk space**: about 600 MB for Killcam '99 itself (most of it the base pack and the bundled Python), plus
  the size of your UT folder (usually 1–3 GB) if you choose *Make a separate copy*, plus your clips.
- **Internet once**, to download ffmpeg (about 100 MB) during the setup. Searching online for missing packages
  is optional.

### Option A: download the ready-to-run release

1. Go to **[Releases](../../releases)** and download `Killcam99-<version>.zip`.
2. Unzip it anywhere you like (your Documents, a second drive), but **not inside your UnrealTournament folder**.
3. Double-click **`Killcam99.bat`**.
   Windows may say *"Windows protected your PC"* because the tool is not signed with a paid certificate:
   click **More info → Run anyway**.
4. The setup wizard opens (see [below](#the-first-start-the-setup-wizard)).

After unzipping you see only this:

```
Killcam99\
  Killcam99.bat     start here (files can also be dropped on it)
  README.txt        the manual for players
  app\              everything else (hidden after the first start)
```

`Clips\` appears next to them on the first start.

### Option B: run it from this repository

The repository has exactly the installed layout, so a clone runs as-is; it just uses *your* Python instead of
the bundled one.

```bash
git clone https://github.com/fnlz-cybs/killcam99.git
```

```bash
py -3 -m pip install numpy pyaudiowpatch
```

Then double-click `Killcam99.bat` in the cloned folder. It looks for `app\python\python.exe` first and falls back
to `py -3` / `python`. Python 3.10 or newer works; the release bundles 3.12.

> **Note:** the clone is about 530 MB because the base pack (`app/packs/base`) is committed as plain files.
> To build the same self-contained zip as the release, see [Building a release](#building-a-release).

### The first start: the setup wizard

The wizard has four steps. You can run it again any time from **Options → Game → Open setup**.

**1 · Find Unreal Tournament.** Killcam '99 lists the UT folders it finds (registry, common install paths, your
Desktop). Pick the folder you play from (the one whose `System` folder holds `UnrealTournament.exe`), or use
*Browse*. It checks that it really is UT with udemo (the 469 patch).

**2 · How should Killcam '99 use it?** Both choices make exactly the same clips; the difference is where
Killcam '99 is allowed to write:

| | **Make a separate copy** (safest) | **Use my UT folder directly** (no extra space) |
|---|---|---|
| Where it works | a copy in `app\UT` | the folder you play from |
| Your UT folder | only ever **read** | gets 1 add-on file + the packages demos need (in `Cache`) |
| Your settings files | untouched | untouched (the game runs with private ini copies) |
| Extra disk space | size of your UT folder | ~18 KB |
| Play UT while clips are made | yes | no |
| Picks up new maps/patches | after *Options → Game → Update* | immediately |
| Undo | delete the copy | *Options → Game → Remove* restores the folder byte-for-byte |

**3 · Your folders.** *Demos* (UT saves them in its `System` folder unless you chose another one), *Recordings*
(optional: where OBS/Streamlabs saves), and *Clips* (default: the `Clips` folder next to `Killcam99.bat`).

**4 · Set up.** Prepares the game, reads which packages are available, and downloads ffmpeg if it is missing.
When it says **All set**, press *Open Demos*.

### Your first clips, step by step

1. Open **Demos**. Every `.dem` file in your demo folder is listed, newest first.
2. Press **Make clips from new demos**.
   - Each new demo is first played very fast (nothing is recorded) to find your moments.
   - Then only the moments worth a clip are played at normal speed and recorded.
3. Watch the progress in the status bar at the bottom; press <kbd>`</kbd> for the console with every message.
4. When the job is done, a notice tells you how many new clips there are. Press <kbd>3</kbd> (or the *Clips*
   menu) to review them.
5. Your videos are in **`Clips\Demos\<kind of moment>\`**, for example:

```
Clips\Demos\Monster Kill\2026-04-19 21.42 CTF-Rune - 07m00s Monster Kill + Flag Return.mp4
```

> **While recording:** do not minimise the game window, and keep music, videos and voice chat quiet: every
> sound your PC plays ends up in the clip (or pick the game's output device in *Options → Speed and sound*).

---

## User guide

### Demos

| Element | What it does |
|---|---|
| **Make clips from new demos** | Find kills in every demo not looked at yet, then record all moments worth a clip. |
| **Find kills in new demos** | Only the fast search; nothing is recorded. Use it to pick moments yourself. |
| **Find kills in all demos again** | Search every demo again (after an update, or when results look wrong). Clips stay. |
| **Moments** | Each found moment is a chip like `4:30 Monster Kill`. Click to pick it (it turns blue), then *Record these moments*. The eye icon plays just that moment in the game. |
| **Watch** | Plays the whole demo in the game at normal speed with sound. |
| **Packages** | Every package version this demo needs and where each one is. |
| **Remove** | Takes the demo off the list (the `.dem` file is **not** touched). Removed demos are skipped by every job; the *Removed* filter has *Put back*. |
| **Selection bar** | Tick demos to *Make clips*, *Find kills again* or *Remove from list* for several at once. |

Status labels: *Not looked at* · *To record* · *Partly recorded* · *Recorded* · *No moments* · and a red
**N packages missing** label when a demo needs a version you do not have (click it for the details).

### Recordings (OBS / Streamlabs)

Point the folder at the top to where OBS or Streamlabs saves (*Change*). Then either:

- **Make clips from new recordings**: reads every new recording (about a quarter of its length) and cuts every
  moment worth a clip; or
- **Find moments in new recordings**: reads them but cuts nothing. Each recording then lists its moments as chips,
  like `13:29 Multi Kill + Flag Carrier Kill + Flag Return`, with a tick on the ones already cut. Click the moments
  you want (they turn blue) and press **Cut these moments** in the bar that appears. Cutting picked moments uses the
  saved reading, so it takes seconds.

| Element | What it does |
|---|---|
| **Moments worth a clip** | Worked out from the saved reading with your *current* clip options: change a trigger or the clip length and the list follows, without reading the recording again. |
| **Find moments** (per row) | Read one new recording and list its moments. |
| **Cut all** (per row) | Cut every moment of that recording that is not cut yet (deleted clips are not brought back). |
| **Read again** | Read a recording from scratch and list its moments again; nothing is cut, your clips stay. |
| Status | *Not read yet* · *Moments found* (read, nothing cut) · *Clips made* · *still being written?* (a recording OBS is still writing is skipped until it is finished) |

Clips go to **`Clips\Recordings\`**.

*Your player name*: leave empty to detect it, or type the name used in those recordings. The name that was found
is remembered per recording, so the moments shown are the same ones that get cut.
*Exact cuts*: frame-exact starts by re-encoding (slower).

### Clips

All clips, playable right in the window, with counters (clips, not reviewed yet, kept, rejected, space on disk) and
filters (kind of moment, state, demos vs recordings).

| Element | What it does |
|---|---|
| **Counters** | Clips, not reviewed yet, kept, rejected, and the space your clips take **on disk**. |
| **Filters** | Kind of moment (Monster Kill, Flag Return, ...), state (not rejected, not reviewed yet, kept, with a warning, rejected, everything), and source (demos, recordings or both). |
| **Keep** | Marks a clip as good. It stays where it is. |
| **Reject** | Moves the clip to `Clips\Rejected\`. A rejected clip is not made again. |
| **Restore** | Moves a rejected clip back. |
| **Delete** (red bin) | Deletes the clip file for good to free disk space. A confirmation shows what is deleted and how much space it frees, and that it cannot be undone. |
| **Delete rejected** | Appears when there are rejected clips: deletes all of them at once, showing their number and total size first. |
| **Open clips folder** | Opens `Clips\` in Explorer (Demos, Recordings and Rejected are inside). |
| Folder icon | Shows that one clip in Explorer. |
| Warning text | A clip with a possible problem (for example *choppy*, or a multi kill level worked out from the kill times because its text could not be read) says so under its title. |

**Deleted clips are remembered.** Their entry stays in the clip list with the state *deleted* (the file is gone).
*Make clips* treats such a moment as done, so it is not recorded or cut again; picking that moment again on purpose
makes a new clip. Deleting a clip file in Explorer works too, but such a clip is *not* remembered and is made again
the next time you make clips from that demo or recording.

### Packages

A demo plays only with the **exact version** (GUID) of every package the server used. The *Packages* page has
three tabs:

- **Missing**: every version your demos need that none of the places has: name, file, full GUID (with a copy
  button), size, generation, which demos need it, which **other versions** of it you do have, and when it was
  last searched online. *Search online* per version or for all of them; *Add a folder that has them*.
- **Where to look**: the places, in lookup order, with how many versions each holds:
  1. your game folder, 2. the **base pack** that ships with Killcam '99, 3. **your own folders**,
  4. packages **found online** earlier. *Refresh packages* re-reads them; *Add a folder* points at another UT
  install, a map collection or a cache folder (only ever read).
- **All packages**: everything known, searchable, filterable (maps, textures, sounds, music, code; community vs
  retail; needed by demos), and exportable as a spreadsheet (`UT_files.csv`).

### Options

| Tab | Settings |
|---|---|
| **Clips** | Which announcer calls make a clip: Mega/Ultra/Monster/Ludicrous Kill, Holy Shit, Multi Kill; Killing Spree, Rampage, Dominating, Unstoppable, Godlike, Wicked Sick. **Combos**: a Multi Kill or better followed by your flag return or capture within N seconds, or a Multi Kill in which you kill the enemy flag carrier. |
| **Length and output** | Seconds before the streak / after the last kill, settle time after a jump, MP4 or MKV, quality (High/Normal/Small). |
| **Speed and sound** | Demos searched at the same time (Auto = what the CPU can carry), search speed (× real time), recording device. |
| **Folders** | Demos, recordings, clips; delete temporary recordings. |
| **Game** | The UT folder in use and the mode; *Open setup*; *Update* (copy and add-on); *Remove* (direct mode undo); *Delete* the separate copy. |
| **App** | Own window (Edge app mode), desktop notifications, developer tools, reset to defaults. |

### Help, keys, console

*Help* shows a **system check** (with fix buttons), the keys, the version, and **Copy diagnostics** (versions,
folders, checks and the end of the log, for bug reports).

| Key | Action |
|---|---|
| <kbd>1</kbd>–<kbd>6</kbd> | Demos, Recordings, Clips, Packages, Options, Help |
| <kbd>`</kbd> | open/close the console (slides down from the top, like in the game) |
| <kbd>Esc</kbd> / <kbd>Enter</kbd> | cancel / confirm a dialog |

The bottom bar is a help line: it describes whatever control you point at, and shows the running job with a
progress bar and a *Stop* button.

### Drag and drop, text menu, command line

- Drop **`.dem` files** (or a folder) on `Killcam99.bat`: they are searched and clipped. Drop **`.mp4`/`.mkv`
  recordings**: they are read for clips. The window does not need to be open.
- `Killcam99.bat menu` opens a small text menu.
- `Killcam99.bat --help` lists every command line option (see [Reference](#command-line-options)).

### Updating and uninstalling

**Update:** close Killcam '99, unzip the new release over the old folder, let it replace files. Settings, clips,
the package index and the game copy are kept because they are not in the zip.

**Uninstall:** in direct mode press *Options → Game → Remove* first; move your `Clips` folder if you want to keep
them; delete the folder. Killcam '99 writes nothing to the registry and nothing outside its folder (except in your
UT folder in direct mode, which *Remove* undoes).

---

## How it works

### The big picture

```
 your demos (.dem)                                             your clips (.mp4)
       │                                                              ▲
       ▼                                                              │
 ┌──────────────┐  40× scan   ┌───────────────┐  plan   ┌───────────┴───────────┐
 │ UT + add-on  │ ──────────▶ │ HUD messages  │ ──────▶ │ moments worth a clip  │
 │ (UT2VidHook) │             │ with demo time│         │ (calls, combos, flags)│
 └──────────────┘             └───────────────┘         └───────────┬───────────┘
       ▲                                                            │ record parts
       │      seek to each part, play at 1×, corner marker on       ▼
       └──────────────────────────────────────────────── ffmpeg gfxcapture + WASAPI
```

### How a moment is recognised, in plain words

Unreal Tournament itself tells every player what just happened, in three lines of text in the middle of the
screen, and the announcer says it out loud. Killcam '99 never guesses from the action: it only follows those
messages, like a referee writing down every call.

- **"You killed Bob"** means you scored a kill.
- **"Double Kill!", "Multi Kill!", "Ultra Kill!", "Monster Kill!"** (red) mean you killed two, three, four or
  five players, each within about 3 seconds of the last one.
- **"... is on a killing spree / rampage / dominating / unstoppable / godlike"** means 5, 10, 15, 20, 25 kills in a
  row without dying.
- **"... returns / captured / dropped / has the flag"** are the flag plays.

```mermaid
flowchart TD
    A(["A demo or a recording"]) --> B{"Where do the messages come from?"}
    B -- "demo" --> C["The game plays the demo at 40x speed.<br/>Our add-on writes down every message<br/>with the exact second. Nothing to guess."]
    B -- "recording" --> D["Killcam '99 looks at the message lines<br/>a few times per second and reads the text<br/>(Windows' own text recognition)."]
    D --> E["Clean up the reading:<br/>one message seen in many pictures is one message;<br/>a fading text read wrongly is still that message;<br/>warm-up before the match does not count."]
    C --> F["Keep only what is about YOU:<br/>your kills, your multi kills, your sprees,<br/>your flag returns and captures."]
    E --> F
    F --> G{"Is it worth a clip?<br/>(your choices in Options, Clips)"}
    G -- "no" --> H(["ignored"])
    G -- "yes" --> I["A moment: from a few seconds before<br/>the first kill of the streak to a few<br/>seconds after the last one."]
    I --> J{"Did something else happen<br/>right after? (flag return, capture,<br/>flag carrier killed)"}
    J -- "yes" --> K["One longer clip that includes it"]
    J -- "no" --> L["The clip"]
    K --> L
    L --> M(["Clips folder"])
```

**When the screen does not show everything** (a recording only): sometimes a message is hidden behind a bright
wall or pushed away by the next one. Killcam '99 then fills in only what the game's own rules *prove*:

| What was seen | What it proves | Example |
|---|---|---|
| "Ultra Kill!" | there was a Double Kill and a Multi Kill on the way, at the kills before it | the Double Kill text was hidden behind a red banner |
| "... is on a rampage!" | the killing spree before it (5 kills earlier) | a flag message pushed the spree line away |
| "Double Kill!" while the kill line still shows the same name | the same player was killed again (instant respawn) | you killed Bob, he respawned, you killed him again |
| two clearly different names on the kill line within about 2.5 s, shown without a gap, but no readable red text | a Double Kill (the clip is marked "worked out from the kill times") | the red text was unreadable on a bright background |

And what it does **not** do: a name that changes while the text is fading (for example "Raven42", then "Rava",
then "Raven42" again) is one kill read three times, not three kills. A faint scrap of text is never taken as a
multi kill. When in doubt, Killcam '99 rather misses a moment than invents one.

### Architecture diagram

```mermaid
flowchart LR
    subgraph User["Player"]
        BAT["Killcam99.bat"]
        WIN["App window<br/>(Edge --app)"]
    end

    subgraph App["app\\ (Python 3.12, standard library + numpy + pyaudiowpatch)"]
        SRV["killcam_app.py<br/>local HTTP server 127.0.0.1:8799<br/>+ killcam_app.html"]
        CFG["kc_config.py<br/>paths · mode · manifest"]
        JOB["Job runner<br/>one subprocess at a time"]
        CORE["ut99_dem2video.py<br/>scan · plan · record · cut"]
        STREAM["ut_stream.py<br/>OBS screen reading"]
        LIB["ut_library.py<br/>package index · base pack · online search"]
        SETUP["setup_game.py<br/>copy / direct / undo"]
        FF["get_ffmpeg.py"]
    end

    subgraph Game["Unreal Tournament 469"]
        EXE["ut2vid_ut_sN.exe<br/>(renamed copies)"]
        HOOK["UT2VidHook.u<br/>UT2VidConsole + UT2VidMsgHUD"]
        CACHE[("Cache\\<GUID>.uxx<br/>cache.ini")]
    end

    subgraph Data["app\\data"]
        SET[("settings.json")]
        CAT[("library\\catalog.json")]
        WORK[("work\\ scans · clip_index.json<br/>ledgers · temp recordings")]
    end

    subgraph Packs["Package places (read only)"]
        BASE[("packs\\base<br/>137 versions")]
        MINE[("your folders")]
        DL[("packs\\downloads")]
    end

    CLIPS[("Clips\\ Demos · Recordings · Rejected")]
    NET(("Internet<br/>gyan.dev · redirects<br/>Wayback · GitHub"))

    BAT --> SRV
    WIN <-->|"JSON API + token"| SRV
    SRV --> JOB
    JOB --> CORE & STREAM & LIB & SETUP & FF
    CORE & LIB & SETUP & SRV --> CFG
    CFG --> SET
    CORE -->|"exec=DEMOPLAY, private ini"| EXE
    EXE --> HOOK
    HOOK -->|"UT2VID MSG / PROGRESS lines in log"| CORE
    CORE -->|"copy exact version"| CACHE
    LIB --> CAT
    LIB --> BASE & MINE & DL
    CORE --> WORK
    CORE -->|"ffmpeg cut"| CLIPS
    STREAM --> CLIPS
    FF -.-> NET
    LIB -.->|"only on request"| NET
```

### From demo to clip: the pipeline

```mermaid
sequenceDiagram
    autonumber
    participant K as Killcam '99
    participant P as Package check
    participant U as UT (scan, 40×)
    participant R as UT (record, 1×)
    participant F as ffmpeg
    participant C as Clips\

    K->>P: which GUIDs does the demo need? (read from the .dem)
    P-->>K: copy missing exact versions into Cache (or report missing)
    K->>U: DEMOPLAY with UT2VidConsole, UVMode=1, UVSpeed=40
    U-->>K: log: UT2VID MSG t=… (every HUD message + exact demo time)
    K->>K: own calls → combos → parts (start, end, labels)
    K->>R: UVMode=3, UVSegments="a:b,c:d", UVSettle=3
    R->>R: seek before each part, settle, play at 1×, corner marker ON
    K->>F: gfxcapture (window) + WASAPI loopback (sound)
    F-->>K: one long recording of all parts
    K->>K: find each part by the corner marker (fallback: SEGMENT lines in log)
    K->>F: cut + encode each part
    F-->>C: Clips\Demos\<kind>\<date> <map> - <time> <labels>.mp4
    K->>K: clip_index.json, parts_done.txt (what is recorded)
```

**Planning** (`plan_parts`) turns the raw message list into parts:

- only messages that belong to *you* count (the demo's recorder; your name is taken from the demo or settings);
- multi kills are counted from your own kill messages, sprees come from the server's announcements;
- a streak becomes one part from *before the streak* to *after the last kill*;
- combos extend a part to your flag return or capture within the configured window;
- overlapping parts are merged so nothing is recorded twice;
- a part is *done* when `parts_done.txt` lists a recorded part covering at least 80 % of it **and** its clip still
  exists (rejected clips count as existing, deleted ones do not).

### The in-game add-on (UT2VidHook)

The add-on is an UnrealScript package (`app/UT2VidHook/Classes`, pre-built as `app/hook/UT2VidHook.u`). It
replaces the game console (`[Engine.Engine] Console=UT2VidHook.UT2VidConsole`), but **only in the private ini
copy the tool starts UT with**, never in your own `UnrealTournament.ini`.

| UVMode | Used for | What it does |
|---|---|---|
| 0 | (not used) | Behaves exactly like UT's own console. |
| 1 | finding kills | Plays the demo as fast as udemo allows (`UVSpeed`, slomo), writes every HUD message with the exact demo time (`UT2VID MSG t=…`) and progress lines, quits at the end. |
| 2 | recording whole demos | Normal speed, only writes messages and progress. |
| 3 | recording parts | Seeks (udemo `SeekTo`) to each part in `UVSegments`, `UVSettle` seconds early so picture and sound are calm, plays it at 1×, shows a green corner marker while a part plays, quits after the last part. |

The messages are caught by `UT2VidMsgHUD`, which takes the place of udemo's *InterceptHUD* on the recorded player
(the first place udemo routes HUD messages), so nothing the player saw is missed.

### Parallel scans

Several demos are searched at once (Auto = what the CPU can carry, up to 8). Two things make that work:

1. **Renamed program copies.** UT 469 allows one running copy *per program name*: a second
   `UnrealTournament.exe` hands its command line to the one already running and quits. So every instance runs
   from its own copy, `ut2vid_ut_s0.exe`, `ut2vid_ut_s1.exe`, … (plus matching `.int` files for window titles).
   This also means Killcam '99 never lands in, or closes, a UT you are playing yourself.
2. **A start gate.** Games load one at a time: the next instance only starts once the previous one is actually
   playing its demo (or after 30 s). Two games loading packages at the same instant could make the second one
   report a package as missing that is there. A game that reports *Cannot play demo* is closed within ~2 s and
   retried, instead of waiting for the 2-minute watchdog.

```mermaid
sequenceDiagram
    participant G as start gate
    participant A as game s0
    participant B as game s1
    A->>G: acquire
    A->>A: load packages, start demo
    A-->>G: first progress line → release
    B->>G: acquire
    B->>B: load packages, start demo
    B-->>G: release
    Note over A,B: both now play side by side at ~35×
```

Every instance has its own demo copy, exec file, log, ini and user ini (UT writes its ini files when it exits,
so they cannot be shared). A watchdog stops an instance that stops moving; `run_scans` retries it once.

### Recording a clip

- **Picture:** ffmpeg's **Windows Graphics Capture** source (`gfxcapture`, ffmpeg 8.1+) records the game window
  even when it is covered. Older ffmpeg falls back to `gdigrab`, which needs the window visible.
- **Sound:** **WASAPI loopback** via `pyaudiowpatch` records what the chosen output device plays. The game runs
  with a private `User.ini` copy that raises the announcer volume.
- **Sync:** while a part plays, the add-on draws a small green **corner marker**. The cutter finds each part's
  exact start and end in the recording from that marker; if it cannot be read, it falls back to the
  `SEGMENT START/END` lines in the log (picking the smallest wall-clock-minus-demo-time to absorb log latency).
- **Quality check:** each clip is checked (distinct frames per second etc.); a choppy clip gets a *CHECK* warning,
  shown on the clip card.

### Clips from stream recordings (screen reading / OCR)

A stream recording shows the same three HUD message lines a demo carries, so Killcam '99 reads them from the
picture and turns them into the **same message list a demo scan produces**. From there on, recordings and demos
share one planner (`plan_parts`) and one cutter: a recording of a match gets the same clips, with the same lead-in
and run-out, as the demo of that match would. No demo, no game and no sound analysis are used.

```
  You killed pixelfox                      <- kill line   (cyan)   your kill, and who
  BlueSky^ returns the red flag!            <- info line   (cyan)   flag events, killing sprees
  Multi Kill!                              <- multi line  (red)    multi kill level
```

```mermaid
flowchart LR
    V["recording<br/>.mp4 / .mkv"] --> F["1 frames<br/>ffmpeg crops the message area<br/>+ the match clock, 6 frames/s"]
    F --> S["2 sieve<br/>colour layers (cyan, red),<br/>local contrast, 'may hold text?'"]
    S -->|"most frames: no text"| X(("skipped"))
    S -->|"text-like frames"| B["3 batch<br/>24 strips stacked into<br/>one picture (BMP)"]
    B --> O["4 OCR<br/>Windows.Media.Ocr<br/>(PowerShell helper, en-US)"]
    O --> I["5 interpret<br/>fuzzy match each line:<br/>kill / death / spree / flag / multi"]
    I --> T["6 track<br/>same message in many frames<br/>= one message, first moment"]
    T --> N["7 names<br/>one spelling per player,<br/>find your own name"]
    N --> W["8 match only<br/>drop warm-up and post-match<br/>(clock standing still)"]
    W --> M["9 messages<br/>demo-scan format + streaks,<br/>implied sprees and multi kills"]
    M --> P["plan_parts<br/>(same as demos)"]
    P --> C["cut: stream copy<br/>or re-encode"]
    I -. "raw readings saved" .-> J[("work/stream_scans/(recording).json")]
    J -. "reused: new clip options,<br/>picking, Read again not needed" .-> T
```

**1. Frames.** ffmpeg decodes the recording once and, at 6 frames per second (`--stream-fps`), crops two small
areas: the **message area** (1000 x 125 pixels at 240 px from the top, centred, for a 1920 x 1080 picture; other
sizes are scaled) enlarged 1.5x with Lanczos for sharper letters, and the **match clock** (bottom, left of the
middle). Both arrive in one raw RGB stream, so the video is read once. A HUD in another place (for example the game
shown smaller inside a stream layout) is set with `--stream-area X,Y,W,H` and `--stream-clock X,Y,W,H`, given for
1920 x 1080.

**2. The sieve (most frames never reach the OCR).** For every frame two colour layers are computed with numpy:
*cyan-ness* (blue and green above red: the kill and info lines) and *red-ness* (red above green and blue: the multi
kill text). Each layer is then reduced to **local contrast** (the value minus the average of the area around it),
so a flat blue wall or red banner behind the text drops out and only thin strokes, the letters, remain. A frame goes
on to the OCR only when enough such strokes sit in the middle part of the area, where every HUD message is centred.
Measured on real recordings: frames with a readable message have 160+ stroke pixels, 3 out of 4 frames without a
message have under 25. Frames with red strokes are sent twice: once as the plain picture, and once as a
**red print** (the red strokes as dark text on white), which reads a faint multi kill text over a bright wall that
the plain picture misses.

**3. Batching.** Calling the OCR per frame would be slow, so up to 24 strips are stacked into one picture with
white gaps between them (limited by the engine's maximum picture size), written as a plain 24-bit BMP (no imaging
library needed). Each recognised line is mapped back to its strip, and so to its frame time, by its vertical
position. Lines that are not centred are ignored: every HUD message is centred.

**4. OCR: Windows' own text recognition.** `Windows.Media.Ocr`, the engine built into Windows 10 and 11, runs in a
small **PowerShell helper process** that stays open for the whole recording: Python writes a picture path to its
input, the helper answers with one line per recognised text line (its box and its text) and an end marker. It
prefers the **English (en-US)** recognizer and falls back to your profile languages; if no recognizer is installed,
the job stops with a clear message (*Settings > Time & language > Language > add English*). Nothing is installed
and nothing leaves your PC: the OCR runs locally and offline.

**5. Interpreting a line.** OCR output is never exact, so every line is matched **fuzzily** (similarity ratios on
the letters only). A red line is only taken as a multi kill when it has real red in it (real ones measure 65 or more,
anything under 30 is ignored) and is not a piece of the kill line (`ou kill` from `You killed` once matched
`Double Kill`):

| Line | Recognised when it resembles | Becomes |
|---|---|---|
| red | `Double Kill`, `Multi Kill`, `Mega Kill`, `Ultra Kill`, `Monster Kill`, `Ludicrous Kill`, `Holy Shit` (74 %+) | a multi kill of that level |
| cyan | `You killed <name>` | your kill, and the victim |
| cyan | `You were killed by <name>` | your death, and the killer |
| cyan | `<name> is on a killing spree / rampage / dominating / unstoppable / godlike / wicked sick` | a spree level, and who |
| cyan | `<name> returns / dropped / captured / has the ... flag` | a flag event, and who |

Typical OCR confusions are folded together before names are compared: `l`, `I` and `1` count as the same letter,
`0` as `o`, `5` as `s`, `rn` as `m`, `vv` as `w`, and `ivi` as `m` (so `Marble` read as `lVlarble` still matches).

**6. Tracking.** A message stays on screen about 3 seconds, so it is read in many frames. Readings of the same
message on the same line become **one message at the moment it first appeared**. A message never comes back once a
newer one has replaced it, so anything read on that line in between is a misreading and is dropped. A name read
only once or twice in the whole recording is a misreading too. A multi kill text read in a single frame is kept
only when one of your kills is right there.

A message **fades** while it is shown, and a fading text is often misread: `You killed Raven42` turns into
`You killed Rava` and back. A new message, on the other hand, always arrives **fresh and bright**. So on the kill
line and the multi kill line, a different reading that follows the shown message without a break and is clearly
fainter (under 80 % of that message's brightest reading) counts as the same message, misread. On the kill line this
needs the names to look alike as well (same first letters, one inside the other, or mostly the same letters), so a
real kill of someone else that happens to be read faintly is still a new kill.

**7. Names.** Each player gets one spelling: every reading is mapped to the spelling seen most often, including
readings where one name contains the other (`LNightOwl.CLN-` and `NightOwl`: a stray letter or a clan tag read along,
or a part cut off). Your own
name, the hardest to read (clan tags full of brackets), is found in this order: your *player name* setting, then
the recording itself (a spree announcement that appears together with one of your kills names you), then the name
your demo files of that day start with. The name found is **saved with the reading**, so the moments the app shows
are exactly the ones that get cut.

**8. Match only.** The match clock is watched second by second: if its last digit changes, the match is running.
Pixels are combined over all frames of a second (majority vote) to remove flicker from moving backgrounds. Stretches
where the clock stands still (warm-up before the match, the time after it) are left out, so warm-up kills never
make a clip. (`--include-warmup` keeps them.)

**9. Messages and streaks.** The tracked messages become demo-style messages (kills, deaths, multi kills, sprees,
flag events with *your* ones marked). Then what the screen cannot show directly is worked out:

- every multi kill text is tied to the kill that caused it; if the kill line still shows the same victim, that
  victim was killed **again** (instant respawn), and that kill is added;
- a multi kill level that *was* read proves the levels below it: an Ultra Kill read at the fourth kill of a
  streak adds the Double Kill and Multi Kill at the second and third kill, when those texts were hidden (only when
  the streak's kills add up to exactly that level);
- a streak whose red text was unreadable (bright background) is rebuilt **from the kill times**, but only under
  strict conditions: gaps under 2.6 s, kills each read at least twice, names that are clearly *different* (not two
  readings of one name), and the kill line showing the earlier kill right up to the later one (if it was unreadable
  in between, the earlier kill may have happened well before its first readable moment, so the gap only looks
  short). Such clips carry the note *multi kill level worked out from the kill times*;
- a spree level that *was* read proves the levels below it (they happened 5, 10, ... kills earlier), so those are
  added even when another message pushed them off the screen.

**10. Saved readings.** Only the raw readings (time, line, text, strength) and the clock are saved, in
`app\data\work\stream_scans\<recording>.json`, with the recording's size and date. Steps 6 to 9 run again from
that file every time, so better rules, new clip options, the moment list in the app and picked cuts all work
**without reading the video again**. A recording is read again only when it changed, when you press *Read again*,
or with `--rescan`.

**Measured accuracy.** Five OBS recordings were compared with the demos of the same eight matches (the demos are
exact, so they are the reference). The developer tool *Compare with the demos* (Recordings page, with developer tools
on) runs this comparison for any recording that has a demo of the same match.

| Your ... | In the demos | Found on screen | Missed | Wrong (extra) |
|---|---|---|---|---|
| kills | 837 | 786 (94 %) | 51 | 50 |
| multi kills | 186 | 181 (97 %) | 5 | 4 |
| sprees | 42 | 39 | 3 | 1 |
| flag returns | 52 | 43 | 9 | 0 |
| **clips** | **16** | **16** (all covered) | **0** | **0** |

Every clip the demos plan is found, and no clip is made that the demos do not plan. The misses are moments where
neither the red text nor the name on the kill line was readable in any frame; the extras that remain are counting
differences (for example a multi kill tied to a kill one second off), not extra clips. Version 1.2 removed a wrong
*Multi Kill* clip that 1.1 made from a single kill whose fading name was read three different ways (extra kills
went from 86 to 50, wrong multi kills from 9 to 4).

**Speed.** Reading takes about a quarter of the recording's length, most of it in the OCR. The sieve keeps that
manageable: in a typical match only a small share of frames holds a message.

**Recording workflow.** *Make clips from new recordings* reads and cuts every moment; *Find moments* reads only
(the recording's status becomes *Moments found*, ledger status `read`) and the app lists the moments; *Cut these
moments* passes the picked times (`--moments`) and cuts only those, from the saved reading. A recording that OBS
wrote to in the last 2 minutes is skipped as *still being written*.

### Packages: exact versions by GUID

```mermaid
flowchart TD
    D["demo needs package P, GUID G"] --> G1{"in the game folder?<br/>(Cache by GUID, or Maps/Textures/…<br/>with matching header GUID)"}
    G1 -- yes --> OK["play"]
    G1 -- no --> G2{"in base pack / your folders /<br/>packs\\downloads?"}
    G2 -- yes --> CP["copy that exact version into<br/>game Cache as G.uxx + cache.ini line<br/>(direct mode: recorded in manifest)"] --> OK
    G2 -- no --> G3{"online search allowed<br/>and not 'not found' in last 7 days?"}
    G3 -- yes --> NET["redirect servers (.uz) → Wayback copies → GitHub releases<br/>unpack with UCC, keep only if GUID == G"]
    NET -- found --> KEEP["store in packs\\downloads"] --> CP
    NET -- not found --> MISS["missing: listed with GUID, size, generation,<br/>other versions you have"]
    G3 -- no --> MISS
```

- Each demo's first ~2 MB contain `USES GUID=… PKG=… FLAGS=… SIZE=… GEN=… FNAME=…` lines; Killcam '99 scans
  them at all eight bit offsets to read every requirement. Client-optional packages (flag `0x02`) never block.
- A demo is **untrusted input**: package and file names from it are only accepted as bare file names (no folder
  separators, drive letters or `..`), because they become file names when packages are downloaded and unpacked.
  Names taken from web pages and download URLs are reduced to bare file names too, and archives from the internet
  are only partly extracted (the wanted files, flattened), so nothing can be written outside the work folder.
- A package file's GUID comes from its header (offset 36 for package version ≥ 68, else the last *heritage*
  entry). That is how files with the same name but a different version are told apart.
- The **index** (`app\data\library\catalog.json`) stores *where* every version is; it copies nothing.
  Only when a demo needs a version is that one file copied into the game's `Cache`.
- **Retail files are never shipped or exported**: they are recognised from the game's own
  `System\Manifest.ini` (every `File=` of every product group).
- The **base pack** is in UT's own cache format (`Cache\<GUID>.uxx` + `cache.ini`) so it is directly usable as a
  package place, and it is a folder (not a zip) so nothing has to be unpacked.

### The two setup modes

```mermaid
flowchart LR
    W["Setup wizard"] --> M{"mode"}
    M -- copy --> C1["copy UT → app\\UT<br/>(size+mtime: unchanged files skipped)"]
    C1 --> C2["merge extra Cache* folders"]
    C2 --> C3["udemo.ini DemoPaths → copy<br/>rewrite ini paths into the original"]
    C3 --> C4["place UT2VidHook.u"]
    C4 --> C5["separation audit before/after every run:<br/>original UT folders must not change"]
    M -- direct --> D1["place UT2VidHook.u in System<br/>(recorded in direct_manifest.json)"]
    D1 --> D2["packages copied into Cache later<br/>(each .uxx + cache.ini line recorded)"]
    D2 --> D3["temp ut2vid_* files removed after every run"]
    D3 --> D4["Remove: delete recorded files,<br/>strip recorded cache.ini lines → byte-identical"]
```

Safety rails in code: every writer checks its target (`guard()` in `setup_game.py` and `ut_library.py` refuses
writes outside the Killcam '99 folder / the package places), the converter refuses a game folder that is not the
configured one (`SAFETY STOP`), and in direct mode only the tool's own renamed processes are ever closed, never
your `UnrealTournament.exe`.

### The app: a local web window

`killcam_app.py` is a `ThreadingHTTPServer` from the standard library, bound to **127.0.0.1:8799** only:

- it refuses requests whose `Host` is not `127.0.0.1`/`localhost` (DNS-rebinding protection);
- it refuses requests the browser marks as coming from another site (`Sec-Fetch-Site: cross-site`/`same-site`),
  so other web pages can neither call the API nor embed your clips in a `<video>`;
- every request except the page itself, its icon and `/api/ping` needs a random per-start **token** embedded in
  the page: `POST` bodies carry it, data requests send it as an `X-Killcam-Token` header, and clip videos as a
  `?t=` parameter. It is compared in constant time, and request bodies are capped at 1 MB;
- the separate stand-alone review page (`--review`) applies the same checks;
- the page is one static HTML file with plain JavaScript (no framework, no build step);
- it opens in **Microsoft Edge app mode** (`--app=`), a window without tabs or address bar, else the default browser;
- a second start finds the running one through `/api/ping` and just shows it again;
- long work runs as **jobs**: one subprocess at a time, its output streamed to the console, progress parsed from
  `=== [n/m] ===` lines, *Stop* kills the process tree and closes the game instances it started;
- the window polls `/api/job` every 0.9 s and the state every 15 s;
- when the code changes on disk, a banner offers *Restart now* (the server restarts itself and the page reconnects).

### Folder layout and data files

```
Killcam99\
├─ Killcam99.bat              launcher: finds app\, hides it, picks app\python or system Python
├─ README.txt                 manual for players
├─ Clips\                     finished videos (clips_folder)
│  ├─ Demos\<kind>\           e.g. Monster Kill, Godlike, Flag Return
│  ├─ Recordings\<kind>\
│  └─ Rejected\
└─ app\                       (hidden)
   ├─ *.py, killcam_app.html, icon.svg
   ├─ hook\UT2VidHook.u       pre-built add-on
   ├─ UT2VidHook\Classes\     add-on source (UnrealScript)
   ├─ packs\base\             shipped packages (Cache\<GUID>.uxx, cache.ini, pack.json, README.txt)
   ├─ packs\downloads\        packages found online
   ├─ python\                 portable Python (release only)
   ├─ tools\ffmpeg\           ffmpeg.exe, ffprobe.exe (downloaded by the setup)
   ├─ UT\                     the separate game copy (copy mode)
   └─ data\
      ├─ settings.json        all options + game_folder, game_mode, setup_done, clips_folder
      ├─ direct_manifest.json everything added to your UT folder (direct mode)
      ├─ killcam.log          the log (rotated at 2 MB → killcam.old.txt)
      ├─ demo_info.json       map names read from renamed demos
      ├─ library\             catalog.json (the index), UT_files.csv, online_search.json
      └─ work\                scans\, stream_scans\, _work\ (temp recordings), clip_index.json,
                              parts_done.txt, done.txt, events.txt, check.txt, obs_processed.txt
```

All JSON files are written atomically (`*.tmp` + `os.replace`). There is no database: the data is small, human
readable and survives crashes.

| Work file | Holds |
|---|---|
| `scans\<demo>.json` | every HUD message of a demo scan, with exact demo times |
| `stream_scans\<recording>.json` | the raw screen readings and clock of a recording, plus the player name found |
| `clip_index.json` | every clip: file (relative to `Clips\`), source, origin, labels, time, check note, and state `new`, `kept`, `rejected` or `deleted` (file gone, remembered so it is not made again) |
| `parts_done.txt` | which parts of which demo were recorded (a part is done when a recorded part covers 80 % of it and its clip exists, or was deleted in the app) |
| `obs_processed.txt` | per recording (size, date, path): `read` (moments found, nothing cut) or `done` (clips made) |
| `_work\moments.json`, `_work\obs_moments.json` | the moments picked in the app for the next job |
| `events.txt`, `check.txt` | a plain log of every moment found, and of clips with a quality warning |

---

## Design decisions and crossroads

Every non-obvious choice, with what was considered and why it went this way.

<details open>
<summary><b>1. Render demos with the real engine, not a re-implementation</b></summary>

- **Context:** a UT demo is a network recording; it has no pixels.
- **Options:** (a) write a demo parser + renderer; (b) drive the real game.
- **Choice:** (b). Only the engine reproduces the exact look, mods, skins and HUD. Everything else in the tool
  exists to drive the engine reliably: exec files, private ini copies, renamed executables, the add-on.
- **Consequence:** UT must be installed, and recording takes real time (1×), which is why the tool records only
  the moments, not whole demos.
</details>

<details>
<summary><b>2. Finding moments: an in-game add-on instead of listening to the sound</b></summary>

- **Before:** the first version recorded the whole demo and found announcer calls in the *audio* by matching the
  game's own announcer sounds (templates from `Sounds`/`Cache`).
- **Options:** keep audio matching; read the screen; hook the game.
- **Choice:** an UnrealScript console (`UT2VidConsole`) that logs every HUD message with the exact demo time.
  It is exact (no false positives from similar sounds, other players' calls are told apart), and because no
  recording is needed it can play the demo at ~40×.
- **Kept:** the audio method remains as a validation tool (`--validate`, developer tools) that checks the scan
  misses nothing the audio found.
</details>

<details>
<summary><b>3. Scan fast, then record only the parts</b></summary>

- **Options:** record whole demos at 1× and cut afterwards; or scan first, then seek.
- **Choice:** a 40× scan (`UVMode=1`) followed by a record run that seeks to each part (`UVMode=3`, udemo
  `SeekTo`) with a settle time before each part.
- **Why:** a 20-minute demo with three moments costs ~30 s of scanning + ~1.5 min of recording instead of 20 min.
- **Trade-off:** seeking in a demo is not frame-perfect and needs a moment to settle; hence `settle` (played but
  not kept) and the corner marker to find each part precisely in the recording.
</details>

<details>
<summary><b>4. One renamed program copy per game instance</b></summary>

- **Problem:** UT 469 forwards a second start of the same program to the running instance. Parallel scans
  mixed demos up; a scan could even land in a UT the player was using.
- **Choice:** run every instance from its own copy `ut2vid_ut_<tag>.exe` (+ `.int` for localised titles).
- **Consequence:** isolation between scans, recording, watching and your own game; closing leftovers only ever
  targets those names (and, in direct mode, never `UnrealTournament.exe`).
</details>

<details>
<summary><b>5. A start gate for parallel scans</b></summary>

- **Problem:** occasionally the second of two games started 2 s apart reported a package as missing although it
  was in the Cache, and then waited 2 minutes for the watchdog.
- **Options:** longer fixed stagger; retry only; serialise the load phase.
- **Choice:** serialise only the load phase (a lock released when the game reports its first progress, max 30 s),
  plus fail-fast detection of *Cannot play demo* with an immediate retry. Games still *play* side by side.
</details>

<details>
<summary><b>6. Separate copy vs. the player's own folder: offer both</b></summary>

- **Copy:** zero risk to the original (only read; a separation audit fingerprints the originals before and after
  every run), costs disk space and goes stale until *Update*.
- **Direct:** no extra space, always current, but writes into the player's folder.
- **Choice:** let the player choose, with the trade-offs spelled out, and make direct mode **minimal and fully
  undoable**: one add-on file, packages in `Cache` only when needed, every addition recorded in
  `direct_manifest.json`, temp files cleaned after every run, and *Remove* restoring the folder byte-for-byte
  (verified by hashing every file before and after).
- **Not done:** editing the player's `UnrealTournament.ini`/`User.ini`. The console and window settings live in
  private ini copies passed with `ini=`/`userini=`.
</details>

<details>
<summary><b>7. Ship the add-on pre-built</b></summary>

- **Options:** compile with UCC on the player's PC (needs `EditPackages=` lines added to their ini and source in
  the game folder); or ship the compiled `.u`.
- **Choice:** ship `UT2VidHook.u`. Compilation is a developer action (`setup_game.py --compile`, copy mode only),
  which also refreshes the shipped file.
</details>

<details>
<summary><b>8. Background recording with gfxcapture; sound with WASAPI loopback</b></summary>

- **gdigrab** needs the window visible and on top; **Windows Graphics Capture** (`gfxcapture` in ffmpeg 8.1+)
  records a window even when covered, so the PC stays usable.
- **WASAPI loopback** (via `pyaudiowpatch`) records the device mix: simple and reliable, at the cost of capturing
  other sounds too (documented, and a device can be chosen).
- **Sync** by a visual corner marker drawn by the add-on, with log timestamps as a fallback.
</details>

<details>
<summary><b>9. The UI: a local web page in an Edge app window</b></summary>

- **Options:** Tkinter, Qt (PySide), Electron, a local web UI.
- **Choice:** standard-library HTTP server + one HTML file, shown with `msedge --app=`. No dependencies, no build
  step, looks like a normal app window, video playback for free (`<video>` with HTTP range requests), and the same
  server could later serve a phone on the LAN (deliberately *not* enabled: bound to 127.0.0.1, host check, token).
- **Look:** a plain light 2010-style desktop look (Segoe UI, soft gradients, one blue accent), chosen over a
  game-themed skin for readability.
</details>

<details>
<summary><b>10. Self-contained runtime: embeddable Python, ffmpeg downloaded at setup</b></summary>

- **Options:** require Python; freeze with PyInstaller; ship python.org's *embeddable* build.
- **Choice:** the embeddable build (~11 MB) + wheels unpacked into `site-packages`. Frozen single-file executables
  are frequently flagged by antivirus heuristics and unpack to temp on every start; the embeddable build is plain
  files, starts fast and keeps the code readable.
- **tkinter** is not in the embeddable build, so folder dialogs use PowerShell's `FolderBrowserDialog`.
- **ffmpeg** is downloaded during setup (gyan.dev release build, checked against its published SHA-256) instead of
  bundled: it keeps the repository and release ~200 MB smaller, always gets a current build, and keeps ffmpeg's own
  (GPL) licensing separate from this MIT project.
</details>

<details>
<summary><b>11. Packages: an index of pointers, not a copied library</b></summary>

- **Before:** every package version from every UT folder was *copied* into one library (5.4 GB of duplicates).
- **Choice:** index where each version is (game folder, base pack, your folders, downloads) and copy a single file
  into the game's `Cache` only when a demo needs it. Refreshing is incremental (a size+mtime memo per file).
- **Retail exclusion** via the game's own `Manifest.ini` keeps the shipped pack legally clean; *came from a server
  cache* only counts for a real UT install's `Cache`, so packs never mask retail files.
</details>

<details>
<summary><b>12. Online package search: exact or nothing</b></summary>

- **Sources:** live redirect servers (`.uz`), every archived copy of those files in the **Wayback Machine** (CDX
  API, one exact-URL query per file, deduplicated by digest), and GitHub releases of known mods.
- **Rule:** a download is unpacked with the game's own UCC and kept **only if its GUID matches**. A miss is
  remembered for 7 days so normal runs do not hammer the archives.
</details>

<details>
<summary><b>13. Stream recordings: Windows' own OCR, behind a cheap sieve</b></summary>

- **Options:** Tesseract (extra install, weaker on this HUD font), a trained model (heavy, a download), or
  `Windows.Media.Ocr` (part of Windows 10/11, offline, good on clean UI text).
- **Choice:** Windows' OCR in a long-lived PowerShell helper, fed with batches of colour-separated strips. A numpy
  sieve (colour layers + local contrast + a stroke count) decides which frames are worth reading at all, which is
  what makes reading a match take minutes instead of hours.
- **Robustness over exactness:** fuzzy matching of every line, OCR look-alikes folded together, tracking that drops
  readings a newer message proves wrong, and streak/spree rules that infer what the screen hid. Then the *same*
  planner as demos, so a recording gets the same clips the demo would.
- **Trade-off:** needs an English (or similar) recognizer language in Windows; a HUD at a non-standard place needs
  `--stream-area`/`--stream-clock`.
</details>

<details>
<summary><b>14. One place for paths; installed vs developer layout</b></summary>

- `kc_config.py` is the single source of every path and of the mode. If it lives in a folder called `app`, the
  install layout applies (`app\data`, `Clips` next to the launcher); otherwise everything stays in one developer
  folder. Older layouts are migrated on first start (clips moved into `Clips\`, the clip list rewritten, work
  files into `app\data\work`).
</details>

<details>
<summary><b>15. Clips separate from bookkeeping</b></summary>

- The visible `Clips` folder holds **only videos**. Ledgers (`parts_done.txt`, `events.txt`, `check.txt`), scans,
  the clip list and temporary recordings live in `app\data\work`. Clip paths in `clip_index.json` are relative to
  the clips folder, so the folder can be moved or changed in Options.
</details>

<details>
<summary><b>16. Files, not a database</b></summary>

- JSON and text files, written atomically. Small data, inspectable by players and developers, no corruption on a
  hard stop, trivially backed up. A demo or clip deleted outside the app is simply forgotten on the next read.
</details>

<details>
<summary><b>17. Pick before you cut: save the reading, not the result</b></summary>

- **Problem:** reading a recording is the slow step (minutes); deciding which moments are worth keeping is the
  player's call.
- **Choice:** split reading from cutting. *Find moments* saves the raw readings; the app recomputes the moments from
  them on every view, with the current clip options, and a picked cut reuses the saved reading (seconds). The same
  pattern as demos, where the 40x scan is saved and recording is a separate step.
- **Consequence:** changing a trigger or the clip length updates the moment list immediately, and the player name
  found while reading is stored with the reading so the list and the cut always agree.
</details>


<details>
<summary><b>18. Delete, but remember</b></summary>

- **Problem:** players want disk space back, but a clip whose file simply disappears looks like a moment that was
  never recorded, so the next *Make clips* would record it again.
- **Choice:** *Delete* removes the file and keeps the clip-list entry with the state `deleted`. The recorder and the
  cutter both treat deleted clips as done; picking the moment again is the explicit way to get it back. Saving the
  clip list merges entries a running job added meanwhile, so deleting during a job loses nothing.
</details>

<details>
<summary><b>19. Fading text is the same message; rather miss than invent</b></summary>

- **Problem:** a recording made a *Multi Kill* clip out of one kill: while the kill message faded, its name was read
  as `Raven42`, `Rava`, `Raven42`, and each change of name looked like a new kill; three kills within 2.6 s then
  "proved" a multi kill.
- **Options:** require more frames per name (loses real quick kills); merge all similar names globally (merges real
  players with similar names); use what the HUD itself does: a new message replaces the old one at full brightness.
- **Choice:** brightness and continuity. A different reading right after the shown message that is clearly fainter
  is that message, misread (kill line: only for names that look alike). The kill-times rule now also requires
  clearly different names and an unbroken view of the earlier kill. To keep the hidden-level cases that the phantom
  kills used to cover by accident, a read multi kill now implies the lower levels at the kills before it.
- **Checked against the demos:** extra kills 86 to 50, wrong multi kills 9 to 4, missed multi kills 6 to 5, and
  the clip plan of all five recordings matches the demos exactly.
</details>

---

## Repository layout

```
.
├─ Killcam99.bat            launcher (CRLF)
├─ README.txt               manual for players (copied into the release)
├─ README.md                this file
├─ LICENSE                  MIT (code)
├─ app/
│  ├─ killcam_app.py        app server, jobs, API
│  ├─ killcam_app.html      the whole UI (HTML + CSS + JS)
│  ├─ kc_config.py          paths, mode, migration, direct-mode manifest/undo
│  ├─ ut99_dem2video.py     scan, plan, record, cut; package check; CLI
│  ├─ ut_stream.py          clips from OBS/Streamlabs recordings
│  ├─ ut_library.py         package index, base pack, missing detail, online search
│  ├─ setup_game.py         copy / direct setup, undo, add-on placement
│  ├─ get_ffmpeg.py         ffmpeg download + checksum
│  ├─ icon.svg              app icon
│  ├─ hook/UT2VidHook.u     pre-built add-on
│  ├─ UT2VidHook/Classes/   add-on source (UnrealScript)
│  └─ packs/base/           base pack: 137 community package versions (529 MB)
└─ tools/
   └─ build_release.py      builds dist/Killcam99 + zip with a portable Python
```

## Building a release

```bash
py tools\build_release.py
```

This copies the launcher, `README.txt` and `app\` (without `data`, `UT`, `tools`, `python`) into
`dist\Killcam99\`, adds python.org's embeddable **Python 3.12.10** with **numpy** and **pyaudiowpatch** wheels
(cached in `tools\_cache`), and zips it as `dist\Killcam99-<version>.zip`. Use `--no-zip` for the folder only.

The version lives in `app/kc_config.py` (`VERSION`).

## Developing

- Run straight from the clone: `Killcam99.bat`, or `py app\killcam_app.py --no-window` and open
  `http://127.0.0.1:8799/`.
- The converter is a normal CLI: `py app\ut99_dem2video.py --help`.
- The package tool: `py app\ut_library.py build | stats | fetch [--guid G] | basepack DEST`.
- Rebuilding the add-on: put UT in copy mode, then `py app\setup_game.py --ut "<your UT>" --mode copy --compile`
  (compiles with the copy's UCC and refreshes `app\hook\UT2VidHook.u`).
- Developer tools in the app: *Options → App → Developer tools* (compare scans with the audio method, compare
  stream readings with demo scans).
- Test the safety promises after changes to setup or package code: fingerprint a scratch UT folder, run direct
  setup + a scan + *Remove*, and compare hashes (the folder must be byte-identical).

---

## Reference

### settings.json

`app\data\settings.json` is written by the app; editing by hand is possible while it is closed.

| Key | Meaning | Default |
|---|---|---|
| `game_folder` | UT folder in use | set by setup |
| `game_mode` | `copy` or `direct` | `copy` |
| `setup_done` | setup finished | `false` |
| `source_folder` | original UT the copy was made from | (none) |
| `demo_folder` | where demos are read | game's `System` (direct) |
| `obs_folder` | where recordings are read | `%USERPROFILE%\Videos` |
| `clips_folder` | where clips go | `<install>\Clips` |
| `triggers` | announcer calls that make a clip | Mega/Ultra/Monster/Ludicrous/Holy Shit, Rampage … Wicked Sick |
| `return_on`, `return_window` | combo: multi kill → flag return within N s | on, 15 |
| `capture_on`, `capture_window` | combo: multi kill → capture within N s | on, 20 |
| `carrier_kills` | multi kill incl. the enemy flag carrier | on |
| `part_before`, `part_after`, `settle` | clip length around a streak | 8, 10, 2 |
| `format`, `clip_quality` | `mp4`/`mkv`; `high`/`normal`/`small` | `mp4`, `normal` |
| `scan_jobs`, `scan_speed` | parallel scans (0 = auto), scan speed × | 0, 40 |
| `audio_device` | recording device name (part of) | Windows default |
| `player`, `obs_reencode` | name in recordings; exact cuts | auto, off |
| `library_sources` | your package folders | `[]` |
| `hidden_demos` | demos removed from the list | `[]` |
| `open_as_app`, `notify`, `dev_mode` | app behaviour | on, on, off |

### Command line options

`Killcam99.bat --help` (or `py app\ut99_dem2video.py --help`) lists all. The most useful:

| Option | Effect |
|---|---|
| `--scan` | find kills only (fast, nothing recorded) |
| `--clips-only --scan-first` | find kills, then record only the moments (what *Make clips* runs) |
| `--obs [FOLDER]` | clips from OBS/Streamlabs recordings (all new recordings in FOLDER) |
| `--obs-file FILE` | only this recording (repeatable) |
| `--obs-find-only` | read recordings and list their moments, cut nothing (status `read`) |
| `--moments FILE` | record or cut only these moments: JSON `{file name: [call times in seconds]}`; works for demos (with `--scan-first`) and recordings |
| `--rescan` | read recordings again even when a saved reading exists |
| `--obs-reencode` | exact cuts (re-encode) instead of a stream copy |
| `--stream-fps N` | frames per second read from recordings (default 6) |
| `--stream-area X,Y,W,H`, `--stream-clock X,Y,W,H` | where the HUD messages and the match clock are, for a 1920 x 1080 picture |
| `--include-warmup` | also count kills made while the match clock stood still |
| `--watch DEMO [--at SECONDS]` | watch a demo (or one moment) in the game |
| `--only TEXT`, `--limit N` | only demos whose name contains TEXT; at most N |
| `--overwrite` | redo demos/parts already done |
| `--scan-jobs N`, `--scan-speed X` | parallel scans; scan speed |
| `--part-before S`, `--part-after S`, `--settle S` | clip length |
| `--clip-quality high/normal/small`, `--format mp4/mkv` | output |
| `--audio-device TEXT`, `--list-audio` | recording device |
| `--no-download`, `--retry-online`, `--redirect URL` | online package search |
| `--dry-run`, `--prepare-only` | check only; only gather packages |
| `--review` | open the stand-alone review page |

### Log messages worth knowing

| Line | Meaning |
|---|---|
| `=== [n/m] ===` | progress (drives the progress bar) |
| `SAFETY STOP: …` | a write outside the allowed folders was refused; nothing was changed |
| `SEPARATION CHECK: original UT folders unchanged.` | copy mode: your originals were verified untouched |
| `the game could not start the demo; closing it to try again` | fail-fast retry of a scan instance |
| `Cannot play demo due to missing packages: X` | UT's own message; see *Packages → Missing* |
| `CHECK: choppy (UT drew few frames)` | a clip may stutter; shown on the clip card |
| `N moment(s) worth a clip found (nothing cut yet)` | *Find moments* read a recording; pick moments in the app |
| `skipped (still being written?): <recording>` | OBS wrote to it in the last 2 minutes; it is read once it is finished |
| `your player name, read from the screen: <name>` | the name used to tell your sprees and flag plays from others' |
| `match clock standing still (warm-up / after the match): ...` | those stretches are left out of a recording |
| `Windows text recognition could not be started` | no OCR language installed: add English in Windows' language settings |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| *Windows protected your PC* | Unsigned tool: **More info → Run anyway**. |
| Nothing happens / a black window flashes | Run `Killcam99.bat` from a Command Prompt to read the message, or open `app\data\killcam.log`. Without Edge it opens in your default browser. |
| *This UT has no udemo* | Install the [OldUnreal 469 patch](https://www.oldunreal.com). |
| A demo shows *N packages missing* | Click the label: exact versions with GUIDs. *Search online*, or *Add a folder that has them*. "Other versions you have" do **not** work for that demo. |
| Clips are black or show the desktop | Don't minimise the game; check *Help → system check* that ffmpeg is 8.1+ (background capture). |
| No or wrong sound | *Options → Speed and sound → Record sound from*: the device the game plays on. |
| Moments missing or wrong | Check your player name; *Find kills in all demos again*. Only your own calls count. |
| A folder dialog does not appear | It may be behind the window; check the taskbar. |
| A game window stays open after Stop | Close it; leftovers are closed on the next start. Your own UT is never closed. |
| Two scan windows, one idle | Fixed in 1.1: games now load one at a time, failures retry within seconds. |
| A recording shows *still being written?* | OBS wrote to it in the last 2 minutes. Finish or stop the recording, wait a moment, then *Find moments*. |
| *Windows text recognition could not be started* | Add English in *Settings > Time & language > Language* (the recognizer comes with it). |
| A recording finds no or too few moments | Check *Your player name* on the Recordings page, then *Read again*. If your stream layout shows the game smaller or moved, set `--stream-area` / `--stream-clock`. |
| A recording made a clip that the match did not have | Version 1.2 fixed the known cause (one fading kill read as several). Moments are worked out again from the saved reading, so the wrong moment simply no longer appears; delete the old clip with *Delete*. |
| A recording clip is labelled from the kill times | The red multi kill text was unreadable (bright background); the level was worked out from your kill times. Check the clip. |
| A deleted clip came back | It was deleted in Explorer, not with *Delete* in the app; only the app remembers deletions. |
| Bug report | *Help → Copy diagnostics* and paste it into an issue. |

## FAQ

**Does it modify my game?** In copy mode, no: your folder is only read and verified. In direct mode it adds one
add-on file and the exact packages demos need to `Cache`; *Remove* undoes all of it.

**Can I play UT while it works?** In copy mode yes (separate program copies); in direct mode not while recording.

**Why does it need the exact map version?** UT refuses to play a demo whose packages differ from the server's;
two `CTF-Face` files can be different versions. The GUID identifies the version.

**Does it work with UT2004 / Unreal?** No, UT99 (Unreal Engine 1, 469 patch) only.

**Is my data sent anywhere?** No. See [Privacy](#privacy-what-goes-online).

**Can it run on Linux/Wine?** Not supported: it drives Windows windows, Windows Graphics Capture, WASAPI and
Windows OCR.

## Known limitations and roadmap

- Windows only; needs the 469 patch.
- Reading recordings needs a Windows OCR language (English is preferred) and the standard HUD position (or
  `--stream-area`); very bright backgrounds can hide the red multi kill text (the level is then inferred).
- Recording is real-time per moment; sound is the device mix (other apps are recorded too).
- Not code-signed (SmartScreen warning on first start).
- Planned: update check, signed launcher/installer, per-clip trimming in the review page, upload presets,
  translations.

## Privacy: what goes online

Killcam '99 connects to the internet **only** for:

- the ffmpeg download during setup (`www.gyan.dev`, verified against its published checksum);
- searching for missing packages when you ask for it (UT redirect servers, `web.archive.org`, GitHub releases of
  known mods).

Reading recordings uses Windows' own text recognition on your PC, offline; no picture or text from your
recordings leaves it. The app window is served on `127.0.0.1` only and cannot be reached from other computers. No telemetry, no
accounts, nothing about you or your demos is sent anywhere.

## Contributing

Issues and pull requests are welcome. Please:

- keep the safety promises (copy mode reads only; direct mode stays fully undoable, so test with hashes);
- keep the runtime dependency-free beyond numpy and pyaudiowpatch;
- keep user-facing text plain and specific (see the existing wording);
- for package reports, include the GUID and the demo name (the *Packages* window has copy buttons).

To ask for removal of a package from the base pack, open an issue (see below).

---

## License, third-party content and fair use

### Code: MIT License

The **source code** of Killcam '99 (everything in this repository except the third-party content listed below) is
released under the **[MIT License](LICENSE)**: you may use, copy, modify, merge, publish, distribute, sublicense and
sell copies, provided the copyright notice and permission notice are included. It is provided *as is*, without
warranty of any kind.

### Third-party content (not covered by the MIT License)

| Content | Owner | Terms |
|---|---|---|
| `app/packs/base/`: community maps, mods, textures, sounds and music | their respective authors | see the fair-use statement below |
| *Unreal*, *Unreal Tournament*, the announcer calls and HUD texts referred to | Epic Games, Inc. | trademarks/copyright of Epic Games; **no part of the retail game is included** |
| Python (portable build in releases) | Python Software Foundation | PSF License |
| numpy (in releases) | NumPy developers | BSD-3-Clause |
| pyaudiowpatch (in releases) | its authors | MIT |
| ffmpeg (downloaded by the setup, not distributed here) | FFmpeg developers / gyan.dev builds | LGPL/GPL, see ffmpeg.org |

### Fair use statement for the base pack

The base pack contains **community-made** Unreal Tournament packages (maps, mods, textures, sounds and music)
in the exact versions that public game servers distributed to every connecting player through UT's own
auto-download ("redirect") system, often for decades. They are included **solely so that recorded demos of matches
on those servers can be played back** for the non-commercial purpose of making highlight clips. In particular:

- **No retail content.** Every file that belongs to the retail game (as listed in the game's own `Manifest.ini`)
  is excluded automatically. Players must own Unreal Tournament.
- **Unmodified.** Files are kept byte-for-byte as servers sent them, in UT's own cache format; authorship
  information inside the packages is preserved.
- **Purpose-limited and minimal.** The pack holds only the versions that demos need, not a general archive.
- **No charge.** Nothing in this repository is sold, and the base pack is not offered for any other purpose.
- **Credit and removal on request.** All rights remain with the original authors. If you are the author or rights
  holder of a package in the base pack and want it credited differently or removed, **open an issue** (or contact
  the repository owner) and it will be removed from the pack and future releases promptly, no questions asked.

This statement describes the intent and the safeguards; it is not legal advice and does not grant any rights in
third-party content beyond those the rights holders have given.

### Trademarks and affiliation

Killcam '99 is an independent fan project. It is **not made by, endorsed by or affiliated with Epic Games, Inc.**
or the OldUnreal team. *Unreal* and *Unreal Tournament* are trademarks or registered trademarks of Epic Games,
Inc. in the United States and elsewhere. All other names are the property of their respective owners.

<div align="center"><sub>Thanks to the OldUnreal team for keeping Unreal Tournament alive, to the FFmpeg project, and to
every mapper and modder whose work still makes these demos play.</sub></div>
