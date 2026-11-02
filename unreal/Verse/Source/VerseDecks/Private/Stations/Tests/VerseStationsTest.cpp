#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "Stations/VerseStation.h"
#include "Stations/VerseStationSubsystem.h"
#include "Stations/VerseStationTypes.h"

#define VERSE_STATIONS_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// Parity S-01: the nine station kinds of today's manifests plus the armoury, nothing else.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksStationKinds, "Verse.Decks.Stations.KindEnum", VERSE_STATIONS_TEST_FLAGS)
bool FVerseDecksStationKinds::RunTest(const FString&)
{
	const UEnum* Enum = StaticEnum<EVerseStationKind>();
	TestEqual(TEXT("ten station kinds"), Enum->NumEnums() - 1, VerseStations::KindCount);
	const TCHAR* Names[] = {TEXT("agents_list"), TEXT("team"), TEXT("service_record"), TEXT("mess_call"), TEXT("games"),
		TEXT("quartermaster"), TEXT("coding_launcher"), TEXT("create_agent"), TEXT("lift"), TEXT("armoury")};
	for (int32 I = 0; I < VerseStations::KindCount; ++I)
	{
		const EVerseStationKind Kind = EVerseStationKind(I);
		TestEqual(TEXT("wire name in manifest order"), VerseStations::KindName(Kind), FName(Names[I]));
		EVerseStationKind Back = EVerseStationKind::Lift;
		TestTrue(TEXT("wire name reads back"), VerseStations::KindFromName(FName(Names[I]), Back) && Back == Kind);
		TestEqual(TEXT("prompt name key"), VerseStations::NameKey(Kind), FString::Printf(TEXT("verse.station.%s.name"), Names[I]));
		TestFalse(TEXT("English fallback present"), VerseStations::FallbackAction(Kind).IsEmpty());
	}
	EVerseStationKind Unknown;
	TestFalse(TEXT("an unknown kind is refused"), VerseStations::KindFromName(FName(TEXT("reactor_ring")), Unknown));
	return true;
}

// Parity S-12: port of eyeLevelGame.test.tsx "works the nearest station without a facing, the one in front with one".
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksStationPick, "Verse.Decks.Stations.PickWithin", VERSE_STATIONS_TEST_FLAGS)
bool FVerseDecksStationPick::RunTest(const FString&)
{
	// The commander at the origin: a console 1 m behind, another 1.6 m ahead (three.js -Z is Unreal -Y here).
	const TArray<FVector> Both = {FVector(0, 100, 0), FVector(0, -160, 0)};
	const FVector Ahead(0, -1, 0);
	const FVector Back(0, 1, 0);
	TestEqual(TEXT("nearest without a facing"), UVerseStationSubsystem::PickWithin(Both, FVector::ZeroVector, VerseStations::ReachCm, nullptr), 0);
	TestEqual(TEXT("the one in front with a facing"), UVerseStationSubsystem::PickWithin(Both, FVector::ZeroVector, VerseStations::ReachCm, &Ahead), 1);
	TestEqual(TEXT("facing the near one keeps it"), UVerseStationSubsystem::PickWithin(Both, FVector::ZeroVector, VerseStations::ReachCm, &Back), 0);
	const TArray<FVector> Alone = {FVector(0, 100, 0)};
	TestEqual(TEXT("a station behind still works when alone"), UVerseStationSubsystem::PickWithin(Alone, FVector::ZeroVector, VerseStations::ReachCm, &Ahead), 0);
	const TArray<FVector> Far = {FVector(0, VerseStations::ReachCm + 30.0, 0)};
	TestEqual(TEXT("out of reach: none"), UVerseStationSubsystem::PickWithin(Far, FVector::ZeroVector, VerseStations::ReachCm, nullptr), int32(INDEX_NONE));
	const TArray<FVector> Under = {FVector(10, 10, 0), FVector(0, -120, 0)};
	TestEqual(TEXT("one under the feet counts as in front"), UVerseStationSubsystem::PickWithin(Under, FVector::ZeroVector, VerseStations::ReachCm, &Back), 0);
	return true;
}

