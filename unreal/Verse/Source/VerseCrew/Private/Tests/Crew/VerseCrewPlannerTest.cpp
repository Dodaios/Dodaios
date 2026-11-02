#include "Crew/VerseCrewCollate.h"
#include "Crew/VerseCrewDeck.h"
#include "Crew/VerseCrewPlanner.h"
#include "Crew/VerseCrewPresentation.h"
#include "Dom/JsonObject.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_CREW_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseCrewPlannerTest
{
	TSharedPtr<FJsonObject> GoldenTable()
	{
		const FString Path = FPaths::ProjectContentDir() / TEXT("Verse/Test/WP15/Golden/planner_golden.json");
		FString Text;
		TSharedPtr<FJsonObject> Root;
		if (FFileHelper::LoadFileToString(Text, *Path))
		{
			const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
			FJsonSerializer::Deserialize(Reader, Root);
		}
		return Root;
	}


	TArray<FVerseCrewMember> GoldenRosterOf(const TSharedPtr<FJsonObject>& G)
	{
		TArray<FVerseCrewMember> Crew;
		for (const TSharedPtr<FJsonValue>& V : G->GetArrayField(TEXT("roster")))
		{
			const TSharedPtr<FJsonObject> O = V->AsObject();
			FVerseCrewMember M;
			M.Id = O->GetStringField(TEXT("id"));
			M.Name = O->GetStringField(TEXT("name"));
			M.Role = O->GetStringField(TEXT("role")) == TEXT("technician") ? EVerseCrewRole::Technician : EVerseCrewRole::Officer;
			M.Duty = VerseCrew::ParseDuty(O->GetStringField(TEXT("status")));
			M.ArrivalOrder = static_cast<int64>(O->GetNumberField(TEXT("createdMs")));
			M.bLead = O->GetBoolField(TEXT("lead"));
			Crew.Add(M);
		}
		return Crew;
	}

	void CheckGoldenPlan(FAutomationTestBase& Test, const FString& Label, const FVerseCrewDeck& Deck, const FVerseCrewDeckPlan& Plan, const TSharedPtr<FJsonObject>& Want)
	{
		const TSharedPtr<FJsonObject> Placements = Want->GetObjectField(TEXT("placements"));
		Test.TestEqual(Label + TEXT(": placement count"), Plan.Placements.Num(), Placements->Values.Num());
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Placements->Values)
		{
			const FVerseCrewPlacement* Got = Plan.Placements.Find(Pair.Key);
			if (!Test.TestNotNull(FString::Printf(TEXT("%s: %s placed"), *Label, *Pair.Key), Got))
			{
				continue;
			}
			const TSharedPtr<FJsonObject> W = Pair.Value->AsObject();
			Test.TestEqual(FString::Printf(TEXT("%s: %s socket"), *Label, *Pair.Key), Got->SocketKey, W->GetStringField(TEXT("socket")));
			Test.TestEqual(FString::Printf(TEXT("%s: %s venue"), *Label, *Pair.Key), FString(VerseCrew::VenueName(Got->Intent.Venue)), W->GetStringField(TEXT("venue")));
			Test.TestEqual(FString::Printf(TEXT("%s: %s activity"), *Label, *Pair.Key), FString(VerseCrew::ActivityName(Got->Intent.Activity)), W->GetStringField(TEXT("activity")));
			Test.TestEqual(FString::Printf(TEXT("%s: %s faces commander"), *Label, *Pair.Key), Got->Intent.bFaceCommander, W->GetBoolField(TEXT("face")));
		}
		const TSharedPtr<FJsonObject> Homes = Want->GetObjectField(TEXT("homes"));
		Test.TestEqual(Label + TEXT(": home count"), Plan.Homes.Num(), Homes->Values.Num());
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Homes->Values)
		{
			const FString* Got = Plan.Homes.Find(Pair.Key);
			Test.TestEqual(FString::Printf(TEXT("%s: %s home"), *Label, *Pair.Key), Got ? *Got : FString(), Pair.Value->AsString());
		}
	}
}

