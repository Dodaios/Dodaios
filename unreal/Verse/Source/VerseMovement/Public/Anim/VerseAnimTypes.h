#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

#include "VerseAnimTypes.generated.h"

class UAnimSequence;

/** Weapon class the upper body holds (clip sets of work-packages.md WP13.6). */
UENUM(BlueprintType)
enum class EVerseAnimWeapon : uint8
{
	None,
	Rifle,
	Pistol,
	Knife
};

/** One-shot upper-body action; its clip plays from `ActionTime` 0. */
UENUM(BlueprintType)
enum class EVerseAnimAction : uint8
{
	None,
	Fire,
	ReloadTactical,
	ReloadEmpty,
	Equip,
	Holster,
	Strike
};

/**
 * Everything the animation layer reads per frame. Gathered from the pawn
 * (`IVerseMovementQuery`, velocity, control rotation) unless a caller sets
 * it with `UVerseAnimInstance::SetExternalInputs` (crew, kill cam, tests).
 */
USTRUCT(BlueprintType)
struct VERSEMOVEMENT_API FVerseAnimInputs
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	EVerseStance Stance = EVerseStance::Stand;

	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	bool bSprinting = false;

	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	bool bAirborne = false;

	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	bool bMantling = false;

	/** Mantle over a ledge above 1.2 m (WP01: high mantle). */
	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	bool bMantleHigh = false;

	/** -1..1, > 0 towards the pawn's right (IVerseMovementQuery::LeanFromQuantized). */
	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	float Lean = 0.f;

	/** Velocity in the pawn's frame, cm/s: X forward, Y right. */
	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	FVector LocalVelocity = FVector::ZeroVector;

	/** Aim pitch relative to the pawn, degrees, > 0 up. */
	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	float AimPitch = 0.f;

	/** Aim-down-sights blend 0..1 (combat-state 2.1 ADS). */
	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	float Ads = 0.f;

	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	EVerseAnimWeapon Weapon = EVerseAnimWeapon::Rifle;

	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	EVerseAnimAction Action = EVerseAnimAction::None;

	/** Seconds since `Action` started. */
	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	float ActionTime = 0.f;

	/** A full-body clip that replaces everything (crew duty, death, finisher, kill cam). */
	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	FName OverrideClip;

	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	float OverrideTime = 0.f;

	UPROPERTY(BlueprintReadWrite, Category = "Verse|Anim")
	bool bOverrideLoop = false;
};

/** Locomotion states of `FVerseAnimStateMachine`. */
enum class EVerseLocoState : uint8
{
	Ground,
	JumpStart,
	Fall,
	Land,
	Slide,
	Mantle,
	ProneEnter,
	ProneExit
};

/** The clip set of `SKEL_Verse_Human` the runtime uses, resolved by name. */
struct VERSEMOVEMENT_API FVerseAnimClipSet
{
	static constexpr int32 NumStances = 3; // Stand, Crouch, Prone
	static constexpr int32 NumHeadings = 8; // F, FL, L, BL, B, BR, R, FR

	const UAnimSequence* Idle[NumStances] = {};
	const UAnimSequence* Move[NumStances][NumHeadings] = {};
	float MoveSpeed[NumStances] = {450.f, 220.f, 90.f};
	const UAnimSequence* Sprint = nullptr;
	float SprintSpeed = 650.f;
	const UAnimSequence* JumpStart = nullptr;
	const UAnimSequence* Fall = nullptr;
	const UAnimSequence* Land = nullptr;
	const UAnimSequence* Slide = nullptr;
	const UAnimSequence* MantleLow = nullptr;
	const UAnimSequence* MantleHigh = nullptr;
	const UAnimSequence* ProneEnter = nullptr;
	const UAnimSequence* ProneExit = nullptr;

	struct FWeapon
	{
		const UAnimSequence* Idle = nullptr;
		const UAnimSequence* Ads = nullptr;
		const UAnimSequence* Fire = nullptr;
		const UAnimSequence* ReloadTactical = nullptr;
		const UAnimSequence* ReloadEmpty = nullptr;
		const UAnimSequence* Equip = nullptr;
		const UAnimSequence* Holster = nullptr;
		const UAnimSequence* Strike = nullptr;
	};
	FWeapon Weapons[4]; // indexed by EVerseAnimWeapon

	/** Loads every clip from /Game/Verse/Animations (synchronous; editor and game thread). */
	void Load();
	bool IsComplete(TArray<FString>* OutMissing = nullptr) const;
	const UAnimSequence* ActionClip(EVerseAnimWeapon Weapon, EVerseAnimAction Action) const;
};

/** What the evaluator samples this frame; built on the game thread. */
struct VERSEMOVEMENT_API FVerseAnimFrame
{
	struct FStanceClips
	{
		const UAnimSequence* Idle = nullptr;
		const UAnimSequence* Move[FVerseAnimClipSet::NumHeadings] = {};
		float MoveLength[FVerseAnimClipSet::NumHeadings] = {};
	};

	// Ground locomotion, blended per stance.
	FStanceClips StanceClips[FVerseAnimClipSet::NumStances];
	float StanceWeight[FVerseAnimClipSet::NumStances] = {1.f, 0.f, 0.f};
	const UAnimSequence* SprintClip = nullptr;
	float SprintLength = 1.f;
	float MovePhase = 0.f; // 0..1, 0 = left foot contact (all move clips)
	float MoveAlpha = 0.f; // idle -> move
	float HeadingDeg = 0.f; // 0 forward, 90 the character's left
	float SprintAlpha = 0.f;
	float SprintPhase = 0.f;

	// A full-body state clip over locomotion (jump, fall, land, slide, mantle, prone transitions).
	const UAnimSequence* Special = nullptr;
	float SpecialTime = 0.f;
	float SpecialWeight = 0.f;
	bool bSpecialLoop = false;

	// Upper-body weapon layer: arms, neck, head, camera and the hand IK bones.
	EVerseAnimWeapon Weapon = EVerseAnimWeapon::Rifle;
	const UAnimSequence* WeaponIdle = nullptr;
	const UAnimSequence* WeaponAds = nullptr;
	float Ads = 0.f;
	float UpperAlpha = 1.f;
	const UAnimSequence* Action = nullptr;
	float ActionTime = 0.f;
	float ActionWeight = 0.f;

	// Procedural: lean over three spine bones, aim pitch, off-hand IK, foot IK.
	float Lean = 0.f;
	float AimPitch = 0.f;
	float OffHandAlpha = 1.f;
	bool bHasSupport = true;
	FTransform SupportInWeapon = FTransform::Identity;
	bool bFootIK = false;
	float FloorOffset[2] = {0.f, 0.f}; // cm, floor height under each foot (L, R) in component space
	FVector FloorNormal[2] = {FVector::UpVector, FVector::UpVector};

	// Full-body override (crew, death, finisher, kill cam).
	const UAnimSequence* Override = nullptr;
	float OverrideTime = 0.f;
	bool bOverrideLoop = false;
};
