#include "Lift/VerseLiftModel.h"

#include "DeckHud/VerseDeckHudModel.h"

void FVerseLiftModel::SetCurrentDeck(FName Deck)
{
	if (FVerseDeckIds::IsDeck(Deck))
	{
		CurrentDeck = Deck;
		if (!bPanelOpen)
		{
			FocusedDeck = Deck;
		}
	}
}

void FVerseLiftModel::OpenPanel(EVerseLiftSource Source)
{
	if (IsRiding())
	{
		return;
	}
	bPanelOpen = true;
	LastSource = Source;
	// The current deck has the keyboard focus.
	FocusedDeck = CurrentDeck;
}

void FVerseLiftModel::ClosePanel()
{
	bPanelOpen = false;
}

TArray<FVerseLiftRow> FVerseLiftModel::Rows() const
{
	TArray<FVerseLiftRow> Out;
	for (const FName Deck : FVerseDeckIds::All())
	{
		FVerseLiftRow Row;
		Row.Deck = Deck;
		Row.Number = FVerseDeckIds::NumberText(Deck);
		Row.NameKey = FString::Printf(TEXT("verse.deck.%s"), *Deck.ToString());
		Row.AboutKey = FString::Printf(TEXT("verse.deck.%s_about"), *Deck.ToString());
		Row.bCurrent = Deck == CurrentDeck;
		Row.bFocused = Deck == FocusedDeck;
		Out.Add(Row);
	}
	return Out;
}

void FVerseLiftModel::MoveFocus(int32 Direction)
{
	const TArray<FName>& Decks = FVerseDeckIds::All();
	const int32 Index = Decks.IndexOfByKey(FocusedDeck);
	FocusedDeck = Decks[FMath::Clamp((Index < 0 ? 0 : Index) + Direction, 0, Decks.Num() - 1)];
}

bool FVerseLiftModel::Choose(FName Deck, double Now)
{
	if (!FVerseDeckIds::IsDeck(Deck) || IsRiding())
	{
		return false;
	}
	bPanelOpen = false;
	if (Deck == CurrentDeck)
	{
		return false;
	}
	Target = Deck;
	Doors = EVerseDoorState::Closing;
	PhaseStartedAt = Now;
	RideStartedAt = Now;
	ClosedAt = -1.0;
	ReadyAt = -1.0;
	OpenStartedAt = -1.0;
	bTravelled = false;
	bReady = false;
	return true;
}

void FVerseLiftModel::NotifyDeckReady(FName Deck, double Now)
{
	if (IsRiding() && Deck == Target && !bReady)
	{
		bReady = true;
		ReadyAt = Now;
		Tick(Now);
	}
}

void FVerseLiftModel::Tick(double Now)
{
	if (Doors == EVerseDoorState::Closing && Now >= PhaseStartedAt + DoorCloseSeconds)
	{
		Doors = EVerseDoorState::Closed;
		ClosedAt = PhaseStartedAt + DoorCloseSeconds;
	}
	if (Doors == EVerseDoorState::Closed)
	{
		if (!bTravelled)
		{
			bTravelled = true;
			if (TravelTo)
			{
				TravelTo(Target);
			}
		}
		const bool bTimedOut = Now >= RideStartedAt + RideTimeoutSeconds;
		const double EarliestOpen = ClosedAt + MinClosedSeconds;
		if ((bReady && Now >= EarliestOpen) || (bTimedOut && Now >= EarliestOpen))
		{
			Doors = EVerseDoorState::Opening;
			// The logical moment, not the tick: shut for MinClosedSeconds, open within the delay.
			OpenStartedAt = bReady ? FMath::Max(ReadyAt, EarliestOpen) : Now;
			PhaseStartedAt = OpenStartedAt;
			if (bReady)
			{
				CurrentDeck = Target;
				FocusedDeck = Target;
			}
		}
	}
	if (Doors == EVerseDoorState::Opening && Now >= PhaseStartedAt + DoorOpenSeconds)
	{
		Doors = EVerseDoorState::Open;
		Target = NAME_None;
	}
}

float FVerseLiftModel::DoorFraction(double Now) const
{
	switch (Doors)
	{
	case EVerseDoorState::Closing: return float(FMath::Clamp((Now - PhaseStartedAt) / DoorCloseSeconds, 0.0, 1.0));
	case EVerseDoorState::Closed: return 1.f;
	case EVerseDoorState::Opening: return float(1.0 - FMath::Clamp((Now - PhaseStartedAt) / DoorOpenSeconds, 0.0, 1.0));
	default: return 0.f;
	}
}
