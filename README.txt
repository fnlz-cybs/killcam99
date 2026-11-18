===============================================================================
  KILLCAM '99   version 1.3.0
  Turns your Unreal Tournament demos and recordings into kill clips
===============================================================================

  Killcam '99 watches your UT demos for the big moments - Multi Kills, Monster
  Kills, Ludicrous, Holy Shit, Godlike sprees, flag returns and captures - and
  records just those moments as short video clips. Every clip is checked for
  stutter, and choppy moments are recorded again. It can do the same with
  gameplay you recorded with OBS or Streamlabs.

  Contents
    1.  Quick start
    2.  What is in this folder
    3.  What you need
    4.  The first start: setup
    5.  Making clips from demos
    6.  Making clips from OBS / Streamlabs recordings
    7.  Reviewing your clips
    8.  Choosing what makes a clip
    9.  Packages: maps, mods and textures demos need
    10. Options, page by page
    11. Keys, drag and drop, and the text menu
    12. Updating Killcam '99
    13. Removing Killcam '99
    14. Troubleshooting
    15. What goes online
    16. Credits and legal


-------------------------------------------------------------------------------
 1. QUICK START
-------------------------------------------------------------------------------

  1. Unzip this folder anywhere you like, for example in Documents or on a
     second drive. Not inside your UnrealTournament folder.
  2. Double-click Killcam99.bat.
  3. The first time, a short setup asks where Unreal Tournament is and how
     Killcam '99 may use it (see section 4). It also downloads ffmpeg.
  4. On the Demos page, press "Make clips from all demos not done yet".
     This does every demo in your demo folder that Killcam '99 has not done
     yet, old ones too. To do only some, tick them in the list first
     (section 5).
  5. Your clips appear in the Clips folder next to Killcam99.bat.


-------------------------------------------------------------------------------
 2. WHAT IS IN THIS FOLDER
-------------------------------------------------------------------------------

  Killcam99.bat     Start Killcam '99. Also accepts files dropped on it.
  README.txt        This manual.
  Clips\            Your finished videos. Created on the first start.
     Demos\           clips made from demos, one folder per kind of moment
                      (Monster Kill, Godlike, Flag Return, ...)
     Recordings\      clips cut from your OBS / Streamlabs recordings
     Rejected\        clips you rejected; Restore in the app puts them back
  app\              Everything Killcam '99 needs to run. This folder is
                    hidden; you never have to open it. Inside:
     python\          a private copy of Python (nothing is installed on
                      your PC)
     packs\base\      map, mod and texture packages that ship with the app
     tools\ffmpeg\    ffmpeg, downloaded during the setup
     UT\              the separate copy of Unreal Tournament, if you chose
                      that in the setup
     data\            your settings, the package list, the log file and
                      work files (scans, temporary recordings)

  To see the hidden app folder in Explorer: View > Show > Hidden items.

  You can move the whole Killcam99 folder to another place at any time, as
  long as you move all of it. You can also choose a different Clips folder in
  Options > Folders.


-------------------------------------------------------------------------------
 3. WHAT YOU NEED
-------------------------------------------------------------------------------

  * Windows 10 or Windows 11, 64-bit.
  * Unreal Tournament (GOTY or the original) with the OldUnreal 469 patch.
    Get the patch, or a complete installer, at https://www.oldunreal.com
  * Disk space: about 600 MB for Killcam '99 itself, plus the size of your
    UT folder if you choose "Make a separate copy" in the setup (usually
    1 to 3 GB), plus your clips.
  * An internet connection once, to download ffmpeg (about 100 MB).

  Nothing else needs to be installed: Python and the libraries come along in
  the app folder.


-------------------------------------------------------------------------------
 4. THE FIRST START: SETUP