using namespace VerseCrewPlannerTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewHashTest, "Verse.Crew.Planner.Hash32", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewHashTest::RunTest(const FString&)
{
	const TSharedPtr<FJsonObject> G = GoldenTable();
	if (!TestTrue(TEXT("golden table loads"), G.IsValid()))
	{
		return false;
	}
	for (const TSharedPtr<FJsonValue>& V : G->GetArrayField(TEXT("hash32")))
	{
		const TSharedPtr<FJsonObject> O = V->AsObject();
		TestEqual(FString::Printf(TEXT("hash32('%s')"), *O->GetStringField(TEXT("text"))),
			static_cast<int64>(VerseCrew::Hash32(O->GetStringField(TEXT("text")))), static_cast<int64>(O->GetNumberField(TEXT("hash"))));
	}
	// localeCompare order the planner sorts with: punctuation < digits < letters, case-blind first.
	TestTrue(TEXT("pit_p_1 < pit_s_1"), VerseCrew::LocaleCompare(TEXT("pit_p_1"), TEXT("pit_s_1")) < 0);
	TestTrue(TEXT("a_b < a1"), VerseCrew::LocaleCompare(TEXT("a_b"), TEXT("a1")) < 0);
	TestTrue(TEXT("a < B"), VerseCrew::LocaleCompare(TEXT("a"), TEXT("B")) < 0);
	TestTrue(TEXT("a < A"), VerseCrew::LocaleCompare(TEXT("a"), TEXT("A")) < 0);
	TestEqual(TEXT("equal"), VerseCrew::LocaleCompare(TEXT("ws_1:T1"), TEXT("ws_1:T1")), 0);
	FString Group;
	int32 Order = 0;
	VerseCrew::SocketGroup(TEXT("pit_p_3"), Group, Order);
	TestEqual(TEXT("pit_p_3 group"), Group, FString(TEXT("pit_p")));
	TestEqual(TEXT("pit_p_3 order"), Order, 3);
	VerseCrew::SocketGroup(TEXT("brief__01"), Group, Order);
	TestEqual(TEXT("brief__01 group"), Group, FString(TEXT("brief")));
	TestEqual(TEXT("brief__01 order"), Order, 1);
	VerseCrew::SocketGroup(TEXT("command__c"), Group, Order);
	TestEqual(TEXT("command__c"), Group + FString::FromInt(Order), FString(TEXT("command0")));
	VerseCrew::SocketGroup(TEXT("12"), Group, Order);
	TestEqual(TEXT("12"), Group + TEXT("/") + FString::FromInt(Order), FString(TEXT("/12")));
	VerseCrew::SocketGroup(TEXT("mess"), Group, Order);
	TestEqual(TEXT("mess"), Group + FString::FromInt(Order), FString(TEXT("mess0")));
	return true;
}

// parity C-07: idleVenueOf(id, t) equals the TypeScript function for 1,000 seeded pairs.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewIdleVenueGoldenTest, "Verse.Crew.Planner.IdleVenueGolden", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewIdleVenueGoldenTest::RunTest(const FString&)
{
	const TSharedPtr<FJsonObject> G = GoldenTable();
	if (!TestTrue(TEXT("golden table loads"), G.IsValid()))
	{
		return false;
	}
	int32 Rows = 0;
	int32 Wrong = 0;
	for (const TSharedPtr<FJsonValue>& V : G->GetArrayField(TEXT("idle_venue")))
	{
		const TSharedPtr<FJsonObject> O = V->AsObject();
		const VerseCrewPlanner::FIdleVenue Got = VerseCrewPlanner::IdleVenueOf(O->GetStringField(TEXT("id")), static_cast<int64>(O->GetNumberField(TEXT("t"))));
		const bool bOk = FString(VerseCrew::VenueName(Got.Venue)) == O->GetStringField(TEXT("venue")) && Got.Deck.ToString() == O->GetStringField(TEXT("deck"))
			&& FString(VerseCrew::ActivityName(Got.Activity)) == O->GetStringField(TEXT("activity"));
		Wrong += bOk ? 0 : 1;
		++Rows;
	}
	TestEqual(TEXT("golden rows"), Rows, 1000);
	TestEqual(TEXT("rows that differ from planner.ts"), Wrong, 0);
	return true;
}

