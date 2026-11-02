#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "GameplayTagContainer.h"

#include "VersePerceptTypes.generated.h"

// The perception boundary (bot.md 2, 3, frozen interface). UVersePerceptionService (VerseCombat)
// produces these; the bot and the harness person models read only these. A percept never
// carries the true location of anything unperceived, nor health, ammo, tier, controller or intent.

/** Bit index in FVerseSightPercept::VisibleMask: the 8 hit-zone sample points of bot.md 3.1. */
UENUM(BlueprintType)
enum class EVerseSightSample : uint8
{
	Head,
	Neck,
	UpperTorso,
	Pelvis,
	ShoulderLeft,
	ShoulderRight,
	KneeLeft,
	KneeRight
};

/** The three arena height levels (README Arena). */
UENUM(BlueprintType)
enum class EVerseArenaLevel : uint8
{
	Floor,
	Mid,
	Upper
};

/** HUD-visible events (bot.md 3.3): kill feed and hit markers. */
UENUM(BlueprintType)
enum class EVerseHudEventKind : uint8
{
	Kill,
	OpponentRespawned,
	HitMarker,
	HeadshotMarker,
	KillMarker
};

/** What the observer's own HUD shows (bot.md 3.3). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseSelfPercept
{
	GENERATED_BODY()

	UPROPERTY()
	float Health = 0.f;

	UPROPERTY()
	float MaxHealth = 0.f;

	UPROPERTY()
	float Armor = 0.f;

	UPROPERTY()
	EVerseLoadoutSlot ActiveSlot = EVerseLoadoutSlot::Primary;

	UPROPERTY()
	int32 Magazine = 0;

	UPROPERTY()
	bool bChambered = false;

	UPROPERTY()
	int32 Reserve = 0;

	/** GadgetA, GadgetB. */
	UPROPERTY()
	int32 GadgetCharges[2] = {0, 0};

	/** Seconds left, GadgetA, GadgetB. */
	UPROPERTY()
	float GadgetCooldownS[2] = {0.f, 0.f};

	UPROPERTY()
	EVerseStance Stance = EVerseStance::Stand;

	/** Own pawn, world cm. */
	UPROPERTY()
	FVector Location = FVector::ZeroVector;

	UPROPERTY()
	FVector Velocity = FVector::ZeroVector;

	/** Own eye (the Camera bone), world cm. */
	UPROPERTY()
	FVector EyeLocation = FVector::ZeroVector;

	UPROPERTY()
	FRotator ViewRotation = FRotator::ZeroRotator;

	UPROPERTY()
	EVerseCombatPhase Phase = EVerseCombatPhase::Alive;

	UPROPERTY()
	bool bSpawnProtected = false;
};

/** One sighting (bot.md 3.1). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseSightPercept
{
	GENERATED_BODY()

	UPROPERTY()
	uint32 PerceptId = 0;

	UPROPERTY()
	FVector PelvisLocation = FVector::ZeroVector;

	UPROPERTY()
	FVector Velocity = FVector::ZeroVector;

	UPROPERTY()
	float FacingYawDeg = 0.f;

	UPROPERTY()
	float FacingPitchDeg = 0.f;

	UPROPERTY()
	EVerseStance Stance = EVerseStance::Stand;

	UPROPERTY()
	int8 LeanQuantized = 0;

	UPROPERTY()
	bool bAds = false;

	/** The weapon model in the target's hands. */
	UPROPERTY()
	FName HeldWeaponId;

	/** The reload animation is visible. */
	UPROPERTY()
	bool bReloading = false;

	/** The spawn protection effect is visible. */
	UPROPERTY()
	bool bSpawnProtected = false;

	/** Bit per EVerseSightSample visible this tick. */
	UPROPERTY()
	uint8 VisibleMask = 0;

	UPROPERTY()
	bool bPeripheral = false;
};

