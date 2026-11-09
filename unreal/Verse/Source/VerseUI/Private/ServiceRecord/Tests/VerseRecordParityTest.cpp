#include "Core/VerseUiStrings.h"
#include "Dom/JsonObject.h"
#include "Engine/GameInstance.h"
#include "Framework/Application/SlateApplication.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Notices/VerseQuietStack.h"
#include "Serialization/JsonReader.h"
#include "UObject/Package.h"
#include "Serialization/JsonSerializer.h"
#include "ServiceRecord/SVerseServiceRecord.h"
#include "ServiceRecord/VerseRankPlate.h"
#include "ServiceRecord/VerseRecordPages.h"
#include "ServiceRecord/VerseServiceRecordModel.h"
#include "ServiceRecord/VerseServiceRecordSubsystem.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Parity.R.*: the five pages of the service record and the promotion moment (parity.md
// rows R-04 to R-11 and R-13), against a seeded progression snapshot
// (unreal/Verse/Tests/Data/progression/record_snapshot.json).

#define VERSE_RECORD_PARITY_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseRecordParity
{
	using FPages = FVerseRecordPages;

	TSharedPtr<FJsonObject> Snapshot(FAutomationTestBase& Test)
	{
		const FString Path = FPaths::Combine(FPaths::ProjectDir(), TEXT("Tests/Data/progression/record_snapshot.json"));
		FString Text;
		TSharedPtr<FJsonObject> Root;
		if (!Test.TestTrue(TEXT("snapshot fixture is readable"), FFileHelper::LoadFileToString(Text, *Path)))
		{
			return nullptr;
		}
		if (!Test.TestTrue(TEXT("snapshot fixture parses"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) && Root.IsValid()))
		{
			return nullptr;
		}
		return Root;
	}

	TSharedPtr<FVerseServiceRecordModel> SeededModel(FAutomationTestBase& Test)
	{
		const TSharedPtr<FJsonObject> Root = Snapshot(Test);
		if (!Root.IsValid())
		{
			return nullptr;
		}
		TSharedPtr<FVerseServiceRecordModel> Model = MakeShared<FVerseServiceRecordModel>();
		Test.TestTrue(TEXT("snapshot applies"), Model->ApplySnapshot(*Root));
		return Model;
	}

	FVerseUiStrings Strings(const FString& Lang = TEXT("en"))
	{
		FVerseUiStrings Out;
		Out.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir());
		Out.SetLanguage(Lang);
		return Out;
	}

	/** An award of the person for a level-up, as the bridge sends it. */
	TSharedRef<FJsonObject> Award(int64 Seq, const FString& Subject, int32 Level, int32 Previous, const TArray<FString>& Unlocked = {})
	{
		TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetNumberField(TEXT("seq"), double(Seq));
		Data->SetStringField(TEXT("subject_id"), Subject);
		Data->SetStringField(TEXT("subject_kind"), Subject == TEXT("person") ? TEXT("person") : (Subject.StartsWith(TEXT("pet:")) ? TEXT("pet") : TEXT("agent")));
		Data->SetStringField(TEXT("xp_source"), TEXT("task_done"));
		Data->SetNumberField(TEXT("xp"), 10);
		Data->SetNumberField(TEXT("total_xp"), double(FVerseServiceRecordModel::TotalXpForLevel(Level) + 5));
		Data->SetNumberField(TEXT("level"), Level);
		Data->SetNumberField(TEXT("previous_level"), Previous);
		Data->SetStringField(TEXT("title"), TEXT("x"));
		TArray<TSharedPtr<FJsonValue>> Items;
		for (const FString& Id : Unlocked)
		{
			Items.Add(MakeShared<FJsonValueString>(Id));
		}
		Data->SetArrayField(TEXT("unlocked"), Items);
		return Data;
	}
}

using namespace VerseRecordParity;

