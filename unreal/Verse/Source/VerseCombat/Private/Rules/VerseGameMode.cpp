#include "Rules/VerseGameMode.h"

#include "Damage/VerseCombatStateComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Controller.h"
#include "GameFramework/GameStateBase.h"
#include "GameFramework/Pawn.h"
#include "Misc/FileHelper.h"
#include "Rules/VersePlayerState.h"
#include "Rules/VerseRulesetConfig.h"
#include "Rules/VerseRuleset_Deathmatch.h"
#include "Rules/VerseSpawnPoint.h"
#include "VerseCollision.h"
#include "VerseLog.h"

AVerseGameMode::AVerseGameMode()
{
	PlayerStateClass = AVersePlayerState::StaticClass();
	PrimaryActorTick.bCanEverTick = false;
}

const UVerseRulesetConfig* AVerseGameMode::ResolveConfig()
{
	if (!RulesetConfig)
	{
		RulesetConfig = NewObject<UVerseRulesetConfig>(this, TEXT("RulesetConfig_Deathmatch"));
		RulesetConfig->RulesetClass = UVerseRuleset_Deathmatch::StaticClass();
		const FString Path = UVerseRulesetConfig::RulesFilePath(TEXT("deathmatch"));
		FString Text;
		FString Error;
		if (!FFileHelper::LoadFileToString(Text, *Path))
		{
			UE_LOG(LogVerseCombat, Warning, TEXT("Rules: %s not found, using the built-in start values"), *Path);
		}
		else if (!RulesetConfig->ApplyJson(Text, Error))
		{
			UE_LOG(LogVerseCombat, Error, TEXT("Rules: %s: %s; using the built-in start values"), *Path, *Error);
			RulesetConfig = NewObject<UVerseRulesetConfig>(this, TEXT("RulesetConfig_Defaults"));
			RulesetConfig->RulesetClass = UVerseRuleset_Deathmatch::StaticClass();
		}
	}
	return RulesetConfig;
}

void AVerseGameMode::CreateRuleset()
{
	const UVerseRulesetConfig* Config = ResolveConfig();
	TSubclassOf<UVerseRuleset> Class = Config && Config->RulesetClass ? Config->RulesetClass : TSubclassOf<UVerseRuleset>(UVerseRuleset_Deathmatch::StaticClass());
	Ruleset = NewObject<UVerseRuleset>(this, Class);
	Ruleset->SetHost(MakeDefaultHost());
	Ruleset->Init(this, Config);
}

void AVerseGameMode::InitGame(const FString& MapName, const FString& Options, FString& ErrorMessage)
{
	Super::InitGame(MapName, Options, ErrorMessage);
	CreateRuleset();
}

void AVerseGameMode::BeginPlay()
{
	Super::BeginPlay();
	if (!Ruleset)
	{
		CreateRuleset();
	}
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		ArenaHandle = Hub->OnArenaSwitch.AddUObject(this, &AVerseGameMode::HandleArenaSwitch);
		DeathHandle = Hub->OnDeath.AddUObject(this, &AVerseGameMode::HandleDeath);
	}
}

void AVerseGameMode::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	// Verse quitting mid-set sends the running set as unfinished (9.1 Leaving).
	if (UVerseRuleset_Deathmatch* Deathmatch = Cast<UVerseRuleset_Deathmatch>(Ruleset))
	{
		Deathmatch->EndMatch();
	}
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnArenaSwitch.Remove(ArenaHandle);
		Hub->OnDeath.Remove(DeathHandle);
	}
	Super::EndPlay(EndPlayReason);
}

void AVerseGameMode::HandleArenaSwitch(const FVerseArenaSwitchEvent& E)
{
	if (Ruleset && E.bArenaOn)
	{
		Ruleset->OnMatchStart();
	}
}

void AVerseGameMode::HandleDeath(const FVerseDeathEvent& E)
{
	if (Ruleset)
	{
		Ruleset->OnKill(E);
	}
}

AActor* AVerseGameMode::ChoosePlayerStart_Implementation(AController* Player)
{
	const UVerseRuleset_Deathmatch* Deathmatch = Cast<UVerseRuleset_Deathmatch>(Ruleset);
	if (Ruleset && Player && (!Deathmatch || Deathmatch->IsMatchRunning()))
	{
		if (AVerseSpawnPoint* Spawn = Ruleset->ChooseSpawn(Player->GetPlayerState<AVersePlayerState>()))
		{
			return Spawn;
		}
	}
	return Super::ChoosePlayerStart_Implementation(Player);
}

bool AVerseGameMode::CanDamage(const FVerseDamageContext& Ctx) const
{
	return Ruleset ? Ruleset->CanDamage(Ctx) : true;
}

