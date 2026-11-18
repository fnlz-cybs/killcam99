//=============================================================================
// UT2VidConsole
// Part of Killcam '99 (ut99_dem2video). Only used by the Killcam '99 tool.
//
// With UVMode=0 this console behaves exactly like UTMenu.UTConsole.
// With UVMode=1 (scan) it writes every HUD message the demo's recorder gets
// (multi kills, sprees, ...) with the exact demo time to the log, plays the
// demo back as fast as possible and quits at the end.
// With UVMode=2 (record) it only writes the messages and progress lines; the
// demo plays at normal speed and nothing else changes (used while recording).
// With UVMode=3 (record parts) it jumps (udemo SeekTo) to each part listed in
// UVSegments (UVSettle seconds early, so the picture and sound settle after the
// jump), plays it at normal speed, and quits after the last part.
//
// The messages are caught by UT2VidMsgHUD, which takes the place of udemo's
// InterceptHUD on the recorded player (that is where udemo sends them first).
//=============================================================================
class UT2VidConsole extends UTConsole;

var config int   UVMode;           // 0 = off, 1 = scan, 2 = log only (recording), 3 = record parts
var config byte  UVPlayback;       // udemo playback mode for scans: 0 = time based, 1 = frame based, 2 = no frame cap
var config float UVSpeed;          // demo speed for scans (udemo's slomo): 40 = forty times real time
var config bool  UVQuitWhenDone;   // exit UT when the demo has ended
var config float UVProgressEvery;  // demo seconds between progress lines
var config string UVSegments;      // mode 3: "start:end,start:end,..." in demo seconds
var config float UVWait;           // mode 3: demo seconds to play before the first jump
var config float UVSettle;         // mode 3: jump this many demo seconds before a part starts
var config bool  UVNoWindows;      // keep UT's window layer (menus, console window) off the picture

var bool   UVInDemo, UVSpeedSet, UVFinished;
var int    UVCount, UVHooks;
var float  UVNextProgress;
var float  UVSegS[32], UVSegE[32];
var int    UVSegN, UVSegI, UVPhase, UVPhaseTicks;  // phase 0 jump, 1 jumping, 4 settle, 2 part, 3 outro
var float  UVOutroUntil;
var bool   UVParsed;

event Tick( float Delta )
{
	Super.Tick(Delta);
	UVPoll();
}

event PostRender( canvas C )
{
	Super.PostRender(C);
	UVPoll();
	UVDrawMarker(C);
}

state UWindow
{
	event Tick( float Delta )
	{
		Super.Tick(Delta);
		UVPoll();
	}

	event PostRender( canvas C )
	{
		Super.PostRender(C);
		UVPoll();
		UVDrawMarker(C);
	}
}

// Mode 3: a small magenta square in the top left corner tells the recorder exactly which video
// frames do NOT belong to a part: it is shown while waiting, jumping, settling and after the last
// part, and hidden while a part plays. The converter reads it from the recording (frame exact);
// the clips are the stretches without it, so they need no cover. Log lines can reach the log
// file seconds late, the picture cannot.
function UVDrawMarker( canvas C )
{
	if ( UVMode != 3 || !UVInDemo || UVFinished || UVPhase == 2 )
		return;
	C.Style = 1;
	C.DrawColor.R = 255;
	C.DrawColor.G = 0;
	C.DrawColor.B = 255;
	C.SetPos(0, 0);
	C.DrawRect(Texture'UWindow.WhiteTexture', 16, 16);
	C.DrawColor.R = 255;
	C.DrawColor.G = 255;
	C.DrawColor.B = 255;
}

// Called by UT2VidMsgHUD for every localized message the recorded player receives.
function UVMessage( DemoPlaybackSpec D, PlayerPawn Rec, class<LocalMessage> M, int Sw,
                    PlayerReplicationInfo PRI1, PlayerReplicationInfo PRI2, Object Obj, string CritStr )
{
	local string Who, Text;
	local bool bRec;
	local float T;

	if ( UVMode == 0 || M == None )
		return;
	T = -1;
	if ( D != None && D.Driver != None )
		T = D.Driver.GetCurrentTime();
	Text = CritStr;
	if ( Text == "" )
		Text = M.static.GetString(Sw, PRI1, PRI2, Obj);
	if ( PRI1 != None )
		Who = PRI1.PlayerName;
	bRec = ( Rec != None && PRI1 != None && PRI1 == Rec.PlayerReplicationInfo );
	UVCount++;
	Log("UT2VID MSG t=" $ T $ " where=hud class=" $ string(M) $ " switch=" $ Sw $ " recorder=" $ bRec
		$ " who=" $ Who $ " text=" $ Text, 'UT2Vid');
}

