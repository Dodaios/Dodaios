#include "Core/VerseUiDefaultPorts.h"

#include "Camera/PlayerCameraManager.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Engine/World.h"
#include "GameFramework/GameStateBase.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerState.h"
#include "Movement/VerseMovementQuery.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "Qa/VerseQaRegistry.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/UnrealType.h"
#include "VerseLog.h"

namespace
{
	FString ToJsonString(const TSharedRef<FJsonObject>& Object)
	{
		FString Out;
		const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer = TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
		FJsonSerializer::Serialize(Object, Writer);
		return Out;
	}

	void RunQa(const FString& Command, const TArray<FString>& Args)
	{
		UVerseQaRegistry* Registry = UVerseQaRegistry::Get();
		FString Result;
		if (!Registry || !Registry->Execute(Command, Args, Result))
		{
			UE_LOG(LogVerseUI, Warning, TEXT("VerseUI: %s is not registered yet (%s)"), *Command, *Result);
			return;
		}
		UE_LOG(LogVerseUI, Log, TEXT("VerseUI: %s -> %s"), *Command, *Result);
	}
}

// ---------------------------------------------------------------------------------------------

void FVerseUiLogBridgePort::SendSettingsSet(const TSharedRef<FJsonObject>& Data)
{
	++NumSent;
	UE_LOG(LogVerseUI, Log, TEXT("VerseUI: no bridge yet; settings.set %s"), *ToJsonString(Data));
}

void FVerseUiLogBridgePort::SendReturnToApp(const FString& Reason)
{
	++NumSent;
	UE_LOG(LogVerseUI, Log, TEXT("VerseUI: no bridge yet; focus.return_to_app {\"reason\":\"%s\"}"), *Reason);
}

// ---------------------------------------------------------------------------------------------

void FVerseUiQaGamePort::StartDuel(FName Tier)
{
	RunQa(TEXT("Verse.QA.Duel.Start"), {Tier.ToString()});
}

void FVerseUiQaGamePort::LeaveDuel()
{
	RunQa(TEXT("Verse.QA.Duel.Leave"), {});
}

void FVerseUiQaGamePort::TravelToDeck(FName Deck)
{
	CurrentDeck = Deck;
	RunQa(TEXT("Verse.QA.View.Set"), {FString::Printf(TEXT("deck=%s"), *Deck.ToString())});
}

void FVerseUiQaGamePort::NoteArenaSwitch(bool bOn, FName Deck)
{
	bArenaOn = bOn;
	if (!Deck.IsNone())
	{
		CurrentDeck = Deck;
	}
}

// ---------------------------------------------------------------------------------------------

APlayerController* FVerseUiWorldHudSource::LocalController() const
{
	UWorld* W = World.Get();
	return W ? W->GetFirstPlayerController() : nullptr;
}

APlayerState* FVerseUiWorldHudSource::FindPlayer(int32 PlayerId) const
{
	UWorld* W = World.Get();
	AGameStateBase* GameState = W ? W->GetGameState() : nullptr;
	if (!GameState)
	{
		return nullptr;
	}
	for (APlayerState* State : GameState->PlayerArray)
	{
		if (State && State->GetPlayerId() == PlayerId)
		{
			return State;
		}
	}
	return nullptr;
}

int32 FVerseUiWorldHudSource::GetLocalPlayerId() const
{
	APlayerController* PC = LocalController();
	return PC && PC->PlayerState ? PC->PlayerState->GetPlayerId() : INDEX_NONE;
}

double FVerseUiWorldHudSource::GetServerTime() const
{
	UWorld* W = World.Get();
	if (!W)
	{
		return 0.0;
	}
	const AGameStateBase* GameState = W->GetGameState();
	return GameState ? GameState->GetServerWorldTimeSeconds() : W->GetTimeSeconds();
}