float AVerseGameMode::ModifyDamage(const FVerseDamageContext& Ctx, float Damage) const
{
	return Ruleset ? Ruleset->ModifyDamage(Ctx, Damage) : Damage;
}

void AVerseGameMode::NotifyPlayerAction(AVersePlayerState* Player, EVersePlayerAction Action)
{
	if (Ruleset)
	{
		Ruleset->OnPlayerAction(Player, Action);
	}
}

void AVerseGameMode::GetLoadout(const AVersePlayerState* Player, TMap<EVerseLoadoutSlot, const UPrimaryDataAsset*>& Out) const
{
	Out.Reset();
	if (Ruleset)
	{
		Ruleset->GetLoadout(Player, Out);
	}
}

FVerseRulesHost AVerseGameMode::MakeDefaultHost()
{
	FVerseRulesHost Host;
	TWeakObjectPtr<AVerseGameMode> Self(this);
	Host.ServerTime = [Self]() { return Self.IsValid() && Self->GetWorld() ? Self->GetWorld()->GetTimeSeconds() : 0.f; };
	Host.Players = [Self]() {
		TArray<AVersePlayerState*> Out;
		const AGameStateBase* State = Self.IsValid() ? Self->GameState.Get() : nullptr;
		if (State)
		{
			for (APlayerState* P : State->PlayerArray)
			{
				if (AVersePlayerState* V = Cast<AVersePlayerState>(P))
				{
					Out.Add(V);
				}
			}
		}
		return Out;
	};
	Host.SpawnPoints = [Self]() {
		TArray<AVerseSpawnPoint*> Out;
		if (UWorld* World = Self.IsValid() ? Self->GetWorld() : nullptr)
		{
			for (TActorIterator<AVerseSpawnPoint> It(World); It; ++It)
			{
				Out.Add(*It);
			}
		}
		return Out;
	};
	Host.SpawnFloor = [](const AVerseSpawnPoint* S) { return S->GetFloorLocation(); };
	Host.EyePoint = [](const AVersePlayerState* P, FVector& OutEye) {
		const APawn* Pawn = P ? P->GetPawn() : nullptr;
		if (!Pawn)
		{
			return false;
		}
		FRotator Rotation;
		Pawn->GetActorEyesViewPoint(OutEye, Rotation);
		return true;
	};
	Host.LineClear = [Self](const FVector& A, const FVector& B) {
		UWorld* World = Self.IsValid() ? Self->GetWorld() : nullptr;
		if (!World)
		{
			return true;
		}
		// Pawns never hide a spawn: only world geometry and the current piece proxies do.
		FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseSpawnSight), false);
		for (TActorIterator<APawn> It(World); It; ++It)
		{
			Params.AddIgnoredActor(*It);
		}
		return !World->LineTraceTestByChannel(A, B, VerseCollision::Bolt, Params);
	};
	// VerseCombat has no NavigationSystem edge in the module DAG (architecture 2), so the
	// default is "no path" and selection uses the Euclidean distance (9.2 fallback). The
	// integration step sets a navmesh path-length function here (arena.md, open items).
	Host.PathLength = [](const FVector&, const FVector&) { return -1.f; };
	Host.PawnNear = [Self](const FVector& Floor, float RadiusCm, const AVersePlayerState* Ignore) {
		UWorld* World = Self.IsValid() ? Self->GetWorld() : nullptr;
		if (!World)
		{
			return false;
		}
		for (TActorIterator<APawn> It(World); It; ++It)
		{
			if (Ignore && It->GetPlayerState() == Ignore)
			{
				continue;
			}
			if (FVector::Dist2D(It->GetActorLocation(), Floor) <= RadiusCm && FMath::Abs(It->GetActorLocation().Z - Floor.Z) <= 300.0)
			{
				return true;
			}
		}
		return false;
	};
	Host.Respawn = [Self](AVersePlayerState* P, AVerseSpawnPoint* Spawn) {
		AController* Controller = P ? P->GetOwningController() : nullptr;
		if (!Self.IsValid() || !Controller)
		{
			return;
		}
		if (APawn* Old = Controller->GetPawn())
		{
			// The body stays for the kill cam and gore, then goes.
			Controller->UnPossess();
			Old->SetLifeSpan(10.f);
		}
		if (Spawn)
		{
			Self->RestartPlayerAtPlayerStart(Controller, Spawn);
		}
		else
		{
			Self->RestartPlayer(Controller);
		}
	};
	Host.CombatState = [](const AVersePlayerState* P) -> UVerseCombatStateComponent* {
		const APawn* Pawn = P ? P->GetPawn() : nullptr;
		return Pawn ? Pawn->FindComponentByClass<UVerseCombatStateComponent>() : nullptr;
	};
	return Host;
}