// R-04: five tabs in that order, each opened by openRecord(tab).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityR04Test, "Verse.Parity.R.04", VERSE_RECORD_PARITY_FLAGS)
bool FVerseParityR04Test::RunTest(const FString&)
{
	const TArray<FVerseRecordPages::FTab>& Tabs = FVerseRecordPages::Tabs();
	if (!TestEqual(TEXT("five tabs"), Tabs.Num(), 5))
	{
		return false;
	}
	const TCHAR* Order[] = {TEXT("record"), TEXT("ladder"), TEXT("rewards"), TEXT("earn"), TEXT("crew")};
	for (int32 I = 0; I < 5; ++I)
	{
		TestEqual(TEXT("tab order"), Tabs[I].Id.ToString(), FString(Order[I]));
		TestEqual(TEXT("enum matches position"), int32(Tabs[I].Tab), I);
		for (const FString& Lang : FVerseUiStrings::SupportedLanguages())
		{
			TestFalse(TEXT("tab label in every language"), Strings(Lang).GetIn(Tabs[I].LabelKey, Lang).IsEmpty());
		}
	}
	TestEqual(TEXT("labels in English: Record, Ladder, Quartermaster, How to earn, Crew"),
		FString::JoinBy(Tabs, TEXT(", "), [](const FVerseRecordPages::FTab& T) { return Strings().Get(T.LabelKey).ToString(); }),
		FString(TEXT("Record, Ladder, Quartermaster, How to earn, Crew")));

	const TSharedPtr<FVerseServiceRecordModel> Model = SeededModel(*this);
	if (Model.IsValid() && FSlateApplication::IsInitialized())
	{
		// The dialog opens on the page asked for, and every page builds from the seeded progression.
		for (const FVerseRecordPages::FTab& Tab : Tabs)
		{
			const TSharedRef<SVerseServiceRecord> View = SNew(SVerseServiceRecord, Model.ToSharedRef(), nullptr, Tab.Tab);
			TestEqual(TEXT("opens on the page asked for"), View->GetTab(), Tab.Tab);
		}
		const TSharedRef<SVerseServiceRecord> View = SNew(SVerseServiceRecord, Model.ToSharedRef());
		for (const FVerseRecordPages::FTab& Tab : Tabs)
		{
			View->SetTab(Tab.Tab);
			TestEqual(TEXT("openRecord(tab) switches the page"), View->GetTab(), Tab.Tab);
		}
	}
	return true;
}

// R-05: the Record page shows every field of the snapshot.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityR05Test, "Verse.Parity.R.05", VERSE_RECORD_PARITY_FLAGS)
bool FVerseParityR05Test::RunTest(const FString&)
{
	const TSharedPtr<FVerseServiceRecordModel> Model = SeededModel(*this);
	if (!Model.IsValid())
	{
		return false;
	}
	const FVerseUiStrings S = Strings();
	const FVerseRecordPages::FRecordPage Page = FVerseRecordPages::Record(*Model, S);
	TestEqual(TEXT("plate of the lieutenant"), Page.RankId.ToString(), FString(TEXT("lieutenant")));
	TestEqual(TEXT("rank"), Page.Rank.ToString(), FString(TEXT("Lieutenant")));
	TestEqual(TEXT("tier"), Page.Tier.ToString(), FString(TEXT("Line officers")));
	TestEqual(TEXT("level"), Page.Level.ToString(), FString(TEXT("14")));
	TestEqual(TEXT("XP"), Page.TotalXp.ToString(), FString(TEXT("3 045")));
	TestEqual(TEXT("this level"), Page.ThisLevel.ToString(), FString(TEXT("130 / 460")));
	TestEqual(TEXT("the bar"), Page.Fraction, 130.f / 460.f);
	TestEqual(TEXT("next rank"), Page.NextRank.ToString(), FString(TEXT("Senior Lieutenant")));
	TestEqual(TEXT("what is missing for the senior lieutenant (level 17)"), Page.NextRankXp.ToString(), FString(TEXT("1 355 XP")));

	TestTrue(TEXT("duels exist"), Page.bHasDuels);
	TestEqual(TEXT("sets"), Page.Sets.ToString(), FString(TEXT("12")));
	TestEqual(TEXT("won / lost"), Page.WonLost.ToString(), FString(TEXT("7 / 5")));
	TestEqual(TEXT("K/D"), Page.KillDeath.ToString(), FString(TEXT("1.19")));
	TestEqual(TEXT("headshots"), Page.Headshots.ToString(), FString(TEXT("31")));
	TestEqual(TEXT("finishers"), Page.Finishers.ToString(), FString(TEXT("4")));
	TestEqual(TEXT("best streak"), Page.BestStreak.ToString(), FString(TEXT("6")));
	TestTrue(TEXT("unfinished sets are said"), Page.Unfinished.ToString().EndsWith(TEXT("2")));

	// Level 14 holds the first ribbon (level 6) and not the second (level 19).
	TestEqual(TEXT("one ribbon"), Page.Ribbons.Num(), 1);
	TestEqual(TEXT("ribbon name"), Page.Ribbons.Num() > 0 ? Page.Ribbons[0].ToString() : FString(), FString(TEXT("Good Conduct Ribbon")));

	// The log: the commander's newest awards first; the officer's award is not in it.
	if (TestEqual(TEXT("three awards of the commander"), Page.Log.Num(), 3))
	{
		TestEqual(TEXT("newest first"), Page.Log[0].Source.ToString(), FString(TEXT("Duel set won")));
		TestEqual(TEXT("its XP"), Page.Log[0].Xp.ToString(), FString(TEXT("+40")));
		TestEqual(TEXT("then"), Page.Log[1].Source.ToString(), FString(TEXT("Reported aboard")));
		TestEqual(TEXT("oldest last"), Page.Log[2].Source.ToString(), FString(TEXT("Chat with the assistant")));
		TestFalse(TEXT("with its date"), Page.Log[0].When.IsEmpty());
	}

	// The bell switch is part of the page and keeps its state.
	TestTrue(TEXT("bell on by default"), Page.bBellOn);
	bool bSaved = true;
	Model->SaveBell = [&bSaved](bool bOn) { bSaved = bOn; };
	Model->SetBellOn(false);
	TestFalse(TEXT("bell off is saved"), bSaved);
	TestFalse(TEXT("and the page shows it"), FVerseRecordPages::Record(*Model, S).bBellOn);

	// A live award moves the page.
	Model->ApplyAwarded(*Award(903, TEXT("person"), 14, 14));
	const FVerseRecordPages::FRecordPage Live = FVerseRecordPages::Record(*Model, S);
	TestEqual(TEXT("a new award joins the log"), Live.Log.Num(), 4);
	TestEqual(TEXT("as the newest"), Live.Log.Num() > 0 ? Live.Log[0].Source.ToString() : FString(), FString(TEXT("Task done")));
	for (const FString& Lang : FVerseUiStrings::SupportedLanguages())
	{
		TestFalse(TEXT("the rank is worded in every language"), FVerseRecordPages::Record(*Model, Strings(Lang)).Rank.IsEmpty());
	}
	return true;
}

