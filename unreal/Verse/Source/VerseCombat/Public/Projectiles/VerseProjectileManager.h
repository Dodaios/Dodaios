#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Engine/HitResult.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseProjectileManager.generated.h"

class IVersePenetrationQuery;
class IVersePieceDamage;
class UVersePenetrationTable;
class UVerseWeaponDefinition;

/** One bolt in flight (server). Not an actor (combat-state.md 5). */
struct FVerseBolt
{
	FVerseFireEvent Fire;
	TWeakObjectPtr<const UVerseWeaponDefinition> Weapon;
	TWeakObjectPtr<AActor> Shooter;
	FVector Position = FVector::ZeroVector;
	FVector Dir = FVector::ForwardVector;
	/** Distance flown, cm. */
	double Travelled = 0.0;
	/** Server time at which the bolt is at Position. */
	double Time = 0.0;
	/** Remaining penetration power, and the damage factor after the pieces passed. */
	float Power = 0.f;
	float Factor = 1.f;
	int32 Passes = 0;
	/** Pieces already passed; a straight bolt never enters one twice (segment starts on an exit face). */
	TArray<uint16, TInlineAllocator<4>> PassedPieces;
	bool bAlive = true;
};

/** How a bolt ended; the shooter's weapon component turns it into ClientConfirmShot. */
struct FVerseBoltResult
{
	TWeakObjectPtr<AActor> Shooter;
	FName WeaponId;
	uint16 ShotCounter = 0;
	EVerseShotResult Result = EVerseShotResult::Miss;
	EVerseHitZone Zone = EVerseHitZone::None;
	bool bKillingBlow = false;
	TWeakObjectPtr<AActor> HitActor;
	FVector Location = FVector::ZeroVector;
	/** Distance flown when it ended, cm. */
	double Travelled = 0.0;
	/** Server time when it ended. */
	double Time = 0.0;
};

DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseBoltResolved, const FVerseBoltResult&);

/** Something in the world (not a piece, not a hit body) that a bolt segment struck. */
using FVerseBoltWorldTrace = TFunction<bool(const FVector& Start, const FVector& End, const AActor* Ignore, FHitResult& OutHit)>;

/**
 * Server bolts (WP02.7, combat-state.md 5, 6). Each tick every bolt moves ProjectileSpeed x dt
 * (300 m/s = 5 m per 60 Hz tick), straight, no drop, and despawns at MaxRange. A new bolt first
 * covers the shooter's latency (capped 250 ms) in tick-sized segments traced against hit bodies
 * rewound to the time the bolt was at that point; later segments trace current bodies. Per
 * segment: pieces (IVersePenetrationQuery), the world on VerseBolt (Bulwarks included), then
 * per-bone hit bodies; the nearest event wins, pieces run the penetration loop of section 6.
 */
UCLASS()
class VERSECOMBAT_API UVerseProjectileManager : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	/** Latency advance cap, s (architecture.md 3.2). */
	static constexpr float MaxLatencyS = 0.25f;
	/** Fixed server step, s (architecture.md 3.2: 60 Hz). */
	static constexpr float ServerStepS = 1.f / 60.f;

	static UVerseProjectileManager* Get(const UObject* WorldContextObject);

	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;

	/** Contract entry (combat-state.md 11.2): a bolt without a known shooter actor. */
	void SpawnBolt(const FVerseFireEvent& Fire, const UVerseWeaponDefinition& Weapon, float LatencyS);

	/** Spawns a bolt and advances it by the latency (capped). Server only. */
	void SpawnBoltFrom(const FVerseFireEvent& Fire, const UVerseWeaponDefinition& Weapon, float LatencyS, AActor* Shooter);

	/** Moves every bolt by Dt to server time Now. Tick calls it; tests call it directly. */
	void StepAll(float Dt, double Now);

	void SetPenetrationQuery(const IVersePenetrationQuery* Query) { PenetrationQuery = Query; }
	void SetPieceDamage(IVersePieceDamage* Damage) { PieceDamage = Damage; }
	void SetPenetrationTable(const UVersePenetrationTable* Table) { PenetrationTable = Table; }
	/** Replaces the world trace (tests). Unset: a line trace on VerseBolt. */
	void SetWorldTrace(FVerseBoltWorldTrace Trace) { WorldTrace = MoveTemp(Trace); }
	/** Server time source (tests). Unset: the world's time. */
	void SetClock(TFunction<double()> Clock) { ClockOverride = MoveTemp(Clock); }

	double Now() const;

	int32 NumActive() const { return Bolts.Num(); }
	const TArray<FVerseBolt>& GetBolts() const { return Bolts; }
	/** Wall time of the last StepAll, seconds (A2.8 cost gate). */
	double GetLastStepSeconds() const { return LastStepSeconds; }

	/** Drops every bolt without resolving it. */
	void Clear() { Bolts.Reset(); }

	FOnVerseBoltResolved OnBoltResolved;

private:
	/** Moves one bolt over [From, To] by Len cm, resolving what it meets; PoseTime < 0 = current bodies. */
	void StepBolt(FVerseBolt& Bolt, double Len, double PoseTime, double EndTime);
	void Resolve(FVerseBolt& Bolt, EVerseShotResult Result, EVerseHitZone Zone, bool bKillingBlow, AActor* HitActor,
		const FVector& Where);
	bool TraceWorld(const FVector& Start, const FVector& End, const AActor* Ignore, FHitResult& Out) const;

	TArray<FVerseBolt> Bolts;
	const IVersePenetrationQuery* PenetrationQuery = nullptr;
	IVersePieceDamage* PieceDamage = nullptr;
	const UVersePenetrationTable* PenetrationTable = nullptr;
	FVerseBoltWorldTrace WorldTrace;
	TFunction<double()> ClockOverride;
	double LastStepSeconds = 0.0;
	bool bManualStepping = false;

public:
	/** Tests step by hand: the world tick then leaves the bolts alone. */
	void SetManualStepping(bool bManual) { bManualStepping = bManual; }
};
