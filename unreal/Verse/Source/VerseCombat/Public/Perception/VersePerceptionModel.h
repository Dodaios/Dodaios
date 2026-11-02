#pragma once

#include "Bot/VersePerceptTypes.h"
#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Templates/Function.h"
#include "VerseRng.h"

class UVerseAudibilityTable;
class UVerseBotTier;

// The world-independent core of the fairness boundary (contracts/bot.md 2, 3; work-packages WP07).
// UVersePerceptionService gathers world truth from actors into FVersePerceptionBody snapshots and
// hub events, and this model turns them into FVersePerceptFrame per observer with all perception
// error applied. Keeping the rules here, free of UWorld, makes them unit-testable with a fake
// sight query and bit-deterministic (bot.md B5, F3): the model draws from an observer's RNG
// stream only for percepts that observer actually receives.

namespace VersePerception
{
	/** bot.md 3.1: half of the shipped 100 deg horizontal FOV plus 5 deg. */
	constexpr float ViewHalfAngleDeg = 55.f;
	/** Outer edge of the peripheral band. */
	constexpr float PeripheralHalfAngleDeg = 80.f;
	constexpr float VerticalHalfAngleDeg = 40.f;
	constexpr float AdsVerticalHalfAngleDeg = 35.f;
	/** ADS: half the ADS FOV plus this margin. */
	constexpr float AdsMarginDeg = 3.f;
	/** Within this distance the opponent is noticed in any direction. */
	constexpr float AwarenessRadiusCm = 200.f;
	/** Peripheral band: only a target faster than this (or firing) is noticed. */
	constexpr float PeripheralSpeedCmS = 200.f;
	/** Hearing error is multiplied by this without line of sight to the source. */
	constexpr float NoLineOfSightErrorMul = 1.5f;
	/** Level guess: correct with this probability when the source is within one level. */
	constexpr float LevelGuessNear = 0.9f;
	constexpr float LevelGuessFar = 0.7f;
	/** Hurt percept direction error, degrees (uniform, yaw; pitch at half). */
	constexpr float HurtDirectionErrorDeg = 8.f;
	/** Bolts fly at about 300 m/s (README Projectiles). */
	constexpr float BoltSpeedCmS = 30000.f;
	/** A bolt the model was not told ended expires after this. */
	constexpr float BoltMaxLifeS = 1.0f;
	/** Default ADS field of view until weapons (WP02) provide theirs. */
	constexpr float DefaultAdsFovDeg = 70.f;
}

/** World truth of one perceivable body for one tick. Only the service and tests fill it. */
struct VERSECOMBAT_API FVersePerceptionBody
{
	int32 PlayerId = INDEX_NONE;
	bool bAlive = true;
	/** Pelvis (the Hips bone), world cm. */
	FVector Pelvis = FVector::ZeroVector;
	FVector Velocity = FVector::ZeroVector;
	float FacingYawDeg = 0.f;
	float FacingPitchDeg = 0.f;
	EVerseStance Stance = EVerseStance::Stand;
	int8 LeanQuantized = 0;
	bool bAds = false;
	float AdsFovDeg = VersePerception::DefaultAdsFovDeg;
	FName HeldWeaponId;
	bool bReloading = false;
	bool bSpawnProtected = false;
	/** Fired this tick (noticed in the peripheral band). */
	bool bFiring = false;
	/** The 8 hit-zone sample points in EVerseSightSample order, world cm. */
	FVector SamplePoints[8];
	/** The Camera bone, world cm. */
	FVector Eye = FVector::ZeroVector;
	FRotator View = FRotator::ZeroRotator;

	FVersePerceptionBody();

	/** Sample points from a standing (or crouched, prone) capsule at Pelvis; for tests and pawns without the rig. */
	void SetSamplePointsFromStance();
};

/** What the model asks of the world. Every callback answers about geometry, never about a pawn. */
struct VERSECOMBAT_API FVersePerceptionWorld
{
	/** IVersePenetrationQuery::TestSight: sight from Eye to Target (holes honoured, pawns ignored). */
	TFunction<bool(const FVector& Eye, const FVector& Target)> TestSight;

	/** Arena VisibilityFactor at a point, 1 = lit; dark zones are below 1 (bot.md 3.1). Optional. */
	TFunction<float(const FVector& Location)> VisibilityFactor;

	/** Height band of a point; optional, default bands below. */
	TFunction<EVerseArenaLevel(const FVector& Location)> LevelOf;

	/** Nominal floor height of a level, world cm; a heard percept reports this Z (never the true one). */
	TFunction<float(EVerseArenaLevel Level)> LevelHeightCm;

	/** The audibility table (DA_Audibility). Must be set. */
	const UVerseAudibilityTable* Audibility = nullptr;

	/** Default bands when LevelOf is not set: below MidMinZ floor, below UpperMinZ mid, else upper. */
	float MidMinZCm = 350.f;
	float UpperMinZCm = 750.f;

	EVerseArenaLevel ResolveLevel(const FVector& Location) const;
	float ResolveLevelHeight(EVerseArenaLevel Level) const;
	float ResolveVisibility(const FVector& Location) const;
	bool Sight(const FVector& Eye, const FVector& Target) const;
};