// R-06: the ladder marks held ranks plain, the current one in red, the ones ahead dimmed with the XP missing.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityR06Test, "Verse.Parity.R.06", VERSE_RECORD_PARITY_FLAGS)
bool FVerseParityR06Test::RunTest(const FString&)
{
	const TSharedPtr<FVerseServiceRecordModel> Model = SeededModel(*this);
	if (!Model.IsValid())
	{
		return false;
	}
	const TArray<FVerseRecordPages::FTierBlock> Ladder = FVerseRecordPages::Ladder(*Model, Strings());
	if (!TestEqual(TEXT("four tiers"), Ladder.Num(), 4))
	{
		return false;
	}
	int32 Held = 0;
	int32 Current = 0;
	int32 Ahead = 0;
	int32 Steps = 0;
	for (const FVerseRecordPages::FTierBlock& Block : Ladder)
	{
		TestFalse(TEXT("tier name"), Block.Name.IsEmpty());
		TestTrue(TEXT("tier start"), Block.FromLevel.ToString().Contains(TEXT("Level")));
		for (const FVerseRecordPages::FStep& Step : Block.Steps)
		{
			++Steps;
			switch (Step.State)
			{
			case FVerseRecordPages::EStepState::Held:
				++Held;
				TestFalse(TEXT("a held rank says Held"), Step.StateText.IsEmpty());
				TestTrue(TEXT("and was reached"), Step.Level < 14);
				break;
			case FVerseRecordPages::EStepState::Current:
				++Current;
				TestEqual(TEXT("the current rank is the lieutenant"), Step.RankId.ToString(), FString(TEXT("lieutenant")));
				TestEqual(TEXT("marked Current"), Step.StateText.ToString(), FString(TEXT("Current")));
				break;
			case FVerseRecordPages::EStepState::Ahead:
				++Ahead;
				TestTrue(TEXT("a rank ahead shows the XP missing"), Step.Right.ToString().EndsWith(TEXT(" XP")));
				TestTrue(TEXT("and no state word"), Step.StateText.IsEmpty());
				TestTrue(TEXT("and lies above the level"), Step.Level > 14);
				break;
			}
		}
	}
	TestEqual(TEXT("all 15 ranks"), Steps, 15);
	TestEqual(TEXT("held"), Held, 5);
	TestEqual(TEXT("current"), Current, 1);
	TestEqual(TEXT("ahead"), Ahead, 9);
	// The flag admiral is the farthest: its missing XP is the largest.
	const FVerseRecordPages::FStep& Last = Ladder.Last().Steps.Last();
	TestEqual(TEXT("the last step is the fleet admiral"), Last.RankId.ToString(), FString(TEXT("fleet_admiral")));
	TestEqual(TEXT("missing XP is exact"), Last.Right.ToString(), SVerseServiceRecord::FormatFigure(FVerseServiceRecordModel::TotalXpForLevel(50) - 3045) + TEXT(" XP"));
	return true;
}

