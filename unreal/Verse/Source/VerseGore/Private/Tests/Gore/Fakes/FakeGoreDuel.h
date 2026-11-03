#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "CoreMinimal.h"
#include "Tests/Gore/VerseGoreTestWorld.h"
#include "VerseRng.h"

/**
 * Fake of the WP10 bot-vs-bot match for the D6 run before WP10 and WP02 land (work-packages.md
 * 0.3, WP05 "Depends on"). Two replicated duellist pawns on the G0 test human move, fire and die
 * from one seed; every hit, death and finisher is published on the hub as Combat would. The
 * duel state lives in this fake (as Combat's replicated state will), so gore can only change it
 * by changing the world.
 */
struct FFakeGoreDuel
{
	struct FDuellist
	{
		int32 Id = 0;
		APawn* Pawn = nullptr;
		USkeletalMeshComponent* Mesh = nullptr;
		float Health = 100.f;
		int32 Kills = 0;
		int32 Deaths = 0;
		float RespawnAt = -1.f;
		FVector Home = FVector::ZeroVector;
	};

	VerseGoreTest::FWorld& W;
	uint32 Seed = 1;
	double Time = 0.0;
	int64 Tick = 0;
	uint16 Shot = 0;
	FDuellist Duellists[2];
	/** World queries the gameplay asked this run, folded together: every shot's bolt and body
	 *  trace, every sight check and the probes toward the walls gore paints (VerseBolt,
	 *  VerseHitBody, VerseSight). A gore primitive that blocked any of them would change it. */
	uint32 QueryHash = 0;
	int32 BlockedShots = 0;
	int32 Queries = 0;

	FFakeGoreDuel(VerseGoreTest::FWorld& InWorld, uint32 InSeed);

	/** One 30 Hz tick: move, sense, fire (traced), damage, deaths, respawns, finishers. */
	void Step(double Dt);

	/**
	 * Hash of everything replicated or gameplay-relevant in the world after the tick: every
	 * replicated actor's net properties and transform, the duel state, and the collision state of
	 * every primitive (gore must add none), and the results of every world query of the tick.
	 */
	uint32 StateHash() const;

private:
	/** One line trace on `Channel`; its result (hit or not, where, what) is folded into QueryHash. */
	bool Query(const FVector& From, const FVector& To, ECollisionChannel Channel, const AActor* Ignore, FHitResult& OutHit);
};

#endif // WITH_DEV_AUTOMATION_TESTS
