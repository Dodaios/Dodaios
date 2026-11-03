#include "Audit/VerseBotFireAudit.h"
#include "Bot/VerseBotTier.h"
#include "Eqs/VerseBeliefNavFilter.h"
#include "Eqs/VerseBotEqs.h"
#include "Learning/VerseBotMatchMemory.h"
#include "Misc/AutomationTest.h"
#include "Tactics/VerseBotTactics.h"
#include "Tests/Brain/Fakes/FakeVerseBotWorld.h"
#include "Tests/Brain/VerseBotTestProof.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_BOT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseBotEqsTest
{
	struct FEqsScene
	{
		FFakeVerseBotWorldQueries World;
		FFakeVerseBotBelief Belief;
		FVerseBotBeliefSummary Summary;
		FVerseSelfPercept Self;
		FVerseBotMatchMemory Memory;
		UVerseBotTier* Tier = nullptr;
		FVerseBotQueryContext Ctx;

		explicit FEqsScene(FName TierId, const FVector& BotAt, const FVector& TopAt)
		{
			FFakeVerseBotWorldQueries::BuildStandardArena(World);
			Tier = NewObject<UVerseBotTier>();
			Tier->AddToRoot();
			UVerseBotTier::ApplyStartValues(TierId, *Tier);
			Memory.Configure(*Tier);
			Self.Location = BotAt;
			Self.EyeLocation = BotAt + FVector(0, 0, 165.f);
			Self.ViewRotation = (TopAt - BotAt).Rotation();
			Summary.State = EVerseBeliefState::Tracked;
			Summary.TopCenter = TopAt;
			Summary.Confidence = 0.9f;
			Summary.SupportAgeS = 1.f;
			Summary.bPriorOnly = false;
			Summary.SpreadCm = 150.f;
			Summary.FacingYawDeg = 90.f;
			Belief.Mass = 0.7f;
			Belief.SupportedMass = 0.7f;
		}
		~FEqsScene() { Tier->RemoveFromRoot(); }

		const FVerseBotQueryContext& Build()
		{
			Belief.S = Summary;
			Ctx = FVerseBotQueryContext();
			Ctx.Self = &Self;
			Ctx.Belief = &Summary;
			Ctx.BeliefMap = &Belief;
			Ctx.World = &World;
			Ctx.Memory = &Memory;
			Ctx.Tier = Tier;
			Ctx.PreferredRangeCm = Tier->PreferredRangeM * 100.f;
			return Ctx;
		}
	};
}

// 8.6: belief contexts, EQS_Cover, EQS_PeekCorner.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotEqsCoverTest, "Verse.Bot.Eqs.Cover", VERSE_BOT_TEST_FLAGS)

bool FVerseBotEqsCoverTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotEqsTest;
	{
		FEqsScene S(TEXT("hard"), FVector(0.f, -300.f, 0.f), FVector(-500.f, 1500.f, 0.f));
		const FVerseBotQueryContext& Ctx = S.Build();
		TestTrue(TEXT("BeliefTop is the TopCluster centre"), VerseBotEqs::BeliefTop(Ctx).Equals(S.Summary.TopCenter));
		TestTrue(TEXT("BeliefFacing is the facing estimate"), VerseBotEqs::BeliefFacing(Ctx).Equals(FVector(0, 1, 0), 1e-4));
		const FVerseBotCoverResult Near = VerseBotEqs::Cover(Ctx, EVerseBotCoverMode::Near);
		TestTrue(TEXT("near cover found"), Near.bFound);
		TArray<FVector> Cells;
		VerseBotEqs::BeliefCells(Ctx, Cells);
		TestTrue(TEXT("the chosen cover is hidden from every BeliefCells item"), VerseBotEqs::HiddenFromBelief(Ctx, Near.Point.Location, Cells, !Near.Point.bHigh));
		const FVerseBotCoverResult Far = VerseBotEqs::Cover(Ctx, EVerseBotCoverMode::Far);
		TestTrue(TEXT("far cover found"), Far.bFound);
		TestTrue(TEXT("far cover is farther from the belief than near cover"),
			FVector::Dist2D(Far.Point.Location, S.Summary.TopCenter) >= FVector::Dist2D(Near.Point.Location, S.Summary.TopCenter));

		// A cover point depending on a piece believed holed is filtered.
		S.Belief.PieceStates.Add(2, EVersePieceState::Holed);
		const FVerseBotCoverResult NoHoled = VerseBotEqs::Cover(S.Build(), EVerseBotCoverMode::Near);
		TestFalse(TEXT("no cover behind a believed-holed piece"), NoHoled.bFound && NoHoled.Point.DependsOnPieces.Contains(2));
	}
	{
		// Learned danger heat (7.2) pushes cover away from where the person shoots from.
		FEqsScene S(TEXT("elite"), FVector(0.f, -300.f, 0.f), FVector(-500.f, 1500.f, 0.f));
		const FVerseBotCoverResult Before = VerseBotEqs::Cover(S.Build(), EVerseBotCoverMode::Near);
		for (int32 i = 0; i < 60; ++i)
		{
			S.Memory.RecordShotFrom(Before.Point.Location, 1.f, true);
		}
		const FVerseBotCoverResult After = VerseBotEqs::Cover(S.Build(), EVerseBotCoverMode::Near);
		TestTrue(TEXT("learned danger lowers the old spot's score"), !After.bFound || After.Point.Id != Before.Point.Id || After.Score < Before.Score);
		FVerseBotQueryContext Explore = S.Build();
		Explore.bIgnoreLearned = true;
		const FVerseBotCoverResult Explored = VerseBotEqs::Cover(Explore, EVerseBotCoverMode::Near);
		TestEqual(TEXT("exploration ignores the learned term"), Explored.Point.Id, Before.Point.Id);
	}
	{
		// PeekCorner: a peek that sees BeliefTop; the repeat penalty lowers a thrice-used edge.
		FEqsScene S(TEXT("elite"), FVector(-500.f, 440.f, 0.f), FVector(-500.f, 1500.f, 0.f));
		FVerseBotCoverPoint From;
		From.Location = FVector(-460.f, 520.f, 0.f);
		From.Facing = FVector(0, 1, 0);
		From.bHigh = true;
		From.EdgeId = 11;
		const FVerseBotPeekResult Fresh = VerseBotEqs::PeekCorner(S.Build(), From);
		TestTrue(TEXT("a peek corner is found"), Fresh.bFound);
		TestTrue(TEXT("the peek eye sees BeliefTop"), S.World.TestSight(Fresh.Eye, S.Summary.TopCenter + FVector(0, 0, 120.f)));
		FVerseBotQueryContext Repeat = S.Build();
		Repeat.RecentPeekEdges = {11, 11, 11};
		const FVerseBotPeekResult Repeated = VerseBotEqs::PeekCorner(Repeat, From);
		TestTrue(TEXT("repeat penalty lowers the score"), Repeated.Score < Fresh.Score - 0.5f);
	}
	return true;
}

// 8.7: EQS_WallbangSpot, EQS_BreachSpot, EQS_FinisherApproach; and the wall-shot authority of 4.5.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotEqsTacticalTest, "Verse.Bot.Eqs.Tactical", VERSE_BOT_TEST_FLAGS)

bool FVerseBotEqsTacticalTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotEqsTest;
	// The north panel (piece 1) is a penetrable, breachable wall at y 6.0-6.4 m.
	{
		FEqsScene S(TEXT("elite"), FVector(0.f, 300.f, 0.f), FVector(0.f, 900.f, 0.f));
		const FVerseBotWallbangResult W = VerseBotEqs::WallbangSpot(S.Build());
		TestTrue(TEXT("wallbang spot through the panel"), W.bFound);
		TestEqual(TEXT("one piece on the path"), W.Pieces, 1);
		S.Summary.bPriorOnly = true;
		TestFalse(TEXT("prior-only mass never authorises"), VerseBotEqs::WallbangSpot(S.Build()).bFound);
		S.Summary.bPriorOnly = false;
		S.Belief.SupportedMass = 0.2f;
		TestFalse(TEXT("mass below the 0.25 floor never authorises"), VerseBotEqs::WallbangSpot(S.Build()).bFound);
		S.Belief.SupportedMass = 0.7f;
		S.Summary.SupportAgeS = 4.5f;
		TestFalse(TEXT("support older than the 4 s cap never authorises"), VerseBotEqs::WallbangSpot(S.Build()).bFound);
	}
	{
		UVerseBotTier* Loose = NewObject<UVerseBotTier>();
		Loose->WallbangMinBelief = 0.05f;
		Loose->WallbangMaxSourceAgeS = 12.f;
		TestEqual(TEXT("floor 0.25 applies"), FVerseBotFireClassifier::MinBelief(*Loose), 0.25f);
		TestEqual(TEXT("cap 4 s applies"), FVerseBotFireClassifier::MaxSourceAgeS(*Loose), 4.f);
		FVerseBotFireEvidence E;
		E.bAimInTopCluster = true;
		E.bPriorOnly = false;
		E.SupportedMassAtAim = 0.24f;
		E.SupportAgeS = 1.f;
		E.TraceDamageFrac = 0.8f;
		E.TracePieces = 1;
		TestFalse(TEXT("0.24 below the floor"), FVerseBotFireClassifier::HasWallShotAuthority(E, *Loose));
		E.SupportedMassAtAim = 0.26f;
		TestTrue(TEXT("0.26 above the floor"), FVerseBotFireClassifier::HasWallShotAuthority(E, *Loose));
		E.TracePieces = 4;
		TestFalse(TEXT("more than 3 pieces"), FVerseBotFireClassifier::HasWallShotAuthority(E, *Loose));
		E.TracePieces = 1;
		E.TraceDamageFrac = 0.1f;
		TestFalse(TEXT("too little damage left"), FVerseBotFireClassifier::HasWallShotAuthority(E, *Loose));
	}
	{
		FEqsScene S(TEXT("elite"), FVector(0.f, 200.f, 0.f), FVector(0.f, 1200.f, 0.f));
		S.Self.GadgetCharges[1] = 2;
		const FVerseBotBreachResult B = VerseBotEqs::BreachSpot(S.Build());
		TestTrue(TEXT("breach spot found"), B.bFound);
		TestEqual(TEXT("the panel between bot and belief"), int32(B.PieceIndex), 1);
		TestTrue(TEXT("plant on the bot's side"), B.PlantPoint.Y < 600.f);
		TestTrue(TEXT("wait outside the self-damage radius"), FVector::Dist2D(B.WaitPoint, FVector(0.f, 620.f, 0.f)) > 300.f);
		S.Belief.PieceStates.Add(1, EVersePieceState::Breached);
		const FVerseBotBreachResult Open = VerseBotEqs::BreachSpot(S.Build());
		TestFalse(TEXT("a piece believed breached is not a breach target"), Open.bFound && Open.PieceIndex == 1);
	}
	{
		FEqsScene S(TEXT("elite"), FVector(400.f, 1000.f, 0.f), FVector(0.f, 1200.f, 0.f));
		const FVerseBotFinisherResult F = VerseBotEqs::FinisherApproach(S.Build());
		TestTrue(TEXT("finisher approach found"), F.bFound);
		TestTrue(TEXT("approach more than 100 deg off the believed facing"), VerseBotEqs::OffFacingDeg(S.Ctx, F.Approach) > 100.f);
		TestTrue(TEXT("approach within 1.5 m"), FVector::Dist2D(F.Approach, S.Summary.TopCenter) <= 150.f);
		TestTrue(TEXT("arrival within MaxStalkS"), F.ArrivalS <= S.Tier->MaxStalkS);
		S.Summary.Confidence = 0.5f;
		TestFalse(TEXT("no approach below FinisherCommitConfidence"), VerseBotEqs::FinisherApproach(S.Build()).bFound);
	}
	return true;
}

