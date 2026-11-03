#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"

#include "VerseMovementTuning.generated.h"

/**
 * Movement tuning in SI units (metres, seconds, degrees), the shape of
 * unreal/Verse/Data/movement/movement_tuning.json. The defaults are the start values of
 * work-packages.md WP01; they are tuning, not contract, and change through the harness.
 * Code reads them through the *Cm() helpers, which convert to Unreal centimetres.
 */
USTRUCT(BlueprintType)
struct VERSEMOVEMENT_API FVerseMovementTuningValues
{
	GENERATED_BODY()

	// Speeds, m/s.
	UPROPERTY(EditAnywhere, Category = "Speed") float WalkSpeed = 4.5f;
	UPROPERTY(EditAnywhere, Category = "Speed") float SprintSpeed = 6.5f;
	UPROPERTY(EditAnywhere, Category = "Speed") float CrouchSpeed = 2.2f;
	UPROPERTY(EditAnywhere, Category = "Speed") float ProneSpeed = 0.9f;
	/** Sprint needs the move input within this angle of the facing. */
	UPROPERTY(EditAnywhere, Category = "Speed") float SprintMaxAngleDeg = 45.f;
	/** Standing ground speed at or below which footsteps are "walk" (4 m) instead of "run" (10 m). */
	UPROPERTY(EditAnywhere, Category = "Speed") float QuietWalkMaxSpeed = 2.6f;

	// Slide.
	UPROPERTY(EditAnywhere, Category = "Slide") float SlideMinEntrySpeed = 5.5f;
	UPROPERTY(EditAnywhere, Category = "Slide") float SlideBoostSpeed = 7.5f;
	/** The slide has decayed to crouch speed by this time at the latest. */
	UPROPERTY(EditAnywhere, Category = "Slide") float SlideMaxDuration = 1.1f;
	UPROPERTY(EditAnywhere, Category = "Slide") float SlideCooldown = 1.0f;
	/** 1 = linear decay from boost to crouch speed; above 1 holds the speed longer. */
	UPROPERTY(EditAnywhere, Category = "Slide") float SlideDecayExponent = 1.4f;

	// Jump.
	UPROPERTY(EditAnywhere, Category = "Jump") float JumpApexHeight = 0.55f;

	// Mantle.
	UPROPERTY(EditAnywhere, Category = "Mantle") float MantleMinHeight = 0.5f;
	UPROPERTY(EditAnywhere, Category = "Mantle") float MantleLowMaxHeight = 1.2f;
	UPROPERTY(EditAnywhere, Category = "Mantle") float MantleHighMaxHeight = 2.0f;
	UPROPERTY(EditAnywhere, Category = "Mantle") float MantleLowDuration = 0.45f;
	UPROPERTY(EditAnywhere, Category = "Mantle") float MantleHighDuration = 0.85f;
	/** Horizontal reach from the capsule surface to the ledge face. */
	UPROPERTY(EditAnywhere, Category = "Mantle") float MantleReach = 0.6f;
	/** Share of the mantle spent rising; the rest moves onto the ledge. */
	UPROPERTY(EditAnywhere, Category = "Mantle") float MantleRiseFraction = 0.55f;
	/** Ledge faces more than this far off the facing are not mantled. */
	UPROPERTY(EditAnywhere, Category = "Mantle") float MantleMaxFaceAngleDeg = 55.f;

	// Lean.
	UPROPERTY(EditAnywhere, Category = "Lean") float LeanCameraOffset = 0.35f;
	UPROPERTY(EditAnywhere, Category = "Lean") float LeanRollDeg = 12.f;
	UPROPERTY(EditAnywhere, Category = "Lean") float LeanEnterTime = 0.15f;
	/** Radius kept clear around the leaned camera by the wall check. */
	UPROPERTY(EditAnywhere, Category = "Lean") float LeanCameraClearance = 0.12f;

	// Prone.
	UPROPERTY(EditAnywhere, Category = "Prone") float ProneEnterTime = 0.7f;
	UPROPERTY(EditAnywhere, Category = "Prone") float ProneExitTime = 0.6f;
	UPROPERTY(EditAnywhere, Category = "Prone") float ProneTurnCapDegPerSec = 90.f;
	/** Vertical space the whole prone body needs. */
	UPROPERTY(EditAnywhere, Category = "Prone") float ProneMinClearance = 0.4f;
	/** Length of the horizontal prone body box, feet to head. */
	UPROPERTY(EditAnywhere, Category = "Prone") float ProneBodyLength = 1.8f;
	UPROPERTY(EditAnywhere, Category = "Prone") float ProneBodyWidth = 0.5f;

