#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseBoltPresentation.generated.h"

class AActor;
class UDecalComponent;
class UInstancedStaticMeshComponent;
class UMaterialInstanceDynamic;
class UMaterialInterface;
class UPointLightComponent;
class UStaticMesh;
class UStaticMeshComponent;
struct FHitResult;

/** What a bullet struck, for the impact look (holes, sparks, dust, shards). */
enum class EVerseImpactSurface : uint8
{
	Metal,
	Concrete,
	Glass,
	/** A body: blood comes from the gore system, nothing drawn here. */
	Flesh,
};

/** One bullet as the viewer sees it. Only tracer rounds draw a streak; the rest are bookkeeping. */
struct FVerseVisualBolt
{
	int32 ShooterId = 0;
	uint16 ShotCounter = 0;
	FName WeaponId;
	FVector Origin = FVector::ZeroVector;
	FVector Dir = FVector::ForwardVector;
	double SpawnTime = 0.0;
	double SpeedCmS = 88000.0;
	double MaxRangeCm = 15000.0;
	/** The local viewer's own shot. */
	bool bOwn = false;
	/** A tracer round (UVerseWeaponDefinition::IsTracerRound): draws the thin yellow-white streak. */
	bool bTracer = false;
	FLinearColor Color = FLinearColor::White;
	/** Where the viewer sees the shot leave (the viewmodel muzzle) minus Origin; fades out over the first metres. */
	FVector VisualOffset = FVector::ZeroVector;
};

/** A short impact flash from the cosmetic hit event. */
struct FVerseVisualImpact
{
	FVector Location = FVector::ZeroVector;
	double SpawnTime = 0.0;
	EVerseImpactSurface Surface = EVerseImpactSurface::Metal;
};

/** A short-lived effect drawn at a point (another shooter's muzzle flash, impact sparks or shards). */
struct FVerseVisualBurst
{
	FVector Location = FVector::ZeroVector;
	FVector Axis = FVector::ForwardVector;
	double SpawnTime = 0.0;
	double Life = 0.1;
	float Roll = 0.f;
	bool bOwn = false;
	EVerseImpactSurface Surface = EVerseImpactSurface::Metal;
};

/** The short fading line a tracer leaves once it has landed: from where it was seen to leave to the impact. */
struct FVerseVisualTrail
{
	FVector Start = FVector::ZeroVector;
	FVector End = FVector::ZeroVector;
	double SpawnTime = 0.0;
	bool bOwn = false;
};

/** A soft translucent puff: muzzle smoke or concrete dust. Rises, grows, thins out. */
struct FVerseVisualPuff
{
	FVector Location = FVector::ZeroVector;
	FVector Velocity = FVector::ZeroVector;
	double SpawnTime = 0.0;
	double Life = 0.6;
	float StartCm = 6.f;
	float EndCm = 40.f;
	float Opacity = 0.2f;
	FLinearColor Tint = FLinearColor(0.2f, 0.2f, 0.2f);
};

/** An ejected shell casing: a small brass cylinder that tumbles, bounces and lies still until it expires. */
struct FVerseVisualCasing
{
	FVector Location = FVector::ZeroVector;
	FVector Velocity = FVector::ZeroVector;
	FQuat Rotation = FQuat::Identity;
	FVector SpinAxis = FVector::UpVector;
	/** rad/s */
	double SpinRate = 30.0;
	double SpawnTime = 0.0;
	bool bResting = false;
	/** Rifle-length case (else a short pistol case). */
	bool bLong = true;
	int32 Bounces = 0;
};

