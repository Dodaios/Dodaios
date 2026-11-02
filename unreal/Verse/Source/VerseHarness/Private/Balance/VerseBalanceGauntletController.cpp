#include "Balance/VerseBalanceGauntletController.h"

#include "Balance/VerseHarnessPerceptFeed.h"
#include "Balance/VerseModelController.h"
#include "Bot/VerseBotTier.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/GameModeBase.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerStart.h"
#include "GameFramework/PlayerState.h"
#include "HAL/PlatformMemory.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformTime.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UnrealType.h"
#include "VerseHarnessJson.h"
#include "VerseLog.h"

namespace VerseBalancePrivate
{
	/** The bot controller class of VerseBot (WP08), found by name so the harness builds before it. */
	const TCHAR* BotControllerPath = TEXT("/Script/VerseBot.VerseBotController");

	/** Harness spawn pair when the map has fewer than two player starts: 20 m apart, facing each other. */
	constexpr double FallbackSpawnGapCm = 2000.0;

	void AppendLine(const FString& File, const FString& Line)
	{
		FFileHelper::SaveStringToFile(Line + TEXT("\n"), *File, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,
			&IFileManager::Get(), FILEWRITE_Append);
	}

	/**
	 * Calls a UFUNCTION of the bot controller by name: the frozen AVerseBotController methods,
	 * reached by reflection so the harness builds before VerseBot has them. Arg fills the first
	 * parameter when bHasArg; OutFloat receives a float return value.
	 */
	bool CallBotFunction(UObject& Target, FName Name, TFunctionRef<bool(FProperty&, void*)> Arg, bool bHasArg, float* OutFloat,
						 FString& OutError)
	{
		UFunction* Fn = Target.FindFunction(Name);
		if (!Fn)
		{
			OutError = FString::Printf(TEXT("%s has no UFUNCTION %s (bot.md frozen interface)"), *Target.GetClass()->GetName(),
									   *Name.ToString());
			return false;
		}
		TArray<uint8, TAlignedHeapAllocator<16>> Buffer;
		Buffer.SetNumZeroed(FMath::Max(1, int32(Fn->ParmsSize)));
		FProperty* First = nullptr;
		FProperty* Return = nullptr;
		for (TFieldIterator<FProperty> It(Fn); It && It->HasAnyPropertyFlags(CPF_Parm); ++It)
		{
			It->InitializeValue_InContainer(Buffer.GetData());
			if (It->HasAnyPropertyFlags(CPF_ReturnParm))
			{
				Return = *It;
			}
			else if (!First)
			{
				First = *It;
			}
		}
		bool bOk = true;
		if (bHasArg)
		{
			bOk = First && Arg(*First, First->ContainerPtrToValuePtr<void>(Buffer.GetData()));
			if (!bOk)
			{
				OutError =
					FString::Printf(TEXT("%s::%s has an unexpected signature"), *Target.GetClass()->GetName(), *Name.ToString());
			}
		}
		if (bOk && OutFloat && !CastField<FFloatProperty>(Return) && !CastField<FDoubleProperty>(Return))
		{
			OutError = FString::Printf(TEXT("%s::%s returns no float"), *Target.GetClass()->GetName(), *Name.ToString());
			bOk = false;
		}
		if (bOk)
		{
			Target.ProcessEvent(Fn, Buffer.GetData());
			if (OutFloat)
			{
				if (const FFloatProperty* F = CastField<FFloatProperty>(Return))
				{
					*OutFloat = F->GetPropertyValue_InContainer(Buffer.GetData());
				}
				else if (const FDoubleProperty* D = CastField<FDoubleProperty>(Return))
				{
					*OutFloat = float(D->GetPropertyValue_InContainer(Buffer.GetData()));
				}
			}
		}
		for (TFieldIterator<FProperty> It(Fn); It && It->HasAnyPropertyFlags(CPF_Parm); ++It)
		{
			It->DestroyValue_InContainer(Buffer.GetData());
		}
		return bOk;
	}

