//=============================================================================
// UT2VidMsgHUD
// Part of ut99_dem2video. Takes the place of udemo's InterceptHUD on the
// recorded player: every localized message (multi kill, spree, ...) that player
// receives is reported to UT2VidConsole, then handled exactly as udemo does.
//=============================================================================
class UT2VidMsgHUD extends InterceptHUD;

var UT2VidConsole Spy;

simulated function LocalizedMessage
(
	class<LocalMessage> Message,
	optional int Switch,
	optional PlayerReplicationInfo RelatedPRI_1,
	optional PlayerReplicationInfo RelatedPRI_2,
	optional Object OptionalObject,
	optional String CriticalString
)
{
	if ( Spy != None )
		Spy.UVMessage(Real, PlayerPawn(Owner), Message, Switch, RelatedPRI_1, RelatedPRI_2, OptionalObject, CriticalString);
	Super.LocalizedMessage(Message, Switch, RelatedPRI_1, RelatedPRI_2, OptionalObject, CriticalString);
}
