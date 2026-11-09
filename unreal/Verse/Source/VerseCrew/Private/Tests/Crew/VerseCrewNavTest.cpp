#include "Crew/VerseCrewPawn.h"
#include "Crew/VerseCrewSubsystem.h"
#include "HAL/PlatformTime.h"
#include "Misc/AutomationTest.h"
#include "Tests/Crew/Fakes/VerseCrewTestWorld.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_CREW_NAV_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseCrewNavTest
{
	/**
	 * Where crew stands at each station of a deck (its stand socket, else a seat, else any of
	 * its sockets), plus the deck's entry points: the lift and every spawn.
	 */
	TMap<FString, FVector> StationPoints(const FVerseCrewDeck& Deck)
	{
		TMap<FString, FVector> Points;
		TMap<FString, int32> Rank;
		for (const FVerseCrewSocket& Socket : Deck.Sockets)
		{
			if (Socket.Kind == EVerseCrewSocketKind::Lift || Socket.Kind == EVerseCrewSocketKind::Spawn)
			{
				Points.Add(Socket.Key(), Socket.Location);
				continue;
			}
			if (Socket.StationId.IsEmpty())
			{
				continue;
			}
			const int32 R = Socket.Kind == EVerseCrewSocketKind::Stand ? 0 : (Socket.Kind == EVerseCrewSocketKind::Seat ? 1 : 2);
			const int32* Have = Rank.Find(Socket.StationId);
			if (!Have || R < *Have)
			{
				Rank.Add(Socket.StationId, R);
				Points.Add(Socket.StationId, Socket.Location);
			}
		}
		return Points;
	}
}

using namespace VerseCrewNavTest;

// Parity C-18, part 1: on every deck a Recast path exists between every pair of stations.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewNavStationPathsTest, "Verse.Crew.Nav.StationPaths", VERSE_CREW_NAV_TEST_FLAGS)
bool FVerseCrewNavStationPathsTest::RunTest(const FString&)
{
	using A = FVerseCrewTestWorld;
	FVerseCrewTestWorld W;
	FString Error;
	const TArray<FName> Decks = { FName(TEXT("bridge")), FName(TEXT("ops")), FName(TEXT("engineering")), FName(TEXT("hangar")) };
	double BuildMs = 0.0;
	if (!TestTrue(TEXT("test world"), W.IsValid()) || !TestTrue(FString::Printf(TEXT("decks: %s"), *Error), W.LoadDecks(Decks, Error))
		|| !TestTrue(FString::Printf(TEXT("navmesh: %s"), *Error), W.BuildNav(Decks, Error, &BuildMs)))
	{
		return false;
	}
	AddInfo(FString::Printf(TEXT("navmesh build %.0f ms: %s"), BuildMs, *W.NavDiag));
	const TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
	Report->SetNumberField(TEXT("nav_build_ms"), BuildMs);
	TArray<TSharedPtr<FJsonValue>> Rows;
	int32 AllPairs = 0;
	int32 AllMissing = 0;
	for (const FName& DeckId : Decks)
	{
		const FVerseCrewDeck* Deck = W.Crew->FindDeck(DeckId);
		const TMap<FString, FVector> Points = StationPoints(*Deck);
		TArray<FString> Ids;
		Points.GetKeys(Ids);
		Ids.Sort();
		int32 Pairs = 0;
		int32 Missing = 0;
		double MaxMs = 0.0;
		double SumMs = 0.0;
		TArray<FString> MissingPairs;
		for (int32 I = 0; I < Ids.Num(); ++I)
		{
			for (int32 J = I + 1; J < Ids.Num(); ++J)
			{
				TArray<FVector> Path;
				const FVector Up(0.f, 0.f, 90.f);
				const double Start = FPlatformTime::Seconds();
				const bool bFound = W.Crew->FindNavPath(Points[Ids[I]] + Up, Points[Ids[J]] + Up, Path);
				const double Ms = (FPlatformTime::Seconds() - Start) * 1000.0;
				MaxMs = FMath::Max(MaxMs, Ms);
				SumMs += Ms;
				++Pairs;
				if (!bFound)
				{
					++Missing;
					if (MissingPairs.Num() < 8)
					{
						MissingPairs.Add(Ids[I] + TEXT(" -> ") + Ids[J]);
					}
				}
			}
		}
		TestTrue(FString::Printf(TEXT("%s: at least 2 stations (%d)"), *DeckId.ToString(), Ids.Num()), Ids.Num() >= 2);
		TestEqual(FString::Printf(TEXT("%s: a Recast path between every station pair (%d pairs; missing: %s)"), *DeckId.ToString(), Pairs,
					  *FString::Join(MissingPairs, TEXT(", "))),
			Missing, 0);
		AddInfo(FString::Printf(TEXT("%s: %d stations, %d pairs, %d missing, path query mean %.3f ms max %.3f ms"), *DeckId.ToString(), Ids.Num(), Pairs, Missing,
			Pairs ? SumMs / Pairs : 0.0, MaxMs));
		const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
		Row->SetStringField(TEXT("deck"), DeckId.ToString());
		Row->SetNumberField(TEXT("stations"), Ids.Num());
		Row->SetNumberField(TEXT("pairs"), Pairs);
		Row->SetNumberField(TEXT("missing"), Missing);
		Row->SetNumberField(TEXT("query_ms_mean"), Pairs ? SumMs / Pairs : 0.0);
		Row->SetNumberField(TEXT("query_ms_max"), MaxMs);
		Rows.Add(MakeShared<FJsonValueObject>(Row));
		AllPairs += Pairs;
		AllMissing += Missing;
	}
	Report->SetArrayField(TEXT("decks"), Rows);
	Report->SetNumberField(TEXT("pairs"), AllPairs);
	Report->SetNumberField(TEXT("missing"), AllMissing);
	A::WriteProof(TEXT("WP15.3"), TEXT("station_paths.json"), Report);
	return true;
}

