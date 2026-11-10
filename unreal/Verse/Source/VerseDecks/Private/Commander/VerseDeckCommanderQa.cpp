#include "Camera/VerseDeckCamera.h"
#include "Camera/VerseDeckView.h"
#include "Engine/World.h"
#include "HAL/IConsoleManager.h"
#include "Input/VerseDeckControlComponent.h"
#include "VerseLog.h"

// QA console commands of the deck commander (stream S5), for harness runs and manual checks:
//   Verse.QA.Commander                 prints the control's state JSON
//   Verse.QA.Commander.Walk <x> <y>    walks the commander to a floor point (cm)
//   Verse.QA.Commander.View <name>     overview, third or first
//   Verse.QA.Commander.Salute          the salute

namespace VerseDeckCommanderQa
{
	UVerseDeckControlComponent* ControlOf(UWorld* World)
	{
		UVerseDeckControlComponent* Control = UVerseDeckControlComponent::Get(World);
		if (Control == nullptr)
		{
			UE_LOG(LogVerse, Warning, TEXT("[VerseDeckControl] no deck control in this world"));
		}
		return Control;
	}

	FAutoConsoleCommandWithWorldAndArgs State(
		TEXT("Verse.QA.Commander"),
		TEXT("Prints the deck commander's state JSON."),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
		{
			if (UVerseDeckControlComponent* Control = ControlOf(World))
			{
				UE_LOG(LogVerse, Display, TEXT("[VerseDeckControl] %s"), *Control->StateJson());
			}
		}));

	FAutoConsoleCommandWithWorldAndArgs Walk(
		TEXT("Verse.QA.Commander.Walk"),
		TEXT("Walks the deck commander to a floor point: Verse.QA.Commander.Walk <x cm> <y cm>."),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			UVerseDeckControlComponent* Control = ControlOf(World);
			if (Control == nullptr || Args.Num() < 2)
			{
				return;
			}
			const FVector Point(FCString::Atod(*Args[0]), FCString::Atod(*Args[1]), Args.Num() > 2 ? FCString::Atod(*Args[2]) : 0.0);
			const bool bOk = Control->WalkTo(Point, true);
			UE_LOG(LogVerse, Display, TEXT("[VerseDeckControl] walk to %s: %s"), *Point.ToString(), bOk ? TEXT("ok") : TEXT("unreachable"));
		}));

	FAutoConsoleCommandWithWorldAndArgs View(
		TEXT("Verse.QA.Commander.View"),
		TEXT("Picks a deck view: Verse.QA.Commander.View overview|third|first."),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			UVerseDeckControlComponent* Control = ControlOf(World);
			const TOptional<EVerseDeckView> Wanted = Args.Num() > 0 ? Verse::DeckView::FromName(Args[0]) : TOptional<EVerseDeckView>();
			if (Control && Wanted.IsSet())
			{
				Control->PickView(Wanted.GetValue());
			}
		}));

	FAutoConsoleCommandWithWorldAndArgs Salute(
		TEXT("Verse.QA.Commander.Salute"),
		TEXT("The deck commander salutes."),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
		{
			if (UVerseDeckControlComponent* Control = ControlOf(World))
			{
				Control->Salute();
			}
		}));
}
