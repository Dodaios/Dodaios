#include "Controller/VerseBotController.h"

#include "Bot/VerseBotAdaptiveConfig.h"
#include "Bot/VerseBotTier.h"
#include "Brain/VerseBotBrainCore.h"
#include "Controller/VerseBotEngineQueries.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerState.h"
#include "Kismet/GameplayStatics.h"
#include "Learning/VerseBotMatchMemory.h"
#include "UObject/UnrealType.h"
#include "VerseLog.h"

namespace
{
	const FName BotTierField(TEXT("BotTier"));
	const FName BotSkillField(TEXT("BotEffectiveSkill"));

	float SkillOf(FName TierId)
	{
		if (TierId == TEXT("elite")) return 1.f;
		if (TierId == TEXT("hard")) return 0.5f;
		return 0.f;
	}
}

AVerseBotController::AVerseBotController()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.bStartWithTickEnabled = true;
}

AVerseBotController::~AVerseBotController() = default;

FName AVerseBotController::ParseBotTierOption(const FString& Options)
{
	const FString Value = UGameplayStatics::ParseOption(Options, TEXT("BotTier")).ToLower();
	if (Value == TEXT("normal") || Value == TEXT("hard") || Value == TEXT("elite") || Value == TEXT("adaptive"))
	{
		return FName(*Value);
	}
	return NAME_None;
}

bool AVerseBotController::WriteBotIdentity(const UStruct* Type, void* Container, FName InTier, float InSkill)
{
	if (!Type || !Container)
	{
		return false;
	}
	FNameProperty* TierProp = FindFProperty<FNameProperty>(Type, BotTierField);
	FFloatProperty* SkillProp = FindFProperty<FFloatProperty>(Type, BotSkillField);
	if (!TierProp || !SkillProp)
	{
		return false;
	}
	TierProp->SetPropertyValue_InContainer(Container, InTier);
	SkillProp->SetPropertyValue_InContainer(Container, InSkill);
	return true;
}

void AVerseBotController::EnsureBrain()
{
	if (!MatchMemory)
	{
		MatchMemory = NewObject<UVerseBotMatchMemory>(this);
	}
	if (!DefaultQueries)
	{
		DefaultQueries = MakeUnique<FVerseBotEngineQueries>(*this);
	}
	if (!Brain)
	{
		Brain = MakeUnique<FVerseBotBrainCore>();
		Brain->UseMemory(MatchMemory->Get());
	}
}

const UVerseBotTier* AVerseBotController::EffectiveTier()
{
	if (!Tier)
	{
		// Default: the hard tier's start values (README: the bot is much stronger than a person).
		UVerseBotTier* Hard = NewObject<UVerseBotTier>(this);
		UVerseBotTier::ApplyStartValues(TEXT("hard"), *Hard);
		Tier = Hard;
	}
	if (!bAdaptive)
	{
		return Tier;
	}
	// Adaptive: interpolate normal / hard / elite at s (9.2).
	UVerseBotTier* Normal = NewObject<UVerseBotTier>(this);
	UVerseBotTier* Hard = NewObject<UVerseBotTier>(this);
	UVerseBotTier* Elite = NewObject<UVerseBotTier>(this);
	UVerseBotTier::ApplyStartValues(TEXT("normal"), *Normal);
	UVerseBotTier::ApplyStartValues(TEXT("hard"), *Hard);
	UVerseBotTier::ApplyStartValues(TEXT("elite"), *Elite);
	if (!InterpolatedTier)
	{
		InterpolatedTier = NewObject<UVerseBotTier>(this);
	}
	UVerseBotAdaptiveConfig::InterpolateTier(*Normal, *Hard, *Elite, EffectiveSkill, *InterpolatedTier);
	return InterpolatedTier;
}

void AVerseBotController::SetTier(const UVerseBotTier* InTier)
{
	const bool bChanged = InTier != Tier;
	Tier = InTier;
	if (!bAdaptive && Tier)
	{
		EffectiveSkill = SkillOf(Tier->TierId);
	}
	if (bChanged)
	{
		ResetMatch();
	}
	WriteIdentity();
}

void AVerseBotController::SetAdaptive(bool bInAdaptive)
{
	if (bInAdaptive == bAdaptive)
	{
		return;
	}
	bAdaptive = bInAdaptive;
	if (bAdaptive)
	{
		EffectiveSkill = GetDefault<UVerseBotAdaptiveConfig>()->StartSkill;
	}
	else if (Tier)
	{
		EffectiveSkill = SkillOf(Tier->TierId);
	}
	ResetMatch();
	WriteIdentity();
}

void AVerseBotController::SetPendingSkill(float S)
{
	PendingSkill = FMath::Clamp(S, 0.f, 1.f);
}

FVerseBotPresentation AVerseBotController::GetPresentation() const
{
	return Brain ? Brain->GetPresentation() : FVerseBotPresentation();
}

