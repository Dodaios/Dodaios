#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

// Synthetic event player (WP05.1): seeded streams of the contract events Gore listens to, so
// Gore, its tests and its screenshots run before Combat exists (work-packages.md 0.3). The
// streams are published on UVerseEventHub, the same path the real Combat events take.

enum class EVerseGoreSyntheticKind : uint8
{
	/** Body hits on every zone at a steady rate. */
	Hits,
	/** Deaths (each with its killing hit). */
	Deaths,
	/** One finisher: Locked, Takedown, Struggle, Kill, Recover plus the death. */
	Finisher,
	/** `gore_storm` of A5.4: 30 hits per second. */
	Storm
};

struct FVerseGoreSyntheticEvent
{
	enum class EType : uint8 { Hit, Death, Finisher };

	/** Seconds after the stream started. */
	double Time = 0.0;
	EType Type = EType::Hit;
	FVerseHitEvent Hit;
	FVerseDeathEvent Death;
	FVerseFinisherEvent Finisher;
};

struct VERSEGORE_API FVerseGoreSyntheticParams
{
	EVerseGoreSyntheticKind Kind = EVerseGoreSyntheticKind::Hits;
	uint32 Seed = 1;
	double DurationSeconds = 10.0;
	/** Events per second (Hits, Deaths); Storm forces 30. */
	double RatePerSecond = 4.0;
	int32 InstigatorId = 1;
	int32 VictimId = 2;
	/** Where the victim stands (floor point, cm) and where the shooter fires from. */
	FVector VictimLocation = FVector::ZeroVector;
	FVector ShooterLocation = FVector(-1000.0, 0.0, 150.0);
};

/** Finisher phase offsets from `SequenceStartServerTime`, s (combat-state.md 7.4). */
namespace VerseGoreFinisherTimes
{
	inline constexpr double Takedown = 0.25;
	inline constexpr double Struggle = 0.9;
	inline constexpr double Kill = 1.8;
	inline constexpr double Recover = 2.1;
	inline constexpr double End = 2.5;
}

struct VERSEGORE_API FVerseGoreSyntheticStream
{
	/** Builds a deterministic stream: the same params give the same events, bit for bit. */
	static TArray<FVerseGoreSyntheticEvent> Build(const FVerseGoreSyntheticParams& Params);

	/** One body hit as Combat would raise it (bone, zone, bone-local impact, bolt direction). */
	static FVerseHitEvent MakeHit(EVerseHitZone Zone, const FVector& VictimLocation, const FVector& ShooterLocation,
		int32 InstigatorId, int32 VictimId, float Damage, uint16 ShotCounter, float ServerTime, bool bKillingBlow);

	/** Bone of `SKEL_Verse_Human` (art-pipeline 12.1) a zone's hit lands on, and its height in cm. */
	static FName BoneForZone(EVerseHitZone Zone);
	static double HeightForZone(EVerseHitZone Zone);

	/** Parses "hits", "deaths", "finisher", "storm". */
	static bool ParseKind(const FString& Text, EVerseGoreSyntheticKind& OutKind);
};
