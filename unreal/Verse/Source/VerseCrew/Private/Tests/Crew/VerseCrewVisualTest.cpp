#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Crew/VerseCrewPawn.h"
#include "Crew/VerseCrewSubsystem.h"
#include "Engine/Engine.h"
#include "Engine/PointLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Tests/AutomationCommon.h"
#include "Tests/Crew/Fakes/VerseCrewTestWorld.h"
#include "UnrealClient.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Visual.Crew (scripts/unreal/screenshot.py --suite Verse.Visual.Crew): the WP15
// evidence shots. Crew from a fake roster at work on each fixture deck, plus the duty sheet
// (every pawn's duty, beacon, activity and socket as JSON). Placeholder floor and lights only
// (the decks themselves are WP12's); the body is the G0 test human.
namespace VerseCrewVisual
{
	struct FState
	{
		TWeakObjectPtr<UWorld> World;
		TWeakObjectPtr<UVerseCrewSubsystem> Crew;
		TWeakObjectPtr<ACameraActor> Camera;
		TArray<TWeakObjectPtr<AActor>> Props;
		TArray<FName> Decks;
		TMap<FName, FVector> Origins;
		int32 Shots = 0;
		FString Dir;
	};

	UWorld* GameWorld()
	{
		for (const FWorldContext& Context : GEngine->GetWorldContexts())
		{
			if ((Context.WorldType == EWorldType::Game || Context.WorldType == EWorldType::PIE) && Context.World())
			{
				return Context.World();
			}
		}
		return nullptr;
	}

	void Prop(FState& S, UWorld* World, const FVector& At, const FVector& Scale)
	{
		UStaticMesh* Plane = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Plane.Plane"));
		AStaticMeshActor* Floor = World->SpawnActor<AStaticMeshActor>(At, FRotator::ZeroRotator);
		if (Floor && Plane)
		{
			Floor->GetStaticMeshComponent()->SetMobility(EComponentMobility::Movable);
			Floor->GetStaticMeshComponent()->SetStaticMesh(Plane);
			Floor->SetActorScale3D(Scale);
			S.Props.Add(Floor);
		}
	}