-------------------------------------------------------------------------------

  The setup has four steps. You can run it again any time from
  Options > Game > Open setup.

  Step 1 - Find Unreal Tournament
    Pick the folder you play UT from: the one with a System folder that holds
    UnrealTournament.exe. Folders found on your PC are listed; use Browse if
    yours is not. Killcam '99 checks that it really is UT with the 469 patch.

  Step 2 - How should Killcam '99 use it?
    Both choices make exactly the same clips. The difference is where
    Killcam '99 is allowed to write.

    Make a separate copy (safest)
      Killcam '99 copies your UT into app\UT and only ever works in that copy.
      + Your own UT folder is only read. Nothing in it ever changes.
      + You can keep playing UT while clips are being made.
      - Needs extra disk space (the size of your UT folder).
      - Changes you make in your own UT later (new maps, a newer patch) reach
        the copy when you press Options > Game > Update.

    Use my UT folder directly (no extra space)
      Killcam '99 works in the folder you play from, with the smallest
      possible footprint.
      + No extra disk space, ready in seconds.
      + Always uses your current UT, maps and mods.
      - Adds one small add-on file (System\UT2VidHook.u) and, when a demo
        needs them, the exact map and mod packages to your Cache folder.
        If an old anti-cheat loader in System is for the wrong type of
        game (32-bit in a 64-bit UT), it is swapped for the right one;
        the original is kept, and Remove puts it back.
      - Do not play UT while clips are being recorded.
      Your settings files (UnrealTournament.ini, User.ini) are never edited:
      Killcam '99 starts the game with its own copies of them. Temporary
      files are removed after every run, and Options > Game > Remove takes
      out everything Killcam '99 ever added.

  Step 3 - Your folders
    Demos:       where your .dem files are. UT saves them in its System
                 folder unless you chose another one.
    Recordings:  where OBS or Streamlabs saves your recordings (optional).
    Clips:       where the finished videos go. Default: the Clips folder next
                 to Killcam99.bat.

  Step 4 - Set up
    Killcam '99 prepares the game, reads which packages are available and, if
    needed, downloads ffmpeg. When it says "All set", press Open Demos.


-------------------------------------------------------------------------------
 5. MAKING CLIPS FROM DEMOS