// R-07: the quartermaster issues uniforms by tier; a pick changes the worn uniform at once and persists.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityR07Test, "Verse.Parity.R.07", VERSE_RECORD_PARITY_FLAGS)
bool FVerseParityR07Test::RunTest(const FString&)
{
	const TSharedPtr<FVerseServiceRecordModel> Model = SeededModel(*this);
	if (!Model.IsValid())
	{
		return false;
	}
	const FVerseUiStrings S = Strings();
	FVerseRecordPages::FQuartermasterPage Page = FVerseRecordPages::Quartermaster(*Model, S);
	if (!TestEqual(TEXT("auto and four tiers"), Page.Uniforms.Num(), 5))
	{
		return false;
	}
	const TCHAR* Order[] = {TEXT("auto"), TEXT("deck"), TEXT("line"), TEXT("command"), TEXT("flag")};
	const bool Open[] = {true, true, true, false, false};
	for (int32 I = 0; I < 5; ++I)
	{
		TestEqual(TEXT("order"), Page.Uniforms[I].Id.ToString(), FString(Order[I]));
		TestEqual(TEXT("issued by level"), Page.Uniforms[I].bOpen, Open[I]);
	}
	TestEqual(TEXT("a closed tier says when it opens"), Page.Uniforms[3].Note.ToString(), FString(TEXT("Opens at level 29")));
	TestEqual(TEXT("and the next one"), Page.Uniforms[4].Note.ToString(), FString(TEXT("Opens at level 37")));
	TestTrue(TEXT("auto is chosen at first"), Page.Uniforms[0].bChosen);
	TestEqual(TEXT("and wears the highest issued"), Model->EffectiveUniform().ToString(), FString(TEXT("line")));

	// A pick is worn at once and is kept.
	TArray<FString> Worn;
	TArray<FString> Saved;
	Model->OnUniformWorn = [&Worn](FName Uniform) { Worn.Add(Uniform.ToString()); };
	Model->SaveUniformChoice = [&Saved](FName Choice) { Saved.Add(Choice.ToString()); };
	TestTrue(TEXT("a work uniform can be picked"), Model->ChooseUniform(TEXT("deck")));
	TestEqual(TEXT("worn at once"), Worn.Num() > 0 ? Worn.Last() : FString(), FString(TEXT("deck")));
	TestEqual(TEXT("saved"), Saved.Num() > 0 ? Saved.Last() : FString(), FString(TEXT("deck")));
	TestEqual(TEXT("the commander wears it"), Model->EffectiveUniform().ToString(), FString(TEXT("deck")));
	Page = FVerseRecordPages::Quartermaster(*Model, S);
	TestTrue(TEXT("the page says Wearing"), Page.Uniforms[1].bChosen && Page.Uniforms[1].StateText.ToString() == TEXT("Wearing"));
	TestEqual(TEXT("the other issued tier says Issued"), Page.Uniforms[2].StateText.ToString(), FString(TEXT("Issued")));
	TestFalse(TEXT("a tier not yet issued cannot be picked"), Model->ChooseUniform(TEXT("command")));
	TestEqual(TEXT("and nothing changed"), Model->EffectiveUniform().ToString(), FString(TEXT("deck")));
	TestTrue(TEXT("auto goes back to the highest"), Model->ChooseUniform(TEXT("auto")) && Model->EffectiveUniform() == FName(TEXT("line")));

	// A new session restores the choice.
	FVerseServiceRecordModel Next;
	Next.ApplySnapshot(*Snapshot(*this));
	Next.RestoreUniformChoice(TEXT("deck"));
	TestEqual(TEXT("persisted across runs"), Next.EffectiveUniform().ToString(), FString(TEXT("deck")));
	Next.RestoreUniformChoice(TEXT("command"));
	TestEqual(TEXT("a stored tier not issued falls back to the highest"), Next.EffectiveUniform().ToString(), FString(TEXT("line")));

	// Under auto, a promotion into the next tier changes the uniform.
	Worn.Reset();
	Model->ApplyAwarded(*Award(910, TEXT("person"), 29, 28));
	TestEqual(TEXT("the command tunic is issued at 29 and worn under auto"), Worn.Num() > 0 ? Worn.Last() : FString(), FString(TEXT("command")));

	// Ribbons with the levels that open them.
	TestEqual(TEXT("four ribbons"), Page.Ribbons.Num(), 4);
	TestEqual(TEXT("first ribbon"), Page.Ribbons[0].Name.ToString(), FString(TEXT("Good Conduct Ribbon")));
	TestEqual(TEXT("for the commander"), Page.Ribbons[0].ForYou.ToString(), FString(TEXT("You: level 6")));
	TestEqual(TEXT("for officers"), Page.Ribbons[0].ForCrew.ToString(), FString(TEXT("Officers: level 4")));
	TestTrue(TEXT("held at 14"), Page.Ribbons[0].bOpen && !Page.Ribbons[1].bOpen);
	return true;
}