// Parity C-18, part 2: 20 pawns crossing the ops corridor from both ends at once follow
// Recast paths, never overlap their capsules (checked on every tick) and all get through.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewNavCorridorTest, "Verse.Crew.Nav.CorridorCrossing", VERSE_CREW_NAV_TEST_FLAGS)
bool FVerseCrewNavCorridorTest::RunTest(const FString&)
{
	using A = FVerseCrewTestWorld;
	FVerseCrewTestWorld W;
	FString Error;
	const FName Ops(TEXT("ops"));
	if (!TestTrue(TEXT("test world"), W.IsValid()) || !TestTrue(FString::Printf(TEXT("deck: %s"), *Error), W.LoadDecks({ Ops }, Error))
		|| !TestTrue(FString::Printf(TEXT("navmesh: %s"), *Error), W.BuildNav({ Ops }, Error)))
	{
		return false;
	}
	// The ops main corridor (deck cm): x 420 to 9180, y 2760 to 3240. Two counter-flows of
	// ten: eastbound on the two southern lanes, westbound on the two northern ones, five ranks
	// 1 m apart; the front rank heads for the far end of the other side.
	const FVector Origin = W.Crew->FindDeck(Ops)->OriginCm;
	const float EastLanes[] = { 2830.f, 2915.f };
	const float WestLanes[] = { 3085.f, 3170.f };
	TArray<FString> Ids;
	for (int32 Lane = 0; Lane < 2; ++Lane)
	{
		for (int32 Rank = 0; Rank < 5; ++Rank)
		{
			const FString EastId = FString::Printf(TEXT("walker_e%d%d"), Lane, Rank);
			const FString WestId = FString::Printf(TEXT("walker_w%d%d"), Lane, Rank);
			TestTrue(TEXT("eastbound walker"), W.Crew->SpawnScriptedWalker(EastId, Ops, Origin + FVector(1000.f + 100.f * Rank, EastLanes[Lane], 90.f),
				Origin + FVector(8000.f + 100.f * Rank, EastLanes[Lane], 90.f)));
			TestTrue(TEXT("westbound walker"), W.Crew->SpawnScriptedWalker(WestId, Ops, Origin + FVector(8000.f + 100.f * Rank, WestLanes[Lane], 90.f),
				Origin + FVector(1000.f + 100.f * Rank, WestLanes[Lane], 90.f)));
			Ids.Add(EastId);
			Ids.Add(WestId);
		}
	}
	const float MinGap = 2.f * W.Crew->GetTuning().CrewRadiusCm;
	// Separation leaves capsules exactly touching; a hair of tolerance for float rounding.
	const float Tolerance = 0.5f;
	int32 OverlapTicks = 0;
	float ClosestCm = TNumericLimits<float>::Max();
	double DoneAt = -1.0;
	const float Dt = 1.f / 30.f;
	int32 Ticks = 0;
	for (; Ticks < 120 * 30; ++Ticks)
	{
		W.Crew->Tick(Dt);
		const TArray<AVerseCrewPawn*> Pawns = W.Crew->GetPawns();
		bool bOverlap = false;
		for (int32 I = 0; I < Pawns.Num(); ++I)
		{
			for (int32 J = I + 1; J < Pawns.Num(); ++J)
			{
				const float D = static_cast<float>(FVector::Dist2D(Pawns[I]->GetActorLocation(), Pawns[J]->GetActorLocation()));
				ClosestCm = FMath::Min(ClosestCm, D);
				bOverlap = bOverlap || D < MinGap - Tolerance;
			}
		}
		OverlapTicks += bOverlap ? 1 : 0;
		bool bAll = Pawns.Num() == Ids.Num();
		for (const FString& Id : Ids)
		{
			bAll = bAll && W.Crew->HasArrived(Id);
		}
		if (bAll)
		{
			DoneAt = W.Crew->GetClockSeconds();
			break;
		}
	}
	const FVerseCrewStats& Stats = W.Crew->GetStats();
	AddInfo(FString::Printf(TEXT("crossing done at %.1f s; closest pair %.1f cm (capsules touch at %.0f cm); overlap ticks %d; nav paths %d, fallbacks %d"),
		DoneAt, ClosestCm, MinGap, OverlapTicks, Stats.NavPaths, Stats.NavFallbacks));
	TestEqual(TEXT("20 walkers"), W.Crew->GetPawns().Num(), 20);
	TestTrue(FString::Printf(TEXT("all 20 crossed within 120 s (%.1f s)"), DoneAt), DoneAt > 0.0);
	TestEqual(TEXT("no capsule overlap on any tick of the crossing"), OverlapTicks, 0);
	TestEqual(TEXT("every walk follows a Recast path"), Stats.NavPaths, 20);
	TestEqual(TEXT("no straight-line fallback"), Stats.NavFallbacks + Stats.NavBlocked, 0);
	TestEqual(TEXT("no stuck walker"), Stats.StuckEvents, 0);
	TestEqual(TEXT("nobody had to squeeze past"), Stats.CrowdYields, 0);
	const TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
	Report->SetNumberField(TEXT("walkers"), Ids.Num());
	Report->SetNumberField(TEXT("crossing_s"), DoneAt);
	Report->SetNumberField(TEXT("ticks"), Ticks);
	Report->SetNumberField(TEXT("closest_pair_cm"), ClosestCm);
	Report->SetNumberField(TEXT("capsule_gap_cm"), MinGap);
	Report->SetNumberField(TEXT("overlap_ticks"), OverlapTicks);
	Report->SetNumberField(TEXT("nav_paths"), Stats.NavPaths);
	Report->SetNumberField(TEXT("stuck"), Stats.StuckEvents);
	A::WriteProof(TEXT("WP15.3"), TEXT("corridor_crossing.json"), Report);
	return true;
}