-------------------------------------------------------------------------------

  The Demos page lists every demo in your demo folder, newest first.

  The quick way
    Press "Make clips from all demos not done yet". For every demo it has
    not done yet, Killcam '99 first plays the demo very fast (about 40 times
    real time, nothing is recorded) to find your kills. Then it plays only
    the moments worth a clip at normal speed and records them.

    "Not done yet" has nothing to do with the date of a demo: it means every
    demo in your demo folder that Killcam '99 has not handled before, however
    old. The first time, that is the whole folder. If that folder holds years
    of demos, this can take a long time; use "Only some demos" below instead.

  Only some demos
    Tick the demos you want in the list (sort by Recorded to find the newest)
    and press "Make clips" in the bar that appears.

  Removing demos and putting them back
    "Remove" (per demo, or "Remove from list" for the ticked ones) takes a
    demo off the list; the .dem file stays where it is and no job touches it.
    To bring demos back: open the "Removed" filter, tick them (the box at the
    top of the list ticks all) and press "Put back".

  Picking moments yourself
    1. Press "Find kills in demos not looked at yet". This is fast and
       records nothing.
    2. Each demo now shows its moments, for example "4:30 Monster Kill".
    3. Click the moments you want; they turn blue.
    4. Press "Record these moments" in the bar that appears.
    The eye icon next to a moment plays just that part in the game, so you
    can check it first. "Watch" plays the whole demo.

  Status of a demo
    Not looked at      kills not searched for yet
    To record          moments found, not all recorded yet
    Partly recorded    some of its moments are recorded
    Recorded           every moment has a clip
    No moments         nothing in this demo matches your choices (section 8)
    N packages missing the demo needs a map or mod version you do not have
                       (section 9); click it for the details

  While recording
    * UT opens in a window and plays the moments. Recording runs in the
      background: you can use other programs, but do not minimise the game.
    * Every sound your PC plays ends up in the clip, so keep music, videos and
      voice chat quiet. To record from a specific sound device, choose it in
      Options > Speed and sound.
    * You can stop at any time with Stop at the bottom. Clips already saved
      stay; the rest is done the next time.

  Choppy moments
    After cutting each clip, Killcam '99 checks that the picture stays
    smooth: a stretch where the game showed far fewer new frames than usual
    (it looks like low fps) counts as choppy. The seconds after you die are
    left out, because a still picture there is normal.
    A choppy moment is not saved straight away. It is recorded once more at
    the end of the queue, with as much of your PC as possible for the game:
    high priority for UT and the recording, the lightest recording settings,
    3 seconds more settle time after each jump, and the game window in front
    (so it takes over your screen for a moment).
    * Smooth this time: that recording is kept, as a normal clip.
    * Still choppy: the smoother of the two recordings is kept, marked with
      a "Choppy" warning (section 7). When both stutter at the same spot,
      the clip says "the stutter is in the demo itself": the lag happened
      while the demo was recorded (the player's PC or connection), and no
      recording can fix that.
    If you stop before the end of the queue, those moments are simply
    recorded again next time. To skip the second try, switch off "Record
    choppy moments again at the end of the queue" (section 8).

  Finding kills again
    "Find kills in all demos again" looks at every demo once more. Useful
    after a Killcam '99 update, or when results look wrong. Your clips stay.

  Starting over
    Options > Folders > "Delete all demo scans" deletes every saved scan
    result. Every demo goes back to Not looked at, and the next Make clips
    or Find kills searches all of them again (with many demos that takes a
    while). Your clips stay, and moments that were already recorded are not
    recorded again; readings of OBS recordings are not touched. It asks
    first and cannot be undone, but once the demos are searched again the
    Demos page shows what changed (see "Comparing results" below).

  Comparing results
    When you change what makes a clip or the combos (section 8), or find
    kills again, Killcam '99 remembers the results as they were. The Demos
    page then shows a blue bar with what changed, for example
      Results changed since 01:10 (you changed the clip options)
      64 moments, was 82: +3 new, -21 no longer a clip, 2 changed
    and marks the moments themselves:
      NEW                a moment that was not there before
      struck through     "no longer a clip": it was a moment before, not
                         now (a clip already made stays in Clips)
      was: ...           the same moment, now with other labels
    "Show changed demos" lists only the demos that changed (also the
    "Changed" filter). "Keep new results" accepts them and the marks go
    away. "Undo changes" puts your clip options back as they were (only
    after an options change). More changes before you decide are all
    compared with the results from before the first one.


-------------------------------------------------------------------------------
 6. MAKING CLIPS FROM OBS / STREAMLABS RECORDINGS
-------------------------------------------------------------------------------

  If you record your games with OBS or Streamlabs, Killcam '99 can cut the
  clips straight out of those recordings. It reads the kill messages from the
  picture itself, so no demo, no game and no sound analysis is needed.

  1. Open the Recordings page and check the folder at the top (Change to pick
     the folder OBS saves to).
  2. Either press "Make clips from new recordings": every new recording is
     read (about a quarter of its length) and all its moments are cut.
     Or press "Find moments in new recordings": the recordings are read but
     nothing is cut. Each recording then lists its moments, for example
     "13:29 Multi Kill + Flag Return"; a tick means it is cut already.
     Click the moments you want (they turn blue) and press "Cut these
     moments". That takes only seconds: the saved reading is used.
  3. The clips go to Clips\Recordings.

  Per recording: "Find moments" reads one new recording, "Cut all" cuts all
  its moments that are not cut yet, "Read again" reads it from scratch and
  lists its moments again (nothing is cut). A recording OBS is still writing
  is skipped until it is finished.

  How the reading works
    Killcam '99 looks at the three message lines in the middle of the HUD
    ("You killed ...", flag and spree messages, and the red multi kill text)
    a few times per second. Frames without text are skipped; the others are
    read with the text recognition built into Windows, on your PC and
    offline. Each message is followed from frame to frame, misreadings are
    filtered out, and the match clock tells warm-up apart from the match, so
    warm-up kills never make a clip. The result is saved, so changing your
    clip options or picking moments never needs a second reading.

    A message fades while it is on screen and is sometimes misread; Killcam
    '99 treats a fading, misread name as the same kill, so one kill never
    turns into a made-up Multi Kill. When something is hidden, it only fills
    in what the game's rules prove (an Ultra Kill means there was a Double
    Kill before it). It would rather miss a moment than invent one.

    Windows needs a text recognition language for this: English is best
    (Settings > Time & language > Language). If your stream layout shows the
    game smaller or moved, see "Killcam99.bat --help" (--stream-area).

  Your player name: leave it empty and Killcam '99 works it out. If you play
  under several names, type the one used in these recordings.
  Exact cuts: makes every clip start on exactly the right frame, but takes
  longer because the video is re-encoded.


-------------------------------------------------------------------------------
 7. REVIEWING YOUR CLIPS