	/** Sets one UVerseBotTier field from a JSON value; false on an unknown field or a wrong type. */
	bool SetTierField(UVerseBotTier& Tier, const FString& Field, const FVerseJson& Value, FString& OutError)
	{
		FProperty* Prop = FindFProperty<FProperty>(UVerseBotTier::StaticClass(), *Field);
		void* Ptr = Prop ? Prop->ContainerPtrToValuePtr<void>(&Tier) : nullptr;
		if (!Prop || !Ptr)
		{
			OutError = FString::Printf(TEXT("tierPatch: UVerseBotTier has no field %s"), *Field);
			return false;
		}
		if (FFloatProperty* F = CastField<FFloatProperty>(Prop); F && Value.Type == FVerseJson::EType::Number)
		{
			F->SetPropertyValue(Ptr, float(Value.Number));
			return true;
		}
		if (FIntProperty* I = CastField<FIntProperty>(Prop); I && Value.Type == FVerseJson::EType::Number)
		{
			I->SetPropertyValue(Ptr, int32(Value.Number));
			return true;
		}
		if (FBoolProperty* B = CastField<FBoolProperty>(Prop); B && Value.Type == FVerseJson::EType::Bool)
		{
			B->SetPropertyValue(Ptr, Value.bBool);
			return true;
		}
		if (FNameProperty* N = CastField<FNameProperty>(Prop); N && Value.Type == FVerseJson::EType::String)
		{
			N->SetPropertyValue(Ptr, FName(*Value.String));
			return true;
		}
		FStructProperty* S = CastField<FStructProperty>(Prop);
		if (S && S->Struct == TVariantStructure<FVector2f>::Get() && Value.Type == FVerseJson::EType::Array && Value.Array.Num() == 2 && Value.Array[0] && Value.Array[1])
		{
			*static_cast<FVector2f*>(Ptr) = FVector2f(float(Value.Array[0]->Number), float(Value.Array[1]->Number));
			return true;
		}
		OutError = FString::Printf(TEXT("tierPatch: %s has the wrong type"), *Field);
		return false;
	}

	bool IsTierId(const FString& Key)
	{
		return Key == TEXT("normal") || Key == TEXT("hard") || Key == TEXT("elite") || Key == TEXT("adaptive");
	}
}

double UVerseBalanceGauntletController::Now() const
{
	const UWorld* W = World.Get();
	return W ? W->GetTimeSeconds() : 0.0;
}

double UVerseBalanceGauntletController::ServerMs() const
{
	return FMath::RoundToDouble(FMath::Max(0.0, Now()) * 1000.0);
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
	Feed = NewObject<UVerseHarnessPerceptFeed>(this);
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
	UE_LOG(LogVerseHarness, Display, TEXT("[VerseHarness] run %s job %d: %d units, bot slots: %s"), *Scenario.Run, Scenario.Job,
		   Scenario.Units.Num(), *BotControllerKind);
	BeginUnit();
	if (bFailed)
	{
		OutError = EndReason;
		return false;
	}
	return true;
}

UVerseBotTier* UVerseBalanceGauntletController::MakeTier(UObject* Outer, FName TierId, bool bLearning, const FString& TierPatchJson,
														 FString& OutError)
{
	using namespace VerseBalancePrivate;
	UVerseBotTier* Tier = NewObject<UVerseBotTier>(Outer ? Outer : GetTransientPackage());
	// The adaptive bot interpolates between tiers itself (bot.md 9.2); its base asset is normal.
	const FName Base = TierId == TEXT("adaptive") || TierId.IsNone() ? FName(TEXT("normal")) : TierId;
	if (!UVerseBotTier::ApplyStartValues(Base, *Tier))
	{
		OutError = FString::Printf(TEXT("unknown tier %s"), *Base.ToString());
		return nullptr;
	}
	if (!TierPatchJson.IsEmpty())
	{
		FString ParseError;
		const TSharedPtr<FVerseJson> Patch = FVerseJson::Parse(TierPatchJson, ParseError);
		if (!Patch || !Patch->IsObject())
		{
			OutError = TEXT("tierPatch is not a JSON object: ") + ParseError;
			return nullptr;
		}
		for (const TPair<FString, TSharedPtr<FVerseJson>>& Member : Patch->Object)
		{
			if (!Member.Value)
			{
				continue;
			}
			if (!IsTierId(Member.Key))
			{
				if (!SetTierField(*Tier, Member.Key, *Member.Value, OutError))
				{
					return nullptr;
				}
				continue;
			}
			if (!Member.Value->IsObject())
			{
				OutError = FString::Printf(TEXT("tierPatch.%s is not an object"), *Member.Key);
				return nullptr;
			}
			if (FName(*Member.Key) != TierId)
			{
				continue;
			}
			for (const TPair<FString, TSharedPtr<FVerseJson>>& Field : Member.Value->Object)
			{
				if (!Field.Value || !SetTierField(*Tier, Field.Key, *Field.Value, OutError))
				{
					if (OutError.IsEmpty())
					{
						OutError = FString::Printf(TEXT("tierPatch.%s.%s is null"), *Member.Key, *Field.Key);
					}
					return nullptr;
				}
			}
		}
	}
	if (!bLearning)
	{
		// Learning off (BG8): the frozen tier has no switch, so the learnt weight is capped at 0.
		Tier->LearnWeightMax = 0.f;
	}
	return Tier;
}