/** Per-tick inputs for one observer. */
struct VERSECOMBAT_API FVersePerceptionObserverInput
{
	FVerseSelfPercept Self;
	bool bAds = false;
	float AdsFovDeg = VersePerception::DefaultAdsFovDeg;
};

/**
 * The perception model for all observers. Not thread-safe; one per server world.
 * Order of calls per tick: events (OnNoise, OnFire, OnHit, OnDeath) as they happen, then
 * BuildFrame once per observer. Events are queued per observer and evaluated at BuildFrame with
 * the observer's eye at that tick.
 */
class VERSECOMBAT_API FVersePerceptionModel
{
public:
	/** Profile values the tier owns (bot.md 9.1 Perception group), with the observer's RNG seed. */
	static FVersePerceptionProfile MakeProfile(const UVerseBotTier& Tier, uint32 Seed);

	void AddObserver(int32 PlayerId, const FVersePerceptionProfile& Profile);
	void RemoveObserver(int32 PlayerId);
	bool HasObserver(int32 PlayerId) const;
	const FVersePerceptionProfile* FindProfile(int32 PlayerId) const;
	TArray<int32> GetObserverIds() const;

	/** A noise event (server only). Heard by every observer except its source. */
	void OnNoise(const FVerseNoiseEvent& Event);
	/** A shot: tracks the bolt so observers can see it in flight. */
	void OnFire(const FVerseFireEvent& Event);
	/** A hit: hurt percept for the victim, hit marker for the instigator; ends the bolt. */
	void OnHit(const FVerseHitEvent& Event);
	/** A death: kill feed for everyone; respawn feed at RespawnAt. KillerBody is the killer's truth for the kill cam. */
	void OnDeath(const FVerseDeathEvent& Event, const FVersePerceptionBody* KillerBody);

	/**
	 * One frame for one observer. Bodies is everything perceivable this tick (the observer's own
	 * body may be in it and is skipped). NowMs is server time; DeltaS the time since the last call.
	 */
	FVersePerceptFrame BuildFrame(int32 ObserverId, const FVersePerceptionObserverInput& Input,
		TConstArrayView<FVersePerceptionBody> Bodies, const FVersePerceptionWorld& World, uint32 NowMs, float DeltaS);

	/** Drop live bolts and queued events (destruction full reset, arena switch). Observers stay. */
	void ResetEvents();

	/** Pure geometry (tests): the cone a view sees. */
	struct FCone
	{
		float HalfAngleDeg = VersePerception::ViewHalfAngleDeg;
		float VerticalHalfAngleDeg = VersePerception::VerticalHalfAngleDeg;
		float PeripheralHalfAngleDeg = VersePerception::PeripheralHalfAngleDeg;
	};
	static FCone ConeFor(bool bAds, float AdsFovDeg);

	enum class EConeZone : uint8
	{
		Outside,
		Peripheral,
		Inside
	};
	static EConeZone Classify(const FVector& Eye, const FRotator& View, const FCone& Cone, const FVector& Point);

private:
	struct FContact
	{
		/** Server time the target became visible without a break; for the dark-zone notice delay. */
		uint32 VisibleSinceMs = 0;
		bool bVisibleLastTick = false;
	};

	struct FLiveBolt
	{
		int32 ShooterId = INDEX_NONE;
		uint16 ShotCounter = 0;
		FVector Origin = FVector::ZeroVector;
		FVector Direction = FVector::ForwardVector;
		float StartS = 0.f;
		/** Seconds of flight until the bolt ended (hit); infinite until known. */
		float EndFlightS = TNumericLimits<float>::Max();
	};

	struct FPendingRespawn
	{
		int32 PlayerId = INDEX_NONE;
		uint32 AtMs = 0;
	};

	struct FObserver
	{
		int32 PlayerId = INDEX_NONE;
		FVersePerceptionProfile Profile;
		FVerseRng Rng;
		uint32 NextPerceptId = 1;
		TMap<int32, FContact> Contacts;
		TArray<FVerseNoiseEvent> PendingNoise;
		TArray<FVerseHitEvent> PendingHurt;
		TArray<FVerseHudEvent> PendingHud;
		uint32 LastFrameMs = 0;
		bool bHasFrame = false;
	};

	FObserver* Find(int32 PlayerId);

	void BuildSightings(FObserver& Observer, const FVersePerceptionObserverInput& Input,
		TConstArrayView<FVersePerceptionBody> Bodies, const FVersePerceptionWorld& World, uint32 NowMs, FVersePerceptFrame& Out);
	void BuildBolts(FObserver& Observer, const FVersePerceptionObserverInput& Input, const FVersePerceptionWorld& World,
		uint32 NowMs, float DeltaS, FVersePerceptFrame& Out);
	void BuildHeard(FObserver& Observer, const FVersePerceptionObserverInput& Input, const FVersePerceptionWorld& World,
		uint32 NowMs, FVersePerceptFrame& Out);
	void BuildHurt(FObserver& Observer, uint32 NowMs, FVersePerceptFrame& Out);
	void BuildHud(FObserver& Observer, uint32 NowMs, FVersePerceptFrame& Out);

	TArray<FObserver> Observers;
	TArray<FLiveBolt> Bolts;
	TArray<FPendingRespawn> Respawns;
	/** Latest server time seen, seconds (bolt flight clock). */
	float ClockS = 0.f;
};