-------------------------------------------------------------------------------

  The Clips page plays every clip right in the window.

  Keep      marks a clip as good (it stays where it is).
  Reject    moves the clip to Clips\Rejected. It is not made again.
  Restore   moves a rejected clip back.

  Delete    (the red bin) deletes the clip file for good to free disk
            space, after asking. "Delete rejected" in the toolbar deletes
            every rejected clip at once. Deleted clips are remembered and
            not made again; picking that moment again makes a new clip.

  A clip with a warning shows it in red under its name, for example when the
  announcer calls are not where they should be. A red "Choppy" label means
  the clip stutters even after a second recording (section 5, "Choppy
  moments"); the line below it says where. Watch it and decide: Keep it if
  the stutter is not in the part that matters, Reject it otherwise.

  Use the filters to show only new clips, kept ones, clips with a warning,
  one kind of moment, or only clips from demos or from recordings. The
  counters show how much space your clips take. Deleting a clip file in
  Explorer works too, but such a clip is not remembered and is made again
  the next time.

  Clip file names tell you everything: date and time of the match, the map,
  the time in the match and what happened, for example
    2026-04-19 21.42 CTF-Rune - 07m00s Monster Kill + Flag Return.mp4


-------------------------------------------------------------------------------
 8. CHOOSING WHAT MAKES A CLIP
-------------------------------------------------------------------------------

  Options > Clips
    Multi kills   Mega Kill, Ultra Kill, Monster Kill, Ludicrous Kill,
                  Holy Shit (and Multi Kill, which makes many clips).
    Sprees        Killing Spree, Rampage, Dominating, Unstoppable, Godlike,
                  Wicked Sick.
    Combos        one longer clip for a multi kill followed by a flag play:
                  * then you return your flag (within the seconds you set),
                  * then you capture (within the seconds you set),
                  * or the multi kill includes killing the enemy flag carrier.
                  Each of the three picks the multi kill it starts at (Multi
                  Kill, Mega Kill, Ultra Kill, Monster Kill, Ludicrous Kill
                  or Holy Shit); that one and every higher one count. For
                  example "Ultra Kill or higher, then you return your flag"
                  next to "Monster Kill or higher, then you capture".
                  Standard: Ultra Kill or higher for all three. Multi Kill or
                  Mega Kill make many more combo clips. Untick a flag play to
                  make no combo clips of that kind.
                  These are separate from the multi kills above: a multi kill
                  you left unticked there can still make a combo clip here,
                  and the other way round.
    Only your own announcer calls count, so other players' sprees never make
    a clip. A multi kill counts by the name the game showed: some mods name
    kill counts differently (one calls 4 kills a Mega Kill, plain UT calls
    that an Ultra Kill), and then the mod's name is the one that counts, the
    same name the clip gets.
    Changing these takes effect at once for demos already searched: the
    moments on the Demos page update without finding the kills again, and
    the page shows what changed (section 5, "Comparing results"). A Make
    clips run that is already busy follows the change too: every demo it
    has not recorded yet is planned again with your new choices.

  Options > Length and output
    Before the streak   seconds of build-up before the first kill.
    After the last kill seconds after the last kill (or the flag play).
    Settle time         a short bit played but not kept, so picture and sound
                        are calm when the clip starts.
    File type           MP4 plays everywhere; MKV if you edit with tools that
                        prefer it.
    Quality             High is like the recording; Normal is about half the
                        size; Small for sharing quickly.
    Record choppy moments again at the end of the queue
                        on by default (section 5, "Choppy moments"). Turn it
                        off on a slow PC to save time: choppy clips are then
                        kept straight away, marked "Choppy".


-------------------------------------------------------------------------------
 9. PACKAGES: MAPS, MODS AND TEXTURES DEMOS NEED
-------------------------------------------------------------------------------

  Why this matters
    A demo can only be played with the exact same version of every map, mod,
    texture and sound package the server used. Two files with the same name
    can be different versions; UT tells them apart by a GUID, a 32-character
    code such as 8E89710A423C6C569CEC6F978498D3C3. If one version is missing,
    the demo does not play.

  Where Killcam '99 looks, in this order
    1. your game folder
    2. the base pack that ships with Killcam '99 (137 versions that demos
       often need)
    3. your own package folders (add them on the Packages page)
    4. packages found online earlier
    When a demo needs one, only that exact version is copied into the game's
    Cache folder. The other places are only read.

  The Packages page
    Missing         every version your demos need that none of the places
                    has: name, file, GUID, size, generation, which demos need
                    it, and which other versions of it you do have.
    Where to look   the places above, how many versions each holds, and
                    buttons to add or remove a folder. Press "Refresh
                    packages" after you add maps to a folder.
    All packages    everything Killcam '99 knows about, with a search box.

  When something is missing
    * Make clips and Find kills already look online by themselves, on UT
      redirect servers, in the GitHub releases of mods whose authors
      publish there, in the archives on medor.no-ip.org, and on Unreal
      Archive (unrealarchive.org, the largest UT collection).
    * For a deeper search press "Search online" (one version) or "Search
      online for all missing": the same places plus old copies saved by the
      Wayback Machine (slower). Only the exact version is kept.
    * Or, if you have the files somewhere (another UT install, a map
      collection, a cache folder from a friend), press "Add a folder that has
      them". Folders you add are only read.
    * "Other versions you have" means you have the map, just not the version
      that server used. Those will not work for this demo.
    * Sounds, textures and music the game loads at start (Announcer.uax,
      for example, when you use another announcer, or the demo's server
      did): Killcam '99 notices when a demo needs another version than the
      game's own and starts the game with the demo's version for that
      demo. Your own files are not changed.
    * The Packages button on each demo shows every version that demo needs
      and where each one is.


