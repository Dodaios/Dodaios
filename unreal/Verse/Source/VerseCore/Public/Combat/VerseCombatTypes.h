#pragma once

#include "CoreMinimal.h"
#include "Engine/NetSerialization.h"
#include "GameplayTagContainer.h"

#include "VerseCombatTypes.generated.h"

// Shared combat enums and event structs (contracts/combat-state.md 11.1). The order of every
// enum entry and every struct field is frozen: replicated values, saved settings and the
// bridge codec depend on it. Verse.Contract.Combat.* tests pin both.

UENUM(BlueprintType)
enum class EVerseStance : uint8
{
	Stand,
	Crouch,
	Prone,
	Slide
};

UENUM(BlueprintType)
enum class EVerseHitZone : uint8
{
	None,
	Head,
	Neck,
	UpperTorso,
	LowerTorso,
	Arm,
	Leg
};

UENUM(BlueprintType)
enum class EVerseFireMode : uint8
{
	Semi,
	Burst,
	Auto
};

UENUM(BlueprintType)
enum class EVerseLoadoutSlot : uint8
{
	Primary,
	Secondary,
	Melee,
	GadgetA,
	GadgetB
};

UENUM(BlueprintType)
enum class EVerseCombatPhase : uint8
{
	Alive,
	Dead,
	FinisherAttacker,
	FinisherVictim
};

UENUM(BlueprintType)
enum class EVerseDamageSource : uint8
{
	Bolt,
	Melee,
	Finisher,
	Gadget,
	World
};

UENUM(BlueprintType)
enum class EVerseShotResult : uint8
{
	Miss,
	HitBody,
	HitPiece,
	Blocked,
	Rejected
};

UENUM(BlueprintType)
enum class EVerseFinisherPhase : uint8
{
	Locked,
	Takedown,
	Struggle,
	Kill,
	Recover,
	Aborted
};

UENUM(BlueprintType)
enum class EVerseGoreLevel : uint8
{
	Full,
	Reduced
};

UENUM(BlueprintType)
enum class EVerseGadgetEventKind : uint8
{
	Deploy,
	Destroyed,
	Expired,
	Plant,
	Detonate
};

UENUM(BlueprintType)
enum class EVerseSetOutcome : uint8
{
	Won,
	Lost,
	Unfinished
};

/** Bit flags in FVerseInputFrame::Buttons and ::Pressed. Values frozen (combat-state.md 11.1). */
UENUM(meta = (Bitflags, UseEnumValuesAsMaskValuesInEditor = "true"))
enum class EVerseInputButton : uint32
{
	None = 0,
	Fire = 0x00000001,
	Ads = 0x00000002,
	Reload = 0x00000004,
	Melee = 0x00000008,
	Jump = 0x00000010,
	Crouch = 0x00000020,
	Prone = 0x00000040,
	Sprint = 0x00000080,
	LeanLeft = 0x00000100,
	LeanRight = 0x00000200,
	GadgetA = 0x00000400,
	GadgetB = 0x00000800,
	SlotPrimary = 0x00001000,
	SlotSecondary = 0x00002000,
	SlotMelee = 0x00004000,
	Interact = 0x00008000
};
ENUM_CLASS_FLAGS(EVerseInputButton);

/** The one input path for persons, bots and harness models (bot.md B1). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseInputFrame
{
	GENERATED_BODY()

	/** -1..1, X forward, Y right (pawn space). */
	UPROPERTY()
	FVector2f Move = FVector2f::ZeroVector;

	/** Pitch, yaw added this tick, degrees. */
	UPROPERTY()
	FVector2f LookDeltaDeg = FVector2f::ZeroVector;

	/** EVerseInputButton bits held this tick. */
	UPROPERTY()
	uint32 Buttons = 0;

	/** Bits that went down this tick. */
	UPROPERTY()
	uint32 Pressed = 0;

	UPROPERTY()
	uint32 ServerTimeMs = 0;

	bool IsHeld(EVerseInputButton Button) const { return (Buttons & uint32(Button)) != 0; }
	bool WasPressed(EVerseInputButton Button) const { return (Pressed & uint32(Button)) != 0; }
};

USTRUCT(BlueprintType)
struct VERSECORE_API FVerseFireEvent
{
	GENERATED_BODY()

	/** Player state id. */
	UPROPERTY()
	int32 ShooterId = 0;

	UPROPERTY()
	FName WeaponId;

	UPROPERTY()
	uint16 ShotCounter = 0;

	UPROPERTY()
	uint32 Seed = 0;

