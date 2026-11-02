#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Gore/VerseGoreSynthetic.h"
#include "Gore/VerseGoreTypes.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseGoreSubsystem.generated.h"

class AVerseGoreActor;
class UDecalComponent;
class UMaterialInstanceDynamic;
class UMaterialInterface;
class USkeletalMeshComponent;
class UVerseEventHub;

/** Resolves a player state id of a contract event to the body mesh gore draws on. */
using FVerseGoreVictimResolver = TFunction<USkeletalMeshComponent*(int32 PlayerId)>;

/**
 * The gore of one world (WP05). Listens on the hub to FVerseHitEvent, FVerseDeathEvent and
 * FVerseFinisherEvent and turns them into blood bursts, wall and floor spatter, wound masks,
 * pools and finisher gore, or into the Reduced level's neutral flash and cut to black.
 *
 * One way only (combat-state.md 8): it reads events and the visibility channel, and writes only
 * its own transient, non-replicated, collision-free components. It does no work on a dedicated
 * server or in a process that cannot render (`-nullrhi`), unless a test forces it on.
 */
UCLASS()
class VERSEGORE_API UVerseGoreSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	static UVerseGoreSubsystem* Get(const UObject* WorldContextObject);

	/** True when this process has a viewport to draw gore into (no dedicated server, no -nullrhi). */
	static bool ProcessCanShowGore();

	// USubsystem / UWorldSubsystem
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;

	// FTickableGameObject
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickableInEditor() const override { return false; }

	/** Listening and drawing (false on a dedicated server, under -nullrhi, or before Initialize). */
	bool IsActive() const { return bActive; }

	/** Test hook: run even where the process cannot render. Binds or unbinds the hub. */
	void SetForceActive(bool bForce);

	/** The viewer's level. Switching to Reduced purges every existing piece of gore live. */
	EVerseGoreLevel GetGoreLevel() const { return Level; }
	void SetGoreLevel(EVerseGoreLevel NewLevel);

	/** Re-reads the level from the viewer's GameUserSettings (`[/Script/Verse.VerseSettings] GoreLevel`). */
	void ReloadLevelFromSettings();

	/** Removes all gore: decals, pools, droplets, flashes, wounds; ends a cut to black. */
	void Purge();

	/** The event handlers bound on the hub (public so tools can feed events without a hub). */
	void HandleHit(const FVerseHitEvent& Event);
	void HandleDeath(const FVerseDeathEvent& Event);
	void HandleFinisher(const FVerseFinisherEvent& Event);

	/** Advances gore time: droplets, flashes, pool growth, synthetic playback, cut-to-black timeout. */
	void AdvanceTime(float DeltaSeconds);

	/** Replaces the default resolver (game state player array -> pawn -> skeletal mesh). */
	void SetVictimResolver(FVerseGoreVictimResolver Resolver);

	/** Plays a synthetic stream through the hub from now on (WP05.1). */
	void PlaySynthetic(const FVerseGoreSyntheticParams& Params);
	void StopSynthetic();
	bool IsPlayingSynthetic() const { return SyntheticCursor < SyntheticEvents.Num(); }

	const FVerseGoreTuning& GetTuning() const { return Tuning; }
	FVerseGoreTuning& MutableTuning() { return Tuning; }

	const FVerseGoreBudget& GetBudget() const { return Budget; }
	void ResetBudget();
	/** Budget as the JSON the harness reads (WP05.8). */
	FString BudgetJson() const;
	/** Writes BudgetJson to a file; false when the write fails. */
	bool WriteBudgetJson(const FString& Path) const;

	const FVerseGoreCutToBlack& GetCutToBlack() const { return CutToBlack; }

	/** The gore actor, created on first use (nullptr while inactive). */
	AVerseGoreActor* GetGoreActor() const { return GoreActor.Get(); }

	/** Wounds currently on one body (ref-pose component space xyz, radius w). */
	TArray<FVector4f> GetWounds(const USkeletalMeshComponent* Mesh) const;

	/** Live spatter decals and pools, oldest first (tests and screenshots). */
	TArray<UDecalComponent*> GetSpatterDecals() const;
	TArray<UDecalComponent*> GetPoolDecals() const;

	/** Bone-space impact -> reference-pose component space (what the wound mask compares against). */
	static bool BoneLocalToRefPose(const USkeletalMeshComponent* Mesh, FName Bone, const FVector& BoneLocal, FVector& OutRefPose);

