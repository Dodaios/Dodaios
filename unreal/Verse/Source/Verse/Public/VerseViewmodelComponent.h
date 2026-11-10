#pragma once

#include "Combat/VerseCombatTypes.h"
#include "Components/ActorComponent.h"
#include "CoreMinimal.h"

#include "VerseViewmodelComponent.generated.h"

class UCameraComponent;
class UMaterialInstanceDynamic;
class UPointLightComponent;
class UPoseableMeshComponent;
class USceneComponent;
class USkeletalMesh;
class UStaticMeshComponent;

/** Where a held weapon sits in front of the eye, camera space (X forward, Y right, Z up), cm and degrees. */
struct VERSE_API FVerseViewmodelPose
{
	/** Grip (the mesh root) at hip. */
	FVector HipOffset = FVector(20.0, 12.0, -15.0);
	FRotator HipRotation = FRotator::ZeroRotator;
	/** Distance from the eye to the sight socket when aiming down sights. */
	double SightDistance = 16.0;
	/** Shot kick: back along X (cm) and up in pitch (deg). */
	double KickBackCm = 2.4;
	double KickPitchDeg = 2.6;
};

/**
 * The person's first-person view of the held weapon (the viewmodel): the WP14 weapon mesh in
 * front of the camera, posed in code until the WP13 arms and clips arrive. Only the locally
 * controlled person gets one; bots and remote pawns never build it.
 *
 * - The active slot's mesh (`/Game/Verse/Weapons/<Name>/SK_Weapon_<Name>`), the knife while a
 *   swing runs from any slot.
 * - Aim down sights: the sight socket slides onto the view axis as the weapon's ADS blend rises.
 * - Shot kick and bolt cycle on every own shot, muzzle flash card and light on the muzzle socket.
 * - Reload: tilt, magazine out and in, from the slot's reload start and end times.
 * - Slot switch: the new weapon rises over its equip time.
 * - Knife: wind-up, thrust at the contact frame, recover, from the knife presentation.
 * - Walk bob, look sway, sprint lowering; hidden while dead or in a finisher.
 *
 * Rendering uses the engine's first-person primitives (own field of view and scale), so the
 * weapon never clips into a wall in front of the person.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSE_API UVerseViewmodelComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseViewmodelComponent();

	static UVerseViewmodelComponent* FindOn(const AActor* Actor);

	/** Field of view of the viewmodel, horizontal degrees (the world keeps the camera's own). */
	static constexpr float ViewmodelFov = 74.f;
	/** First-person scale towards the camera: small enough to stay in front of any wall. */
	static constexpr float ViewmodelScale = 0.25f;
	static constexpr float MuzzleFlashSeconds = 0.05f;
	/** Shot kick spring: natural frequency (rad/s), damping ratio (below 1 = a little overshoot), and how a shot splits into a jump and a velocity. */
	static constexpr double KickSpringOmega = 28.0;
	static constexpr double KickSpringZeta = 0.55;
	static constexpr double KickJump = 0.4;
	static constexpr double KickImpulse = 0.9;
	/** Muzzle flash light: lumens, and how far ahead of the eye it sits (past the drawn weapon). */
	static constexpr float FlashLumens = 1200.f;
	static constexpr float FlashLightForwardCm = 80.f;
	/** Fill light on the held weapon, lumens; it sits above and right of the eye (camera space, cm, drawn space). */
	static constexpr float FillLumens = 380.f;
	/** Eye to the Graveline's reflex dot while aiming, cm: far enough that the frame stays small. */
	static constexpr double GravelineSightDistanceCm = 24.0;
	/** Eye to the rear window of a hero holographic sight while aiming, cm. */
	static constexpr double HeroSightDistanceCm = 15.0;
	/** True for `/Game/Verse/Weapons/<Name>Hero/SK_Weapon_<Name>Hero` (baked hero meshes). */
	static bool IsHeroMeshPath(const FString& Path);
	/** Lowest roughness of the held weapon's surfaces: satin, so the steel never mirrors the ceiling. */
	static constexpr float ViewmodelRoughnessMin = 0.45f;

	/** The pose table per weapon id (pure, tests read it). */
	static FVerseViewmodelPose PoseFor(FName WeaponId);
	/** `/Game/Verse/Weapons/<Name>/SK_Weapon_<Name>.SK_Weapon_<Name>` for a weapon id; empty for an id without art. */
	static FString MeshPathFor(FName WeaponId);

	/** The weapon id shown now (None when nothing is drawn). */
	FName GetShownWeaponId() const { return ShownWeaponId; }
	bool IsBuilt() const { return Root != nullptr; }
	bool IsShowing() const;
	/** The drawn weapon carries a sight with its own reticle (an `Optic` material slot). */
	bool HasOptic() const;
	/** The muzzle socket in world space; false without a firearm drawn. */
	bool GetMuzzleWorld(FVector& OutLocation) const;
	/** The current offset of the mesh root from the camera, camera space (tests). */
	const FTransform& GetLocalPose() const { return LocalPose; }

	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

	/** One step (TickComponent calls it). */
	void Step(float DeltaSeconds);

private:
	bool ShouldBuild() const;
	void Build();
	void TearDown();
	void HandleFire(const FVerseFireEvent& Event);
	void ShowWeapon(FName WeaponId);
	UCameraComponent* GetCamera() const;
	float Now() const;

	UPROPERTY(Transient)
	TObjectPtr<USceneComponent> Root;
	UPROPERTY(Transient)
	TObjectPtr<UPoseableMeshComponent> Mesh;
	UPROPERTY(Transient)
	TObjectPtr<UStaticMeshComponent> Flash;
	UPROPERTY(Transient)
	TObjectPtr<UPointLightComponent> FlashLight;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInstanceDynamic> FlashMaterial;
	/** Soft key light on lighting channel 1: lights the held weapon only, never the world. */
	UPROPERTY(Transient)
	TObjectPtr<UPointLightComponent> FillLight;

	FName ShownWeaponId;
	bool bShowingHero = false;
	EVerseLoadoutSlot LastSlot = EVerseLoadoutSlot::Primary;
	FName MagBone;
	FName BoltBone;
	FVector MagRest = FVector::ZeroVector;
	FVector BoltRest = FVector::ZeroVector;
	FVerseViewmodelPose Pose;
	FTransform LocalPose = FTransform::Identity;

	// Motion state.
	float EquipStartedAt = -100.f;
	float EquipSeconds = 0.3f;
	/** Shot kick: position (cm) and rotation (pitch, yaw, roll in degrees) with their spring velocities. */
	FVector KickPos = FVector::ZeroVector;
	FVector KickRot = FVector::ZeroVector;
	FVector KickPosVel = FVector::ZeroVector;
	FVector KickRotVel = FVector::ZeroVector;
	float BoltCycle = 0.f;
	float FlashUntil = -1.f;
	FRotator LastViewRotation = FRotator::ZeroRotator;
	bool bHaveViewRotation = false;
	FVector2D Sway = FVector2D::ZeroVector;
	double BobPhase = 0.0;
	float BobAmount = 0.f;
	float SprintBlend = 0.f;
	float AdsSmoothed = 0.f;
	uint16 LastShotCounter = 0;
	bool bHaveShot = false;
	int32 OwnId = MIN_int32;

	FDelegateHandle FireHandle;
};
