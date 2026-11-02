#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"

/**
 * Client debris budget of destruction.md 10: at most 400 rigid bodies on High (150 on Low), at
 * most 40 per fracture, at most 32 geometry collection actors, sleep at 3 s, despawn at 10 s
 * (6 s on Low), oldest removed first with a 0.3 s fade. Pure bookkeeping: the debris subsystem
 * asks it before spawning and drives the actors from its answers, and the storm scenario runs
 * it without a world.
 */
class VERSEDESTRUCTION_API FVerseDebrisBudget
{
public:
	struct FConfig
	{
		int32 MaxBodies = 400;
		int32 MaxBodiesPerFracture = 40;
		int32 MaxGeometryCollectionActors = 32;
		float SleepS = 3.f;
		float DespawnS = 10.f;
		float FadeS = 0.3f;

		static FConfig High();
		static FConfig Low();
	};

	/** One spawned burst (one geometry collection actor, or Niagara only when Bodies is 0). */
	struct FBurst
	{
		int32 Id = 0;
		uint16 PieceIndex = 0;
		int32 Bodies = 0;
		double SpawnS = 0.0;
		bool bAsleep = false;
		/** Set when evicted or expired; the actor fades out over FadeS and stops counting. */
		bool bFading = false;
		double FadeStartS = 0.0;
	};

	/** What a fracture's debris consists of, before the budget. */
	struct FRequest
	{
		uint16 PieceIndex = 0;
		EVerseDebrisType Type = EVerseDebrisType::SparksOnly;
		EVersePieceState ToState = EVersePieceState::Damaged;
	};

	struct FGrant
	{
		/** 0 = no burst (Niagara only or nothing). */
		int32 BurstId = 0;
		int32 Bodies = 0;
		/** Niagara-only effects (glass shards, dust, sparks) always play. */
		bool bNiagara = false;
		/** Bursts the caller must start fading now (oldest first). */
		TArray<int32> Evicted;
		/** Bursts whose actors must be destroyed now (the pool of 32 actors was full). */
		TArray<int32> Removed;
	};

	explicit FVerseDebrisBudget(const FConfig& InConfig = FConfig::High());

	/** Rigid bodies a fracture wants before the budget (WP06 start values, tuning.json). */
	static int32 DesiredBodies(EVerseDebrisType Type, EVersePieceState ToState);
	/** True if the debris type has a Niagara part (shards, dust, sparks). */
	static bool HasNiagara(EVerseDebrisType Type);

	/** Reserves bodies for a burst (at most the grant); Commit then charges the real count. */
	FGrant Request(const FRequest& Request, double NowS);

	/**
	 * The burst really simulates RealBodies (<= the grant; the spawned set's chunk count, or 0
	 * when nothing spawned, which frees the reservation). The real peaks count only committed bodies.
	 */
	void Commit(int32 BurstId, int32 RealBodies);

	/** Advances sleep, despawn and fade; returns bursts whose actors must be destroyed now. */
	TArray<int32> Tick(double NowS);

	/** Reset: every burst is removed at once (destruction.md 11). */
	TArray<int32> PurgeAll();

	int32 ActiveBodies() const;
	int32 AliveActors() const;
	int32 GetPeakBodies() const { return PeakBodies; }
	int32 GetPeakActors() const { return PeakActors; }
	int32 GetPeakBodiesPerFracture() const { return PeakPerFracture; }
	/** Peaks of the committed (really spawned) bodies, actors and bodies per fracture. */
	int32 GetPeakRealBodies() const { return PeakRealBodies; }
	int32 GetPeakRealActors() const { return PeakRealActors; }
	int32 GetPeakRealBodiesPerFracture() const { return PeakRealPerFracture; }
	const FConfig& GetConfig() const { return Config; }
	const TArray<FBurst>& GetBursts() const { return Bursts; }

private:
	void EvictOldest(double NowS, TArray<int32>& OutEvicted);

	FConfig Config;
	TArray<FBurst> Bursts;
	int32 NextId = 1;
	int32 PeakBodies = 0;
	int32 PeakActors = 0;
	int32 PeakPerFracture = 0;
	int32 PeakRealBodies = 0;
	int32 PeakRealActors = 0;
	int32 PeakRealPerFracture = 0;
};