/**
 * Bullet presentation (WP02.11, ballistics decision): every shot is a real round. The viewer sees
 * another shooter's muzzle flash with a short warm light and a smoke puff; every shooter ejects a
 * brass casing that bounces and lies on the floor for a few seconds; only tracer rounds (every Nth
 * round and the last rounds of a magazine, UVerseWeaponDefinition::IsTracerRound) draw a thin
 * yellow-white streak; impacts come only from the cosmetic hit event (never from the client's own
 * trace) and look like their surface: sparks and a dark hole on metal, a dust puff and a grey chip
 * on concrete, glinting shards and a pale crack on glass, nothing on a body (gore draws the blood).
 * Penetrations leave a hole on the entry and the exit. The class keeps its historic name. Not
 * created on a dedicated server; without a renderer (-nullrhi) it draws nothing but keeps the same
 * bookkeeping, which the tests read.
 */
UCLASS()
class VERSECOMBAT_API UVerseBoltPresentation : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	/** Placeholder tracer (no WP14.9 art): a thin cylinder. */
	static constexpr double StreakLengthCm = 250.0;
	static constexpr double StreakRadiusCm = 0.6;
	static constexpr double ImpactLifeS = 0.08;
	/** The tracer streak: up to this long, this many times the modelled rod's width (a thin line). */
	static constexpr double ArtStreakLengthCm = 450.0;
	static constexpr double ArtWidthScale = 0.45;
	/** An own round starts at the viewmodel muzzle and joins the true line over this distance. */
	static constexpr double ConvergeCm = 900.0;
	static constexpr double SparkLifeS = 0.09;
	/** A landed tracer's line fades over this long. */
	static constexpr double TrailLifeS = 0.05;
	static constexpr double MuzzleFlashLifeS = 0.045;
	static constexpr double CasingLifeS = 3.0;
	static constexpr int32 MaxCasings = 40;
	static constexpr int32 MaxPuffs = 24;
	static constexpr int32 MaxHoleDecals = 64;
	static constexpr int32 MaxLights = 6;
	/** Tracer colour: burning tracer compound, yellow-white. */
	static FLinearColor TracerColor() { return FLinearColor(1.f, 0.78f, 0.42f); }

	static UVerseBoltPresentation* Get(const UObject* WorldContextObject);

	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;

	/** The local viewer's player id; rounds with this shooter id are own. Tests may set it. */
	TOptional<int32> LocalPlayerIdOverride;
	int32 GetLocalPlayerId() const;

	/** A fire event reached this viewer (hub OnFire: own prediction or the server's multicast). */
	void HandleFire(const FVerseFireEvent& E);
	/** The cosmetic hit: the round ends there with an impact that matches the surface. */
	void HandleHit(const FVerseHitEvent& E);
	/** A round passed a piece: a hole on the entry and on the exit. */
	void HandlePenetration(const FVersePenetrationEvent& E);
	/** A predicted shot the server rejected. */
	void HandleRejected(int32 ShooterId, uint16 ShotCounter);

	/** Advances the visuals to Now (Tick uses world time). */
	void Advance(double Now);

	const TArray<FVerseVisualBolt>& GetBolts() const { return Bolts; }
	const TArray<FVerseVisualImpact>& GetImpacts() const { return Impacts; }
	const TArray<FVerseVisualBurst>& GetSparks() const { return Sparks; }
	const TArray<FVerseVisualBurst>& GetMuzzleFlashes() const { return MuzzleFlashes; }
	const TArray<FVerseVisualTrail>& GetTrails() const { return Trails; }
	const TArray<FVerseVisualPuff>& GetPuffs() const { return Puffs; }
	const TArray<FVerseVisualCasing>& GetCasings() const { return Casings; }
	int32 NumOwn() const;
	int32 NumFoe() const;
	int32 NumTracers() const;
	/** Where a round is at Now: muzzle velocity along Dir plus gravity drop. */
	static FVector HeadAt(const FVerseVisualBolt& B, double Now);
	/** Where the viewer sees the head: the true head plus the muzzle offset, fading over ConvergeCm. */
	static FVector VisualHeadAt(const FVerseVisualBolt& B, double Now);
	/** Surface of a traced hit for the impact look (material and actor names; metal by default). */
	static EVerseImpactSurface ClassifySurface(const FHitResult& Hit);
	/** Surface of a penetration table material. */
	static EVerseImpactSurface SurfaceOfWireId(uint8 MaterialWireId);

	/** Time source override (tests). */
	TFunction<double()> ClockOverride;

	/**
	 * Where the viewer sees its own shot leave (the first-person weapon's muzzle), set by the
	 * module that owns the viewmodel; unset, own rounds start at the fire origin.
	 */
	TFunction<bool(int32 ShooterId, FVector& OutMuzzle)> VisualMuzzle;

	/** Rounds left in the shooter's magazine after a shot (tests); unset, read from its inventory; < 0 unknown. */
	TFunction<int32(int32 ShooterId, FName WeaponId)> RoundsLeftOverride;