// parity C-09: golden placement of a 12-officer + 4-technician roster on bridge, ops and
// engineering, and again with one idle officer gone (nobody else changes console).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewPlacementGoldenTest, "Verse.Crew.Planner.PlacementGolden", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewPlacementGoldenTest::RunTest(const FString&)
{
	const TSharedPtr<FJsonObject> G = GoldenTable();
	if (!TestTrue(TEXT("golden table loads"), G.IsValid()))
	{
		return false;
	}
	const TArray<FVerseCrewMember> Crew = GoldenRosterOf(G);
	TMap<FString, EVerseCrewRoundPart> Rounds;
	for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : G->GetObjectField(TEXT("rounds"))->Values)
	{
		Rounds.Add(Pair.Key, Pair.Value->AsString() == TEXT("speaker") ? EVerseCrewRoundPart::Speaker : EVerseCrewRoundPart::Listener);
	}
	const int64 NowMs = static_cast<int64>(G->GetNumberField(TEXT("now_ms")));
	for (const TSharedPtr<FJsonValue>& V : G->GetArrayField(TEXT("plans")))
	{
		const TSharedPtr<FJsonObject> P = V->AsObject();
		const FName DeckId(*P->GetStringField(TEXT("deck")));
		FVerseCrewDeck Deck;
		FString Error;
		if (!TestTrue(FString::Printf(TEXT("fixture deck %s: %s"), *DeckId.ToString(), *Error), VerseCrew::LoadFixtureDeck(DeckId, FVector::ZeroVector, Deck, Error)))
		{
			continue;
		}
		FVerseCrewPlanInput In;
		In.Deck = &Deck;
		In.Crew = Crew;
		In.Rounds = &Rounds;
		In.NowMs = NowMs;
		const FVerseCrewDeckPlan First = VerseCrewPlanner::PlaceOnDeck(In);
		CheckGoldenPlan(*this, DeckId.ToString() + TEXT(" first"), Deck, First, P->GetObjectField(TEXT("first")));

		TMap<FString, FString> Previous;
		for (const TPair<FString, FVerseCrewPlacement>& Pl : First.Placements)
		{
			Previous.Add(Pl.Key, Pl.Value.SocketKey);
		}
		TArray<FVerseCrewMember> Fewer = Crew.FilterByPredicate([](const FVerseCrewMember& M) { return M.Id != TEXT("ag_02"); });
		FVerseCrewPlanInput In2 = In;
		In2.Crew = Fewer;
		In2.Previous = &Previous;
		In2.Homes = &First.Homes;
		const FVerseCrewDeckPlan Second = VerseCrewPlanner::PlaceOnDeck(In2);
		CheckGoldenPlan(*this, DeckId.ToString() + TEXT(" second"), Deck, Second, P->GetObjectField(TEXT("second")));
		for (const TPair<FString, FString>& Home : First.Homes)
		{
			if (Home.Key != TEXT("ag_02") && Second.Homes.Contains(Home.Key))
			{
				TestEqual(FString::Printf(TEXT("%s keeps console after a colleague left"), *Home.Key), Second.Homes[Home.Key], Home.Value);
			}
		}
	}
	return true;
}

