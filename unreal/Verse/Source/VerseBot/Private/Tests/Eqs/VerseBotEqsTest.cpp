#include "Audit/VerseBotFireAudit.h"
#include "Bot/VerseBotTier.h"
#include "Eqs/VerseBeliefNavFilter.h"
#include "Eqs/VerseBotEqs.h"
#include "Learning/VerseBotMatchMemory.h"
#include "Misc/AutomationTest.h"
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

#endif // WITH_DEV_AUTOMATION_TESTS