/** An opponent bolt segment seen in the cone (bot.md 3.1). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseBoltPercept
{
	GENERATED_BODY()

	UPROPERTY()
	uint32 PerceptId = 0;

	UPROPERTY()
	FVector Position = FVector::ZeroVector;

	UPROPERTY()
	FVector Direction = FVector::ForwardVector;

	UPROPERTY()
	uint32 ServerTimeMs = 0;
};

/** One heard noise, error already applied (bot.md 3.2). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseHeardPercept
{
	GENERATED_BODY()

	UPROPERTY()
	uint32 PerceptId = 0;

	/** The Noise.* tag. */
	UPROPERTY()
	FGameplayTag Noise;

	/** Noisy location, never the true one. */
	UPROPERTY()
	FVector Location = FVector::ZeroVector;

	/** The position error sd used, metres. */
	UPROPERTY()
	float ErrorSdM = 0.f;

	UPROPERTY()
	EVerseArenaLevel LevelGuess = EVerseArenaLevel::Floor;

	UPROPERTY()
	uint32 ServerTimeMs = 0;
};

/** Damage taken (bot.md 3.2: a hurt percept, not a noise). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseHurtPercept
{
	GENERATED_BODY()

	UPROPERTY()
	uint32 PerceptId = 0;

	/** Direction the damage came from, +-8 deg error applied. */
	UPROPERTY()
	FVector IncomingDirection = FVector::ForwardVector;

	UPROPERTY()
	float Damage = 0.f;

	UPROPERTY()
	EVerseDamageSource Source = EVerseDamageSource::Bolt;

	UPROPERTY()
	uint32 ServerTimeMs = 0;
};

/** Kill feed entry or hit marker (bot.md 3.3). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseHudEvent
{
	GENERATED_BODY()

	UPROPERTY()
	EVerseHudEventKind Kind = EVerseHudEventKind::HitMarker;

	UPROPERTY()
	int32 KillerId = 0;

	UPROPERTY()
	int32 VictimId = 0;

	UPROPERTY()
	EVerseDamageSource Cause = EVerseDamageSource::Bolt;

	UPROPERTY()
	FName WeaponId;

	UPROPERTY()
	bool bWallShot = false;

	/** Set when the kill cam shows where the killer stood. */
	UPROPERTY()
	bool bKillerPositionShown = false;

	UPROPERTY()
	FVector KillerPosition = FVector::ZeroVector;

	UPROPERTY()
	uint32 ServerTimeMs = 0;
};

/** Everything one observer perceives in one server tick (bot.md frozen interface). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVersePerceptFrame
{
	GENERATED_BODY()

	UPROPERTY()
	uint32 ServerTimeMs = 0;

	UPROPERTY()
	FVerseSelfPercept Self;

	UPROPERTY()
	TArray<FVerseSightPercept> Sightings;

	UPROPERTY()
	TArray<FVerseBoltPercept> Bolts;

	UPROPERTY()
	TArray<FVerseHeardPercept> Heard;

	/** Hurt is optional: valid only when bHasHurt. */
	UPROPERTY()
	bool bHasHurt = false;

	UPROPERTY()
	FVerseHurtPercept Hurt;

	UPROPERTY()
	TArray<FVerseHudEvent> Hud;
};

/**
 * What UVersePerceptionService::RegisterObserver gets (bot.md frozen interface): the tier's
 * hearing and acquisition fields and the seed of the observer's error RNG stream.
 */
USTRUCT(BlueprintType)
struct VERSECORE_API FVersePerceptionProfile
{
	GENERATED_BODY()

	UPROPERTY()
	float HearingErrorBaseM = 3.0f;

	UPROPERTY()
	float HearingErrorPerM = 0.10f;

	/** Mean, sd. */
	UPROPERTY()
	FVector2f ReactionMs = FVector2f(320.f, 60.f);

	UPROPERTY()
	float PeripheralReactionMul = 1.6f;

	UPROPERTY()
	float PartialExposureAcquireMul = 1.5f;

	UPROPERTY()
	float TrackLatencyMs = 150.f;

	UPROPERTY()
	uint32 Seed = 0;
};