// Put UT2VidMsgHUD in place of udemo's InterceptHUD (udemo only replaces it again when the
// recorded player changes, and then we simply swap again).
function UVHookPlayer( DemoPlaybackSpec D )
{
	local InterceptHUD OldHUD;
	local UT2VidMsgHUD NewHUD;

	if ( D.PlayerLinked == None || D.PlayerLinked.myHUD == None )
		return;
	if ( UT2VidMsgHUD(D.PlayerLinked.myHUD) != None )
		return;
	OldHUD = InterceptHUD(D.PlayerLinked.myHUD);
	if ( OldHUD == None )
		return;
	NewHUD = D.Spawn(class'UT2VidMsgHUD', D.PlayerLinked);
	if ( NewHUD == None )
		return;
	NewHUD.SetOwner(D.PlayerLinked);
	NewHUD.Real = OldHUD.Real;
	NewHUD.Spy = self;
	D.PlayerLinked.myHUD = NewHUD;
	D.h = NewHUD;
	UVHooks++;
	Log("UT2VID HOOKED player=" $ string(D.PlayerLinked) $ " count=" $ UVHooks, 'UT2Vid');
}

// "12.5:40,300:351.2" -> UVSegS / UVSegE
function UVParseSegments()
{
	local string Rest, Part;
	local int i, j;

	Rest = UVSegments;
	UVSegN = 0;
	while ( Rest != "" && UVSegN < 32 )
	{
		i = InStr(Rest, ",");
		if ( i < 0 )
		{
			Part = Rest;
			Rest = "";
		}
		else
		{
			Part = Left(Rest, i);
			Rest = Mid(Rest, i + 1);
		}
		j = InStr(Part, ":");
		if ( j > 0 )
		{
			UVSegS[UVSegN] = float(Left(Part, j));
			UVSegE[UVSegN] = float(Mid(Part, j + 1));
			if ( UVSegE[UVSegN] > UVSegS[UVSegN] )
				UVSegN++;
		}
	}
	Log("UT2VID SEGMENTS count=" $ UVSegN, 'UT2Vid');
}

function UVSegmentsDone()
{
	UVFinished = true;
	Log("UT2VID SEGMENTS DONE count=" $ UVSegN, 'UT2Vid');
	Viewport.Actor.ConsoleCommand("exit");
}

// Mode 3: jump to a little before a part, wait until udemo has finished the jump and the part's
// start is reached, play it, next part. After the last part the marker stays up for a second.
function UVSegmentTick( DemoPlaybackSpec D, float T )
{
	local float Target;

	if ( !UVParsed )
	{
		UVParsed = true;
		UVParseSegments();
		if ( UVSegN == 0 )
		{
			UVSegmentsDone();
			return;
		}
	}
	if ( UVPhase == 3 )
	{
		if ( T >= UVOutroUntil )
			UVSegmentsDone();
		return;
	}
	if ( UVSegI >= UVSegN )
		return;
	if ( UVPhase == 0 )
	{
		if ( UVSegI == 0 && T < UVWait )
			return;  // give the recorder a moment to start
		Target = UVSegS[UVSegI] - UVSettle;
		if ( Target < 0 )
			Target = 0;
		Log("UT2VID SEEK n=" $ UVSegI $ " to=" $ Target $ " from=" $ T, 'UT2Vid');
		if ( T < Target - 0.5 || T > UVSegS[UVSegI] )
			D.SeekTo(string(Target));
		UVPhase = 1;
		UVPhaseTicks = 0;
		return;
	}
	if ( UVPhase == 1 )
	{
		UVPhaseTicks++;
		if ( UVPhaseTicks < 4 || D.bSeeking || D.SeekTick != 0 )
		{
			if ( UVPhaseTicks < 2000 )
				return;
		}
		UVPhase = 4;
	}
	if ( UVPhase == 4 )
	{
		if ( T < UVSegS[UVSegI] - 0.02 )
			return;  // settling: play on to the part's real start
		Log("UT2VID SEGMENT START n=" $ UVSegI $ " t=" $ T, 'UT2Vid');
		UVNextProgress = 0;
		UVPhase = 2;
		return;
	}
	if ( T >= UVSegE[UVSegI] )
	{
		Log("UT2VID SEGMENT END n=" $ UVSegI $ " t=" $ T, 'UT2Vid');
		UVSegI++;
		UVPhase = 0;
		if ( UVSegI >= UVSegN )
		{
			UVPhase = 3;
			UVOutroUntil = T + 1.0;
		}
	}
}