FVersePersonModel UVerseBalanceGauntletController::PersonFromTier(const UVerseBotTier& Tier, FName Name)
{
	FVersePersonModel Person;
	Person.Name = Name;
	Person.ReactionMeanMs = Tier.ReactionMs.X;
	Person.ReactionSdMs = Tier.ReactionMs.Y;
	Person.TurnRateDegS = Tier.TurnRateDegS;
	Person.RecoilPatternComp = Tier.RecoilPatternComp;
	Person.HeadAimChance = Tier.HeadAimChance;
	Person.AimWanderSdDeg = Tier.AimNoiseDeg;
	Person.AimWanderTheta = Tier.AimNoiseRate;
	Person.LearnWeight = Tier.LearnWeightMax;
	Person.bLearning = Tier.LearnWeightMax > 0.f;
	return Person;
}

bool UVerseBalanceGauntletController::ConfigureBot(AController& Bot, const FVerseHarnessSlot& Slot, const FString& TierPatchJson,
												   FString& OutError)
{
	using namespace VerseBalancePrivate;
	UVerseBotTier* Tier = MakeTier(this, Slot.Tier, Slot.bLearning, TierPatchJson, OutError);
	if (!Tier)
	{
		return false;
	}
	UnitTiers.Add(Tier);
	const bool bTier = CallBotFunction(
		Bot, TEXT("SetTier"),
		[Tier](FProperty& Param, void* Value)
		{
			FObjectPropertyBase* Object = CastField<FObjectPropertyBase>(&Param);
			if (!Object || !Tier->IsA(Object->PropertyClass))
			{
				return false;
			}
			Object->SetObjectPropertyValue(Value, Tier);
			return true;
		},
		true, nullptr, OutError);
	if (!bTier)
	{
		return false;
	}
	const bool bAdaptive = Slot.Tier == TEXT("adaptive");
	return CallBotFunction(
		Bot, TEXT("SetAdaptive"),
		[bAdaptive](FProperty& Param, void* Value)
		{
			FBoolProperty* Flag = CastField<FBoolProperty>(&Param);
			if (!Flag)
			{
				return false;
			}
			Flag->SetPropertyValue(Value, bAdaptive);
			return true;
		},
		true, nullptr, OutError);
}

