#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseBoltPresentation.generated.h"

class AActor;
class UDecalComponent;
class UInstancedStaticMeshComponent;
class UMaterialInterface;
class UPointLightComponent;
class UStaticMesh;
class UStaticMeshComponent;

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
	/** Where the viewer sees the shot leave (the viewmodel muzzle) minus Origin; fades out over the first metres. */
	FVector VisualOffset = FVector::ZeroVector;
};

/** A short impact flash from the cosmetic hit event. */
struct FVerseVisualImpact
{
	FVector Location = FVector::ZeroVector;
	double SpawnTime = 0.0;
};

/** A short-lived effect drawn at a point (another shooter's muzzle flash, impact sparks). */
struct FVerseVisualBurst
{
	FVector Location = FVector::ZeroVector;
	FVector Axis = FVector::ForwardVector;
	double SpawnTime = 0.0;
	double Life = 0.1;
	float Roll = 0.f;
	bool bOwn = false;
};

/**
 * Bolt presentation (WP02.11): the owner's predicted bolt drawn amber at fire time, every other
 * shooter's bolt drawn red from FVerseFireEvent, removal on Rejected and on the bolt's cosmetic hit,
 * impact flashes only from the cosmetic hit event (never from the client's own trace). The look is
 * the WP14.9 art: the glowing bolt rod stretched into a streak, another shooter's muzzle flash card,
 * impact sparks with a scorch decal on world surfaces, and a few short point lights so a shot lights
 * the room it crosses. A clone without that art falls back to the placeholder shapes. Not created
 * on a dedicated server; without a renderer (-nullrhi) it draws nothing but keeps the same
 * bookkeeping, which the tests read.
 */
UCLASS()
class VERSECOMBAT_API UVerseBoltPresentation : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	static constexpr double StreakLengthCm = 150.0;
	static constexpr double StreakRadiusCm = 3.0;
	static constexpr double ImpactLifeS = 0.08;
	/** The art streak: up to this long, this many times the modelled rod's width. */
	static constexpr double ArtStreakLengthCm = 260.0;
	static constexpr double ArtWidthScale = 2.6;
	/** An own bolt starts at the viewmodel muzzle and joins the true line over this distance. */
	static constexpr double ConvergeCm = 900.0;
	static constexpr double SparkLifeS = 0.14;
	static constexpr double FoeFlashLifeS = 0.06;
	static constexpr int32 MaxScorchDecals = 48;
	static constexpr int32 MaxLights = 6;

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
	const TArray<FVerseVisualBurst>& GetSparks() const { return Sparks; }
	const TArray<FVerseVisualBurst>& GetFoeFlashes() const { return FoeFlashes; }
	int32 NumOwn() const;
	int32 NumFoe() const;
	/** Where a bolt's streak head is at Now. */
	static FVector HeadAt(const FVerseVisualBolt& B, double Now);
	/** Where the viewer sees the head: the true head plus the muzzle offset, fading over ConvergeCm. */
	static FVector VisualHeadAt(const FVerseVisualBolt& B, double Now);

	/** Time source override (tests). */
	TFunction<double()> ClockOverride;

	/**
	 * Where the viewer sees its own shot leave (the first-person weapon's muzzle), set by the
	 * module that owns the viewmodel; unset, own bolts start at the fire origin.
	 */
	TFunction<bool(int32 ShooterId, FVector& OutMuzzle)> VisualMuzzle;

private:
	void Subscribe();
	void EnsureRender();
	void UpdateRender(double Now);
	void UpdateLights(double Now);
	void PlaceScorch(const FVector& Location, const FVector& Normal);
	double WorldNow() const;

	TArray<FVerseVisualBolt> Bolts;
	TArray<FVerseVisualImpact> Impacts;
	TArray<FVerseVisualBurst> Sparks;
	TArray<FVerseVisualBurst> FoeFlashes;
	FDelegateHandle FireHandle;
	FDelegateHandle HitHandle;
	FDelegateHandle RejectHandle;
	bool bSubscribed = false;
	/** The WP14.9 rod and its materials are there; else the placeholder cylinder draws the bolts. */
	bool bArtBolts = false;
	int32 NextScorch = 0;

	UPROPERTY(Transient)
	TObjectPtr<AActor> RenderActor;
	UPROPERTY(Transient)
	TObjectPtr<UInstancedStaticMeshComponent> OwnMeshes;
	UPROPERTY(Transient)
	TObjectPtr<UInstancedStaticMeshComponent> FoeMeshes;
	UPROPERTY(Transient)
	TObjectPtr<UInstancedStaticMeshComponent> ImpactMeshes;
	/** The WP14.9 meshes and brightened looks (not built for instancing: drawn from a component pool). */
	UPROPERTY(Transient)
	TObjectPtr<UStaticMesh> RodArt;
	UPROPERTY(Transient)
	TObjectPtr<UStaticMesh> FlashArt;
	UPROPERTY(Transient)
	TObjectPtr<UStaticMesh> SparkArt;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> RodOwnLook;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> RodFoeLook;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> FlashFoeLook;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> SparkLook;
	UPROPERTY(Transient)
	TArray<TObjectPtr<UStaticMeshComponent>> ArtPool;
	int32 ArtUsed = 0;
	void DrawArt(UStaticMesh* Mesh, UMaterialInterface* Look, const FTransform& Transform);
	UPROPERTY(Transient)
	TArray<TObjectPtr<UPointLightComponent>> Lights;
	UPROPERTY(Transient)
	TArray<TObjectPtr<UDecalComponent>> Scorches;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> ScorchMaterial;
};