private:
	void Subscribe();
	void EnsureRender();
	void UpdateRender(double Now);
	void UpdateLights(double Now);
	void StepCasings(double Now, double Dt);
	void PlaceHole(const FVector& Location, const FVector& Normal, EVerseImpactSurface Surface);
	void SpawnCasing(const FVector& Port, const FVector& ShotDir, bool bLong, double Now);
	void SpawnPuff(const FVector& Location, const FVector& Velocity, double Now, double Life, float StartCm, float EndCm,
		float Opacity, const FLinearColor& Tint);
	int32 RoundsLeft(int32 ShooterId, FName WeaponId) const;
	double WorldNow() const;

	TArray<FVerseVisualBolt> Bolts;
	TArray<FVerseVisualImpact> Impacts;
	TArray<FVerseVisualBurst> Sparks;
	TArray<FVerseVisualBurst> MuzzleFlashes;
	TArray<FVerseVisualTrail> Trails;
	TArray<FVerseVisualPuff> Puffs;
	TArray<FVerseVisualCasing> Casings;
	FDelegateHandle FireHandle;
	FDelegateHandle HitHandle;
	FDelegateHandle PenetrationHandle;
	FDelegateHandle RejectHandle;
	bool bSubscribed = false;
	/** The WP14.9 rod, flash and spark meshes and their materials are there; else placeholder shapes draw. */
	bool bArtBolts = false;
	int32 NextHole = 0;
	double LastAdvance = -1.0;

	UPROPERTY(Transient)
	TObjectPtr<AActor> RenderActor;
	UPROPERTY(Transient)
	TObjectPtr<UInstancedStaticMeshComponent> TracerMeshes;
	UPROPERTY(Transient)
	TObjectPtr<UInstancedStaticMeshComponent> ImpactMeshes;
	UPROPERTY(Transient)
	TObjectPtr<UInstancedStaticMeshComponent> CasingMeshes;
	/** The WP14.9 meshes and recoloured looks (not built for instancing: drawn from a component pool). */
	UPROPERTY(Transient)
	TObjectPtr<UStaticMesh> RodArt;
	UPROPERTY(Transient)
	TObjectPtr<UStaticMesh> FlashArt;
	UPROPERTY(Transient)
	TObjectPtr<UStaticMesh> SparkArt;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> TracerLook;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> FlashLook;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> SparkLook;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> ShardLook;
	UPROPERTY(Transient)
	TArray<TObjectPtr<UStaticMeshComponent>> ArtPool;
	int32 ArtUsed = 0;
	void DrawArt(UStaticMesh* Mesh, UMaterialInterface* Look, const FTransform& Transform);
	/** Puffs: one translucent sphere each, with its own fading material. */
	UPROPERTY(Transient)
	TArray<TObjectPtr<UStaticMeshComponent>> PuffPool;
	UPROPERTY(Transient)
	TArray<TObjectPtr<UMaterialInstanceDynamic>> PuffLooks;
	UPROPERTY(Transient)
	TArray<TObjectPtr<UPointLightComponent>> Lights;
	UPROPERTY(Transient)
	TArray<TObjectPtr<UDecalComponent>> Holes;
	/** Bullet hole decal per surface (Metal, Concrete, Glass). */
	UPROPERTY(Transient)
	TArray<TObjectPtr<UMaterialInterface>> HoleLooks;
};