// R-08: how to earn lists every rule the running server pays, with limits.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityR08Test, "Verse.Parity.R.08", VERSE_RECORD_PARITY_FLAGS)
bool FVerseParityR08Test::RunTest(const FString&)
{
	const TSharedPtr<FVerseServiceRecordModel> Model = SeededModel(*this);
	if (!Model.IsValid())
	{
		return false;
	}
	const FVerseRecordPages::FEarnPage Page = FVerseRecordPages::Earn(*Model, Strings());
	TestFalse(TEXT("the hint"), Page.Hint.IsEmpty());
	if (!TestEqual(TEXT("commander, officers, drone"), Page.Groups.Num(), 3))
	{
		return false;
	}
	TestEqual(TEXT("commander first"), Page.Groups[0].Kind, EVerseSubjectKind::Person);
	TestEqual(TEXT("officers"), Page.Groups[1].Kind, EVerseSubjectKind::Agent);
	TestEqual(TEXT("drone"), Page.Groups[2].Kind, EVerseSubjectKind::Pet);
	// The rules the server paid, in its order; a rule of a newer server without words is left out.
	TArray<FString> Sources;
	for (const FVerseRecordPages::FEarnGroup& Group : Page.Groups)
	{
		for (const FVerseRecordPages::FRuleRow& Rule : Group.Rules)
		{
			Sources.Add(Rule.Source.ToString());
		}
	}
	TestEqual(TEXT("five known rules"), FString::Join(Sources, TEXT(",")), FString(TEXT("chat_turn,daily_visit,duel_won,task_done,walk_together")));
	TestEqual(TEXT("the server pays six"), Model->Rules().Num(), 6);
	const FVerseRecordPages::FRuleRow& Chat = Page.Groups[0].Rules[0];
	TestEqual(TEXT("chat words"), Chat.Text.ToString(), FString(TEXT("Finish a chat turn with the assistant.")));
	TestEqual(TEXT("chat XP"), Chat.Xp.ToString(), FString(TEXT("+5")));
	TestEqual(TEXT("chat cooldown"), Chat.Limits.ToString(), FString(TEXT("at most every 45 s")));
	const FVerseRecordPages::FRuleRow& Duel = Page.Groups[0].Rules[2];
	TestEqual(TEXT("duel cap"), Duel.Limits.ToString(), FString(TEXT("up to 200 a day")));
	TestEqual(TEXT("duel XP"), Duel.Xp.ToString(), FString(TEXT("+40")));
	TestEqual(TEXT("officer cooldown in minutes and a cap"), Page.Groups[1].Rules[0].Limits.ToString(), FString(TEXT("up to 100 a day · at most every 10 min")));
	TestTrue(TEXT("no limits, no line"), Page.Groups[0].Rules[1].Limits.IsEmpty());
	return true;
}

// R-09: the crew page lists every officer, highest first, and the companion.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityR09Test, "Verse.Parity.R.09", VERSE_RECORD_PARITY_FLAGS)
bool FVerseParityR09Test::RunTest(const FString&)
{
	const TSharedPtr<FVerseServiceRecordModel> Model = SeededModel(*this);
	if (!Model.IsValid())
	{
		return false;
	}
	const FVerseUiStrings S = Strings();
	// No names yet: the ids stand in, and the companion has the generic word.
	FVerseRecordPages::FCrewPage Page = FVerseRecordPages::Crew(*Model, S);
	TestFalse(TEXT("officers aboard"), Page.bNoOfficers);
	TestEqual(TEXT("three officers and the drone"), Page.Rows.Num(), 4);

	TMap<FString, FString> Names;
	Names.Add(TEXT("ag_001"), TEXT("Wren"));
	Names.Add(TEXT("ag_002"), TEXT("Isolde"));
	Names.Add(TEXT("ag_003"), TEXT("Alder"));
	Model->SetCrewNames(Names, TEXT("Spark"));
	Page = FVerseRecordPages::Crew(*Model, S);
	if (!TestEqual(TEXT("rows"), Page.Rows.Num(), 4))
	{
		return false;
	}
	TestEqual(TEXT("highest first"), Page.Rows[0].Name.ToString(), FString(TEXT("Isolde")));
	TestEqual(TEXT("level 12 is an ensign"), Page.Rows[0].Rank.ToString(), FString(TEXT("Ensign")));
	TestEqual(TEXT("equal XP: by name"), Page.Rows[1].Name.ToString(), FString(TEXT("Alder")));
	TestEqual(TEXT("then"), Page.Rows[2].Name.ToString(), FString(TEXT("Wren")));
	TestEqual(TEXT("level 9 is a senior technician"), Page.Rows[2].Rank.ToString(), FString(TEXT("Senior Technician")));
	TestTrue(TEXT("the companion last"), Page.Rows.Last().bCompanion);
	TestEqual(TEXT("with its name"), Page.Rows.Last().Name.ToString(), FString(TEXT("Spark")));
	TestEqual(TEXT("its level"), Page.Rows.Last().Level, 4);
	TestEqual(TEXT("its rank"), Page.Rows.Last().Rank.ToString(), FString(TEXT("Deckhand")));

	// An officer who levels up moves the page; with nobody aboard the page says so.
	Model->ApplyAwarded(*Award(920, TEXT("agent:ag_001"), 18, 9));
	TestEqual(TEXT("an officer's award raises the row"), FVerseRecordPages::Crew(*Model, S).Rows[0].Name.ToString(), FString(TEXT("Wren")));
	FVerseServiceRecordModel Empty;
	const FVerseRecordPages::FCrewPage None = FVerseRecordPages::Crew(Empty, S);
	TestTrue(TEXT("no officers"), None.bNoOfficers);
	TestFalse(TEXT("and the words for it"), None.Empty.IsEmpty());
	TestEqual(TEXT("the companion is always there"), None.Rows.Num(), 1);
	return true;
}