-------------------------------------------------------------------------------
 10. OPTIONS, PAGE BY PAGE
-------------------------------------------------------------------------------

  Every change is saved right away and used by the next job.

  Clips               what makes a clip, and which multi kill each combo
                      starts at (section 8).
  Length and output   clip length, file type, quality, and whether choppy
                      moments are recorded again (section 8).
  Speed and sound     how many demos are searched at the same time (Auto
                      suits most PCs; more uses more CPU), the search speed,
                      and which sound device is recorded.
  Folders             the demo, recordings and clips folders; deleting
                      temporary recordings to free space; and deleting all
                      demo scans to start over (section 5).
  Game                which UT folder is used and how; Open setup to change
                      it; Update to refresh the copy or the add-on; Remove
                      to take Killcam '99 out of your UT folder; Delete to
                      remove the separate copy.
  App                 open in its own window, a desktop notification when a
                      job is done, check for updates when Killcam '99
                      starts, Developer tools, and Reset to the standard
                      options (your folders and game setup stay).

  Help shows a system check (with buttons to fix what is missing), the keys,
  the version with "Check for updates" (section 12), and "Copy diagnostics"
  for bug reports.


-------------------------------------------------------------------------------
 11. KEYS, DRAG AND DROP, AND THE TEXT MENU