// WP16.6 + WP16.8: a placed station offers its prompt, and using it raises FVerseStationUsedEvent on the hub.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksStationUse, "Verse.Decks.Stations.UseRaisesEvent", VERSE_STATIONS_TEST_FLAGS)
bool FVerseDecksStationUse::RunTest(const FString&)
{
	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("VerseStationsTestWorld"));
	if (!TestNotNull(TEXT("test world"), World))
	{
		return false;
	}
	UVerseEventHub* Hub = World->GetSubsystem<UVerseEventHub>();
	UVerseStationSubsystem* Stations = World->GetSubsystem<UVerseStationSubsystem>();
	if (TestNotNull(TEXT("hub"), Hub) && TestNotNull(TEXT("station subsystem"), Stations))
	{
		TArray<FVerseStationUsedEvent> Seen;
		Hub->OnStationUsed.AddLambda([&Seen](const FVerseStationUsedEvent& E) { Seen.Add(E); });
		TArray<FVerseStationPrompt> Prompts;
		Stations->OnPromptChanged.AddLambda([&Prompts](const FVerseStationPrompt& P) { Prompts.Add(P); });

		AVerseArmouryStation* Armoury = World->SpawnActor<AVerseArmouryStation>(FVector(0, 0, 0), FRotator::ZeroRotator);
		Armoury->StationId = TEXT("hangar_armoury");
		AVerseStation* Ledger = World->SpawnActor<AVerseStation>(FVector(1000, 0, 0), FRotator::ZeroRotator);
		Ledger->StationId = TEXT("bridge_command");
		Ledger->Kind = EVerseStationKind::AgentsList;
		Armoury->DispatchBeginPlay();
		Ledger->DispatchBeginPlay();
		TestEqual(TEXT("both stations registered as use targets"), Stations->NumUseTargets(), 2);
		TestEqual(TEXT("found by id"), Stations->FindStation(TEXT("bridge_command")), Ledger);

		Stations->SetViewerOverride(FVector(120, 0, 0), FVector(-1, 0, 0));
		Stations->RefreshPrompt();
		TestTrue(TEXT("walking into reach offers the armoury prompt with the use key"),
			Stations->Prompt().IsValid() && Stations->Prompt().Label == TEXT("Armoury") && Stations->Prompt().Key == TEXT("E"));
		TestEqual(TEXT("one prompt change"), Prompts.Num(), 1);
		Stations->RefreshPrompt();
		TestEqual(TEXT("an unchanged prompt is not re-announced"), Prompts.Num(), 1);

		TestTrue(TEXT("the use key works it"), Stations->UseFocused(7));
		if (TestEqual(TEXT("one station event"), Seen.Num(), 1))
		{
			TestEqual(TEXT("kind armoury"), Seen[0].Kind, FName(TEXT("armoury")));
			TestEqual(TEXT("station id"), Seen[0].StationId, FName(TEXT("hangar_armoury")));
			TestEqual(TEXT("user id"), Seen[0].UserId, 7);
		}
		Armoury->bEnabled = false;
		Stations->RefreshPrompt();
		TestFalse(TEXT("a disabled station offers nothing"), Stations->Prompt().IsValid());
		TestFalse(TEXT("nothing in reach: the use key does nothing"), Stations->UseFocused(7));
		TestEqual(TEXT("no event from a disabled station"), Seen.Num(), 1);

		Stations->SetViewerOverride(FVector(500, 0, 0), FVector(1, 0, 0), Ledger);
		Stations->RefreshPrompt();
		TestEqual(TEXT("the crosshair station wins out of reach"), Stations->Prompt().Label, FString(TEXT("Command station")));
		Stations->UseFocused(3);
		TestTrue(TEXT("ledger event"), Seen.Num() == 2 && Seen[1].Kind == FName(TEXT("agents_list")));
	}
	World->DestroyWorld(false);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