AController* UVerseBalanceGauntletController::SpawnSlot(const FVerseHarnessSlot& Slot, const FString& TierPatchJson, uint32 SlotSeed,
														FString& OutError)
{
	UWorld* W = World.Get();
	if (!W)
	{
		OutError = TEXT("no game world");
		return nullptr;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	if (Slot.IsBot())
	{
		if (UClass* BotClass = FindObject<UClass>(nullptr, VerseBalancePrivate::BotControllerPath))
		{
			AController* Bot = W->SpawnActor<AController>(BotClass, Params);
			if (!Bot)
			{
				OutError = TEXT("cannot spawn ") + BotClass->GetName();
				return nullptr;
			}
			if (!ConfigureBot(*Bot, Slot, TierPatchJson, OutError))
			{
				Bot->Destroy();
				return nullptr;
			}
			return Bot;
		}
	}
	FVersePersonModel Person;
	if (!Slot.Model.IsNone())
	{
		const FVersePersonModel* Found = PersonModels.Models.Find(Slot.Model);
		if (!Found)
		{
			OutError = FString::Printf(TEXT("unknown person model %s"), *Slot.Model.ToString());
			return nullptr;
		}
		Person = *Found;
	}
	else
	{
		// A tier-based model (trick pairings "base hard") or the null-brain stand-in of a bot slot.
		UVerseBotTier* Tier = MakeTier(this, Slot.Tier, Slot.bLearning, TierPatchJson, OutError);
		if (!Tier)
		{
			return nullptr;
		}
		UnitTiers.Add(Tier);
		Person = PersonFromTier(*Tier, Slot.Tier);
	}
	FVerseTrickConfig Trick;
	if (!Slot.Trick.IsNone() && Slot.Trick != TEXT("none"))
	{
		const FVerseTrickConfig* Found = PersonModels.Tricks.Find(Slot.Trick);
		if (!Found)
		{
			OutError = FString::Printf(TEXT("unknown trick %s"), *Slot.Trick.ToString());
			return nullptr;
		}
		Trick = *Found;
	}
	AVerseModelController* Model = W->SpawnActor<AVerseModelController>(Params);
	if (!Model)
	{
		OutError = TEXT("cannot spawn a model controller");
		return nullptr;
	}
	Model->Configure(Person, Trick, SlotSeed);
	FVersePerceptionProfile Profile;
	Profile.Seed = SlotSeed;
	Model->AttachPerception(Feed, Profile);
	return Model;
}

void UVerseBalanceGauntletController::ResolveSpawnPair()
{
	using namespace VerseBalancePrivate;
	UWorld* W = World.Get();
	TArray<APlayerStart*> Starts;
	if (W)
	{
		for (TActorIterator<APlayerStart> It(W); It; ++It)
		{
			Starts.Add(*It);
		}
	}
	Starts.Sort([](const APlayerStart& L, const APlayerStart& R)
				{ return L.GetName() < R.GetName(); });
	APlayerStart* Side0 = nullptr;
	APlayerStart* Side1 = nullptr;
	for (APlayerStart* Start : Starts)
	{
		if (!Side0 && Start->PlayerStartTag == TEXT("VerseSide0"))
		{
			Side0 = Start;
		}
		if (!Side1 && Start->PlayerStartTag == TEXT("VerseSide1"))
		{
			Side1 = Start;
		}
	}
	if ((!Side0 || !Side1) && Starts.Num() >= 2)
	{
		Side0 = Starts[0];
		Side1 = nullptr;
		double Best = -1.0;
		for (APlayerStart* Start : Starts)
		{
			const double D = FVector::DistSquared(Start->GetActorLocation(), Side0->GetActorLocation());
			if (Start != Side0 && D > Best)
			{
				Best = D;
				Side1 = Start;
			}
		}
	}
	if (Side0 && Side1)
	{
		SpawnPair[0] = FTransform(Side0->GetActorRotation(), Side0->GetActorLocation());
		SpawnPair[1] = FTransform(Side1->GetActorRotation(), Side1->GetActorLocation());
		return;
	}
	const FVector Base = Starts.Num() ? Starts[0]->GetActorLocation() : FVector(0.0, 0.0, 200.0);
	SpawnPair[0] = FTransform(FRotator::ZeroRotator, Base);
	SpawnPair[1] = FTransform(FRotator(0.0, 180.0, 0.0), Base + FVector(FallbackSpawnGapCm, 0.0, 0.0));
}

void UVerseBalanceGauntletController::RespawnSlot(AController& Controller, const FTransform& Where)
{
	UWorld* W = World.Get();
	if (!W)
	{
		return;
	}
	if (APawn* Old = Controller.GetPawn())
	{
		Controller.UnPossess();
		Old->Destroy();
	}
	Controller.SetControlRotation(Where.Rotator());
	if (AGameModeBase* Mode = W->GetAuthGameMode())
	{
		Mode->RestartPlayerAtTransform(&Controller, Where);
		if (Controller.GetPawn())
		{
			return;
		}
	}
	// No game mode (fixture worlds) or no default pawn: a plain character stands in.
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	if (ACharacter* Character = W->SpawnActor<ACharacter>(ACharacter::StaticClass(), Where, Params))
	{
		Character->GetCharacterMovement()->GetNavAgentPropertiesRef().bCanCrouch = true;
		Controller.Possess(Character);
	}
}

int32 UVerseBalanceGauntletController::MeasureSpawnSideA() const
{
	const AController* A = GetSlot(0);
	const APawn* Pawn = A ? A->GetPawn() : nullptr;
	if (!Pawn)
	{
		return SpawnSideA;
	}
	const FVector At = Pawn->GetActorLocation();
	return FVector::DistSquared(At, SpawnPair[1].GetLocation()) < FVector::DistSquared(At, SpawnPair[0].GetLocation()) ? 1 : 0;
}

void UVerseBalanceGauntletController::ClearSlots()
{
	for (const TWeakObjectPtr<AController>& Weak : Slots)
	{
		if (AController* Controller = Weak.Get())
		{
			if (AVerseModelController* Model = Cast<AVerseModelController>(Controller))
			{
				Model->DetachPerception();
			}
			if (APawn* Pawn = Controller->GetPawn())
			{
				Pawn->Destroy();
			}
			Controller->Destroy();
		}
	}
	Slots.Reset();
	UnitTiers.Reset();
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
	FString Error;
	AController* A = SpawnSlot(Unit.A, Unit.TierPatchJson, FVerseRng::Hash(Unit.Seed, 0xA, 0), Error);
	AController* B = A ? SpawnSlot(Unit.B, Unit.TierPatchJson, FVerseRng::Hash(Unit.Seed, 0xB, 0), Error) : nullptr;
	if (A)
	{
		Slots.Add(A);
	}
	if (!A || !B)
	{
		Fail(FString::Printf(TEXT("unit %s#%d: %s"), *Unit.Pairing, Unit.Match, *Error));
		return;
	}
	Slots.Add(B);
	ResolveSpawnPair();
	BeginBout();
}

void UVerseBalanceGauntletController::BeginBout()
{
	const FVerseHarnessUnit& Unit = Scenario.Units[UnitIndex];
	// bot.md 11.1: slots alternate spawn sides per bout. Both pawns are reset every bout.
	SpawnSideA = BoutIndex % 2;
	for (int32 Index = 0; Index < Slots.Num(); ++Index)
	{
		if (AController* Controller = Slots[Index].Get())
		{
			RespawnSlot(*Controller, SpawnPair[(Index + SpawnSideA) % 2]);
		}
	}
	const int32 Measured = MeasureSpawnSideA();
	if (Measured != SpawnSideA)
	{
		UE_LOG(LogVerseHarness, Warning, TEXT("[VerseHarness] bout %d: slot A spawned on side %d, planned %d"), BoutIndex, Measured,
			   SpawnSideA);
		SpawnSideA = Measured;
	}
	BoutStartS = Now();
	BoutStartMs = ServerMs();
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
	FString Line =
		Recorder->ToJsonLine(Unit.Pairing, Unit.Match, BoutIndex, BoutSeed, SpawnSideA, Duration, MatchTimeS, AdaptiveTrace);
	// The server-time window of the bout: balance.py maps fire-audit lines onto bouts with it.
	Line.LeftChopInline(1);
	Line += FString::Printf(TEXT(",\"serverStartMs\":%s,\"serverEndMs\":%s}"), *FVerseJsonWriter::Number(BoutStartMs),
							*FVerseJsonWriter::Number(ServerMs()));
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
	// Model slots perceive and act once per server tick (bot slots run their own perception).
	Feed->Tick(World.Get());
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
	// s of the adaptive bot through the frozen AVerseBotController::GetEffectiveSkill() (bot.md 9.2).
	for (const TWeakObjectPtr<AController>& Weak : Slots)
	{
		AController* Controller = Weak.Get();
		if (!Controller || Controller->IsA<AVerseModelController>())
		{
			continue;
		}
		float Skill = 0.f;
		FString Error;
		if (VerseBalancePrivate::CallBotFunction(*Controller, TEXT("GetEffectiveSkill"), [](FProperty&, void*)
												 { return true; }, false, &Skill, Error))
		{
			AdaptiveTrace.Add(Skill);
		}
		else if (!bWarnedNoSkill)
		{
			bWarnedNoSkill = true;
			UE_LOG(LogVerseHarness, Warning, TEXT("[VerseHarness] no adaptive trace: %s"), *Error);
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

void UVerseBalanceGauntletController::Fail(const FString& Why)
{
	UE_LOG(LogVerseHarness, Error, TEXT("[VerseHarness] run failed: %s"), *Why);
	bFailed = true;
	const FString Reason = TEXT("failed: ") + Why;
	Finish(*Reason);
}

void UVerseBalanceGauntletController::Finish(const TCHAR* Why)
{
	if (bFinished)
	{
		return;
	}
	bFinished = true;
	EndReason = Why;
	const int32 UnitsStarted = FMath::Clamp(UnitIndex + (bFailed ? 1 : 0), 0, Scenario.Units.Num());
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
		.Str(TEXT("end"), Why)
		.Bool(TEXT("failed"), bFailed)
		.Num(TEXT("unitsPlanned"), Scenario.Units.Num())
		.Num(TEXT("unitsFinished"), bFailed ? FMath::Max(0, UnitsStarted - 1) : FMath::Min(UnitIndex, Scenario.Units.Num()));
	const FString Text = Speed.Close();
	FFileHelper::SaveStringToFile(Text, *FPaths::Combine(Scenario.OutputDir, TEXT("speed.json")),
		FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	UE_LOG(LogVerseHarness, Display, TEXT("[VerseHarness] done (%s): %.1f s simulated in %.1f s wall, %.1fx real time"), Why, SimS,
		WallS, WallS > 0.0 ? SimS / WallS : 0.0);
}
