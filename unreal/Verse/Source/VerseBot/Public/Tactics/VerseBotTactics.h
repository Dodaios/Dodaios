#pragma once

#include "Audit/VerseBotFireAudit.h"
#include "Brain/VerseBotTypes.h"
#include "CoreMinimal.h"
#include "Eqs/VerseBotEqs.h"
#include "VerseRng.h"

// The decision states of bot.md 5.1: utility terms and what each state does per tick. The states
// read belief, own HUD, static arena data and the EQS cache; never truth.

/** The EQS queries the brain schedules (at most 2 in flight, results used on the next decision). */
enum class EVerseBotQuery : uint8
{
	CoverNear,
	CoverFar,
	CoverFlank,
	CoverBulwark,
	PeekCorner,
	WallbangSpot,
	BreachSpot,
	FinisherApproach,
	Count
};

/** Latest result of every query and the decision index it was produced for. */
struct VERSEBOT_API FVerseBotQueryCache
{
	FVerseBotCoverResult Cover[4];
	FVerseBotPeekResult Peek;
	FVerseBotWallbangResult Wallbang;
	FVerseBotBreachResult Breach;
	FVerseBotFinisherResult Finisher;
	int32 ProducedAt[int32(EVerseBotQuery::Count)] = {-1, -1, -1, -1, -1, -1, -1, -1};

	const FVerseBotCoverResult& GetCover(EVerseBotCoverMode Mode) const { return Cover[int32(Mode)]; }
	void Reset() { *this = FVerseBotQueryCache(); }
};

/** Per-life working memory of the states. */
struct VERSEBOT_API FVerseBotTacticsMemory
{
	EVerseBotHoldPhase HoldPhase = EVerseBotHoldPhase::Go;
	float PhaseUntilS = 0.f;
	bool bHasCover = false;
	FVerseBotCoverPoint Cover;
	bool bHasPeek = false;
	FVerseBotPeekResult Peek;
	TArray<int32, TInlineAllocator<3>> RecentPeekEdges;
	int8 StrafeSign = 1;
	float StrafeUntilS = 0.f;
	/** Stalk: when it started; aborted this life. */
	float StalkStartS = -1.f;
	/** Breach: plant pressed, waiting for the detonation. */
	bool bBreachPlanted = false;
	float BreachPlantedS = -1.f;
	uint16 BreachPiece = 0;
	/** Bulwark deployed this life. */
	bool bBulwarkDeployed = false;
	float BulwarkDeployedS = -1.f;
	/** Wallbang burst counter. */
	int32 BurstShots = 0;
	float BurstPauseUntilS = 0.f;
	/** Search: chosen target and when it was chosen. */
	FVector SearchTarget = FVector::ZeroVector;
	bool bHasSearchTarget = false;
	float SearchSweepPhase = 0.f;
	float SearchUntilS = 0.f;
	/** Search: when each arena cover point was last visited this life (information gain). */
	TMap<int32, float> Visited;
	/** Flank: chosen point. */
	FVector FlankPoint = FVector::ZeroVector;
	bool bHasFlankPoint = false;
	/** Prefire roll for the current approach (8.4: one roll per approach). */
	bool bPrefireRolled = false;
	bool bPrefireRollDone = false;

	void Reset() { *this = FVerseBotTacticsMemory(); }
};

/** Everything a state reads this tick. */
struct VERSEBOT_API FVerseBotTacticsContext
{
	FVerseBotQueryContext Query;
	const FVersePerceptFrame* Frame = nullptr;
	const FVerseBotQueryCache* Cache = nullptr;
	/** The visible, not spawn-protected sighting of this frame, if any. */
	const FVerseSightPercept* Sighting = nullptr;
	/** The newest heard percept of the last 2 s, if any. */
	const FVerseHeardPercept* RecentHeard = nullptr;
	float RecentHeardAgeS = 1.0e6f;
	/** Own health 0..1, own magazine 0..1. */
	float HealthFrac = 1.f;
	float MagazineFrac = 1.f;
	bool bPistolLow = false;
	/** Seconds since the bot last had a sighting; large when none. */
	float SinceSightS = 1.0e6f;
	/** Seconds since the last own hit taken. */
	float SinceHurtS = 1.0e6f;
	/** Bulwark and breach charges and cooldowns from the HUD. */
	bool bBulwarkReady = false;
	bool bBreachReady = false;
	/** The bot is unseen as far as it can tell: no hurt in 1.5 s and in cover. */
	bool bInCover = false;
	/** Wall-shot authority holds for the cached wallbang spot. */
	bool bWallbangAuthorised = false;
	FVerseBotFireEvidence WallbangEvidence;
};

namespace VerseBotTactics
{
	/** Utility per state (5.1); negative means the state cannot run. */
	VERSEBOT_API void Utilities(const FVerseBotTacticsContext& Ctx, float (&Out)[VerseBot::NumStates]);

	/** Called when the selector switches to State. */
	VERSEBOT_API void Enter(EVerseBotState State, const FVerseBotTacticsContext& Ctx, FVerseBotTacticsMemory& Mem, FVerseRng& Rng);

	/** One tick of State. */
	VERSEBOT_API FVerseBotIntent Tick(EVerseBotState State, const FVerseBotTacticsContext& Ctx, FVerseBotTacticsMemory& Mem, FVerseRng& Rng);

	/** Which queries the states want refreshed, in priority order. */
	VERSEBOT_API void WantedQueries(EVerseBotState Current, const FVerseBotTacticsContext& Ctx, TArray<EVerseBotQuery, TInlineAllocator<8>>& Out);

	/** Hold substate times (5.2): hide U(0.5, 1.1) s, peek U(0.7, 1.5) s. */
	inline constexpr float HideMinS = 0.5f, HideMaxS = 1.1f, PeekMinS = 0.7f, PeekMaxS = 1.5f;
}