private:
	struct FDroplet
	{
		FVector Position = FVector::ZeroVector;
		FVector Velocity = FVector::ZeroVector;
		float Age = 0.f;
		float Life = 0.f;
		float Size = 1.f;
	};

	struct FFlash
	{
		FVector Position = FVector::ZeroVector;
		float Age = 0.f;
	};

	struct FPool
	{
		TWeakObjectPtr<UDecalComponent> Decal;
		int32 VictimId = 0;
		double StartTime = 0.0;
		float Radius = 0.f;
	};

	struct FWoundSet
	{
		TWeakObjectPtr<USkeletalMeshComponent> Mesh;
		TArray<FVector4f> Wounds;    // ring, oldest first after Normalize
		int32 Next = 0;              // ring write index once full
		TArray<TWeakObjectPtr<UMaterialInstanceDynamic>> Materials;
		bool bMaterialsResolved = false;
	};

	void BindHub();
	void UnbindHub();
	void UpdateActive();
	AVerseGoreActor* EnsureGoreActor();
	void LoadLook();

	USkeletalMeshComponent* ResolveVictim(int32 PlayerId) const;
	USkeletalMeshComponent* DefaultResolve(int32 PlayerId) const;

	void SpawnBurst(const FVector& Origin, const FVector& Direction, int32 Count, uint32 Seed);
	void SpawnSpatter(const FVector& Origin, const FVector& Direction, int32 Traces, uint32 Seed, const AActor* Ignore);
	void SpawnFlash(const FVector& Location);
	bool PlaceSpatterDecal(const FVector& Location, const FVector& Normal, float Size, uint32 Seed);
	void AddWound(USkeletalMeshComponent* Mesh, FName Bone, const FVector& BoneLocal, float Damage);
	/** Writes the wound slots to the body materials: only `Changed`, or all when INDEX_NONE. Slot i = ring entry i. */
	void ApplyWounds(FWoundSet& Set, int32 Changed = INDEX_NONE);
	void StartPool(int32 VictimId, const FVector& BodyLocation, const AActor* Ignore);
	void UpdatePools();
	void UpdateDroplets(float DeltaSeconds);
	void UpdateFlashes(float DeltaSeconds);
	void StartCutToBlack(const FVerseFinisherEvent& Event);
	void EndCutToBlack();
	void SetCameraFade(bool bBlack);
	void RefreshBudgetLive();

	FVector BodyPoint(USkeletalMeshComponent* Mesh, FName Bone, const FVector& Fallback) const;

	FVerseGoreTuning Tuning;
	FVerseGoreBudget Budget;
	FVerseGoreCutToBlack CutToBlack;
	EVerseGoreLevel Level = EVerseGoreLevel::Full;
	bool bActive = false;
	bool bForceActive = false;
	bool bBound = false;
	bool bLookLoaded = false;
	double GoreTime = 0.0;

	TWeakObjectPtr<UVerseEventHub> Hub;
	FDelegateHandle HitHandle;
	FDelegateHandle DeathHandle;
	FDelegateHandle FinisherHandle;

	TWeakObjectPtr<AVerseGoreActor> GoreActor;

	/** Spatter decal ring: components are reused oldest first once the cap is reached. */
	UPROPERTY(Transient)
	TArray<TObjectPtr<UDecalComponent>> SpatterRing;
	int32 SpatterNext = 0;
	int32 SpatterLive = 0;

	TArray<FPool> Pools;     // oldest first
	TArray<FDroplet> DropletsSim;
	TArray<FFlash> FlashesSim;
	TArray<FWoundSet> WoundSets;
	/** Bodies whose wounds clear at a gore time (respawn). */
	TArray<TPair<TWeakObjectPtr<USkeletalMeshComponent>, double>> PendingWoundClears;

	UPROPERTY(Transient)
	TArray<TObjectPtr<UMaterialInterface>> SpatterMaterials;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> DripMaterial;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> PoolMaterial;

	FVerseGoreVictimResolver VictimResolver;

	TArray<FVerseGoreSyntheticEvent> SyntheticEvents;
	int32 SyntheticCursor = 0;
	double SyntheticStart = 0.0;
};