void FVerseUiWorldHudSource::GetPawnState(FVerseHudPawnState& Out) const
{
	Out = FVerseHudPawnState();
	APlayerController* PC = LocalController();
	APawn* Pawn = PC ? PC->GetPawn() : nullptr;
	if (!Pawn)
	{
		return;
	}
	Out.bValid = true;
	// Health lives in WP02's attribute set; until it lands the UI tracks it from hit events.
	Out.bHealthKnown = false;
	if (const UVerseCombatStateComponent* Combat = Pawn->FindComponentByClass<UVerseCombatStateComponent>())
	{
		Out.Phase = Combat->Phase;
		Out.bSpawnProtected = Combat->bSpawnProtected;
		Out.SpawnProtectionRemaining = Combat->bSpawnProtected ? float(FMath::Max(0.0, Combat->SpawnProtectedUntil - GetServerTime())) : 0.f;
	}
	if (UActorComponent* Movement = Pawn->FindComponentByInterface(UVerseMovementQuery::StaticClass()))
	{
		if (const IVerseMovementQuery* Query = Cast<IVerseMovementQuery>(Movement))
		{
			Out.Stance = Query->GetStance();
		}
	}
	// Magazine, reserve and gadgets come from WP02's inventory (combat-state 2.1), owner only.
	Out.bHasWeapon = false;
}

bool FVerseUiWorldHudSource::GetView(FVerseHudView& Out) const
{
	APlayerController* PC = LocalController();
	if (!PC || !PC->PlayerCameraManager)
	{
		return false;
	}
	const FMinimalViewInfo& View = PC->PlayerCameraManager->GetCameraCacheView();
	Out.Location = View.Location;
	Out.Rotation = View.Rotation;
	Out.HorizontalFovDeg = View.FOV;
	return true;
}

bool FVerseUiWorldHudSource::GetPredictedBoltDirection(FVector& OutDirection, float& OutSpreadHalfAngleDeg) const
{
	// Without WP02's weapon prediction the bolt leaves along the camera axis.
	FVerseHudView View;
	if (!GetView(View))
	{
		return false;
	}
	OutDirection = View.Rotation.Vector();
	OutSpreadHalfAngleDeg = 0.f;
	return true;
}

FText FVerseUiWorldHudSource::GetDisplayName(int32 PlayerId) const
{
	const APlayerState* State = FindPlayer(PlayerId);
	// A player's own name is data, not a UI string.
	return State ? FText::AsCultureInvariant(State->GetPlayerName()) : FText::GetEmpty();
}

bool FVerseUiWorldHudSource::IsBot(int32 PlayerId) const
{
	const APlayerState* State = FindPlayer(PlayerId);
	return State && State->IsABot();
}

FName FVerseUiWorldHudSource::GetBotTier(int32 PlayerId) const
{
	const APlayerState* State = FindPlayer(PlayerId);
	if (!State)
	{
		return NAME_None;
	}
	if (const FNameProperty* Prop = FindFProperty<FNameProperty>(State->GetClass(), TEXT("BotTier")))
	{
		return Prop->GetPropertyValue_InContainer(State);
	}
	return NAME_None;
}

float FVerseUiWorldHudSource::GetBotEffectiveSkill(int32 PlayerId) const
{
	const APlayerState* State = FindPlayer(PlayerId);
	if (!State)
	{
		return -1.f;
	}
	if (const FFloatProperty* Prop = FindFProperty<FFloatProperty>(State->GetClass(), TEXT("BotEffectiveSkill")))
	{
		return Prop->GetPropertyValue_InContainer(State);
	}
	return -1.f;
}

void FVerseUiWorldHudSource::GetPawnPoses(TArray<FVersePawnPose>& Out) const
{
	Out.Reset();
	UWorld* W = World.Get();
	AGameStateBase* GameState = W ? W->GetGameState() : nullptr;
	if (!GameState)
	{
		return;
	}
	for (APlayerState* State : GameState->PlayerArray)
	{
		const APawn* Pawn = State ? State->GetPawn() : nullptr;
		if (Pawn)
		{
			FVersePawnPose Pose;
			Pose.PlayerId = State->GetPlayerId();
			Pose.Location = Pawn->GetActorLocation();
			Pose.Rotation = Pawn->GetBaseAimRotation();
			Out.Add(Pose);
		}
	}
}
