#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "GameplayTagContainer.h"

#include "VerseBotTypes.generated.h"

// Shared types of the bot brain (bot.md 5, 6). Units: Unreal cm, seconds, degrees.

/** The decision states of bot.md 5.1, in table order (Bot.State.* tags, same order). */
UENUM(BlueprintType)
enum class EVerseBotState : uint8
{
	Attack,
	Hold,
	Flank,
	StalkForFinisher,
	Retreat,
	Reload,
	DeployBulwark,
	Breach,
	Wallbang,
	Search
};

/** Hold substates (bot.md 5.2): Go -> Hide -> Peek -> Hide. */
UENUM(BlueprintType)
enum class EVerseBotHoldPhase : uint8
{
	Go,
	Hide,
	Peek
};

/** Peek types EQS_PeekCorner generates (bot.md 6.2). */
UENUM(BlueprintType)
enum class EVerseBotPeekType : uint8
{
	LeanLeft,
	LeanRight,
	CrouchRise,
	StepOut,
	JumpPeek
};

/** Belief states of bot.md 4.3 plus Dead (kill feed). */
UENUM(BlueprintType)
enum class EVerseBeliefState : uint8
{
	Known,
	Tracked,
	Rough,
	Lost,
	Dead
};

/** What AVerseBotController::GetPresentation returns: presentation and screenshots only. */
USTRUCT(BlueprintType)
struct VERSEBOT_API FVerseBotPresentation
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "Bot")
	EVerseBotState State = EVerseBotState::Search;

	/** The Bot.State.* tag of State (not reflected: VerseBot links no GameplayTags module of its own). */
	FGameplayTag StateTag;

	UPROPERTY(BlueprintReadOnly, Category = "Bot")
	EVerseBotHoldPhase HoldPhase = EVerseBotHoldPhase::Go;

	UPROPERTY(BlueprintReadOnly, Category = "Bot")
	bool bHasCoverSpot = false;

	/** World cm. */
	UPROPERTY(BlueprintReadOnly, Category = "Bot")
	FVector CoverSpot = FVector::ZeroVector;

	UPROPERTY(BlueprintReadOnly, Category = "Bot")
	bool bHasPeekPoint = false;

	/** World cm. */
	UPROPERTY(BlueprintReadOnly, Category = "Bot")
	FVector PeekPoint = FVector::ZeroVector;

	/** Believed opponent position (TopCluster centre), world cm. */
	UPROPERTY(BlueprintReadOnly, Category = "Bot")
	FVector BeliefTop = FVector::ZeroVector;

	UPROPERTY(BlueprintReadOnly, Category = "Bot")
	float Confidence = 0.f;
};

/** What a state wants this tick; the brain turns it into one FVerseInputFrame. */
struct VERSEBOT_API FVerseBotIntent
{
	bool bHasMoveTarget = false;
	/** World cm; the brain paths there through IVerseBotWorldQueries::FindPath. */
	FVector MoveTarget = FVector::ZeroVector;
	bool bHasLookTarget = false;
	/** World cm. */
	FVector LookTarget = FVector::ZeroVector;
	EVerseStance Stance = EVerseStance::Stand;
	/** -1 left, 0 none, 1 right. */
	int8 Lean = 0;
	bool bSprint = false;
	/** Walk instead of run (sound discipline, 8.3); crouch-walk is Stance Crouch plus bWalk. */
	bool bWalk = false;
	bool bSlide = false;
	bool bJump = false;
	bool bAds = false;
	/** The state wants to shoot at LookTarget; the fire gate decides (audit 8.10). */
	bool bWantFire = false;
	bool bReload = false;
	bool bMelee = false;
	/** GadgetA = Bulwark, GadgetB = breach charge (combat-state.md 2.2). */
	bool bGadgetA = false;
	bool bGadgetB = false;
	bool bSwitchSecondary = false;
	bool bSwitchPrimary = false;
	/** Strafe sign while attacking: -1, 0, 1 (pawn right). */
	int8 Strafe = 0;
};

namespace VerseBot
{
	inline constexpr float CmPerM = 100.f;
	inline constexpr int32 NumStates = 10;

	/** The Bot.State.* tag of a state. */
	VERSEBOT_API FGameplayTag StateTag(EVerseBotState State);

	/** Stable lower-case name for logs and reports. */
	VERSEBOT_API const TCHAR* StateName(EVerseBotState State);
}