// 8.8: UVerseBeliefNavFilter rule on the piece belief.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotNavFilterTest, "Verse.Bot.Eqs.NavFilter", VERSE_BOT_TEST_FLAGS)

bool FVerseBotNavFilterTest::RunTest(const FString& Parameters)
{
	using R = EVerseNavPieceRelation;
	using P = EVersePieceState;
	struct FRow { R Rel; P State; bool bUsable; };
	const FRow Rows[] = {
		{R::None, P::Intact, true},
		{R::OpenedBy, P::Intact, false}, {R::OpenedBy, P::Damaged, false}, {R::OpenedBy, P::Holed, false},
		{R::OpenedBy, P::Breached, true}, {R::OpenedBy, P::Destroyed, true}, {R::OpenedBy, P::Repairing, false},
		{R::StandsOn, P::Intact, true}, {R::StandsOn, P::Holed, true}, {R::StandsOn, P::Destroyed, false},
	};
	for (const FRow& Row : Rows)
	{
		TestEqual(FString::Printf(TEXT("relation %d state %d"), int32(Row.Rel), int32(Row.State)),
			FVerseBeliefNavFilter::IsUsableInState(Row.Rel, Row.State), Row.bUsable);
	}
	// Belief, not truth: a breach the bot has not perceived stays closed for it (F7).
	FFakeVerseBotBelief Belief;
	TestFalse(TEXT("unperceived breach opening excluded"), FVerseBeliefNavFilter::IsUsable(R::OpenedBy, 5, Belief));
	Belief.NoteOwnPieceChange(5, P::Breached);
	TestTrue(TEXT("own breach opens it"), FVerseBeliefNavFilter::IsUsable(R::OpenedBy, 5, Belief));
	UVerseBotTier* T = NewObject<UVerseBotTier>();
	UVerseBotTier::ApplyStartValues(TEXT("normal"), *T);
	TestEqual(TEXT("link cost x NavLinkCostMul"), FVerseBeliefNavFilter::LinkCost(10.f, *T), 20.f);
	return true;
}

// 7.2 biases on EQS: peek habits (PeekShare, RepeekShare, TopPeekEdges) steer EQS_PeekCorner and
// Hold; the person's most used route steers EQS_Cover flank; each changes the decision.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotEqsLearnedTest, "Verse.Bot.Eqs.Learned", VERSE_BOT_TEST_FLAGS)

bool FVerseBotEqsLearnedTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotEqsTest;
	{
		// An open floor with one peek edge (id 7) where the believed person stands.
		FEqsScene S(TEXT("hard"), FVector::ZeroVector, FVector(1000.f, 1000.f, 0.f));
		S.World.Walls.Reset();
		S.World.Cover.Reset();
		FVerseBotCoverPoint Edge;
		Edge.Id = 7;
		Edge.EdgeId = 7;
		Edge.Location = FVector(1000.f, 1000.f, 0.f);
		Edge.Facing = FVector(-1.f, 0.f, 0.f);
		S.World.Cover.Add(Edge);
		FVerseBotCoverPoint From;
		From.Id = 3;
		From.EdgeId = 3;
		From.Location = FVector::ZeroVector;
		From.Facing = FVector(1.f, 1.f, 0.f).GetSafeNormal();
		// The person re-peeks edge 7 within 3 s every time.
		for (int32 i = 0; i < 10; ++i)
		{
			S.Memory.RecordPeek(7, EVerseBotPeekType::StepOut, float(i));
		}
		FVerseBotQueryContext Ctx = S.Build();
		Ctx.NowS = 10.f;
		const FVerseBotPeekResult Learned = VerseBotEqs::PeekCorner(Ctx, From);
		Ctx.Memory = nullptr;
		const FVerseBotPeekResult Plain = VerseBotEqs::PeekCorner(Ctx, From);
		TestTrue(TEXT("a peek is found"), Learned.bFound && Plain.bFound);
		TestTrue(TEXT("the learned peek watches the person's top peek edge"), Learned.bHasWatch && Learned.WatchEdge == 7);
		TestFalse(TEXT("no watch without learning"), Plain.bHasWatch);
		TestTrue(TEXT("PeekShare raises the peek's score"), Learned.Score > Plain.Score);
		const float Scale = VerseBotTactics::PeekHoldScale(Learned);
		TestTrue(FString::Printf(TEXT("RepeekShare holds the peek longer (x%.2f)"), Scale), Scale > 1.05f && Scale <= 1.f + 2.f * 0.35f);
		TestEqual(TEXT("no hold change without learning"), VerseBotTactics::PeekHoldScale(Plain), 1.f);
	}
	{
		// Two mirror flank points; the person's most used route runs through the east one.
		FEqsScene S(TEXT("hard"), FVector(0.f, -2000.f, 0.f), FVector::ZeroVector);
		S.World.Walls.Reset();
		S.World.Cover.Reset();
		// A wall hides both points from the only belief cell, far north.
		S.World.AddWall(-30.f, 19.6f, 30.f, 20.f, 3.f);
		S.Belief.Cells = {FVector(0.f, 3000.f, 0.f)};
		for (const float X : {-1000.f, 1000.f})
		{
			FVerseBotCoverPoint P;
			P.Id = X < 0.f ? 1 : 2;
			P.Location = FVector(X, -364.f, 0.f);
			P.Facing = FVector(0.f, 1.f, 0.f);
			P.bHigh = true;
			P.MaterialProtection = 1.f;
			S.World.Cover.Add(P);
		}
		// The same mirror pair, the person's route once through the east point, once through the west one.
		int32 Picked[2] = {INDEX_NONE, INDEX_NONE};
		for (int32 Side = 0; Side < 2; ++Side)
		{
			S.Memory.Reset();
			const float X = Side == 0 ? 1000.f : -1000.f;
			for (int32 i = 0; i < 6; ++i)
			{
				S.Memory.RecordZone(1, FVector(X, -1000.f, 0.f), float(2 * i));
				S.Memory.RecordZone(2, FVector(X, 500.f, 0.f), float(2 * i + 1));
			}
			const FVerseBotQueryContext& Ctx = S.Build();
			const FVerseBotCoverResult R = VerseBotEqs::Cover(Ctx, EVerseBotCoverMode::Flank);
			TestTrue(TEXT("flank point found"), R.bFound);
			Picked[Side] = R.bFound ? R.Point.Id : INDEX_NONE;
		}
		TestEqual(TEXT("route east: the flank cuts it at the east point"), Picked[0], 2);
		TestEqual(TEXT("route west: the flank cuts it at the west point"), Picked[1], 1);
	}
	{
		// Time slicing: a budgeted query resumes and ends with the same answer as the full run.
		FEqsScene S(TEXT("hard"), FVector(0.f, -300.f, 0.f), FVector(-500.f, 1500.f, 0.f));
		const FVerseBotQueryContext& Ctx = S.Build();
		const FVerseBotCoverResult Full = VerseBotEqs::Cover(Ctx, EVerseBotCoverMode::Near);
		FVerseBotEqsSlice Slice;
		FVerseBotCoverResult Sliced;
		int32 MaxUnits = 0;
		int32 Slices = 0;
		while (!Slice.bDone && Slices < 100)
		{
			Slice.BeginSlice(24);
			VerseBotEqs::CoverSlice(Ctx, EVerseBotCoverMode::Near, Slice, Sliced);
			MaxUnits = FMath::Max(MaxUnits, Slice.SpentUnits);
			++Slices;
		}
		TestTrue(TEXT("the sliced query finishes"), Slice.bDone);
		TestTrue(FString::Printf(TEXT("the query spans several ticks (%d slices)"), Slices), Slices > 1);
		TestTrue(TEXT("same answer as the full run"), Sliced.bFound == Full.bFound && Sliced.Point.Id == Full.Point.Id && Sliced.Score == Full.Score);
		TestTrue(FString::Printf(TEXT("one slice stays near the budget (max %d units, one candidate at most over)"), MaxUnits), MaxUnits <= 24 + 40);
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
