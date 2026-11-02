#include "Decks/VerseLiftTravel.h"

bool FVerseLiftTravel::Request(FName From, FName To, double NowS, bool bReducedMotion)
{
	if (To.IsNone() || From == To || IsBusy())
	{
		return false;
	}
	OriginDeck = From;
	TargetDeck = To;
	RequestedAt = NowS;
	LoadStartedAt = NowS;
	ArrivedAt = -1.0;
	bReduced = bReducedMotion;
	bLoadIssued = false;
	bDeckMissing = false;
	if (bReduced)
	{
		CurrentPhase = EVerseLiftPhase::Riding;
	}
	else
	{
		CurrentPhase = EVerseLiftPhase::DoorsClosing;
		Cues.Add(EVerseLiftCue::DoorClose);
	}
	return true;
}

bool FVerseLiftTravel::Tick(double NowS)
{
	bool bStartLoad = false;
	if (CurrentPhase == EVerseLiftPhase::DoorsClosing && NowS - RequestedAt >= DoorsS)
	{
		CurrentPhase = EVerseLiftPhase::Riding;
		Cues.Add(EVerseLiftCue::Ride);
	}
	if (CurrentPhase == EVerseLiftPhase::Riding && !bLoadIssued)
	{
		bLoadIssued = true;
		LoadStartedAt = NowS;
		bStartLoad = true;
	}
	if (CurrentPhase == EVerseLiftPhase::Riding && ArrivedAt < 0.0 && NowS - RequestedAt >= GiveUpS)
	{
		bDeckMissing = true;
		Cues.Add(EVerseLiftCue::GaveUp);
		CurrentPhase = EVerseLiftPhase::DoorsOpening;
		ArrivedAt = NowS - OpenAfterArrivalS;
	}
	if (CurrentPhase == EVerseLiftPhase::DoorsOpening && (bReduced || NowS - ArrivedAt >= OpenAfterArrivalS))
	{
		Finish(NowS);
	}
	return bStartLoad;
}

void FVerseLiftTravel::NotifyArrived(double NowS)
{
	if (CurrentPhase != EVerseLiftPhase::Riding || !bLoadIssued)
	{
		return;
	}
	ArrivedAt = NowS;
	LastLoad = NowS - LoadStartedAt;
	CurrentPhase = EVerseLiftPhase::DoorsOpening;
	if (bReduced)
	{
		Finish(NowS);
	}
}

void FVerseLiftTravel::NotifyFailed(double NowS)
{
	if (CurrentPhase != EVerseLiftPhase::Riding)
	{
		return;
	}
	bDeckMissing = true;
	Cues.Add(EVerseLiftCue::GaveUp);
	ArrivedAt = NowS;
	LastLoad = NowS - LoadStartedAt;
	Finish(NowS);
}

void FVerseLiftTravel::Finish(double NowS)
{
	if (!bReduced)
	{
		Cues.Add(EVerseLiftCue::DoorOpen);
	}
	LastRide = NowS - RequestedAt;
	CurrentPhase = EVerseLiftPhase::Idle;
}

TArray<EVerseLiftCue> FVerseLiftTravel::TakeCues()
{
	TArray<EVerseLiftCue> Out = MoveTemp(Cues);
	Cues.Reset();
	return Out;
}
