#include "Framework/Application/SlateApplication.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "ServiceRecord/SVerseServiceRecord.h"
#include "ServiceRecord/VerseServiceRecordModel.h"
#include "ServiceRecord/VerseServiceRecordSubsystem.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.UI.ServiceRecord.*: the Unreal service record of WP21.7 against the G0.11 fake bridge's
// `awards` scenario (unreal/Verse/Tests/Data/bridge/scenarios/awards.json).

#define VERSE_RECORD_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseRecordTest
{
	TSharedPtr<FJsonObject> Scenario(FAutomationTestBase& Test)
	{
		const FString Path = FPaths::Combine(FPaths::ProjectDir(), TEXT("Tests/Data/bridge/scenarios/awards.json"));
		FString Text;
		TSharedPtr<FJsonObject> Root;
		if (!Test.TestTrue(TEXT("awards scenario is readable"), FFileHelper::LoadFileToString(Text, *Path)))
		{
			return nullptr;
		}
		const TSharedRef<TJsonReader<TCHAR>> Reader = TJsonReaderFactory<TCHAR>::Create(Text);
		if (!Test.TestTrue(TEXT("awards scenario parses"), FJsonSerializer::Deserialize(Reader, Root) && Root.IsValid()))
		{
			return nullptr;
		}
		return Root;
	}

	TSharedPtr<FJsonObject> Snapshot(const FJsonObject& Scenario)
	{
		return Scenario.GetObjectField(TEXT("state"))->GetObjectField(TEXT("progression.snapshot"));
	}

	/** Feed every `progression.awarded` step of the scenario; returns how many queued a notice. */
	int32 PlayAwards(const FJsonObject& Scenario, FVerseServiceRecordModel& Model)
	{
		int32 Queued = 0;
		for (const TSharedPtr<FJsonValue>& Step : Scenario.GetArrayField(TEXT("steps")))
		{
			const TSharedPtr<FJsonObject>* Frame = nullptr;
			if (Step->AsObject()->TryGetObjectField(TEXT("frame"), Frame) && (*Frame)->GetStringField(TEXT("type")) == TEXT("progression.awarded"))
			{
				Queued += Model.ApplyAwarded(*(*Frame)->GetObjectField(TEXT("data"))) ? 1 : 0;
			}
		}
		return Queued;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseRecordCurveTest, "Verse.UI.ServiceRecord.Rulebook", VERSE_RECORD_TEST_FLAGS)
bool FVerseRecordCurveTest::RunTest(const FString& Parameters)
{
	// Reference numbers from dodaios/progression/rules.py (progress_for_xp, total_xp_for_level).
	TestEqual(TEXT("level 1 -> 2 costs 40"), FVerseServiceRecordModel::XpToNext(1), int64(40));
	TestEqual(TEXT("level 10 -> 11 costs 320"), FVerseServiceRecordModel::XpToNext(10), int64(320));
	TestEqual(TEXT("level 49 -> 50 costs 1805"), FVerseServiceRecordModel::XpToNext(49), int64(1805));
	TestEqual(TEXT("cap costs nothing"), FVerseServiceRecordModel::XpToNext(50), int64(0));
	TestEqual(TEXT("level 50 total"), FVerseServiceRecordModel::TotalXpForLevel(50), int64(43230));
	TestEqual(TEXT("39 XP is level 1"), FVerseServiceRecordModel::LevelForXp(39), 1);
	TestEqual(TEXT("40 XP is level 2"), FVerseServiceRecordModel::LevelForXp(40), 2);
	TestEqual(TEXT("5230 XP is level 18"), FVerseServiceRecordModel::LevelForXp(5230), 18);
	TestEqual(TEXT("15 ranks"), FVerseServiceRecordModel::Ladder().Num(), 15);
	TestEqual(TEXT("level 14 holds lieutenant"), FVerseServiceRecordModel::RankFor(14).Id, FName(TEXT("lieutenant")));
	TestEqual(TEXT("level 16 still lieutenant"), FVerseServiceRecordModel::RankFor(16).Id, FName(TEXT("lieutenant")));
	TestEqual(TEXT("next after 14"), FVerseServiceRecordModel::NextRank(14)->Id, FName(TEXT("senior_lieutenant")));
	TestNull(TEXT("nothing above the top"), FVerseServiceRecordModel::NextRank(50));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseRecordSnapshotTest, "Verse.UI.ServiceRecord.Snapshot", VERSE_RECORD_TEST_FLAGS)
bool FVerseRecordSnapshotTest::RunTest(const FString& Parameters)
{
	using namespace VerseRecordTest;
	const TSharedPtr<FJsonObject> Root = Scenario(*this);
	if (!Root.IsValid())
	{
		return false;
	}
	FVerseServiceRecordModel Model;
	TestTrue(TEXT("snapshot applies"), Model.ApplySnapshot(*Snapshot(*Root)));
	const FVerseCommanderRecord& C = Model.Commander();
	TestEqual(TEXT("level"), C.Level, 14);
	TestEqual(TEXT("total xp"), C.TotalXp, int64(5230));
	TestEqual(TEXT("into level as the server says"), C.IntoLevel, int64(130));
	TestEqual(TEXT("for next as the server says"), C.ForNext, int64(600));
	TestEqual(TEXT("told seq"), Model.ToldSeq(), int64(897));
	const FVerseDuelTotals& D = Model.Duels();
	TestEqual(TEXT("sets"), D.Matches, 12);
	TestEqual(TEXT("wins"), D.Wins, 7);
	TestEqual(TEXT("losses"), D.Losses, 5);
	TestEqual(TEXT("headshots"), D.Headshots, 31);
	TestEqual(TEXT("finishers"), D.Finishers, 4);
	TestEqual(TEXT("best streak"), D.BestStreak, 6);
	TestTrue(TEXT("K/D 96 / 81"), FMath::IsNearlyEqual(D.KillDeathRatio(), 96.f / 81.f));
	TestEqual(TEXT("hard tier"), D.ByTier.FindRef(TEXT("hard")), FIntPoint(5, 3));
	FJsonObject NotASnapshot;
	TestFalse(TEXT("a frame without subjects is refused"), Model.ApplySnapshot(NotASnapshot));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseRecordToldTest, "Verse.UI.ServiceRecord.PromotionTold", VERSE_RECORD_TEST_FLAGS)
bool FVerseRecordToldTest::RunTest(const FString& Parameters)
{
	using namespace VerseRecordTest;
	const TSharedPtr<FJsonObject> Root = Scenario(*this);
	if (!Root.IsValid())
	{
		return false;
	}
	TSharedRef<FVerseServiceRecordModel> Model = MakeShared<FVerseServiceRecordModel>();
	TArray<int64> Told;
	Model->SendTold = [&Told](int64 Seq) { Told.Add(Seq); };
	Model->ApplySnapshot(*Snapshot(*Root));
	TestEqual(TEXT("only the commander's level-up queues a notice"), PlayAwards(*Root, *Model), 1);
	const FVersePromotion* Pending = Model->PendingPromotion();
	if (!TestNotNull(TEXT("a promotion waits"), Pending))
	{
		return false;
	}
	TestEqual(TEXT("seq 905"), Pending->Seq, int64(905));
	TestEqual(TEXT("level 15"), Pending->Level, 15);
	TestFalse(TEXT("14 -> 15 keeps the rank"), Pending->IsNewRank());
	TestEqual(TEXT("commander now level 15"), Model->Commander().Level, 15);

	// No screen: the notice waits and nothing is told.
	FVersePromotionPresenter Headless(Model, [](const FVersePromotion&) { return false; }, []() {});
	for (int32 I = 0; I < 50; ++I)
	{
		Headless.Tick(0.1f);
	}
	TestEqual(TEXT("nothing told without a screen"), Told.Num(), 0);

	// On screen for NoticeSeconds, then told exactly once.
	int32 Shows = 0;
	int32 Hides = 0;
	FVersePromotionPresenter Presenter(Model, [&Shows](const FVersePromotion&) { ++Shows; return true; }, [&Hides]() { ++Hides; });
	Presenter.Tick(0.f);
	TestTrue(TEXT("on screen"), Presenter.IsShowing());
	Presenter.Tick(FVersePromotionPresenter::NoticeSeconds * 0.5f);
	TestEqual(TEXT("not told while on screen"), Told.Num(), 0);
	Presenter.Tick(FVersePromotionPresenter::NoticeSeconds);
	TestEqual(TEXT("progression.told sent once"), Told.Num(), 1);
	TestEqual(TEXT("with seq 905"), Told.Num() > 0 ? Told[0] : int64(0), int64(905));
	TestEqual(TEXT("shown once, hidden once"), Shows * 10 + Hides, 11);
	for (int32 I = 0; I < 50; ++I)
	{
		Presenter.Tick(0.1f);
	}
	TestEqual(TEXT("no second notice"), Shows, 1);

	// A level-up shown once is never shown again: a replay of the award or an older snapshot.
	PlayAwards(*Root, *Model);
	Model->ApplySnapshot(*Snapshot(*Root));
	TestNull(TEXT("replay queues nothing"), Model->PendingPromotion());
	TestEqual(TEXT("told seq kept"), Model->ToldSeq(), int64(905));

	// A promotion the web app showed first (told_seq moved past it) is dropped untold.
	TSharedRef<FVerseServiceRecordModel> Fresh = MakeShared<FVerseServiceRecordModel>();
	Fresh->SendTold = [&Told](int64 Seq) { Told.Add(Seq); };
	Fresh->ApplySnapshot(*Snapshot(*Root));
	PlayAwards(*Root, *Fresh);
	FString SnapshotText;
	FJsonSerializer::Serialize(Snapshot(*Root).ToSharedRef(), TJsonWriterFactory<>::Create(&SnapshotText));
	TSharedPtr<FJsonObject> Later;
	FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(SnapshotText), Later);
	Later->SetNumberField(TEXT("told_seq"), 905);
	Fresh->ApplySnapshot(*Later);
	TestNull(TEXT("told elsewhere: dropped"), Fresh->PendingPromotion());
	TestEqual(TEXT("and not told again"), Told.Num(), 1);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseRecordViewTest, "Verse.UI.ServiceRecord.View", VERSE_RECORD_TEST_FLAGS)
