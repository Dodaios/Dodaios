#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"

class IVersePenetrationQuery;
class IVersePieceQuery;
struct FVerseHeardPercept;

/** What the bot believes about one destructible piece (contracts/bot.md 4.4, destruction.md 6.2). */
struct VERSEBOT_API FVerseBelievedPiece
{
	uint16 Index = 0;
	EVersePieceState State = EVersePieceState::Intact;
	EVersePenetrationMaterial Material = EVersePenetrationMaterial::Concrete;
	FBox Bounds = FBox(ForceInit);
	/** A heard fracture may have changed it; the state is the last one perceived. */
	bool bChangedUnknown = false;
	float LastSeenS = -1.f;
};

/**
 * The bot's copy of piece states. The only place in VerseBot that may call
 * IVersePieceQuery::GetPieceState (bot.md F1), and only for a piece it sees this step
 * (destruction.md 6.2 Sight), or after a full reset both players see. Layout (index, material,
 * initial bounds) is public arena data, read at Initialize.
 */
class VERSEBOT_API FVersePieceBelief
{
public:
	/** Learn the layout of every piece in the arena box; every piece believed Intact. */
	void Initialize(const IVersePieceQuery& Query, const FBox& ArenaBox);

	/** Destruction full reset: every piece Intact again, flags cleared (both players see it). */
	void ResetAll();

	/**
	 * Look at the pieces: a piece with part of its bounds in the view cone and in line of sight
	 * enters the belief with its true state and bounds. MaxSightTests bounds the TestSight calls
	 * per call (round robin). Returns the number of pieces whose believed state changed.
	 */
	int32 ObserveSight(const FVector& Eye, const FRotator& View, const IVersePieceQuery& Query,
		const IVersePenetrationQuery& Sight, float NowS, int32 MaxSightTests = TNumericLimits<int32>::Max());

	/** A heard Noise.Fracture: pieces within 2 sd of the noisy location are "changed, state unknown". */
	void OnHeardFracture(const FVerseHeardPercept& Heard, float NowS);

	/** The bot caused the change itself (its own breach, its own bolts): no error. */
	void OnOwnAction(uint16 Piece, EVersePieceState NewState, float NowS);

	const FVerseBelievedPiece* Find(uint16 Piece) const;
	EVersePieceState GetBelievedState(uint16 Piece) const;
	/** Believed Breached or Destroyed: an opening the bot may plan through. */
	bool IsBelievedOpen(int32 Piece) const;
	/** Not believed Destroyed (a catwalk the bot may walk on). */
	bool IsBelievedStanding(int32 Piece) const;
	int32 Num() const { return Pieces.Num(); }
	TConstArrayView<FVerseBelievedPiece> GetPieces() const { return Pieces; }

	/** Cover dependency sets (bot.md 4.4): a belief change on one of these pieces dirties the cover point. */
	void RegisterCover(int32 CoverId, TConstArrayView<uint16> DependsOn);
	void UnregisterCover(int32 CoverId);
	/** Cover ids whose pieces changed in the belief since the last call. */
	TArray<int32> ConsumeDirtyCover();
	/** Pieces whose believed state changed since the last call (grid gates, nav filter). */
	TArray<uint16> ConsumeChangedPieces();

	/**
	 * Distance along a ray to the first piece the belief says stops a bolt (an intact or damaged
	 * concrete or armour-steel piece), or MaxDistCm. Used for the hurt wedge.
	 */
	float OpaqueDistance(const FVector& Origin, const FVector& Direction, float MaxDistCm) const;

	/** Points of a piece the sight test aims at: centre and 8 corners pulled 10 % inward. */
	static void SightPoints(const FBox& Bounds, FVector OutPoints[9]);

private:
	int32 FindIndex(uint16 Piece) const;
	void MarkChanged(int32 Slot);

	TArray<FVerseBelievedPiece> Pieces;
	TMap<uint16, int32> SlotOf;
	TMap<int32, TArray<uint16>> CoverDeps;
	TSet<int32> DirtyCover;
	TArray<uint16> Changed;
	int32 Cursor = 0;
};