// Without a navmesh the crew still walks where the straight line is clear, and counts it.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewNavFallbackTest, "Verse.Crew.Nav.Fallback", VERSE_CREW_NAV_TEST_FLAGS)
bool FVerseCrewNavFallbackTest::RunTest(const FString&)
{
	FVerseCrewTestWorld W;
	FString Error;
	const FName Ops(TEXT("ops"));
	if (!TestTrue(TEXT("deck"), W.LoadDecks({ Ops }, Error)))
	{
		return false;
	}
	TestFalse(TEXT("no navmesh in a bare world"), W.Crew->HasNavigation());
	const FVector Origin = W.Crew->FindDeck(Ops)->OriginCm;
	TestTrue(TEXT("walker"), W.Crew->SpawnScriptedWalker(TEXT("walker"), Ops, Origin + FVector(1000.f, 3000.f, 90.f), Origin + FVector(2000.f, 3000.f, 90.f)));
	W.Run(15.f);
	TestTrue(TEXT("it arrived on the straight line"), W.Crew->HasArrived(TEXT("walker")));
	TestEqual(TEXT("one walk without a navmesh"), W.Crew->GetStats().NavMissing, 1);
	TestEqual(TEXT("counted as a straight-line fallback"), W.Crew->GetStats().NavFallbacks, 1);
	TestEqual(TEXT("no nav path"), W.Crew->GetStats().NavPaths, 0);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
