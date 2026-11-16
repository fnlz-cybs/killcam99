===============================================================================
  KILLCAM '99   version 1.1.0
  Turns your Unreal Tournament demos and recordings into kill clips
===============================================================================

  Killcam '99 watches your UT demos for the big moments - Multi Kills, Monster
  Kills, Ludicrous, Holy Shit, Godlike sprees, flag returns and captures - and
  records just those moments as short video clips. It can do the same with
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
  4. On the Demos page, press "Make clips from new demos".
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
    Press "Make clips from new demos". For every demo it has not seen yet,
    Killcam '99 first plays the demo very fast (about 40 times real time,
    nothing is recorded) to find your kills. Then it plays only the moments
    worth a clip at normal speed and records them.

  Picking moments yourself
    1. Press "Find kills in new demos". This is fast and records nothing.
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

  Finding kills again
    "Find kills in all demos again" looks at every demo once more. Useful
    after a Killcam '99 update, or when results look wrong. Your clips stay.


-------------------------------------------------------------------------------
 6. MAKING CLIPS FROM OBS / STREAMLABS RECORDINGS
-------------------------------------------------------------------------------

  If you record your games with OBS or Streamlabs, Killcam '99 can cut the
  clips straight out of those recordings. It reads the kill messages from the
  picture itself, so no demo, no game and no sound analysis is needed.

  1. Open the Recordings page and check the folder at the top (Change to pick
     the folder OBS saves to).
  2. Press "Make clips from new recordings". Reading takes about a quarter of
     each recording's length.
  3. The clips go to Clips\Recordings.

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

  Use the filters to show only new clips, kept ones, one kind of moment, or
  only clips from demos or from recordings. You can also simply delete a clip
  file in Explorer; Killcam '99 notices. A deleted clip (not a rejected one)
  is made again the next time you make clips from that demo.

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
    Combos        a Multi Kill or better followed by your flag return or your
                  capture within a number of seconds, or a Multi Kill in which
                  you kill the enemy flag carrier: one longer clip.
    Only your own announcer calls count, so other players' sprees never make
    a clip.

  Options > Length and output
    Before the streak   seconds of build-up before the first kill.
    After the last kill seconds after the last kill (or the flag play).
    Settle time         a short bit played but not kept, so picture and sound
                        are calm when the clip starts.
    File type           MP4 plays everywhere; MKV if you edit with tools that
                        prefer it.
    Quality             High is like the recording; Normal is about half the
                        size; Small for sharing quickly.


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
    * Press "Search online" (one version) or "Search online for all
      missing". Killcam '99 looks on UT redirect servers, in old copies saved
      by the Wayback Machine, and in the releases of known mods. Only the
      exact version is kept.
    * Or, if you have the files somewhere (another UT install, a map
      collection, a cache folder from a friend), press "Add a folder that has
      them". Folders you add are only read.
    * "Other versions you have" means you have the map, just not the version
      that server used. Those will not work for this demo.
    * The Packages button on each demo shows every version that demo needs
      and where each one is.


-------------------------------------------------------------------------------
 10. OPTIONS, PAGE BY PAGE
-------------------------------------------------------------------------------

  Every change is saved right away and used by the next job.

  Clips               what makes a clip (section 8).
  Length and output   clip length, file type and quality (section 8).
  Speed and sound     how many demos are searched at the same time (Auto
                      suits most PCs; more uses more CPU), the search speed,
                      and which sound device is recorded.
  Folders             the demo, recordings and clips folders, and deleting
                      temporary recordings to free space.
  Game                which UT folder is used and how; Open setup to change
                      it; Update to refresh the copy or the add-on; Remove
                      to take Killcam '99 out of your UT folder; Delete to
                      remove the separate copy.
  App                 open in its own window, a desktop notification when a
                      job is done, Developer tools, and Reset to the
                      standard options (your folders and game setup stay).

  Help shows a system check (with buttons to fix what is missing), the keys,
  the version, and "Copy diagnostics" for bug reports.


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

  1. Close Killcam '99 (Quit at the top right).
  2. Unzip the new version over this folder and let it replace files.
  Your settings, clips, package list and game copy are kept: they are not in
  the zip. If Killcam '99 is open while you update, it shows a banner asking
  to restart.

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

  A demo shows "packages missing"
    See section 9. Click the red label for the exact versions.

  Clips are black, or show the desktop
    Do not minimise the game window while recording. Update Killcam '99's
    ffmpeg with Help > system check if it says it is too old (8.1 or newer
    records in the background).

  Clips have no sound, or the wrong sound
    Choose the device your game plays on in Options > Speed and sound.

  Finding kills misses moments or finds wrong ones
    Make sure your player name is right, then use "Find kills in all demos
    again". Only your own announcer calls count.

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

  Killcam '99 only connects to the internet for these, and only when you ask
  for it:
    * the ffmpeg download during setup (from www.gyan.dev, checked against
      its published checksum),
    * searching for missing packages (UT redirect servers, the Wayback
      Machine at web.archive.org, and GitHub releases of known mods).
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