	void Light(FState& S, UWorld* World, const FVector& At, float Lumens, float Radius)
	{
		APointLight* Lamp = World->SpawnActor<APointLight>(At, FRotator::ZeroRotator);
		if (Lamp)
		{
			UPointLightComponent* C = Cast<UPointLightComponent>(Lamp->GetLightComponent());
			C->SetMobility(EComponentMobility::Movable);
			C->SetIntensityUnits(ELightUnits::Lumens);
			C->SetIntensity(Lumens);
			C->SetAttenuationRadius(Radius);
			C->SetLightColor(FLinearColor::FromSRGBColor(FColor(255, 214, 170)));
			C->SetCastShadows(false);
			S.Props.Add(Lamp);
		}
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewVisualTest, "Verse.Visual.Crew",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FVerseCrewVisualTest::RunTest(const FString&)
{
	using namespace VerseCrewVisual;
	using A = FVerseCrewTestWorld;
	UWorld* World = GameWorld();
	UVerseCrewSubsystem* Crew = World ? World->GetSubsystem<UVerseCrewSubsystem>() : nullptr;
	if (!TestNotNull(TEXT("a game world with the crew subsystem (run with -game)"), Crew))
	{
		return false;
	}
	const TSharedRef<FState> S = MakeShared<FState>();
	S->World = World;
	S->Crew = Crew;
	S->Decks = { FName(TEXT("bridge")), FName(TEXT("ops")), FName(TEXT("engineering")), FName(TEXT("hangar")) };
	for (int32 I = 0; I < S->Decks.Num(); ++I)
	{
		S->Origins.Add(S->Decks[I], FVector(0.0, 15000.0 * I, 0.0));
	}
	S->Dir = A::ProofDir(TEXT("WP15.2"));
	IFileManager::Get().MakeDirectory(*S->Dir, true);
	FString Error;
	if (!TestTrue(FString::Printf(TEXT("fixture decks: %s"), *Error), Crew->RegisterFixtureDecks(S->Origins, Error)))
	{
		return false;
	}
	Crew->SetLoadedDecks(S->Decks);
	Crew->SetCommanderDeck(FName(TEXT("hangar")));
	for (const TPair<FName, FVector>& Pair : S->Origins)
	{
		Prop(*S, World, Pair.Value + FVector(5000.f, 3100.f, -1.f), FVector(110.f, 70.f, 1.f));
		for (int32 X = 0; X < 4; ++X)
		{
			for (int32 Y = 0; Y < 3; ++Y)
			{
				Light(*S, World, Pair.Value + FVector(1200.f + X * 2500.f, 1000.f + Y * 2200.f, 600.f), 9000.f, 2600.f);
			}
		}
	}
	// A crew at work: officers on every duty, technicians at the terminals, a team round.
	const TCHAR* Duties[] = { TEXT("working"), TEXT("waiting"), TEXT("error"), TEXT("working"), TEXT("idle"), TEXT("paused") };
	TArray<TSharedRef<FJsonObject>> Agents;
	for (int32 I = 0; I < 24; ++I)
	{
		Agents.Add(A::Agent(FString::Printf(TEXT("ag_%02d"), I), FString::Printf(TEXT("Officer %02d"), I), Duties[I % 6], 1 + I * 2, I == 0 ? TEXT("lead") : TEXT("specialist")));
	}
	TArray<TSharedRef<FJsonObject>> Panes;
	const TCHAR* PaneDuties[] = { TEXT("working"), TEXT("waiting"), TEXT("error"), TEXT("idle"), TEXT("working"), TEXT("working"), TEXT("waiting"), TEXT("idle") };
	for (int32 I = 0; I < 8; ++I)
	{
		Panes.Add(A::Pane(FString::Printf(TEXT("ws_1:T%d"), I + 1), PaneDuties[I]));
	}
	FFakeVerseCrewBridge Bridge;
	Bridge.Send(Crew, TEXT("roster.snapshot"), A::Snapshot(Agents, Panes));
	Bridge.Send(Crew, TEXT("companion.snapshot"), FFakeVerseCrewBridge::GoldenFrames(TEXT("companion.snapshot"))[0]->GetObjectField(TEXT("data")).ToSharedRef());
	const FVector HangarLift = Crew->FindDeck(FName(TEXT("hangar")))->Lift()->Location;
	Crew->SetCommanderOverride(HangarLift + FVector(-300.f, -300.f, 90.f), 180.f);
	// Two newcomers walk from the shuttle to the lift for the hangar shot.
	Bridge.Send(Crew, TEXT("roster.delta"), A::Delta({ A::Agent(TEXT("ag_new1"), TEXT("Nova"), TEXT("idle")), A::Agent(TEXT("ag_new2"), TEXT("Rook"), TEXT("idle")) }));
	Crew->ReplanNow();
	S->Camera = World->SpawnActor<ACameraActor>(FVector::ZeroVector, FRotator::ZeroRotator);
	if (APlayerController* PC = World->GetFirstPlayerController())
	{
		PC->SetViewTarget(S->Camera.Get());
	}
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(4.f));
	struct FShot
	{
		FName Deck;
		FVector Offset;
		FRotator Rotation;
		const TCHAR* File;
	};
	const TArray<FShot> Shots = {
		{ FName(TEXT("bridge")), FVector(3600.f, -700.f, 1500.f), FRotator(-38.f, 90.f, 0.f), TEXT("deck_bridge.png") },
		{ FName(TEXT("ops")), FVector(4000.f, 1200.f, 1700.f), FRotator(-40.f, 60.f, 0.f), TEXT("deck_ops.png") },
		{ FName(TEXT("engineering")), FVector(2400.f, 2000.f, 1300.f), FRotator(-40.f, 35.f, 0.f), TEXT("deck_engineering.png") },
		{ FName(TEXT("hangar")), FVector(5000.f, 2000.f, 1600.f), FRotator(-40.f, 60.f, 0.f), TEXT("deck_hangar.png") },
	};
	for (const FShot& Shot : Shots)
	{
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([S, Shot]() {
			if (ACameraActor* Camera = S->Camera.Get())
			{
				Camera->SetActorLocationAndRotation(S->Origins[Shot.Deck] + Shot.Offset, Shot.Rotation);
				Camera->GetCameraComponent()->SetFieldOfView(75.f);
			}
			return true;
		}));
		ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(1.5f));
		ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([S, Shot]() {
			FScreenshotRequest::RequestScreenshot(S->Dir / Shot.File, false, false);
			++S->Shots;
			return true;
		}));
		ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(1.f));
	}
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, S]() {
		if (UVerseCrewSubsystem* C = S->Crew.Get())
		{
			// The duty status sheet: every pawn's duty, beacon, activity, socket and rank.
			const TSharedRef<FJsonObject> Sheet = C->DumpJson();
			FVerseCrewTestWorld::WriteProof(TEXT("WP15.2"), TEXT("duty_sheet.json"), Sheet);
			TestTrue(TEXT("crew on the decks"), Sheet->GetArrayField(TEXT("crew")).Num() >= 24);
		}
		for (const TWeakObjectPtr<AActor>& Spawned : S->Props)
		{
			if (Spawned.IsValid())
			{
				Spawned->Destroy();
			}
		}
		if (S->Camera.IsValid())
		{
			S->Camera->Destroy();
		}
		TestEqual(TEXT("four deck shots requested"), S->Shots, 4);
		return true;
	}));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