	/** cm */
	UPROPERTY()
	FVector_NetQuantize10 Origin = FVector_NetQuantize10(0.0, 0.0, 0.0);

	UPROPERTY()
	FVector_NetQuantizeNormal Direction = FVector_NetQuantizeNormal(1.0, 0.0, 0.0);

	UPROPERTY()
	float ServerTime = 0.f;
};

USTRUCT(BlueprintType)
struct VERSECORE_API FVerseHitEvent
{
	GENERATED_BODY()

	FVerseHitEvent()
		: bHeadshot(0)
		, bKillingBlow(0)
		, bBlockedBySpawnProtection(0)
	{
	}

	UPROPERTY()
	int32 InstigatorId = 0;

	UPROPERTY()
	int32 VictimId = 0;

	UPROPERTY()
	FName WeaponId;

	UPROPERTY()
	EVerseDamageSource Source = EVerseDamageSource::Bolt;

	UPROPERTY()
	uint16 ShotCounter = 0;

	UPROPERTY()
	EVerseHitZone Zone = EVerseHitZone::None;

	UPROPERTY()
	FName Bone;

	/** cm */
	UPROPERTY()
	FVector_NetQuantize10 ImpactWorld = FVector_NetQuantize10(0.0, 0.0, 0.0);

	UPROPERTY()
	FVector_NetQuantize10 ImpactBoneLocal = FVector_NetQuantize10(0.0, 0.0, 0.0);

	UPROPERTY()
	FVector_NetQuantizeNormal Direction = FVector_NetQuantizeNormal(1.0, 0.0, 0.0);

	UPROPERTY()
	float DistanceM = 0.f;

	/** After all factors. */
	UPROPERTY()
	float Damage = 0.f;

	UPROPERTY()
	uint8 PenetrationCount = 0;

	UPROPERTY()
	uint8 bHeadshot : 1;

	UPROPERTY()
	uint8 bKillingBlow : 1;

	UPROPERTY()
	uint8 bBlockedBySpawnProtection : 1;

	UPROPERTY()
	float ServerTime = 0.f;
};

USTRUCT(BlueprintType)
struct VERSECORE_API FVersePenetrationEvent
{
	GENERATED_BODY()

	UPROPERTY()
	int32 ShooterId = 0;

	UPROPERTY()
	uint16 ShotCounter = 0;

	/** DA_PieceManifest index (destruction.md 8). */
	UPROPERTY()
	uint16 PieceIndex = 0;

	/** DA_PenetrationTable wire id (destruction.md 2). */
	UPROPERTY()
	uint8 MaterialWireId = 0;

	UPROPERTY()
	FVector_NetQuantize10 Entry = FVector_NetQuantize10(0.0, 0.0, 0.0);

	UPROPERTY()
	FVector_NetQuantize10 Exit = FVector_NetQuantize10(0.0, 0.0, 0.0);

	UPROPERTY()
	float ThicknessCm = 0.f;

	UPROPERTY()
	float PowerBefore = 0.f;

	UPROPERTY()
	float PowerAfter = 0.f;

	UPROPERTY()
	float DamageFactorAfter = 1.f;

	UPROPERTY()
	bool bPassed = false;
};

USTRUCT(BlueprintType)
struct VERSECORE_API FVerseDeathEvent
{
	GENERATED_BODY()

	UPROPERTY()
	int32 VictimId = 0;

	UPROPERTY()
	int32 KillerId = 0;

	UPROPERTY()
	EVerseDamageSource Cause = EVerseDamageSource::Bolt;

	UPROPERTY()
	FName WeaponId;

	UPROPERTY()
	EVerseHitZone LastZone = EVerseHitZone::None;

	UPROPERTY()
	float ServerTime = 0.f;

	UPROPERTY()
	float RespawnAt = 0.f;
};

USTRUCT(BlueprintType)
struct VERSECORE_API FVerseFinisherEvent
{
	GENERATED_BODY()

	UPROPERTY()
	int32 AttackerId = 0;

	UPROPERTY()
	int32 VictimId = 0;

	UPROPERTY()
	EVerseFinisherPhase Phase = EVerseFinisherPhase::Locked;

	/** Phases derive from this plus the fixed offsets of combat-state.md 7.4. */
	UPROPERTY()
	float SequenceStartServerTime = 0.f;

	UPROPERTY()
	FTransform WarpTarget = FTransform::Identity;
};

