#include "Controller/VerseBotController.h"

#include "Bot/VerseBotAdaptiveConfig.h"
#include "Bot/VerseBotTier.h"
#include "Brain/VerseBotBrainCore.h"
#include "Brain/VerseBotGridBelief.h"
#include "Controller/VerseBotArenaData.h"
#include "Belief/VerseBeliefDebugDraw.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Controller/VerseBotEngineQueries.h"
#include "Engine/World.h"
#include "GameFramework/GameStateBase.h"
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
	/** Match seconds between two health lines of a bot. */
	constexpr float DiagnosticPeriodS = 30.f;

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
	LastRealFrame = Frame;
	bHasRealFrame = true;
}

void AVerseBotController::AttachArena()
{
	UWorld* World = GetWorld();
	if (bArenaAttached || !World || !Brain || !DefaultQueries)
	{
		return;
	}
	IVerseBotWorldQueries& Queries = QueriesOverride ? *QueriesOverride : *DefaultQueries;
	GridBelief = FVerseBotArenaData::AttachTo(*World, *Brain, *static_cast<FVerseBotEngineQueries*>(DefaultQueries.Get()), Queries,
		PlayerState ? PlayerState->GetPlayerId() : INDEX_NONE);
	if (!GridBelief)
	{
		return;
	}
	bArenaAttached = true;
	FParse::Value(FCommandLine::Get(), TEXT("VerseBotBeliefPng="), BeliefPngDir);
	UE_LOG(LogVerseBot, Log, TEXT("[VerseBot] %s: belief grid attached (%d cells)"), *GetName(), GridBelief->GetMap().GetGrid().NumCells());
}

void AVerseBotController::LogDiagnostics(const FVersePerceptFrame& Frame, const FVerseInputFrame& Input)
{
	++DiagFrames;
	DiagSightFrames += Frame.Sightings.ContainsByPredicate([](const FVerseSightPercept& S) { return S.VisibleMask != 0; }) ? 1 : 0;
	DiagHeardFrames += Frame.Heard.Num() > 0 ? 1 : 0;
	DiagFireFrames += (Input.Buttons & uint32(EVerseInputButton::Fire)) != 0 ? 1 : 0;
	const float NowS = float(Frame.ServerTimeMs) / 1000.f;
	if (NowS < NextDiagnosticS)
	{
		return;
	}
	NextDiagnosticS = NowS + (BeliefPngDir.IsEmpty() ? DiagnosticPeriodS : 5.f);
	const FVerseBotPresentation P = Brain->GetPresentation();
	const APawn* Own = GetPawn();
	UE_LOG(LogVerseBot, Log,
		TEXT("[VerseBot] %s t=%.0f s: state %s, belief %s conf %.2f at %s, at %s, frames %d (sight %d, heard %d, fire %d; want %d, unclassified %d, unaimed %d), grid %d"),
		*GetName(), NowS, *P.StateTag.ToString(), *UEnum::GetValueAsString(Brain->GetBelief().Summary().State), P.Confidence,
		*P.BeliefTop.ToCompactString(), Own ? *Own->GetActorLocation().ToCompactString() : TEXT("-"), DiagFrames, DiagSightFrames,
		DiagHeardFrames, DiagFireFrames, Brain->FireWantTicks, Brain->FireUnclassifiedTicks, Brain->FireUnaimedTicks, bArenaAttached ? 1 : 0);
	Brain->FireWantTicks = Brain->FireUnclassifiedTicks = Brain->FireUnaimedTicks = 0;
	DiagFrames = DiagSightFrames = DiagHeardFrames = DiagFireFrames = 0;
	if (GridBelief && !BeliefPngDir.IsEmpty())
	{
		const FVector Marks[] = {Own ? Own->GetActorLocation() : FVector::ZeroVector};
		for (const EVerseArenaLevel Level : {EVerseArenaLevel::Floor, EVerseArenaLevel::Upper})
		{
			const FString Path = FPaths::Combine(BeliefPngDir, FString::Printf(TEXT("%s_%04d_L%d.png"), *GetName(), int32(NowS), int32(Level)));
			FVerseBeliefDebugDraw::SavePng(Path, GridBelief->GetMap().GetGrid(), GridBelief->GetMap().GetDerived(), Level, 4, Marks);
		}
	}
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

uint32 AVerseBotController::WorldServerTimeMs() const
{
	const UWorld* World = GetWorld();
	if (!World)
	{
		return LastThinkMs;
	}
	const AGameStateBase* GameState = World->GetGameState();
	const double Seconds = GameState ? GameState->GetServerWorldTimeSeconds() : World->GetTimeSeconds();
	return uint32(FMath::Max(Seconds, 0.0) * 1000.0);
}

FVersePerceptFrame AVerseBotController::SelfRefreshedFrame(uint32 ServerTimeMs) const
{
	// The own HUD of the last service frame (3.3) with the own pose refreshed; no percepts, so
	// nothing new about the opponent and no stimulus is replayed.
	FVersePerceptFrame F;
	F.ServerTimeMs = ServerTimeMs;
	F.Self = LastRealFrame.Self;
	if (const APawn* P = GetPawn())
	{
		F.Self.Location = P->GetActorLocation();
		F.Self.Velocity = P->GetVelocity();
		F.Self.EyeLocation = P->GetPawnViewLocation();
		F.Self.ViewRotation = GetControlRotation();
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
	GridBelief = nullptr;
	bArenaAttached = false;
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
	// Without any service frame the bot has no HUD to act on (health, magazine): it waits.
	if (!bHasRealFrame)
	{
		return;
	}
	FVersePerceptFrame Frame = bHasFrame ? PendingFrame : SelfRefreshedFrame(WorldServerTimeMs());
	bHasFrame = false;
	// One monotonic clock for the brain: a frame never moves time backward.
	Frame.ServerTimeMs = FMath::Max(Frame.ServerTimeMs, LastThinkMs);
	LastThinkMs = Frame.ServerTimeMs;
	AttachArena();
	IVerseBotWorldQueries& Queries = QueriesOverride ? *QueriesOverride : *DefaultQueries;
	const FVerseInputFrame Input = Brain->Think(Frame, Queries);
	if (GetPawn())
	{
		ApplyInput(Input);
	}
	LogDiagnostics(Frame, Input);
}