// R-10: the promotion notice for a new rank lays the tiles on one by one, lasts 7 s, never takes the focus.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityR10Test, "Verse.Parity.R.10", VERSE_RECORD_PARITY_FLAGS)
bool FVerseParityR10Test::RunTest(const FString&)
{
	const TSharedPtr<FVerseServiceRecordModel> Model = SeededModel(*this);
	if (!Model.IsValid())
	{
		return false;
	}
	TArray<int64> Told;
	Model->SendTold = [&Told](int64 Seq) { Told.Add(Seq); };
	// 20 -> 21 is the commander's rank.
	TestTrue(TEXT("the new rank queues a notice"), Model->ApplyAwarded(*Award(930, TEXT("person"), 21, 20, {TEXT("uniform_line"), TEXT("ribbon_good_conduct"), TEXT("plate_unknown")})));
	const FVersePromotion* Promotion = Model->PendingPromotion();
	if (!TestNotNull(TEXT("waiting"), Promotion))
	{
		return false;
	}
	TestTrue(TEXT("a new rank is the full notice"), Promotion->IsFullNotice());
	TestEqual(TEXT("the notice lasts 7 s"), FVersePromotionPresenter::SecondsFor(*Promotion), 7.0f);

	int32 Shown = 0;
	int32 Hidden = 0;
	bool bOn = true;
	FVersePromotionPresenter Presenter(Model.ToSharedRef(), [&Shown](const FVersePromotion&) { ++Shown; return true; }, [&Hidden] { ++Hidden; }, [&bOn] { return bOn; });
	Presenter.Tick(0.f);
	TestTrue(TEXT("on screen"), Presenter.IsShowing());
	Presenter.Tick(6.9f);
	TestTrue(TEXT("still up at 6.9 s"), Presenter.IsShowing());
	TestEqual(TEXT("not told while up"), Told.Num(), 0);
	Presenter.Tick(0.2f);
	TestFalse(TEXT("gone after 7 s"), Presenter.IsShowing());
	TestEqual(TEXT("told once with its seq"), Told.Num() == 1 ? Told[0] : int64(-1), int64(930));

	// Acknowledge (or Escape) ends it at once.
	Model->ApplyAwarded(*Award(931, TEXT("person"), 25, 24));
	Presenter.Tick(0.f);
	TestTrue(TEXT("second notice up"), Presenter.IsShowing());
	Presenter.Tick(1.0f);
	TestTrue(TEXT("up at 1 s"), Presenter.IsShowing());
	bOn = false;
	Presenter.Tick(0.1f);
	TestFalse(TEXT("acknowledged: gone"), Presenter.IsShowing());
	TestEqual(TEXT("and told"), Told.Num(), 2);

	// Tiles are laid on one by one; reduced motion shows them all.
	const int32 Lit = FVerseRankPlate::For(TEXT("commander")).NumLit();
	TestEqual(TEXT("the commander plate has four tiles"), Lit, 4);
	TestEqual(TEXT("none at first"), SVersePromotionNotice::TilesAt(0.0, Lit, false), 0);
	TestEqual(TEXT("one after a step"), SVersePromotionNotice::TilesAt(SVersePromotionNotice::TileStepSeconds + 0.001, Lit, false), 1);
	TestEqual(TEXT("three after three steps"), SVersePromotionNotice::TilesAt(SVersePromotionNotice::TileStepSeconds * 3 + 0.001, Lit, false), 3);
	TestEqual(TEXT("all and no more"), SVersePromotionNotice::TilesAt(60.0, Lit, false), Lit);
	TestEqual(TEXT("reduced motion: all at once"), SVersePromotionNotice::TilesAt(0.0, Lit, true), Lit);

	if (FSlateApplication::IsInitialized())
	{
		FVersePromotion Rank;
		Rank.Seq = 940;
		Rank.Level = 21;
		Rank.PreviousLevel = 20;
		Rank.RankId = TEXT("commander");
		Rank.PreviousRankId = TEXT("senior_lieutenant");
		Rank.Unlocked = {TEXT("uniform_line"), TEXT("ribbon_good_conduct"), TEXT("plate_unknown")};
		const TSharedRef<SVersePromotionNotice> Notice = SNew(SVersePromotionNotice, Rank, nullptr);
		TestFalse(TEXT("the notice itself takes no focus"), Notice->SupportsKeyboardFocus());
		// No child takes it either: the acknowledge button is not focusable.
		TFunction<int32(const TSharedRef<SWidget>&)> Focusable = [&Focusable](const TSharedRef<SWidget>& W) -> int32
		{
			int32 Count = W->SupportsKeyboardFocus() ? 1 : 0;
			FChildren* Children = W->GetChildren();
			for (int32 I = 0; Children && I < Children->Num(); ++I)
			{
				Count += Focusable(Children->GetChildAt(I));
			}
			return Count;
		};
		TestEqual(TEXT("nothing in the notice is focusable"), Focusable(Notice), 0);
		TestEqual(TEXT("headline"), Notice->Headline().ToString(), FString(TEXT("Promotion")));
		TestEqual(TEXT("the rank"), Notice->Detail().ToString(), FString(TEXT("Commander")));
		const TArray<FString> Issued = Notice->IssuedNames();
		TestEqual(TEXT("what the quartermaster issued; unknown ids are left out"), FString::Join(Issued, TEXT(", ")), FString(TEXT("Line tunic, Good Conduct Ribbon")));

		FVersePromotion Drone = Rank;
		Drone.Kind = EVerseSubjectKind::Pet;
		const TSharedRef<SVersePromotionNotice> DroneNotice = SNew(SVersePromotionNotice, Drone, nullptr);
		TestEqual(TEXT("the drone has its own headline"), DroneNotice->Headline().ToString(), FString(TEXT("Companion drone promoted")));
	}
	return true;
}