/** Declared in architecture.md; fields frozen in combat-state.md 11.1. Server only. */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseNoiseEvent
{
	GENERATED_BODY()

	/** One Noise.* tag of bot.md 3.2, the DA_Audibility row key. */
	UPROPERTY()
	FGameplayTag Noise;

	/** Player state id, -1 = world (pieces, drones). */
	UPROPERTY()
	int32 SourceId = 0;

	/** True position; the bot's perception adds error. */
	UPROPERTY()
	FVector Location = FVector::ZeroVector;

	/** destruction.md 6.2 loudness for Noise.Fracture and Noise.Drone, else 1. */
	UPROPERTY()
	float Loudness = 1.f;

	UPROPERTY()
	float ServerTime = 0.f;
};

USTRUCT(BlueprintType)
struct VERSECORE_API FVerseReloadEvent
{
	GENERATED_BODY()

	UPROPERTY()
	int32 PlayerId = 0;

	UPROPERTY()
	FName WeaponId;

	/** A round was chambered. */
	UPROPERTY()
	bool bTactical = true;

	UPROPERTY()
	float StartServerTime = 0.f;

	UPROPERTY()
	float EndServerTime = 0.f;

	UPROPERTY()
	bool bCancelled = false;
};

USTRUCT(BlueprintType)
struct VERSECORE_API FVerseGadgetEvent
{
	GENERATED_BODY()

	UPROPERTY()
	EVerseGadgetEventKind Kind = EVerseGadgetEventKind::Deploy;

	UPROPERTY()
	FName GadgetId;

	UPROPERTY()
	int32 OwnerId = 0;

	UPROPERTY()
	FVector_NetQuantize10 Location = FVector_NetQuantize10(0.0, 0.0, 0.0);

	UPROPERTY()
	float ServerTime = 0.f;
};

/** Raised by VerseDecks (hangar day/arena switch). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseArenaSwitchEvent
{
	GENERATED_BODY()

	UPROPERTY()
	bool bArenaOn = false;

	/** "hangar" */
	UPROPERTY()
	FName Deck;

	UPROPERTY()
	float ServerTime = 0.f;
};

/** Raised by VerseDecks stations; VerseUI opens the matching view. */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseStationUsedEvent
{
	GENERATED_BODY()

	UPROPERTY()
	FName StationId;

	/** Station kind (parity S-01), e.g. "armoury". */
	UPROPERTY()
	FName Kind;

	/** Player state id. */
	UPROPERTY()
	int32 UserId = 0;
};

/** One player's numbers in one set. */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseSetLine
{
	GENERATED_BODY()

	UPROPERTY()
	int32 PlayerId = 0;

	UPROPERTY()
	bool bIsBot = false;

	UPROPERTY()
	int32 Kills = 0;

	UPROPERTY()
	int32 Deaths = 0;

	UPROPERTY()
	int32 Headshots = 0;

	UPROPERTY()
	int32 Finishers = 0;

	UPROPERTY()
	int32 MeleeKills = 0;

	UPROPERTY()
	int32 ShotsFired = 0;

	UPROPERTY()
	int32 ShotsHit = 0;

	UPROPERTY()
	int32 DamageDealt = 0;

	UPROPERTY()
	int32 DamageTaken = 0;

	UPROPERTY()
	int32 WallsBreached = 0;

	UPROPERTY()
	int32 BulwarksPlaced = 0;

	UPROPERTY()
	int32 BestStreak = 0;

	/** Weapon id -> (kills, headshots, shots fired, shots hit). */
	UPROPERTY()
	TMap<FName, FIntVector4> PerWeapon;
};

/** Payload of duel.result (bridge-protocol.md 10), one per set (combat-state.md 9.1). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseSetSummary
{
	GENERATED_BODY()

	/** Unique per set result, idempotency key. */
	UPROPERTY()
	FString MatchId;

	/** One arena session. */
	UPROPERTY()
	FString SessionId;

	/** 1-based index of the set in its session. */
	UPROPERTY()
	int32 SetIndex = 0;

	/** "endless/1" */
	UPROPERTY()
	FName RulesetId;

	/** As AVersePlayerState::BotTier. */
	UPROPERTY()
	FName BotTier;

	/** From the person's side. */
	UPROPERTY()
	EVerseSetOutcome Outcome = EVerseSetOutcome::Unfinished;

	UPROPERTY()
	double StartedAtUnix = 0.0;

	UPROPERTY()
	double EndedAtUnix = 0.0;

	/** Paused time excluded. */
	UPROPERTY()
	float MatchTimeS = 0.f;

	UPROPERTY()
	FVerseSetLine Person;

	UPROPERTY()
	FVerseSetLine Opponent;
};