// parity C-10: 100 random roster refreshes: no socket twice, at least 95 % keep their socket.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewPlacementStabilityTest, "Verse.Crew.Planner.Stability", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewPlacementStabilityTest::RunTest(const FString&)
{
	TMap<FName, FVerseCrewDeck> Decks;
	for (const FName Id : { FName(TEXT("bridge")), FName(TEXT("ops")), FName(TEXT("engineering")) })
	{
		FString Error;
		FVerseCrewDeck Deck;
		if (!TestTrue(TEXT("fixture deck loads"), VerseCrew::LoadFixtureDeck(Id, FVector::ZeroVector, Deck, Error)))
		{
			return false;
		}
		Decks.Add(Id, Deck);
	}
	const EVerseCrewDuty Duties[] = { EVerseCrewDuty::Working, EVerseCrewDuty::Waiting, EVerseCrewDuty::Idle, EVerseCrewDuty::Paused, EVerseCrewDuty::Error };
	FRandomStream Rng(1507);
	TArray<FVerseCrewMember> Crew;
	for (int32 I = 0; I < 30; ++I)
	{
		FVerseCrewMember M;
		M.Id = FString::Printf(TEXT("ag_%02d"), I);
		M.Role = I < 24 ? EVerseCrewRole::Officer : EVerseCrewRole::Technician;
		M.Duty = Duties[Rng.RandRange(0, 4)];
		M.ArrivalOrder = I;
		Crew.Add(M);
	}
	TMap<FName, TMap<FString, FString>> Previous;
	TMap<FName, TMap<FString, FString>> Homes;
	int32 Kept = 0;
	int32 Comparable = 0;
	int32 Doubles = 0;
	const int64 NowMs = 1790000000000LL;
	for (int32 Refresh = 0; Refresh < 100; ++Refresh)
	{
		// A refresh: about one member in ten changes duty (what a 5 s roster refresh looks like).
		TSet<FString> Changed;
		for (FVerseCrewMember& M : Crew)
		{
			if (Refresh > 0 && Rng.FRand() < 0.1f)
			{
				M.Duty = Duties[Rng.RandRange(0, 4)];
				Changed.Add(M.Id);
			}
		}
		for (TPair<FName, FVerseCrewDeck>& Pair : Decks)
		{
			FVerseCrewPlanInput In;
			In.Deck = &Pair.Value;
			In.Crew = Crew;
			In.NowMs = NowMs;
			In.Previous = Previous.Find(Pair.Key);
			In.Homes = Homes.Find(Pair.Key);
			const FVerseCrewDeckPlan Plan = VerseCrewPlanner::PlaceOnDeck(In);
			TSet<FString> Used;
			TMap<FString, FString> Next;
			for (const TPair<FString, FVerseCrewPlacement>& P : Plan.Placements)
			{
				bool bAlready = false;
				Used.Add(P.Value.SocketKey, &bAlready);
				Doubles += bAlready ? 1 : 0;
				Next.Add(P.Key, P.Value.SocketKey);
				if (const FString* Before = In.Previous ? In.Previous->Find(P.Key) : nullptr)
				{
					if (!Changed.Contains(P.Key))
					{
						++Comparable;
						Kept += *Before == P.Value.SocketKey ? 1 : 0;
					}
				}
			}
			Previous.Add(Pair.Key, Next);
			Homes.Add(Pair.Key, Plan.Homes);
		}
	}
	TestEqual(TEXT("sockets used twice"), Doubles, 0);
	const double Share = Comparable > 0 ? static_cast<double>(Kept) / Comparable : 1.0;
	AddInfo(FString::Printf(TEXT("kept %d of %d (%.2f %%)"), Kept, Comparable, 100.0 * Share));
	TestTrue(TEXT("at least 95 % keep their socket"), Share >= 0.95);
	return true;
}

// parity C-22: plate tiles and uniforms of the 15 ranks.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewRanksTest, "Verse.Crew.Presentation.Ranks", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewRanksTest::RunTest(const FString&)
{
	FVerseCrewPresentation P;
	FString Error;
	TestTrue(FString::Printf(TEXT("data loads: %s"), *Error), P.LoadFrom(FVerseCrewPresentation::DefaultDataDir(), Error));
	const TCHAR* Plates[][2] = {
		{ TEXT("recruit"), TEXT("000010") }, { TEXT("deckhand"), TEXT("000101") }, { TEXT("technician"), TEXT("000111") },
		{ TEXT("senior_technician"), TEXT("010111") }, { TEXT("ensign"), TEXT("010000") }, { TEXT("lieutenant"), TEXT("101000") },
		{ TEXT("senior_lieutenant"), TEXT("111000") }, { TEXT("commander"), TEXT("111010") }, { TEXT("captain"), TEXT("111101") },
		{ TEXT("line_captain"), TEXT("010010") }, { TEXT("commodore"), TEXT("101010") }, { TEXT("rear_admiral"), TEXT("010101") },
		{ TEXT("vice_admiral"), TEXT("101101") }, { TEXT("admiral"), TEXT("101111") }, { TEXT("fleet_admiral"), TEXT("111111") },
	};
	TestEqual(TEXT("15 ranks"), P.Ranks().Num(), 15);
	for (const auto& Row : Plates)
	{
		const FVerseCrewRank& R = P.Rank(Row[0]);
		FString Bits;
		for (const bool bLit : R.PlateLit)
		{
			Bits += bLit ? TEXT("1") : TEXT("0");
		}
		TestEqual(FString::Printf(TEXT("%s plate"), Row[0]), Bits, FString(Row[1]));
		FVerseCrewMember M;
		M.RankId = Row[0];
		TestEqual(FString::Printf(TEXT("%s uniform is its tier's"), Row[0]), P.LookOf(M).Uniform, P.TierStyle(R.Tier).Uniform);
	}
	TestEqual(TEXT("unknown rank falls back to the first"), P.Rank(TEXT("galactic_overlord")).Id, FString(TEXT("recruit")));
	TestEqual(TEXT("level 14 is lieutenant"), P.RankForLevel(14).Id, FString(TEXT("lieutenant")));
	TestEqual(TEXT("level 13 is ensign"), P.RankForLevel(13).Id, FString(TEXT("ensign")));
	return true;
}

