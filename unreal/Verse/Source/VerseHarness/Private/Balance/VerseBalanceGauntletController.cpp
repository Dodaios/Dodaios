#include "Balance/VerseBalanceGauntletController.h"

#include "Balance/VerseModelController.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/GameModeBase.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerState.h"
#include "HAL/PlatformMemory.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformTime.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "UObject/UObjectGlobals.h"
#include "VerseHarnessJson.h"
#include "VerseLog.h"

namespace VerseBalancePrivate
{
	/** The bot controller class of VerseBot (WP08), found by name so the harness builds before it. */
	const TCHAR* BotControllerPath = TEXT("/Script/VerseBot.VerseBotController");

	void AppendLine(const FString& File, const FString& Line)
	{
		FFileHelper::SaveStringToFile(Line + TEXT("\n"), *File, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,
			&IFileManager::Get(), FILEWRITE_Append);
	}
}

double UVerseBalanceGauntletController::Now() const
{
	const UWorld* W = World.Get();
	return W ? W->GetTimeSeconds() : 0.0;
}

bool UVerseBalanceGauntletController::Start(UWorld* InWorld, const FVerseHarnessScenario& InScenario, FString& OutError)
{
	World = InWorld;
	Scenario = InScenario;
	if (!InWorld)
	{
		OutError = TEXT("no game world");
		return false;
	}
	if (!FVersePersonModelSet::LoadDefault(PersonModels, OutError))
	{
		return false;
	}
	IFileManager::Get().MakeDirectory(*Scenario.OutputDir, true);
	BoutsFile = FPaths::Combine(Scenario.OutputDir, TEXT("bouts.jsonl"));
	IFileManager::Get().Delete(*BoutsFile, false, true, true);

	if (UVerseEventHub* Hub = UVerseEventHub::Get(InWorld))
	{
		HubHandles.Add(Hub->OnFire.AddUObject(this, &UVerseBalanceGauntletController::HandleFire));
		HubHandles.Add(Hub->OnHit.AddUObject(this, &UVerseBalanceGauntletController::HandleHit));
		HubHandles.Add(Hub->OnDeath.AddUObject(this, &UVerseBalanceGauntletController::HandleDeath));
		HubHandles.Add(Hub->OnReload.AddUObject(this, &UVerseBalanceGauntletController::HandleReload));
		HubHandles.Add(Hub->OnGadget.AddUObject(this, &UVerseBalanceGauntletController::HandleGadget));
	}
	else
	{
		UE_LOG(LogVerseHarness, Warning, TEXT("[VerseHarness] no UVerseEventHub in the world; bouts will hold no combat"));
	}
	BotControllerKind = FindObject<UClass>(nullptr, VerseBalancePrivate::BotControllerPath) ? TEXT("VerseBotController")
	                                                                                        : TEXT("null-brain stand-in");
	WallStartS = FPlatformTime::Seconds();
	StartupS = WallStartS - GStartTime;
	SimStartS = Now();
	UE_LOG(LogVerseHarness, Display, TEXT("[VerseHarness] run %s job %d: %d units, bot slots: %s"), *Scenario.Run,
		Scenario.Job, Scenario.Units.Num(), *BotControllerKind);
	BeginUnit();
	return true;
}