-------------------------------------------------------------------------------

  Keys in the window (not while typing in a box)
    1 to 6     Demos, Recordings, Clips, Packages, Options, Help
    `          open or close the console with every message of the job
    Esc        cancel a dialog, close the console
    Enter      confirm a dialog

  Drag and drop
    Drop .dem files (or a folder of them) on Killcam99.bat: they are searched
    and their clips are made. Drop .mp4 or .mkv recordings: they are read for
    clips. The window does not need to be open.

  Text menu and command line
    Killcam99.bat menu      a simple text menu
    Killcam99.bat --help    every command line option


-------------------------------------------------------------------------------
 12. UPDATING KILLCAM '99
-------------------------------------------------------------------------------

  The easy way
    When a new version is out, a banner says so ("Killcam '99 1.4.0 is
    out"). Press "Update now": it is downloaded from GitHub and checked
    while you keep working. Then press "Restart and update": Killcam '99
    closes, puts the new version in place and opens again by itself.
    Help > Updates > "Check for updates" asks at any time. Killcam '99 asks
    GitHub once when it starts; switch that off in Options > App.

  By hand
    1. Close Killcam '99 (Quit at the top right).
    2. Unzip the new version (github.com/fnlz-cybs/killcam99, Releases) over
       this folder and let it replace files.

  Either way your settings, clips, package list and game copy are kept. If
  Killcam '99 is open while you update by hand, it shows a banner asking to
  restart.

  After an update, Options > Game > Update puts the newest add-on in place if
  the system check asks for it.


-------------------------------------------------------------------------------
 13. REMOVING KILLCAM '99
-------------------------------------------------------------------------------

  1. If you chose "Use my UT folder directly": open Options > Game and press
     Remove. Your UT folder is then exactly as it was before.
  2. Move your Clips folder somewhere else if you want to keep the clips.
  3. Delete the Killcam99 folder.
  Killcam '99 writes nothing to the registry and nothing outside this folder,
  except in your UT folder in direct mode (undone by step 1).


-------------------------------------------------------------------------------
 14. TROUBLESHOOTING
-------------------------------------------------------------------------------

  Windows says "Windows protected your PC"
    Killcam '99 is not signed with a paid certificate. Click "More info" and
    then "Run anyway".

  Nothing happens when I double-click Killcam99.bat
    The window opens in Microsoft Edge app mode. If Edge is missing, it opens
    in your normal browser instead. If a black window flashes and closes,
    start it from a Command Prompt to read the message, or open
    app\data\killcam.log.

  "This UT has no udemo"
    Install the OldUnreal 469 patch (https://www.oldunreal.com).

  The game crashes on some demos ("General protection fault")
    Demos from servers with the NPLoader / ACE anti-cheat crashed a 64-bit
    UT when NPLoader's old 32-bit loader was still in the game folder.
    Killcam '99 now puts the matching 64-bit loader (from the demo itself)
    in place before it plays such a demo, and keeps the old anti-cheat
    from ending the demo early or putting a window over the picture.
    After updating Killcam '99, press Options > Game > Update once, so
    the game gets the newest add-on. Demos you took off the list because
    of the crash: open the Removed filter on the Demos page and press Put
    back.

  A demo shows "packages missing"
    See section 9. Click the red label for the exact versions.

  Clips are black, or show the desktop
    Do not minimise the game window while recording. Update Killcam '99's
    ffmpeg with Help > system check if it says it is too old (8.1 or newer
    records in the background).

  Clips have no sound, or the wrong sound
    Choose the device your game plays on in Options > Speed and sound.

  Clips stutter or look low fps
    Killcam '99 checks every clip and records choppy moments again by itself
    (section 5, "Choppy moments"). If many clips still come out "Choppy":
    * close games, browser videos and other heavy programs while recording;
    * make sure Help > system check shows ffmpeg 8.1 or newer (it records
      the game window directly, which is lighter than recording the screen);
    * a higher "Settle time after a jump" (Options > Length and output)
      helps when the stutter is at the very start of clips.
    "The stutter is in the demo itself" cannot be fixed: the demo was
    recorded with that lag.

  Too many clips
    Untick Multi Kill and Killing Spree under "What makes a clip", and let
    the combos start at a higher multi kill, for example captures from
    Monster Kill (Options > Clips).

  Old demos get clips too
    "Make clips from all demos not done yet" does every demo in the folder
    that Killcam '99 has not done, whatever its date. Tick only the demos you
    want and use "Make clips" in the bar, or use "Remove" on the ones you
    never want (the files stay; Removed brings them back).

  Finding kills misses moments or finds wrong ones
    Make sure your player name is right, then use "Find kills in all demos
    again" (or start over with Options > Folders > "Delete all demo
    scans"). Only your own announcer calls count.

  A folder window did not appear
    It may have opened behind the Killcam '99 window. Look in the taskbar.

  The game window stays open after stopping
    Press Stop again or close it; Killcam '99 closes its own game windows the
    next time it starts. Your own UT is never closed.

  Reporting a problem
    Help > Copy diagnostics copies your versions, folders, the system check
    and the end of the log. Paste that into your message. The full log is in
    app\data\killcam.log (Help > Log file > Open).


-------------------------------------------------------------------------------
 15. WHAT GOES ONLINE
-------------------------------------------------------------------------------

  Killcam '99 only connects to the internet for these:
    * the ffmpeg download during setup (from www.gyan.dev, checked against
      its published checksum),
    * searching for missing packages (UT redirect servers, GitHub releases
      of known mods, medor.no-ip.org, unrealarchive.org, and on request the
      Wayback Machine at web.archive.org),
    * the update check: one question to GitHub (api.github.com) when
      Killcam '99 starts (Options > App switches it off) or when you press
      Check for updates, and the download of a new version when you press
      Update now (checked against GitHub's SHA-256 checksum).
  The window itself runs on your PC only (127.0.0.1) and cannot be reached
  from other computers. Nothing about you or your demos is sent anywhere.


-------------------------------------------------------------------------------
 16. CREDITS AND LEGAL
-------------------------------------------------------------------------------

  Killcam '99 is not made by or affiliated with Epic Games. Unreal and
  Unreal Tournament are trademarks of Epic Games, Inc. You need your own copy
  of Unreal Tournament; Killcam '99 contains no part of the retail game.

  The base pack holds community-made maps, mods and textures as servers sent
  them to players. They remain the work of their authors.

  Thanks to the OldUnreal team for keeping Unreal Tournament alive, and to
  the FFmpeg project.