bool FVerseRecordViewTest::RunTest(const FString& Parameters)
{
	using namespace VerseRecordTest;
	const TSharedPtr<FJsonObject> Root = Scenario(*this);
	if (!Root.IsValid())
	{
		return false;
	}
	TSharedRef<FVerseServiceRecordModel> Model = MakeShared<FVerseServiceRecordModel>();
	Model->ApplySnapshot(*Snapshot(*Root));
	TMap<FString, FText> Facts = SVerseServiceRecord::DescribeFacts(*Model);
	auto Fact = [&Facts](const TCHAR* Key) { const FText* T = Facts.Find(Key); return T ? T->ToString() : FString(); };
	TestEqual(TEXT("rank"), Fact(TEXT("rank")), FString(TEXT("Lieutenant")));
	TestEqual(TEXT("level"), Fact(TEXT("level")), FString(TEXT("14")));
	TestEqual(TEXT("next rank"), Fact(TEXT("next")), FString(TEXT("Senior Lieutenant")));
	TestEqual(TEXT("sets"), Fact(TEXT("sets")), FString(TEXT("12")));
	TestEqual(TEXT("won / lost"), Fact(TEXT("won_lost")), FString(TEXT("7 / 5")));
	TestEqual(TEXT("K/D"), Fact(TEXT("kd")), FString(TEXT("1.19")));
	TestEqual(TEXT("headshots"), Fact(TEXT("headshots")), FString(TEXT("31")));
	TestEqual(TEXT("finishers"), Fact(TEXT("finishers")), FString(TEXT("4")));
	TestEqual(TEXT("best streak"), Fact(TEXT("best_streak")), FString(TEXT("6")));

	PlayAwards(*Root, *Model);
	Facts = SVerseServiceRecord::DescribeFacts(*Model);
	TestEqual(TEXT("live: level after the award"), Fact(TEXT("level")), FString(TEXT("15")));

	FVersePromotion Promotion;
	Promotion.Level = 21;
	Promotion.PreviousLevel = 20;
	Promotion.RankId = TEXT("commander");
	Promotion.PreviousRankId = TEXT("senior_lieutenant");
	if (!FSlateApplication::IsInitialized())
	{
		AddInfo(TEXT("no Slate application in this run; the widgets themselves are not built"));
		return true;
	}
	TSharedRef<SVerseServiceRecord> View = SNew(SVerseServiceRecord, Model);
	TestTrue(TEXT("record widget builds"), View->GetChildren()->Num() > 0);
	TSharedRef<SVersePromotionNotice> Notice = SNew(SVersePromotionNotice, Promotion);
	TestEqual(TEXT("new rank headline"), Notice->Headline().ToString(), FString(TEXT("PROMOTED")));
	TestEqual(TEXT("new rank detail"), Notice->Detail().ToString(), FString(TEXT("Commander, level 21")));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
