#include "Eqs/VerseBeliefNavFilter.h"

#include "Bot/VerseBotTier.h"
#include "Brain/VerseBotBelief.h"

bool FVerseBeliefNavFilter::IsOpen(EVersePieceState State)
{
	return State == EVersePieceState::Breached || State == EVersePieceState::Destroyed;
}

bool FVerseBeliefNavFilter::IsUsableInState(EVerseNavPieceRelation Relation, EVersePieceState BelievedState)
{
	switch (Relation)
	{
	case EVerseNavPieceRelation::None:
		return true;
	case EVerseNavPieceRelation::OpenedBy:
		// Breach openings exist for the bot only once it believes the piece open.
		return IsOpen(BelievedState);
	case EVerseNavPieceRelation::StandsOn:
		// A catwalk believed standing is used until the bot sees it gone.
		return BelievedState != EVersePieceState::Destroyed;
	}
	return true;
}

bool FVerseBeliefNavFilter::IsUsable(EVerseNavPieceRelation Relation, uint16 PieceIndex, const IVerseBotBelief& Belief)
{
	return Relation == EVerseNavPieceRelation::None || IsUsableInState(Relation, Belief.GetPieceBelief(PieceIndex));
}

float FVerseBeliefNavFilter::LinkCost(float BaseCost, const UVerseBotTier& Tier)
{
	return BaseCost * FMath::Max(Tier.NavLinkCostMul, 0.f);
}