// "disconnect" while Killcam '99 plays a demo: ignored. Old anti-cheat code in a demo (ACE v1.3,
// NPLoader v20) cannot load its 32-bit native library in a 64-bit game; it then sends the console
// command "disconnect" (live, the server would have kicked the player), which would end the demo
// after ~25 seconds. The tool ends demos itself. Outside a Killcam '99 session it disconnects as usual.
exec function Disconnect()
{
	if ( UVMode != 0 && UVInDemo && !UVFinished )
	{
		Log("UT2VID BLOCKED disconnect", 'UT2Vid');
		return;
	}
	if ( Viewport != None && Viewport.Actor != None )
		Viewport.Actor.ClientTravel("?failed", TRAVEL_Absolute, false);
}

function UVPoll()
{
	local DemoPlaybackSpec D;
	local float T;
	local string MapName;
	local int i;

	if ( UVMode == 0 || UVFinished )
		return;
	if ( Viewport == None || Viewport.Actor == None )
		return;

	D = DemoPlaybackSpec(Viewport.Actor);
	if ( D == None )
	{
		// back in the menu level after the demo: we are done
		if ( UVInDemo )
		{
			UVFinished = true;
			Log("UT2VID SCAN END messages=" $ UVCount $ " hooks=" $ UVHooks, 'UT2Vid');
			if ( UVMode == 1 && UVQuitWhenDone )
				Viewport.Actor.ConsoleCommand("exit");
		}
		return;
	}
	if ( D.Driver == None )
		return;

	// Old anti-cheat code in some demos (NPLoader) starts UT's window layer; the console then
	// draws its console window over the game. Nothing of it belongs in a clip.
	if ( UVNoWindows )
	{
		if ( bShowConsole )
			HideConsole();
		if ( IsInState('UWindow') )
		{
			CloseUWindow();
			Log("UT2VID CLOSED window layer t=" $ D.Driver.GetCurrentTime(), 'UT2Vid');
		}
	}

	if ( !UVInDemo )
	{
		UVInDemo = true;
		MapName = string(D.Level);
		i = InStr(MapName, ".");
		if ( i > 0 )
			MapName = Left(MapName, i);
		Log("UT2VID SCAN START total=" $ D.Driver.GetTotalTime() $ " frames=" $ D.Driver.GetTotalFrames()
			$ " map=" $ MapName $ " version=17", 'UT2Vid');
	}
	if ( !UVSpeedSet )
	{
		// Scan: time based playback at a high speed; every recorded packet (and so every
		// message) is still read, the game just covers more demo time per frame.
		// Recording: time based at exactly 1x. udemo's default when a demo is started from the
		// console is frame based (one recorded frame per drawn frame), which plays demos
		// recorded at a high frame rate in slow motion.
		UVSpeedSet = true;
		if ( UVMode == 1 )
		{
			D.Driver.SetPlayBackMode(UVPlayback);
			if ( UVSpeed > 0 )
				D.Driver.SetSpeed(UVSpeed);
		}
		else
		{
			D.Driver.SetPlayBackMode(0);
			D.Driver.SetSpeed(1.0);
		}
		Log("UT2VID SPEED mode=" $ D.Driver.PlayBackMode $ " speed=" $ D.Driver.mySpeed, 'UT2Vid');
	}
	UVHookPlayer(D);

	T = D.Driver.GetCurrentTime();
	if ( UVMode == 3 )
		UVSegmentTick(D, T);
	if ( UVProgressEvery > 0 && T >= UVNextProgress )
	{
		UVNextProgress = T + UVProgressEvery;
		// td: the level's time dilation (the server's game speed, 1.1 in 'hardcore'), so the
		// converter can apply the game's 3 second multi kill rule in game seconds
		Log("UT2VID PROGRESS t=" $ T $ " td=" $ D.Level.TimeDilation $ " speed=" $ D.Driver.mySpeed, 'UT2Vid');
	}
}

defaultproperties
{
	UVMode=0
	UVPlayback=0
	UVSpeed=40.0
	UVWait=6.0
	UVSettle=2.0
	UVQuitWhenDone=True
	UVProgressEvery=60.0
	UVNoWindows=True
}