// A15.2: each duty value maps to its presentation; an unknown value maps to idle.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewDutyMappingTest, "Verse.Crew.Presentation.DutyMapping", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewDutyMappingTest::RunTest(const FString&)
{
	FVerseCrewPresentation P;
	FString Error;
	TestTrue(FString::Printf(TEXT("data loads: %s"), *Error), P.LoadFrom(FVerseCrewPresentation::DefaultDataDir(), Error));
	struct FRow
	{
		const TCHAR* Raw;
		EVerseCrewDuty Duty;
		EVerseCrewBeacon Beacon;
		bool bOnDuty;
	};
	const FRow Rows[] = {
		{ TEXT("working"), EVerseCrewDuty::Working, EVerseCrewBeacon::Steady, true },
		{ TEXT("waiting"), EVerseCrewDuty::Waiting, EVerseCrewBeacon::SlowPulse, true },
		{ TEXT("idle"), EVerseCrewDuty::Idle, EVerseCrewBeacon::None, false },
		{ TEXT("paused"), EVerseCrewDuty::Paused, EVerseCrewBeacon::None, false },
		{ TEXT("error"), EVerseCrewDuty::Error, EVerseCrewBeacon::SlowPulse, true },
		{ TEXT("on_leave"), EVerseCrewDuty::Idle, EVerseCrewBeacon::None, false },
		{ TEXT(""), EVerseCrewDuty::Idle, EVerseCrewBeacon::None, false },
		{ TEXT("WORKING"), EVerseCrewDuty::Idle, EVerseCrewBeacon::None, false },
	};
	TSet<uint32> Colours;
	for (const FRow& Row : Rows)
	{
		const FVerseCrewDutyLook& Look = P.DutyLookOf(Row.Raw);
		TestEqual(FString::Printf(TEXT("'%s' duty"), Row.Raw), static_cast<int32>(Look.Duty), static_cast<int32>(Row.Duty));
		TestEqual(FString::Printf(TEXT("'%s' beacon"), Row.Raw), static_cast<int32>(Look.Beacon), static_cast<int32>(Row.Beacon));
		TestEqual(FString::Printf(TEXT("'%s' ring on duty"), Row.Raw), Look.bOnDuty, Row.bOnDuty);
		Colours.Add(Look.Colour.ToFColor(true).ToPackedARGB());
	}
	TestEqual(TEXT("five distinct status colours"), Colours.Num(), 5);
	// The status colours stay in the Verse palette: never cyan or violet (README Look).
	for (const EVerseCrewDuty D : { EVerseCrewDuty::Working, EVerseCrewDuty::Waiting, EVerseCrewDuty::Idle, EVerseCrewDuty::Paused, EVerseCrewDuty::Error })
	{
		const FLinearColor Hsv = P.DutyLook(D).Colour.LinearRGBToHSV();
		const bool bBanned = Hsv.G > 0.25f && Hsv.R >= 170.f && Hsv.R <= 300.f;
		TestFalse(FString::Printf(TEXT("%s colour is not cyan or violet"), VerseCrew::DutyName(D)), bBanned);
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
