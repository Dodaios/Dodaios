#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseLagCompensation.generated.h"

class USkeletalMeshComponent;

/** One per-bone hit body as a capsule in world space (cm). */
struct FVerseHitCapsule
{
	FName Bone;
	EVerseHitZone Zone = EVerseHitZone::None;
	/** Axis end points. */
	FVector A = FVector::ZeroVector;
	FVector B = FVector::ZeroVector;
	float Radius = 0.f;
	/** World transform of the bone, for the bone-local impact point (gore). */
	FTransform BoneTransform = FTransform::Identity;
};

/** The hit bodies and root transform of one target at one server time. */
struct FVerseHitBodyPose
{
	double Time = 0.0;
	FTransform Root = FTransform::Identity;
	TArray<FVerseHitCapsule> Capsules;
};

/** A hit body a rewound trace entered. */
struct FVerseRewindHit
{
	TWeakObjectPtr<AActor> Actor;
	FName Bone;
	EVerseHitZone Zone = EVerseHitZone::None;
	FVector ImpactWorld = FVector::ZeroVector;
	FVector ImpactBoneLocal = FVector::ZeroVector;
	/** Distance from the segment start, cm. */
	double Distance = 0.0;
	/** Server time the bodies were rewound to (after the clamp). */
	double PoseTime = 0.0;
};

/** Ring buffer of poses of one target, one per server tick, 1 s deep (architecture.md 3.2). */
class VERSECOMBAT_API FVerseHitBodyHistory
{
public:
	explicit FVerseHitBodyHistory(int32 InCapacity = 72);

	void Push(FVerseHitBodyPose&& Pose);
	void Reset() { Count = 0; Head = 0; }
	int32 Num() const { return Count; }
	double OldestTime() const;
	double NewestTime() const;

	/** The pose at Time, interpolated between the two snapshots around it; clamped to the buffer's span. */
	bool Sample(double Time, FVerseHitBodyPose& Out) const;

private:
	const FVerseHitBodyPose& At(int32 IndexFromOldest) const;

	TArray<FVerseHitBodyPose> Ring;
	int32 Capacity = 72;
	int32 Head = 0;
	int32 Count = 0;
};

/** Produces the current hit bodies of a target (world space). */
using FVerseHitBodyProvider = TFunction<void(FTransform& OutRoot, TArray<FVerseHitCapsule>& OutCapsules)>;

/**
 * Lag compensation (WP02.8, combat-state.md 1, 5): a 1 s ring buffer of per-bone hit bodies per
 * target, recorded every server tick, and rewound queries capped at 250 ms. Bolts (the projectile
 * manager) and melee and finisher checks (WP04) use the same query API. Traces are analytic
 * capsule tests on the recorded poses, so a rewound query never moves physics bodies.
 */
UCLASS()
class VERSECOMBAT_API UVerseLagCompSubsystem : public UWorldSubsystem
{
	GENERATED_BODY()

public:
	/** Rewind cap, s (architecture.md 3.2). */
	static constexpr double MaxRewindS = 0.25;
	/** History depth, s. */
	static constexpr double HistoryS = 1.0;

	static UVerseLagCompSubsystem* Get(const UObject* WorldContextObject);

	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/** Registers a target with its own hit body provider (tests, future non-skeletal targets). */
	void RegisterTarget(AActor* Target, FVerseHitBodyProvider Provider);

	/** Registers a pawn whose hit bodies are the capsules of its mesh's physics asset (SK_Test_Human, PHYS_Verse_Human). */
	void RegisterSkeletalTarget(AActor* Target, USkeletalMeshComponent* Mesh);

	void UnregisterTarget(AActor* Target);

	/** Records every registered target's pose at server time Now. Runs after actor tick on the server. */
	void Record(double Now);

	/** The rewind target time: ViewTime clamped to [Now - 250 ms, Now]. */
	static double ClampRewindTime(double Now, double ViewTime);

	/** The pose of a target at Time (interpolated). WP04 uses it for rewound transforms. */
	bool GetPoseAt(const AActor* Target, double Time, FVerseHitBodyPose& Out) const;

	/** Nearest hit body a segment enters, with bodies at ClampRewindTime(Now, ViewTime). */
	bool TraceRewound(const FVector& Start, const FVector& End, double Now, double ViewTime, const AActor* Ignore,
		FVerseRewindHit& Out) const;

	/** Same against the poses at exactly Time (no clamp; Time inside the buffer). */
	bool TraceAt(const FVector& Start, const FVector& End, double Time, const AActor* Ignore, FVerseRewindHit& Out) const;

	/** Nearest hit body of one pose a segment enters. */
	static bool TracePose(const FVerseHitBodyPose& Pose, const FVector& Start, const FVector& End, FVerseRewindHit& Out);

	/** Distance along the ray (unit Dir) to the capsule's surface; < 0 when missed. Start inside = 0. */
	static double RayCapsule(const FVector& Origin, const FVector& Dir, const FVector& A, const FVector& B, double Radius);

	/** The bone table of the frozen rig (art-pipeline.md 12.1) to hit zones. */
	static EVerseHitZone ZoneForBone(FName Bone);

	int32 NumTargets() const { return Targets.Num(); }

private:
	struct FTarget
	{
		TWeakObjectPtr<AActor> Actor;
		FVerseHitBodyProvider Provider;
		FVerseHitBodyHistory History;
	};

	void OnPostActorTick(UWorld* World, ELevelTick TickType, float DeltaSeconds);

	TArray<FTarget> Targets;
	FDelegateHandle PostTickHandle;
};