AController* UVerseBalanceGauntletController::SpawnSlot(const FVerseHarnessSlot& Slot, uint32 SlotSeed)
{
	UWorld* W = World.Get();
	if (!W)
	{
		return nullptr;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AController* Controller = nullptr;
	if (Slot.IsBot())
	{
		if (UClass* BotClass = FindObject<UClass>(nullptr, VerseBalancePrivate::BotControllerPath))
		{
			Controller = W->SpawnActor<AController>(BotClass, Params);
		}
	}
	if (!Controller)
	{
		AVerseModelController* Model = W->SpawnActor<AVerseModelController>(Params);
		FVersePersonModel Person;
		if (const FVersePersonModel* Found = PersonModels.Models.Find(Slot.Model))
		{
			Person = *Found;
		}
		else
		{
			Person.Name = Slot.Tier;
		}
		FVerseTrickConfig Trick;
		if (const FVerseTrickConfig* Found = PersonModels.Tricks.Find(Slot.Trick))
		{
			Trick = *Found;
		}
		Model->Configure(Person, Trick, SlotSeed);
		Controller = Model;
	}
	if (AGameModeBase* Mode = W->GetAuthGameMode())
	{
		Mode->RestartPlayer(Controller);
	}
	return Controller;
}

void UVerseBalanceGauntletController::ClearSlots()
{
	for (const TWeakObjectPtr<AController>& Weak : Slots)
	{
		if (AController* Controller = Weak.Get())
		{
			if (APawn* Pawn = Controller->GetPawn())
			{
				Pawn->Destroy();
			}
			Controller->Destroy();
		}
	}
	Slots.Reset();
}

int32 UVerseBalanceGauntletController::PlayerIdOf(const AController* Controller) const
{
	return Controller && Controller->PlayerState ? Controller->PlayerState->GetPlayerId() : INDEX_NONE;
}

void UVerseBalanceGauntletController::BeginUnit()
{
	++UnitIndex;
	BoutIndex = 0;
	MatchTimeS = 0.0;
	AdaptiveTrace.Reset();
	ClearSlots();
	if (!Scenario.Units.IsValidIndex(UnitIndex))
	{
		Finish(TEXT("all units played"));
		return;
	}
	// A fresh pair of controllers per match: nothing learnt carries over (bot.md 7.3, BG9).
	const FVerseHarnessUnit& Unit = Scenario.Units[UnitIndex];
	Slots.Add(SpawnSlot(Unit.A, FVerseRng::Hash(Unit.Seed, 0xA, 0)));
	Slots.Add(SpawnSlot(Unit.B, FVerseRng::Hash(Unit.Seed, 0xB, 0)));
	BeginBout();
}

void UVerseBalanceGauntletController::BeginBout()
{
	const FVerseHarnessUnit& Unit = Scenario.Units[UnitIndex];
	BoutStartS = Now();
	const int32 IdA = PlayerIdOf(Slots[0].Get());
	const int32 IdB = PlayerIdOf(Slots[1].Get());
	Recorder = MakeUnique<FVerseBoutRecorder>(IdA, IdB, Unit.KillsToWin, Unit.MatchTimeLimitS);
	Recorder->OnRespawn(IdA, 0.0);
	Recorder->OnRespawn(IdB, 0.0);
	// Destruction resets between bouts through the ruleset's reset (destruction.md 11) once
	// WP06 and WP11 land; the hub carries no reset command the harness could send today.
}

void UVerseBalanceGauntletController::EndBout()
{
	const FVerseHarnessUnit& Unit = Scenario.Units[UnitIndex];
	const double Duration = Now() - BoutStartS;
	const uint32 BoutSeed = FVerseRng::Hash(Unit.Seed, uint32(BoutIndex), 0xB0u);
	FString Line = Recorder->ToJsonLine(Unit.Pairing, Unit.Match, BoutIndex, BoutSeed, BoutIndex % 2, Duration, MatchTimeS,
		AdaptiveTrace);
	VerseBalancePrivate::AppendLine(BoutsFile, Line);
	MatchTimeS += Duration;
	AdaptiveTrace.Reset();
	++BoutIndex;
	if (BoutIndex >= Unit.Bouts)
	{
		BeginUnit();
	}
	else
	{
		BeginBout();
	}
}

bool UVerseBalanceGauntletController::Tick()
{
	if (bFinished)
	{
		return false;
	}
	++Ticks;
	if (Scenario.MaxWallS > 0.0 && FPlatformTime::Seconds() - WallStartS > Scenario.MaxWallS)
	{
		Finish(TEXT("wall-clock guard reached"));
		return false;
	}
	if (!Recorder)
	{
		return !bFinished;
	}
	const double T = Now() - BoutStartS;
	for (int32 Index = 0; Index < Slots.Num(); ++Index)
	{
		const AController* Controller = Slots[Index].Get();
		const APawn* Pawn = Controller ? Controller->GetPawn() : nullptr;
		Recorder->SamplePosition(Index == 0 ? EVerseSide::A : EVerseSide::B, Pawn ? Pawn->GetActorLocation() : FVector::ZeroVector,
			Pawn != nullptr, T);
	}
	if (Recorder->IsOver(T))
	{
		EndBout();
	}
	return !bFinished;
}

void UVerseBalanceGauntletController::ReadAdaptive()
{
	// BotEffectiveSkill lives on AVersePlayerState (combat-state.md 2.1, VerseCombat); read by
	// reflection so this works before and after the field exists.
	for (const TWeakObjectPtr<AController>& Weak : Slots)
	{
		const AController* Controller = Weak.Get();
		const APlayerState* State = Controller ? Controller->PlayerState.Get() : nullptr;
		if (!State)
		{
			continue;
		}
		if (const FFloatProperty* Prop = FindFProperty<FFloatProperty>(State->GetClass(), TEXT("BotEffectiveSkill")))
		{
			AdaptiveTrace.Add(Prop->GetPropertyValue_InContainer(State));
		}
	}
}

void UVerseBalanceGauntletController::HandleFire(const FVerseFireEvent& Event)
{
	if (Recorder)
	{
		Recorder->OnFire(Event, Now() - BoutStartS);
	}
}

void UVerseBalanceGauntletController::HandleHit(const FVerseHitEvent& Event)
{
	if (Recorder)
	{
		Recorder->OnHit(Event, Now() - BoutStartS);
	}
}

void UVerseBalanceGauntletController::HandleDeath(const FVerseDeathEvent& Event)
{
	if (!Recorder)
	{
		return;
	}
	Recorder->OnDeath(Event, Now() - BoutStartS);
	ReadAdaptive();
	// The ruleset respawns after 3 s (combat-state.md 9.1); RespawnAt is server time.
	Recorder->OnRespawn(Event.VictimId, FMath::Max(0.0, double(Event.RespawnAt) - BoutStartS));
}

void UVerseBalanceGauntletController::HandleReload(const FVerseReloadEvent& Event)
{
	if (Recorder)
	{
		Recorder->OnReload(Event, Now() - BoutStartS);
	}
}

void UVerseBalanceGauntletController::HandleGadget(const FVerseGadgetEvent& Event)
{
	if (Recorder)
	{
		Recorder->OnGadget(Event, Now() - BoutStartS);
	}
}

void UVerseBalanceGauntletController::Finish(const TCHAR* Why)
{
	if (bFinished)
	{
		return;
	}
	bFinished = true;
	ClearSlots();
	Recorder.Reset();
	if (UVerseEventHub* Hub = UVerseEventHub::Get(World.Get()))
	{
		Hub->OnFire.RemoveAll(this);
		Hub->OnHit.RemoveAll(this);
		Hub->OnDeath.RemoveAll(this);
		Hub->OnReload.RemoveAll(this);
		Hub->OnGadget.RemoveAll(this);
	}
	const double WallS = FPlatformTime::Seconds() - WallStartS;
	const double SimS = Now() - SimStartS;
	FVerseJsonWriter Speed;
	Speed.Str(TEXT("schema"), TEXT("verse.speed/1"))
		.Str(TEXT("run"), Scenario.Run)
		.Num(TEXT("job"), Scenario.Job)
		.Num(TEXT("simS"), SimS)
		.Num(TEXT("wallS"), WallS)
		.Num(TEXT("startupS"), StartupS)
		.Num(TEXT("ticks"), double(Ticks))
		.Num(TEXT("xRealTime"), WallS > 0.0 ? SimS / WallS : 0.0)
		.Num(TEXT("peakRamMb"), double(FPlatformMemory::GetStats().PeakUsedPhysical) / (1024.0 * 1024.0))
		.Str(TEXT("botController"), BotControllerKind)
		.Str(TEXT("end"), Why);
	const FString Text = Speed.Close();
	FFileHelper::SaveStringToFile(Text, *FPaths::Combine(Scenario.OutputDir, TEXT("speed.json")),
		FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	UE_LOG(LogVerseHarness, Display, TEXT("[VerseHarness] done (%s): %.1f s simulated in %.1f s wall, %.1fx real time"), Why, SimS,
		WallS, WallS > 0.0 ? SimS / WallS : 0.0);
}