void AVerseBotController::ReceivePerceptFrame(const FVersePerceptFrame& Frame)
{
	PendingFrame = Frame;
	bHasFrame = true;
}

void AVerseBotController::ResetMatch()
{
	EnsureBrain();
	const UVerseBotTier* T = EffectiveTier();
	FVerseBotBrainCore::FConfig Config;
	Seed = FixedSeed != 0 ? FixedSeed : FVerseRng::Mix(uint64(GetUniqueID()) ^ (uint64(FPlatformTime::Cycles64()) << 1));
	Config.Seed = Seed;
	Config.SelfId = PlayerState ? PlayerState->GetPlayerId() : 0;
	MatchMemory->ResetMatch();
	Brain->Init(*T, Config);
	Brain->UseMemory(MatchMemory->Get());
	bBrainReady = true;
}

FVersePerceptFrame AVerseBotController::SelfOnlyFrame() const
{
	// The own HUD only (3.3): no opponent percepts without the perception service.
	FVersePerceptFrame F;
	F.ServerTimeMs = uint32(FMath::Max(ServerTimeS, 0.f) * 1000.f);
	if (const APawn* P = GetPawn())
	{
		F.Self.Location = P->GetActorLocation();
		F.Self.Velocity = P->GetVelocity();
		F.Self.EyeLocation = P->GetPawnViewLocation();
		F.Self.ViewRotation = GetControlRotation();
		F.Self.Health = 100.f;
		F.Self.MaxHealth = 100.f;
		F.Self.Magazine = 30;
		F.Self.bChambered = true;
		F.Self.Reserve = 90;
		F.Self.Phase = EVerseCombatPhase::Alive;
	}
	else
	{
		F.Self.Phase = EVerseCombatPhase::Dead;
	}
	return F;
}

void AVerseBotController::ApplyInput(const FVerseInputFrame& Frame)
{
	LastInput = Frame;
	FRotator Control = GetControlRotation();
	Control.Pitch = FMath::ClampAngle(Control.Pitch + Frame.LookDeltaDeg.X, -89.f, 89.f);
	Control.Yaw = FRotator::NormalizeAxis(Control.Yaw + Frame.LookDeltaDeg.Y);
	SetControlRotation(Control);
	if (APawn* P = GetPawn())
	{
		const FRotator YawOnly(0.f, Control.Yaw, 0.f);
		const FVector Forward = YawOnly.Vector();
		const FVector Right = FRotationMatrix(YawOnly).GetUnitAxis(EAxis::Y);
		P->AddMovementInput(Forward, Frame.Move.X);
		P->AddMovementInput(Right, Frame.Move.Y);
	}
	OnInputFrame.Broadcast(Frame);
}

void AVerseBotController::WriteIdentity()
{
	if (!PlayerState)
	{
		return;
	}
	const FName TierName = bAdaptive ? FName(TEXT("adaptive")) : (Tier ? Tier->TierId : FName(TEXT("hard")));
	WriteBotIdentity(PlayerState->GetClass(), PlayerState, TierName, EffectiveSkill);
}

void AVerseBotController::PostInitializeComponents()
{
	Super::PostInitializeComponents();
	// A bot is a player: it gets an ordinary player state on the server (B1).
	if (HasAuthority() && GetWorld() && GetWorld()->IsGameWorld() && !PlayerState)
	{
		InitPlayerState();
	}
}

void AVerseBotController::OnPossess(APawn* InPawn)
{
	Super::OnPossess(InPawn);
	if (!bBrainReady)
	{
		ResetMatch();
	}
	// Adaptive s is applied at the bot's respawn only (9.2).
	if (bAdaptive && PendingSkill >= 0.f && Brain)
	{
		EffectiveSkill = PendingSkill;
		PendingSkill = -1.f;
		Brain->SetTier(*EffectiveTier());
	}
	WriteIdentity();
}

void AVerseBotController::OnUnPossess()
{
	Super::OnUnPossess();
}

void AVerseBotController::EndPlay(const EEndPlayReason::Type Reason)
{
	// Verse.exe exit or level change: the match memory is dropped (7.3, B8).
	if (MatchMemory)
	{
		MatchMemory->ResetMatch();
	}
	Brain.Reset();
	bBrainReady = false;
	Super::EndPlay(Reason);
}

void AVerseBotController::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!HasAuthority())
	{
		return;
	}
	if (!bBrainReady)
	{
		ResetMatch();
	}
	ServerTimeS += DeltaSeconds;
	const FVersePerceptFrame Frame = bHasFrame ? PendingFrame : SelfOnlyFrame();
	bHasFrame = false;
	IVerseBotWorldQueries& Queries = QueriesOverride ? *QueriesOverride : *DefaultQueries;
	const FVerseInputFrame Input = Brain->Think(Frame, Queries);
	if (GetPawn())
	{
		ApplyInput(Input);
	}
}
