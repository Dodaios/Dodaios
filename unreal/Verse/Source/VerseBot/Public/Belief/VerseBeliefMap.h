#pragma once

#include "Belief/VerseBeliefGrid.h"
#include "Belief/VerseOpponentEstimate.h"
#include "Belief/VersePieceBelief.h"
#include "Bot/VersePerceptTypes.h"
#include "CoreMinimal.h"

class IVersePenetrationQuery;
class IVersePieceQuery;

/** World queries the belief layer may use: sight (the fair channel) and the gated piece query. */
struct VERSEBOT_API FVerseBeliefWorld
{
	/** TestSight for clearing cells and seeing pieces. Required. */
	const IVersePenetrationQuery* Sight = nullptr;
	/** Read only through FVersePieceBelief (bot.md F1). Optional (no pieces). */
	const IVersePieceQuery* Pieces = nullptr;
};

struct VERSEBOT_API FVerseBeliefMapConfig
{
	/** The bot's own player state id (kill feed: who died). */
	int32 SelfPlayerId = INDEX_NONE;
	/** Arena spawn points (public arena data), world cm. */
	TArray<FVector> SpawnPoints;
	/** Arena box for the piece layout. */
	FBox ArenaBox = FBox(ForceInit);
	/** Belief step period: 10 Hz (bot.md 2). */
	float StepIntervalS = 0.1f;
	/** TestSight calls per step for clearing cells (cached visibility is reused when the eye barely moved). */
	int32 MaxCellSightTestsPerStep = 384;
	/** TestSight calls per step for pieces. */
	int32 MaxPieceSightTestsPerStep = 48;
	/** Clear tests cells up to this range, cm. */
	float ClearRangeCm = 6000.f;
	/** A cached cell visibility is reused while the eye moved less than this, cm. */
	float VisibilityCacheMoveCm = 50.f;
	/** Damage of one own confirmed hit and headshot, for the health estimate, until weapons provide it. */
	float OwnHitDamage = 25.f;
	float OwnHeadshotDamage = 50.f;
};

/**
 * The belief map of one bot (work-packages WP07.5-7.8): the grid, the opponent estimates and the
 * piece belief, fed only by FVersePerceptFrame (bot.md B2). ApplyFrame runs the bot.md 4.2 step at
 * 10 Hz and at once on a positive percept. Deterministic for a given percept stream and world
 * answers (B5); holds nothing that outlives the match.
 */
class VERSEBOT_API FVerseBeliefMap
{
public:
	void Initialize(const FVerseBeliefGridSource& Source, const FVerseBeliefMapConfig& InConfig,
		const FVerseBeliefWorld& World, const FVerseBeliefTuning& Tuning = FVerseBeliefTuning());

	/** Feed one perception frame (every server tick). Returns true when a belief step ran. */
	bool ApplyFrame(const FVersePerceptFrame& Frame, const FVerseBeliefWorld& World);

	/** Own death: belief cleared (bot.md 5.2); the opponent is somewhere. */
	void OnOwnDeath(float NowS);
	/** The bot changed a piece itself (own breach). */
	void OnOwnPieceAction(uint16 Piece, EVersePieceState NewState, float NowS);
	/** Destruction full reset, which both players see. */
	void OnDestructionReset();

	const FVerseBeliefGrid& GetGrid() const { return Grid; }
	FVerseBeliefGrid& GetGridMutable() { return Grid; }
	const FVerseBeliefDerived& GetDerived() const { return Derived; }
	const FVerseOpponentEstimate& GetOpponent() const { return Opponent; }
	FVerseOpponentEstimate& GetOpponentMutable() { return Opponent; }
	const FVersePieceBelief& GetPieces() const { return Pieces; }
	FVersePieceBelief& GetPiecesMutable() { return Pieces; }
	const FVerseBeliefMapConfig& GetConfig() const { return Config; }
	int32 GetStepCount() const { return StepCount; }
	float GetLastStepS() const { return LastStepS; }

	/** Cell visible from the eye in the view cone at 1.0 m or 1.6 m (0.4 m prone-capable). Uncached. */
	bool TestCellVisible(int32 Cell, const FVector& Eye, const FRotator& View, const IVersePenetrationQuery& Sight) const;

	/** The public spawn rule ranked from Eye: out of sight first, then farthest. */
	TArray<FVector> RankSpawnPoints(const FVector& Eye, const IVersePenetrationQuery* Sight) const;

private:
	bool InViewCone(const FVector& Eye, const FVector& ForwardFlat, float ViewPitchDeg, const FVector& Point) const;
	void RunClear(const FVerseSelfPercept& Self, const FVerseBeliefWorld& World, float NowS);
	void RefreshGates();

	FVerseBeliefMapConfig Config;
	FVerseBeliefGrid Grid;
	FVerseBeliefDerived Derived;
	FVerseOpponentEstimate Opponent;
	FVersePieceBelief Pieces;

	/** Per cell: cached visibility and where the eye was. */
	TArray<uint8> CachedVisible;
	TArray<FVector> CachedEye;
	TArray<float> CachedAtS;
	int32 ClearCursor = 0;

	float LastStepS = -1.f;
	int32 StepCount = 0;
	bool bHasFrame = false;
};
