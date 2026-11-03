// Developer console commands of the gore module (WP05.1 synthetic event player, WP05.8 budget).
// Not part of the Verse.QA.* set of parity.md 19; non-Shipping only.

#include "CoreMinimal.h"

#if !UE_BUILD_SHIPPING

#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerState.h"
#include "Gore/VerseGoreSubsystem.h"
#include "HAL/IConsoleManager.h"
#include "VerseLog.h"

namespace VerseGoreConsole
{
	/** Places a synthetic victim: the first pawn that is not the viewer, else 3 m in front of the camera. */
	void PickTargets(UWorld* World, FVerseGoreSyntheticParams& Params)
	{
		APawn* Viewer = nullptr;
		if (APlayerController* Controller = World->GetFirstPlayerController())
		{
			Viewer = Controller->GetPawn();
			FVector EyeLocation;
			FRotator EyeRotation;
			Controller->GetPlayerViewPoint(EyeLocation, EyeRotation);
			Params.ShooterLocation = EyeLocation;
			Params.VictimLocation = EyeLocation + EyeRotation.Vector() * 300.0 - FVector(0.0, 0.0, 150.0);
		}
		for (TActorIterator<APawn> It(World); It; ++It)
		{
			if (*It != Viewer)
			{
				Params.VictimLocation = It->GetActorLocation() - FVector(0.0, 0.0, It->GetSimpleCollisionHalfHeight());
				if (const APlayerState* PlayerState = It->GetPlayerState())
				{
					Params.VictimId = PlayerState->GetPlayerId();
				}
				break;
			}
		}
	}

	FAutoConsoleCommandWithWorldAndArgs PlayCommand(
		TEXT("Verse.Gore.Play"),
		TEXT("Verse.Gore.Play <hits|deaths|finisher|storm> [seed] [seconds]: play a synthetic event stream into gore only (never on the hub)"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			UVerseGoreSubsystem* Gore = UVerseGoreSubsystem::Get(World);
			FVerseGoreSyntheticParams Params;
			if (!Gore || Args.Num() < 1 || !FVerseGoreSyntheticStream::ParseKind(Args[0], Params.Kind))
			{
				UE_LOG(LogVerseGore, Warning, TEXT("Verse.Gore.Play <hits|deaths|finisher|storm> [seed] [seconds]"));
				return;
			}
			Params.Seed = Args.Num() > 1 ? uint32(FCString::Atoi(*Args[1])) : 1u;
			Params.DurationSeconds = Args.Num() > 2 ? FCString::Atod(*Args[2]) : (Params.Kind == EVerseGoreSyntheticKind::Storm ? 60.0 : 10.0);
			PickTargets(World, Params);
			Gore->PlaySynthetic(Params);
			UE_LOG(LogVerseGore, Log, TEXT("Synthetic %s stream started (seed %u, %.1f s)"), *Args[0], Params.Seed, Params.DurationSeconds);
		}));

	FAutoConsoleCommandWithWorldAndArgs LevelCommand(
		TEXT("Verse.Gore.Level"),
		TEXT("Verse.Gore.Level <full|reduced>: switch the gore level live (reduced purges existing gore)"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UVerseGoreSubsystem* Gore = UVerseGoreSubsystem::Get(World); Gore && Args.Num() == 1)
			{
				Gore->SetGoreLevel(Args[0].Equals(TEXT("reduced"), ESearchCase::IgnoreCase) ? EVerseGoreLevel::Reduced : EVerseGoreLevel::Full);
			}
		}));

	FAutoConsoleCommandWithWorldAndArgs StatsCommand(
		TEXT("Verse.Gore.Stats"),
		TEXT("Verse.Gore.Stats [file]: log the gore budget JSON, or write it to a file"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (const UVerseGoreSubsystem* Gore = UVerseGoreSubsystem::Get(World))
			{
				if (Args.Num() > 0)
				{
					Gore->WriteBudgetJson(Args[0]);
				}
				UE_LOG(LogVerseGore, Display, TEXT("%s"), *Gore->BudgetJson());
			}
		}));

	FAutoConsoleCommandWithWorldAndArgs PurgeCommand(
		TEXT("Verse.Gore.Purge"),
		TEXT("Verse.Gore.Purge: remove all gore"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
		{
			if (UVerseGoreSubsystem* Gore = UVerseGoreSubsystem::Get(World))
			{
				Gore->Purge();
			}
		}));
}

#endif // !UE_BUILD_SHIPPING
