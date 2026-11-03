#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseBoltPresentation.generated.h"

class AActor;
class UInstancedStaticMeshComponent;

/** One bolt as the viewer sees it. */
struct FVerseVisualBolt
{
	int32 ShooterId = 0;
	uint16 ShotCounter = 0;
	FName WeaponId;
	FVector Origin = FVector::ZeroVector;
	FVector Dir = FVector::ForwardVector;
	double SpawnTime = 0.0;
	double SpeedCmS = 30000.0;
	double MaxRangeCm = 15000.0;
	/** Own predicted bolt (amber) or the opponent's (red). */
	bool bOwn = false;
	FLinearColor Color = FLinearColor::White;
};

/** A short impact flash from the cosmetic hit event. */
struct FVerseVisualImpact
{
	FVector Location = FVector::ZeroVector;
	double SpawnTime = 0.0;
};

/**
 * Bolt presentation (WP02.11): the owner's predicted bolt drawn amber at fire time, every other
 * shooter's bolt drawn red from FVerseFireEvent, removal on Rejected and on the bolt's cosmetic hit,
 * impact flashes only from the cosmetic hit event (never from the client's own trace). Placeholder
 * look (engine basic shapes) until WP14.9. Not created on a dedicated server; without a renderer
 * (-nullrhi) it draws nothing but keeps the same bookkeeping, which the tests read.
 */
UCLASS()
class VERSECOMBAT_API UVerseBoltPresentation : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	static constexpr double StreakLengthCm = 150.0;
	static constexpr double StreakRadiusCm = 3.0;
	static constexpr double ImpactLifeS = 0.08;

	static UVerseBoltPresentation* Get(const UObject* WorldContextObject);

	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;

	/** The local viewer's player id; bolts with this shooter id are own (amber). Tests may set it. */
	TOptional<int32> LocalPlayerIdOverride;
	int32 GetLocalPlayerId() const;

	/** A fire event reached this viewer (hub OnFire: own prediction or the server's multicast). */
	void HandleFire(const FVerseFireEvent& E);
	/** The cosmetic hit: the bolt ends there with an impact flash. */
	void HandleHit(const FVerseHitEvent& E);
	/** A predicted shot the server rejected. */
	void HandleRejected(int32 ShooterId, uint16 ShotCounter);

	/** Advances the visuals to Now (Tick uses world time). */
	void Advance(double Now);

	const TArray<FVerseVisualBolt>& GetBolts() const { return Bolts; }
	const TArray<FVerseVisualImpact>& GetImpacts() const { return Impacts; }
	int32 NumOwn() const;
	int32 NumFoe() const;
	/** Where a bolt's streak head is at Now. */
	static FVector HeadAt(const FVerseVisualBolt& B, double Now);

	/** Time source override (tests). */
	TFunction<double()> ClockOverride;

private:
	void Subscribe();
	void EnsureRender();
	void UpdateRender(double Now);
	double WorldNow() const;

	TArray<FVerseVisualBolt> Bolts;
	TArray<FVerseVisualImpact> Impacts;
	FDelegateHandle FireHandle;
	FDelegateHandle HitHandle;
	FDelegateHandle RejectHandle;
	bool bSubscribed = false;

	UPROPERTY(Transient)
	TObjectPtr<AActor> RenderActor;
	UPROPERTY(Transient)
	TObjectPtr<UInstancedStaticMeshComponent> OwnMeshes;
	UPROPERTY(Transient)
	TObjectPtr<UInstancedStaticMeshComponent> FoeMeshes;
	UPROPERTY(Transient)
	TObjectPtr<UInstancedStaticMeshComponent> ImpactMeshes;
};