// R-11: other level-ups are a quiet corner line, 5 s or a click.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityR11Test, "Verse.Parity.R.11", VERSE_RECORD_PARITY_FLAGS)
bool FVerseParityR11Test::RunTest(const FString&)
{
	const TSharedPtr<FVerseServiceRecordModel> Model = SeededModel(*this);
	if (!Model.IsValid())
	{
		return false;
	}
	// An officer's level-up and the drone's rank-less one are quiet lines, not notices.
	TestFalse(TEXT("an officer's level-up queues no notice"), Model->ApplyAwarded(*Award(950, TEXT("agent:ag_001"), 10, 9)));
	TestFalse(TEXT("nor the drone's level-up"), Model->ApplyAwarded(*Award(951, TEXT("pet:drone"), 7, 6)));
	TestNull(TEXT("no notice waits"), Model->PendingPromotion());
	TestEqual(TEXT("two quiet lines"), Model->QuietLines().Num(), 2);
	// The drone's new rank (level 7 technician to level 8 senior technician) is a full notice.
	TestTrue(TEXT("the drone's new rank is a notice"), Model->ApplyAwarded(*Award(952, TEXT("pet:drone"), 8, 7)));
	TestTrue(TEXT("for the companion"), Model->PendingPromotion() && Model->PendingPromotion()->Kind == EVerseSubjectKind::Pet);
	// A commander's level without a new rank is quiet as well (the existing 14 -> 15).
	TestTrue(TEXT("the commander's plain level is queued to be shown quietly"), Model->ApplyAwarded(*Award(953, TEXT("person"), 15, 14)));
	const FVersePromotion* Plain = Model->PendingPromotion();
	Model->MarkPromotionShown();
	Plain = Model->PendingPromotion();
	if (TestNotNull(TEXT("the plain level waits"), Plain))
	{
		TestFalse(TEXT("it is no full notice"), Plain->IsFullNotice());
		TestEqual(TEXT("it lasts 5 s"), FVersePromotionPresenter::SecondsFor(*Plain), 5.0f);
	}

	// The stack: five seconds, or a click; three at most.
	FVerseQuietStack Stack;
	Stack.Add(1, FText::AsCultureInvariant(TEXT("a")), TEXT("recruit"), 10.0);
	Stack.Add(2, FText::AsCultureInvariant(TEXT("b")), TEXT("recruit"), 11.0);
	TestEqual(TEXT("two lines"), Stack.Entries().Num(), 2);
	Stack.Tick(14.9);
	TestTrue(TEXT("up at 4.9 s"), Stack.Contains(1));
	Stack.Tick(15.0);
	TestFalse(TEXT("gone at 5 s"), Stack.Contains(1));
	TestTrue(TEXT("the second runs its own time"), Stack.Contains(2));
	TestTrue(TEXT("a click dismisses"), Stack.Dismiss(2));
	TestEqual(TEXT("empty"), Stack.Entries().Num(), 0);
	for (int32 I = 0; I < 5; ++I)
	{
		Stack.Add(10 + I, FText::AsCultureInvariant(TEXT("x")), TEXT("recruit"), 20.0);
	}
	TestEqual(TEXT("three at most"), Stack.Entries().Num(), FVerseQuietStack::MaxVisible);
	TestEqual(TEXT("the oldest made room"), Stack.Entries()[0].Id, int64(12));
	const uint32 Before = Stack.Revision();
	Stack.Add(12, FText::AsCultureInvariant(TEXT("x")), TEXT("recruit"), 21.0);
	TestEqual(TEXT("a repeat changes nothing"), Stack.Revision(), Before);

	// The words, in every language.
	for (const FString& Lang : FVerseUiStrings::SupportedLanguages())
	{
		const FVerseUiStrings S = Strings(Lang);
		TestFalse(TEXT("level line"), FVerseRecordPages::Fill(S, TEXT("verse.ranks.promo.toast_level"), {{TEXT("who"), TEXT("Wren")}, {TEXT("level"), TEXT("10")}}).IsEmpty());
		TestTrue(TEXT("names the officer"), FVerseRecordPages::Fill(S, TEXT("verse.ranks.promo.toast_level"), {{TEXT("who"), TEXT("Wren")}, {TEXT("level"), TEXT("10")}}).ToString().Contains(TEXT("Wren")));
	}

	// A click ends the line the presenter stands in with: counted as shown at once.
	TArray<int64> Told;
	Model->SendTold = [&Told](int64 Seq) { Told.Add(Seq); };
	bool bOn = true;
	FVersePromotionPresenter Presenter(Model.ToSharedRef(), [](const FVersePromotion&) { return true; }, [] {}, [&bOn] { return bOn; });
	Presenter.Tick(0.f);
	Presenter.Tick(1.f);
	TestTrue(TEXT("up at 1 s"), Presenter.IsShowing());
	bOn = false;
	Presenter.Tick(0.1f);
	TestFalse(TEXT("a click ended it"), Presenter.IsShowing());
	TestEqual(TEXT("and it was told"), Told.Num() == 1 ? Told[0] : int64(-1), int64(953));
	return true;
}

