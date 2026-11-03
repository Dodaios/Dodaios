#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"

class IVerseBotBelief;
class UVerseBotTier;

/** How a nav poly or link depends on a destructible piece (destruction 6.1). */
enum class EVerseNavPieceRelation : uint8
{
	/** Not tied to a piece. */
	None,
	/** Exists only because the piece is open: breach openings, mantle links over low breaches, drop-downs. */
	OpenedBy,
	/** Exists while the piece stands: catwalk decks and their links. */
	StandsOn
};

/**
 * The rule of UVerseBeliefNavFilter (bot.md 6.1) on the piece belief, never on truth: polys a
 * breach or destruction created are excluded while the piece is believed closed; polys of a piece
 * believed standing are used until the bot sees it gone (the path then fails and it re-plans).
 * The engine filter class answers every poly through this function.
 */
struct VERSEBOT_API FVerseBeliefNavFilter
{
	/** True for Breached and Destroyed: an opening a bot or person can pass. */
	static bool IsOpen(EVersePieceState State);

	static bool IsUsable(EVerseNavPieceRelation Relation, uint16 PieceIndex, const IVerseBotBelief& Belief);

	/** Same, on a known believed state. */
	static bool IsUsableInState(EVerseNavPieceRelation Relation, EVersePieceState BelievedState);

	/** Nav link cost x NavLinkCostMul (stairs, ladders, mantles, jumps, drops). */
	static float LinkCost(float BaseCost, const UVerseBotTier& Tier);
};
