#include "Camera/VerseDeckView.h"
#include "Decks/VerseDeckLook.h"
#include "Decks/VerseDeckManifest.h"
#include "Decks/VerseDeckSubsystem.h"
#include "Decks/VerseLiftTravel.h"
#include "Dom/JsonObject.h"
#include "Engine/GameInstance.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Space/VerseSpaceView.h"
#include "UObject/Package.h"
#include "WorldActions/VerseWorldActionReporter.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Decks.*: WP12 acceptance tests that need no world (work-packages.md WP12, A12.1, A12.5;
// parity B-01, B-02, B-06, L-02 to L-05, L-07, V-02 to V-09, W-01 to W-03, Z-11).

#define VERSE_DECKS_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseDecksTest
{
	const double WheelIn = FMath::Exp(-0.12);
	const double WheelOut = FMath::Exp(0.12);

	TSharedPtr<FJsonValue> ReadJson(const FString& Path)
	{
		FString Text;
		if (!FFileHelper::LoadFileToString(Text, *Path))
		{
			return nullptr;
		}
		TSharedPtr<FJsonValue> Value;
		const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
		FJsonSerializer::Deserialize(Reader, Value);
		return Value;
	}

	/** Today's cooked manifest (`verse.deck/1`), the parity reference of A12.1. */
	TSharedPtr<FJsonObject> TodayManifest(FName Deck)
	{
		const FString Path = FPaths::Combine(FPaths::ProjectDir(), TEXT("../../dodaios/ui/web/frontend/public/verse/decks"), Deck.ToString(), TEXT("manifest.json"));
		const TSharedPtr<FJsonValue> Value = ReadJson(Path);
		return Value.IsValid() ? Value->AsObject() : nullptr;
	}

	bool LoadDeck(FAutomationTestBase& Test, FName Deck, FVerseDeckManifest& Out)
	{
		FString Error;
		const bool bOk = FVerseDeckManifest::Load(Deck, Verse::Decks::PlacementsDir(), Out, Error);
		Test.TestTrue(FString::Printf(TEXT("deck %s loads (%s)"), *Deck.ToString(), *Error), bOk);
		return bOk;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksRegistryTest, "Verse.Decks.Registry.Order", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksRegistryTest::RunTest(const FString&)
{
	const TCHAR* Expected[] = { TEXT("bridge"), TEXT("ops"), TEXT("engineering"), TEXT("hangar") };
	const TConstArrayView<FVerseDeckInfo> Decks = Verse::Decks::All();
	TestEqual(TEXT("four decks"), Decks.Num(), 4);
	for (int32 Index = 0; Index < Decks.Num() && Index < 4; ++Index)
	{
		TestEqual(TEXT("deck order"), Decks[Index].Id, FName(Expected[Index]));
		TestEqual(TEXT("one-based number"), Decks[Index].Number, Index + 1);
		TestTrue(TEXT("level path"), Decks[Index].LevelPath.StartsWith(TEXT("/Game/Verse/Decks/")));
	}
	TestEqual(TEXT("hangar is 04"), FString::Printf(TEXT("%02d"), Verse::Decks::Find(TEXT("hangar"))->Number), FString(TEXT("04")));
	TestNull(TEXT("testbed never ships"), Verse::Decks::Find(TEXT("testbed")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksManifestParityTest, "Verse.Decks.Manifest.ParityWithToday", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksManifestParityTest::RunTest(const FString&)
{
	for (const FName Deck : { FName(TEXT("bridge")), FName(TEXT("ops")), FName(TEXT("engineering")) })
	{
		FVerseDeckManifest Manifest;
		const TSharedPtr<FJsonObject> Today = VerseDecksTest::TodayManifest(Deck);
		if (!VerseDecksTest::LoadDeck(*this, Deck, Manifest) || !TestTrue(TEXT("today's manifest is readable"), Today.IsValid()))
		{
			continue;
		}
		TSet<FString> Want;
		for (const TSharedPtr<FJsonValue>& Room : Today->GetArrayField(TEXT("rooms")))
		{
			Want.Add(TEXT("room:") + Room->AsObject()->GetStringField(TEXT("id")));
		}
		for (const TSharedPtr<FJsonValue>& Socket : Today->GetArrayField(TEXT("sockets")))
		{
			const TSharedPtr<FJsonObject> Object = Socket->AsObject();
			Want.Add(TEXT("socket:") + Object->GetStringField(TEXT("kind")) + TEXT(":") + Object->GetStringField(TEXT("id")));
		}
		for (const TSharedPtr<FJsonValue>& Station : Today->GetArrayField(TEXT("stations")))
		{
			Want.Add(TEXT("station:") + Station->AsObject()->GetStringField(TEXT("id")) + TEXT(":") + Station->AsObject()->GetStringField(TEXT("kind")));
		}
		TSet<FString> Got;
		for (const FVerseDeckRoom& Room : Manifest.Rooms)
		{
			Got.Add(TEXT("room:") + Room.Id.ToString());
		}
		for (const FVerseDeckSocket& Socket : Manifest.Sockets)
		{
			Got.Add(TEXT("socket:") + Socket.Kind.ToString() + TEXT(":") + Socket.ManifestId.ToString());
		}
		for (const FVerseDeckStation& Station : Manifest.Stations)
		{
			Got.Add(TEXT("station:") + Station.Id.ToString() + TEXT(":") + Station.Kind.ToString());
		}
		TestEqual(FString::Printf(TEXT("%s: ids of today's manifest"), *Deck.ToString()), Got.Num(), Want.Num());
		for (const FString& Id : Want)
		{
			if (!Got.Contains(Id))
			{
				AddError(FString::Printf(TEXT("%s: missing %s"), *Deck.ToString(), *Id));
			}
		}
		for (const FString& Id : Got)
		{
			if (!Want.Contains(Id))
			{
				AddError(FString::Printf(TEXT("%s: extra %s"), *Deck.ToString(), *Id));
			}
		}
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksArrivalTest, "Verse.Decks.Manifest.Arrival", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksArrivalTest::RunTest(const FString&)
{
	FVerseDeckManifest Hangar;
	if (!VerseDecksTest::LoadDeck(*this, TEXT("hangar"), Hangar))
	{
		return true;
	}
	FTransform Spawn;
	TestTrue(TEXT("first visit uses the spawn socket"), Hangar.ArrivalTransform(false, Spawn));
	// contracts/coordinates.md 3.2: commander (70, 0, 54.2) yaw 0 -> (7000, 5420, 0), heading 90.
	TestTrue(TEXT("commander spawn location"), Spawn.GetLocation().Equals(FVector(7000.0, 5420.0, 0.0), 0.01));
	TestEqual(TEXT("commander spawn heading"), Spawn.Rotator().Yaw, 90.0, 1e-3);
	FTransform ByLift;
	TestTrue(TEXT("a ride arrives at the lift"), Hangar.ArrivalTransform(true, ByLift));
	TestFalse(TEXT("lift and spawn differ"), ByLift.GetLocation().Equals(Spawn.GetLocation(), 1.0));
	const FVerseDeckStation* Arrivals = Hangar.FindStation(TEXT("arrivals"));
	TestTrue(TEXT("create_agent counter"), Arrivals && Arrivals->Kind == FName(TEXT("create_agent")));
	TestTrue(TEXT("commander stands in the lift lobby"), Hangar.RoomsAt(Spawn.GetLocation()).Contains(FName(TEXT("lift_lobby"))));
	TestEqual(TEXT("nobody stands in a room 2 m above it"), Hangar.RoomsAt(Spawn.GetLocation() + FVector(0, 0, 200)).Num(), 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksLiftRideTest, "Verse.Decks.Lift.Ride", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksLiftRideTest::RunTest(const FString&)
{
	FVerseLiftTravel Lift;
	TestFalse(TEXT("same deck: nothing rides (L-05)"), Lift.Request(TEXT("bridge"), TEXT("bridge"), 0.0, false));
	TestTrue(TEXT("ride starts"), Lift.Request(TEXT("bridge"), TEXT("ops"), 10.0, false));
	TestFalse(TEXT("no second ride while one runs"), Lift.Request(TEXT("bridge"), TEXT("hangar"), 10.1, false));
	TestFalse(TEXT("no load while the doors shut"), Lift.Tick(10.2));
	TestTrue(TEXT("load starts once the doors are shut"), Lift.Tick(10.0 + FVerseLiftTravel::DoorsS));
	TestEqual(TEXT("riding"), Lift.Phase(), EVerseLiftPhase::Riding);
	Lift.NotifyArrived(11.2);
	Lift.Tick(11.3);
	TestEqual(TEXT("doors stay shut until 150 ms after the first frame"), Lift.Phase(), EVerseLiftPhase::DoorsOpening);
	Lift.Tick(11.2 + FVerseLiftTravel::OpenAfterArrivalS);
	TestEqual(TEXT("idle after the doors open"), Lift.Phase(), EVerseLiftPhase::Idle);
	TestTrue(TEXT("doors were shut at least 400 ms (L-02)"), Lift.LastRideS() >= 0.4);
	TestEqual(TEXT("ride time"), Lift.LastRideS(), 1.35, 1e-9);
	TestFalse(TEXT("deck there"), Lift.DeckMissing());
	const TArray<EVerseLiftCue> Cues = Lift.TakeCues();
	TestEqual(TEXT("door-close, ride, door-open cues (L-07)"), Cues, TArray<EVerseLiftCue>{ EVerseLiftCue::DoorClose, EVerseLiftCue::Ride, EVerseLiftCue::DoorOpen });
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksLiftGiveUpTest, "Verse.Decks.Lift.GiveUpAndReducedMotion", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksLiftGiveUpTest::RunTest(const FString&)
{
	FVerseLiftTravel Lift;
	Lift.Request(TEXT("ops"), TEXT("hangar"), 0.0, false);
	double OpenedAt = -1.0;
	for (double T = 0.0; T < 8.0 && OpenedAt < 0.0; T += 1.0 / 60.0)
	{
		Lift.Tick(T);
		if (!Lift.IsBusy())
		{
			OpenedAt = T;
		}
	}
	TestEqual(TEXT("doors give up at 5 s +- 0.2 (L-03)"), OpenedAt, 5.0, 0.2);
	TestTrue(TEXT("deck marked missing (A-10)"), Lift.DeckMissing());

	FVerseLiftTravel Reduced;
	TestTrue(TEXT("reduced motion rides"), Reduced.Request(TEXT("ops"), TEXT("bridge"), 0.0, true));
	TestTrue(TEXT("load starts at once (L-04)"), Reduced.Tick(0.0));
	Reduced.NotifyArrived(0.3);
	TestFalse(TEXT("no door phase"), Reduced.IsBusy());
	TestEqual(TEXT("no door cues"), Reduced.TakeCues().Num(), 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksSubsystemRideTest, "Verse.Decks.Subsystem.RideWithFakeLoader", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksSubsystemRideTest::RunTest(const FString&)
{
	// A game instance without a world: the subsystem rides and reports but spawns nothing.
	UGameInstance* Instance = NewObject<UGameInstance>(GetTransientPackage());
	UVerseDeckSubsystem* Decks = NewObject<UVerseDeckSubsystem>(Instance);
	double Clock = 100.0;
	TArray<FName> Loads;
	TFunction<void(bool)> Pending;
	TArray<FVerseWorldAction> Actions;
	Decks->SetClock([&Clock]() { return Clock; });
	Decks->SetDayProvider([]() { return FString(TEXT("2026-11-02")); });
	Decks->SetPlacementsDir(Verse::Decks::PlacementsDir());
	Decks->GetReporter().Sink = [&Actions](const FVerseWorldAction& Action) { Actions.Add(Action); };
	Decks->SetLevelLoader([&Loads, &Pending](const FVerseDeckInfo& Deck, TFunction<void(bool)> Done)
		{
			Loads.Add(Deck.Id);
			Pending = MoveTemp(Done);
		});

	TestTrue(TEXT("cold load starts"), Decks->LoadDeckDirect(TEXT("bridge")));
	Clock += 1.5;
	Pending(true);
	TestEqual(TEXT("on the bridge"), Decks->GetCurrentDeck(), FName(TEXT("bridge")));
	TestEqual(TEXT("cold load time measured"), Decks->GetLastColdLoadS(), 1.5, 1e-9);
	TestTrue(TEXT("cold load within 4 s budget (A12.2, fake loader)"), Decks->GetLastColdLoadS() <= 4.0);

	TestTrue(TEXT("ride to ops"), Decks->RequestDeck(TEXT("ops")));
	TestFalse(TEXT("riding to the same target twice is refused"), Decks->RequestDeck(TEXT("ops")));
	Clock += FVerseLiftTravel::DoorsS;
	Decks->TickDecks(Clock);
	TestEqual(TEXT("the ride loads ops"), Loads, TArray<FName>{ TEXT("bridge"), TEXT("ops") });
	Clock += 0.8;
	Pending(true);
	Clock += FVerseLiftTravel::OpenAfterArrivalS;
	Decks->TickDecks(Clock);
	TestEqual(TEXT("on ops"), Decks->GetCurrentDeck(), FName(TEXT("ops")));
	TestFalse(TEXT("lift idle"), Decks->GetLift().IsBusy());
	TestTrue(TEXT("ride within 3 s (A12.2, fake loader)"), Decks->GetLift().LastRideS() <= 3.0);

	const TArray<FVerseWorldAction> Discovered = { { TEXT("deck_discovered"), TEXT("bridge") }, { TEXT("deck_discovered"), TEXT("ops") } };
	TestEqual(TEXT("deck_discovered once per deck (W-02)"), Actions, Discovered);
	Decks->NotifyVisible();
	Decks->NotifyVisible();
	TestEqual(TEXT("daily_visit once per launch (W-01)"), Actions.Last().Action, FString(TEXT("daily_visit")));
	TestEqual(TEXT("three actions"), Actions.Num(), 3);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksInspectionTest, "Verse.Decks.WorldActions.Inspection", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksInspectionTest::RunTest(const FString&)
{
	for (const FVerseDeckInfo& Info : Verse::Decks::All())
	{
		FVerseDeckManifest Deck;
		if (!VerseDecksTest::LoadDeck(*this, Info.Id, Deck))
		{
			continue;
		}
		FVerseWorldActionReporter Reporter;
		TArray<FVerseWorldAction> Actions;
		Reporter.Sink = [&Actions](const FVerseWorldAction& Action) { Actions.Add(Action); };
		// Walk through every room: stand on its first socket inside it, else its polygon centroid.
		for (int32 Pass = 0; Pass < 2; ++Pass)
		{
			for (const FVerseDeckRoom& Room : Deck.Rooms)
			{
				FVector2D Centre = FVector2D::ZeroVector;
				for (const FVector2D& Point : Room.PolygonCm)
				{
					Centre += Point / Room.PolygonCm.Num();
				}
				FVector Feet(Centre.X, Centre.Y, Room.ZCm);
				for (const FVerseDeckSocket& Socket : Deck.Sockets)
				{
					if (Socket.Room == Room.Id && Room.Contains(Socket.Transform.GetLocation()))
					{
						Feet = Socket.Transform.GetLocation();
						break;
					}
				}
				Reporter.NotifyPosition(Deck, Feet, TEXT("2026-11-02"));
			}
		}
		TestEqual(FString::Printf(TEXT("%s: every room visited"), *Info.Id.ToString()), Reporter.VisitedRooms(Info.Id).Num(), Deck.Rooms.Num());
		TestEqual(FString::Printf(TEXT("%s: one inspection for a tour, none for the second (W-03)"), *Info.Id.ToString()),
			Actions, TArray<FVerseWorldAction>{ { TEXT("inspection"), Info.Id.ToString() } });
		Reporter.NotifyPosition(Deck, Deck.Sockets[0].Transform.GetLocation(), TEXT("2026-11-03"));
		TestEqual(FString::Printf(TEXT("%s: the next day pays again"), *Info.Id.ToString()), Actions.Num(), 2);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksWorldActionGoldenTest, "Verse.Decks.WorldActions.GoldenBridgeMessage", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksWorldActionGoldenTest::RunTest(const FString&)
{
	const TSharedPtr<FJsonValue> Golden = VerseDecksTest::ReadJson(FPaths::Combine(FPaths::ProjectDir(), TEXT("Tests/Data/bridge/messages/progression.action.json")));
	if (!TestTrue(TEXT("golden fixture"), Golden.IsValid()))
	{
		return true;
	}
	const TSharedPtr<FJsonObject> Expected = Golden->AsArray()[0]->AsObject();
	const FVerseWorldAction Action{ Expected->GetObjectField(TEXT("data"))->GetStringField(TEXT("action")), Expected->GetObjectField(TEXT("data"))->GetStringField(TEXT("ref")) };
	const FString Json = FVerseWorldActionReporter::ToBridgeJson(Action, Expected->GetStringField(TEXT("id")), Expected->GetNumberField(TEXT("ts")));
	TSharedPtr<FJsonObject> Got;
	FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Got);
	if (!TestTrue(TEXT("our message parses"), Got.IsValid()))
	{
		return true;
	}
	TestEqual(TEXT("type"), Got->GetStringField(TEXT("type")), Expected->GetStringField(TEXT("type")));
	TestEqual(TEXT("id"), Got->GetStringField(TEXT("id")), Expected->GetStringField(TEXT("id")));
	TestEqual(TEXT("ts"), Got->GetNumberField(TEXT("ts")), Expected->GetNumberField(TEXT("ts")));
	TestEqual(TEXT("data.action"), Got->GetObjectField(TEXT("data"))->GetStringField(TEXT("action")), Action.Action);
	TestEqual(TEXT("data.ref"), Got->GetObjectField(TEXT("data"))->GetStringField(TEXT("ref")), Action.Ref);
	TestEqual(TEXT("no extra fields"), Got->Values.Num(), Expected->Values.Num());
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksViewModeTest, "Verse.Decks.View.Modes", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksViewModeTest::RunTest(const FString&)
{
	using namespace Verse::DeckView;
	TestEqual(TEXT("V: overview -> third"), Cycle(EVerseDeckView::Overview, true), EVerseDeckView::Third);
	TestEqual(TEXT("V: third -> first"), Cycle(EVerseDeckView::Third, true), EVerseDeckView::First);
	TestEqual(TEXT("V: first -> overview"), Cycle(EVerseDeckView::First, true), EVerseDeckView::Overview);
	TestEqual(TEXT("V skips first without eye level"), Cycle(EVerseDeckView::Third, false), EVerseDeckView::Overview);
	TestEqual(TEXT("first resolves to third without eye level"), Resolve(EVerseDeckView::First, false), EVerseDeckView::Third);
	TestEqual(TEXT("key 1"), ForKey(TEXT("One")).Get(EVerseDeckView::Third), EVerseDeckView::Overview);
	TestEqual(TEXT("keypad 3"), ForKey(TEXT("NumPadThree")).Get(EVerseDeckView::Third), EVerseDeckView::First);
	TestFalse(TEXT("key 4 picks nothing"), ForKey(TEXT("Four")).IsSet());
	TestEqual(TEXT("unknown stored view is third (V-21)"), Normalize(TEXT("ego")), EVerseDeckView::Third);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksZoomTest, "Verse.Decks.View.WheelHandover", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksZoomTest::RunTest(const FString&)
{
	using namespace VerseDecksTest;
	const FVerseShoulderTuning T;
	auto Step = [&T](const FVerseZoomState& S, double F) { return VerseZoomStep(S, F, T.MinDistanceCm, T.MaxDistanceCm, T.Handover); };

	FVerseZoomState S = Step({ EVerseDeckPerson::Third, 240.0, 0.0 }, WheelOut);
	TestEqual(TEXT("scales the distance"), S.DistanceCm, 240.0 * WheelOut, 1e-9);
	for (int32 I = 0; I < 30; ++I)
	{
		S = Step(S, WheelOut);
	}
	TestEqual(TEXT("stops at 5 m"), S.DistanceCm, T.MaxDistanceCm, 1e-9);

	S = Step({ EVerseDeckPerson::Third, 125.0, 0.0 }, WheelIn);
	TestEqual(TEXT("the notch reaching 1.2 m stops there"), S.Person, EVerseDeckPerson::Third);
	TestEqual(TEXT("at the closest distance"), S.DistanceCm, T.MinDistanceCm, 1e-9);
	TestEqual(TEXT("a step out clears the push"), Step(S, WheelOut).Push, 0.0);
	S = Step(S, WheelIn);
	TestEqual(TEXT("pushing on hands over to first person"), S.Person, EVerseDeckPerson::First);

	const FVerseZoomState First{ EVerseDeckPerson::First, T.MinDistanceCm, 0.0 };
	TestEqual(TEXT("in stays first"), Step(First, WheelIn).Person, EVerseDeckPerson::First);
	const FVerseZoomState Nudge = Step(First, FMath::Exp(20 * 0.0012));
	TestEqual(TEXT("a nudge is not enough"), Nudge.Person, EVerseDeckPerson::First);
	TestEqual(TEXT("a notch out returns to third"), Step(Nudge, FMath::Exp(80 * 0.0012)).Person, EVerseDeckPerson::Third);

	FVerseShoulderRig Rig;
	Rig.DistanceCm = 130.0;
	TestFalse(TEXT("rig: first notch stays third"), Rig.Zoom(WheelIn).IsSet());
	TestTrue(TEXT("rig: second notch reports first"), Rig.Zoom(WheelIn).Get(EVerseDeckPerson::Third) == EVerseDeckPerson::First);
	TestTrue(TEXT("rig: out reports third"), Rig.Zoom(WheelOut).Get(EVerseDeckPerson::First) == EVerseDeckPerson::Third);
	TestEqual(TEXT("rig: back at the closest distance"), Rig.DistanceCm, T.MinDistanceCm, 1e-9);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksRigTest, "Verse.Decks.View.ShoulderRig", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksRigTest::RunTest(const FString&)
{
	FVerseShoulderRig Rig;
	const FVerseRigBody Body{ FVector(1000.0, 2000.0, 0.0), 90.0 };
	Rig.SnapBehind(90.0);
	Rig.SetPerson(EVerseDeckPerson::First);
	for (int32 I = 0; I < 120; ++I)
	{
		Rig.Update(1.0 / 60.0, Body, nullptr);
	}
	TestEqual(TEXT("eyes at 165 cm +- 2 (V-06)"), Rig.Location.Z, 165.0, 2.0);
	TestEqual(TEXT("first-person FOV 85 (V-09)"), Rig.Hfov(), 85.0, 1e-6);

	// Facing a wall 10 cm ahead of the eyes: the camera stays short of it.
	const double WallY = Body.FeetCm.Y + 20.0;
	const FVerseSegmentTest Wall = [WallY](const FVector& From, const FVector& To) -> TOptional<double>
	{
		if ((From.Y - WallY) * (To.Y - WallY) > 0.0 || FMath::IsNearlyEqual(From.Y, To.Y))
		{
			return {};
		}
		return (WallY - From.Y) / (To.Y - From.Y);
	};
	Rig.Update(1.0 / 60.0, Body, Wall);
	TestTrue(TEXT("eyes stay outside the wall"), Rig.Location.Y < WallY);

	// Back to third: FOV blends to 70 over about 0.2 s (V-07) and pitch comes inside its limits (V-08).
	Rig.Look(0.0, 100000.0, true);
	TestEqual(TEXT("first person pitch down to -80"), Rig.PitchDeg, -80.0, 1e-9);
	Rig.SetPerson(EVerseDeckPerson::Third);
	double Elapsed = 0.0;
	while (Rig.FirstShare > 0.01 && Elapsed < 2.0)
	{
		Rig.Update(1.0 / 60.0, Body, nullptr);
		Elapsed += 1.0 / 60.0;
	}
	TestTrue(TEXT("blend finishes in about 0.2-0.5 s"), Elapsed > 0.1 && Elapsed < 0.6);
	TestEqual(TEXT("third-person FOV 70"), Rig.Hfov(), 70.0, 0.5);
	TestEqual(TEXT("pitch clamped back to the third-person limit"), Rig.PitchDeg, -60.0, 1e-9);

	// Same mouse delta, same turn in every view (V-10); inverted Y flips only pitch.
	FVerseShoulderRig A;
	FVerseShoulderRig B;
	B.bInvertY = true;
	A.Look(50.0, 20.0, true);
	B.Look(50.0, 20.0, true);
	TestEqual(TEXT("same yaw"), A.YawDeg, B.YawDeg, 1e-9);
	TestTrue(TEXT("inverted pitch"), A.PitchDeg < -7.0 && B.PitchDeg > -7.0);
	TestTrue(TEXT("mouse right turns right"), A.YawDeg > 0.0);

	// Third person: behind and above the head, the commander right of centre (V-05).
	FVerseShoulderRig Third;
	Third.SnapBehind(0.0);
	Third.Update(1.0 / 60.0, FVerseRigBody{ FVector::ZeroVector, 0.0 }, nullptr);
	TestTrue(TEXT("camera behind the body"), Third.Location.X < -150.0);
	TestTrue(TEXT("camera left of the body"), Third.Location.Y < 0.0);
	TestTrue(TEXT("camera above the head"), Third.Location.Z > 174.0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksOverviewTest, "Verse.Decks.View.OverviewFocusReturn", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksOverviewTest::RunTest(const FString&)
{
	FVerseOverviewCamera Overview;
	Overview.CentreCm = FVector(3600.0, 2000.0, 0.0);
	TestFalse(TEXT("nothing to return to"), Overview.Return());
	Overview.Focus(FVector(500.0, 500.0, 0.0));
	Overview.Update();
	TestTrue(TEXT("looks at the focus point"), (Overview.Location + Overview.Rotation.Vector() * Overview.DistanceCm).Equals(FVector(500.0, 500.0, 0.0), 0.01));
	TestEqual(TEXT("looks down 60 degrees"), Overview.Rotation.Pitch, -60.0, 1e-6);
	TestTrue(TEXT("return restores the framing"), Overview.Return());
	TestTrue(TEXT("centre back"), Overview.CentreCm.Equals(FVector(3600.0, 2000.0, 0.0)));
	Overview.Zoom(1000.0);
	TestEqual(TEXT("zoom clamps"), Overview.DistanceCm, Overview.MaxDistanceCm, 1e-9);
	const FVector Before = Overview.CentreCm;
	Overview.Pan(FVector2D(0.0, 1.0), 0.1);
	TestTrue(TEXT("W pans forward along the view yaw"), Overview.CentreCm.Y > Before.Y);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksLookTest, "Verse.Decks.Look.NoirLights", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksLookTest::RunTest(const FString&)
{
	using namespace Verse::DeckLook;
	FLinearColor C;
	TestTrue(TEXT("hex parses"), ParseHex(TEXT("#F2A33A"), C));
	TestTrue(TEXT("amber allowed"), BannedLightColour(C).IsEmpty());
	ParseHex(TEXT("#E3242B"), C);
	TestTrue(TEXT("signal red allowed"), BannedLightColour(C).IsEmpty());
	ParseHex(TEXT("#00C8FF"), C);
	TestEqual(TEXT("cyan banned"), BannedLightColour(C), FString(TEXT("cyan")));
	ParseHex(TEXT("#9B30FF"), C);
	TestEqual(TEXT("violet banned"), BannedLightColour(C), FString(TEXT("violet")));
	TestTrue(TEXT("cyan pixel banned"), IsBannedPixel(FColor(0, 200, 255)));
	TestFalse(TEXT("graphite pixel allowed"), IsBannedPixel(FColor(0x2A, 0x2D, 0x31)));
	TestFalse(TEXT("dark blue-ish noise below value 0.08 allowed"), IsBannedPixel(FColor(5, 10, 18)));

	for (const FVerseDeckInfo& Info : Verse::Decks::All())
	{
		const FVerseDeckLook Look = FVerseDeckLook::For(Info.Id);
		TestTrue(FString::Printf(TEXT("%s: neutral fog"), *Info.Id.ToString()), IsNeutralFog(Look.FogAlbedo));
		FVerseDeckManifest Deck;
		if (!VerseDecksTest::LoadDeck(*this, Info.Id, Deck))
		{
			continue;
		}
		int32 Count = 0;
		for (const FVerseDeckSocket& Socket : Deck.Sockets)
		{
			FLightSpec Spec;
			if (!LightFor(Socket, Look, Spec))
			{
				continue;
			}
			++Count;
			TestTrue(TEXT("work light 4300-6500 K"), Spec.Kelvin >= MinKelvin && Spec.Kelvin <= MaxKelvin);
			TestTrue(TEXT("lamp colour allowed"), Spec.bUseTemperature || BannedLightColour(Spec.Colour).IsEmpty());
			TestTrue(TEXT("light reaches somewhere"), Spec.AttenuationCm > 0.0 && Spec.Lumen > 0.0 && Spec.Lumen <= MaxLumen);
		}
		TestTrue(FString::Printf(TEXT("%s: has lights"), *Info.Id.ToString()), Count > 0);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksSpaceTest, "Verse.Decks.Space.Orbit", VERSE_DECKS_TEST_FLAGS)
bool FVerseDecksSpaceTest::RunTest(const FString&)
{
	FVerseSpaceLook Look;
	TestEqual(TEXT("orbit rate equals ORBIT_RAD_PER_S x orbitSpeed (Z-11)"), Look.OrbitRadPerS(), 7.7 / 6371.0 * 2.0, 1e-12);
	TestTrue(TEXT("set by today's name"), Look.Set(TEXT("orbitSpeed"), 1.0));
	TestEqual(TEXT("rate follows"), Look.OrbitRadPerS(), 7.7 / 6371.0, 1e-12);
	TestFalse(TEXT("unknown field refused"), Look.Set(TEXT("hue"), 1.0));
	TestTrue(TEXT("state lists the rate"), Look.ToJson(10.0).Contains(TEXT("orbit_rad_per_s")));
	TestEqual(TEXT("13 fields"), FVerseSpaceLook::FieldNames().Num(), 13);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