// R-13: the overlay draws only while the Verse is visible, and the queue is kept.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityR13Test, "Verse.Parity.R.13", VERSE_RECORD_PARITY_FLAGS)
bool FVerseParityR13Test::RunTest(const FString&)
{
	const TSharedPtr<FVerseServiceRecordModel> Model = SeededModel(*this);
	if (!Model.IsValid())
	{
		return false;
	}
	TArray<int64> Told;
	Model->SendTold = [&Told](int64 Seq) { Told.Add(Seq); };
	bool bVisible = false;  // Dormant
	int32 Shown = 0;
	FVersePromotionPresenter Presenter(Model.ToSharedRef(),
		[&bVisible, &Shown](const FVersePromotion&) { if (!bVisible) { return false; } ++Shown; return true; }, [] {});
	TestTrue(TEXT("an award while the Verse is dormant"), Model->ApplyAwarded(*Award(960, TEXT("person"), 25, 24)));
	for (int32 I = 0; I < 100; ++I)
	{
		Presenter.Tick(0.1f);
	}
	TestEqual(TEXT("nothing shown while dormant"), Shown, 0);
	TestEqual(TEXT("nothing told"), Told.Num(), 0);
	TestEqual(TEXT("the queue is kept"), Model->NumPendingPromotions(), 1);
	// A second award piles up behind it.
	Model->ApplyAwarded(*Award(961, TEXT("person"), 29, 28));
	TestEqual(TEXT("and grows"), Model->NumPendingPromotions(), 2);

	bVisible = true;
	Presenter.Tick(0.1f);
	TestEqual(TEXT("shown on the next show"), Shown, 1);
	TestEqual(TEXT("the oldest first"), Model->PendingPromotion() ? Model->PendingPromotion()->Seq : int64(0), int64(960));
	Presenter.Tick(FVersePromotionPresenter::NoticeSeconds);
	TestEqual(TEXT("told after its time"), Told.Num() == 1 ? Told[0] : int64(-1), int64(960));
	Presenter.Tick(0.1f);
	TestEqual(TEXT("then the second"), Shown, 2);

	// The game instance subsystem takes the gate from the lifecycle (Dormant hides the overlay).
	UGameInstance* Instance = NewObject<UGameInstance>(GetTransientPackage());
	UVerseServiceRecordSubsystem* Subsystem = NewObject<UVerseServiceRecordSubsystem>(Instance);
	TestTrue(TEXT("visible by default"), Subsystem->IsOverlayVisible());
	bool bShowing = false;
	Subsystem->SetOverlayVisible([&bShowing] { return bShowing; });
	TestFalse(TEXT("dormant"), Subsystem->IsOverlayVisible());
	bShowing = true;
	TestTrue(TEXT("visible"), Subsystem->IsOverlayVisible());
	Subsystem->SetOverlayVisible(nullptr);
	TestTrue(TEXT("default again"), Subsystem->IsOverlayVisible());
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