	// Capsule and eyes (feet-relative heights).
	UPROPERTY(EditAnywhere, Category = "Body") float CapsuleRadius = 0.34f;
	UPROPERTY(EditAnywhere, Category = "Body") float StandHeight = 1.8f;
	UPROPERTY(EditAnywhere, Category = "Body") float CrouchHeight = 1.1f;
	UPROPERTY(EditAnywhere, Category = "Body") float ProneRadius = 0.2f;
	UPROPERTY(EditAnywhere, Category = "Body") float StandEyeHeight = 1.65f;
	UPROPERTY(EditAnywhere, Category = "Body") float CrouchEyeHeight = 0.98f;
	UPROPERTY(EditAnywhere, Category = "Body") float ProneEyeHeight = 0.3f;
	/** Seconds the camera takes to settle on a new eye height. */
	UPROPERTY(EditAnywhere, Category = "Body") float EyeBlendTime = 0.12f;

	// Noise (bot.md 3.2; ranges come from DA_Audibility, not from here).
	UPROPERTY(EditAnywhere, Category = "Noise") float WalkStride = 0.7f;
	UPROPERTY(EditAnywhere, Category = "Noise") float RunStride = 0.95f;
	UPROPERTY(EditAnywhere, Category = "Noise") float SprintStride = 1.25f;
	/** Landing raises Noise.Move.Land at or above this fall speed. */
	UPROPERTY(EditAnywhere, Category = "Noise") float LandNoiseMinFallSpeed = 3.0f;

	float WalkSpeedCm() const { return WalkSpeed * 100.f; }
	float SprintSpeedCm() const { return SprintSpeed * 100.f; }
	float CrouchSpeedCm() const { return CrouchSpeed * 100.f; }
	float ProneSpeedCm() const { return ProneSpeed * 100.f; }
	float StandHalfHeightCm() const { return StandHeight * 50.f; }
	float CrouchHalfHeightCm() const { return CrouchHeight * 50.f; }
	/** The prone capsule is a sphere-like capsule of the prone clearance. */
	float ProneHalfHeightCm() const { return FMath::Max(ProneRadius * 100.f, ProneMinClearance * 50.f); }
	float JumpZVelocityCm(float GravityZ) const { return FMath::Sqrt(2.f * FMath::Abs(GravityZ) * JumpApexHeight * 100.f); }

	/** Every value finite and in a sane range; OutError names the first that is not. */
	bool Validate(FString& OutError) const;
};

/**
 * DA_MovementTuning: the movement DataAsset (work-packages.md WP01.1). Its source of truth is
 * Data/movement/movement_tuning.json; the asset is imported from it, and code without an
 * asset loads the JSON directly (GetDefaultTuning).
 */
UCLASS(BlueprintType)
class VERSEMOVEMENT_API UVerseMovementTuning : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Movement")
	FVerseMovementTuningValues Values;

	/** Parses JSON (field names as in FVerseMovementTuningValues; unknown fields fail). */
	static bool ParseJson(const FString& Json, FVerseMovementTuningValues& Out, FString& OutError);

	/** Replaces Values from a JSON file; false (Values unchanged) on any error. */
	bool LoadFromJsonFile(const FString& Path, FString& OutError);

	/** Editor import (Content/Verse/Test/WP01/make_content.py): Values from the JSON file. */
	UFUNCTION(BlueprintCallable, Category = "Verse|Movement")
	bool ImportJsonFile(const FString& Path, FString& OutError) { return LoadFromJsonFile(Path, OutError); }

	/** The values as JSON in the shape the file uses. */
	static FString ToJson(const FVerseMovementTuningValues& Values);

	/** unreal/Verse/Data/movement/movement_tuning.json of the running project. */
	static FString DefaultJsonPath();

	/** The process-wide default: the JSON file when it loads, else the C++ start values. */
	static const UVerseMovementTuning* GetDefaultTuning();
};
