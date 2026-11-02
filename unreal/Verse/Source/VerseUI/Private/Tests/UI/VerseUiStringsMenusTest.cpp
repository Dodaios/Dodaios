#include "Core/VerseUiStrings.h"
#include "Events/VerseEventHub.h"
#include "Framework/Application/SlateApplication.h"
#include "Hud/VerseHudPainter.h"
#include "HAL/FileManager.h"
#include "Internationalization/Regex.h"
#include "Menus/VerseUiMenus.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Tests/UI/Fakes/VerseUiFakes.h"

#if WITH_DEV_AUTOMATION_TESTS

namespace VerseUiStringsTest
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	FString SourceDir()
	{
		return FPaths::Combine(FPaths::GameSourceDir(), TEXT("VerseUI"));
	}

	TSet<FString> Placeholders(const FString& Text)
	{
		TSet<FString> Out;
		FRegexMatcher M(FRegexPattern(TEXT("\\{([a-z_]+)\\}")), Text);
		while (M.FindNext())
		{
			Out.Add(M.GetCaptureGroup(1));
		}
		return Out;
	}

	/** Every text WP18 lays out in a box of fixed width: key, reference width, point size, bold. */
	struct FFixedBox
	{
		FString Key;
		float Width;
		int32 Size;
		bool bBold;
	};
}

using namespace VerseUiStringsTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiCatalogueTest, "Verse.UI.Strings.Catalogue", Flags)
bool FVerseUiCatalogueTest::RunTest(const FString&)
{
	FVerseUiStrings Strings;
	FString Error;
	if (!TestTrue(TEXT("the strings catalogue loads"), Strings.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir(), &Error)))
	{
		AddError(Error);
		return false;
	}
	int32 Missing = 0;
	for (const FString& Key : Strings.GetKeys())
	{
		const TSet<FString> English = Placeholders(Strings.GetIn(Key, TEXT("en")));
		for (const FString& Lang : FVerseUiStrings::SupportedLanguages())
		{
			const FString Text = Strings.GetIn(Key, Lang);
			if (Text.IsEmpty())
			{
				AddError(FString::Printf(TEXT("%s has no %s text"), *Key, *Lang));
				++Missing;
				continue;
			}
			const TSet<FString> Here = Placeholders(Text);
			TestTrue(FString::Printf(TEXT("%s/%s keeps the placeholders"), *Key, *Lang), Here.Num() == English.Num() && Here.Includes(English));
		}
	}
	TestEqual(TEXT("missing translations"), Missing, 0);
	TestTrue(TEXT("catalogue is not empty"), Strings.GetKeys().Num() > 100);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiBridgeStringsTest, "Verse.UI.Strings.Bridge", Flags)
bool FVerseUiBridgeStringsTest::RunTest(const FString&)
{
	FVerseUiStrings Strings;
	Strings.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir());
	TSharedRef<FJsonObject> Locale = MakeShared<FJsonObject>();
	Locale->SetStringField(TEXT("lang"), TEXT("de"));
	Locale->SetStringField(TEXT("fallback"), TEXT("en"));
	TSharedRef<FJsonObject> Table = MakeShared<FJsonObject>();
	Table->SetStringField(TEXT("verse.menu.resume"), TEXT("Fortsetzen"));
	Locale->SetObjectField(TEXT("strings"), Table);
	Strings.ApplyBridgeLocale(Locale);
	TestEqual(TEXT("language from welcome"), Strings.GetLanguage(), FString(TEXT("de")));
	TestEqual(TEXT("bridge string wins"), Strings.Get(TEXT("verse.menu.resume")).ToString(), FString(TEXT("Fortsetzen")));
	TestEqual(TEXT("catalogue in the language"), Strings.Get(TEXT("verse.settings.text_size")).ToString(), FString(TEXT("Textgröße")));

	TSharedRef<FJsonObject> Changed = MakeShared<FJsonObject>();
	Changed->SetStringField(TEXT("lang"), TEXT("zh-CN"));
	Strings.ApplySettingsChanged(Changed);
	TestEqual(TEXT("settings.changed switches language"), Strings.GetLanguage(), FString(TEXT("zh")));
	TestEqual(TEXT("old bridge strings dropped on a switch"), Strings.NumBridgeStrings(), 0);
	TestEqual(TEXT("chinese text"), Strings.Get(TEXT("verse.ui.back")).ToString(), FString(TEXT("返回")));

	Strings.SetLanguage(TEXT("fr"));
	TestEqual(TEXT("an unknown language falls back to English"), Strings.GetLanguage(), FString(TEXT("en")));
	TestEqual(TEXT("a missing key shows itself"), Strings.Get(TEXT("verse.no.such.key")).ToString(), FString(TEXT("verse.no.such.key")));
	FFormatNamedArguments Args;
	Args.Add(TEXT("seconds"), FText::AsNumber(2));
	TestEqual(TEXT("format"), Strings.Format(TEXT("verse.hud.respawn_in"), Args).ToString(), FString(TEXT("Redeploying in 2")));
	return true;
}

// A18.4 (scan): 0 hard-coded user strings in VerseUI; every key the code names exists.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiNoHardCodedStringsTest, "Verse.UI.Strings.NoHardCoded", Flags)
bool FVerseUiNoHardCodedStringsTest::RunTest(const FString&)
{
	TArray<FString> Files;
	IFileManager::Get().FindFilesRecursive(Files, *SourceDir(), TEXT("*.cpp"), true, false);
	IFileManager::Get().FindFilesRecursive(Files, *SourceDir(), TEXT("*.h"), true, false, false);
	if (!TestTrue(TEXT("VerseUI sources found"), Files.Num() > 5))
	{
		return false;
	}
	FVerseUiStrings Strings;
	Strings.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir());
	const TSet<FString> Keys(Strings.GetKeys());

	// Text literals that would reach a person without the string table.
	const FRegexPattern Forbidden(TEXT("LOCTEXT\\s*\\(|NSLOCTEXT\\s*\\(|INVTEXT\\s*\\(|FText::FromString\\s*\\(\\s*TEXT|AsCultureInvariant\\s*\\(\\s*TEXT|FText::FromName\\s*\\(\\s*TEXT"));
	const FRegexPattern KeyLiteral(TEXT("TEXT\\(\"(verse\\.[a-z0-9_.]+)\"\\)"));
	int32 HardCoded = 0;
	int32 Unknown = 0;
	int32 Named = 0;
	for (const FString& File : Files)
	{
		const FString Normal = FPaths::ConvertRelativePathToFull(File).Replace(TEXT("\\"), TEXT("/"));
		// Tests may name strings freely; Stations, ServiceRecord and Audio belong to other packages.
		if (Normal.Contains(TEXT("/Tests/")) || Normal.Contains(TEXT("/Stations/")) || Normal.Contains(TEXT("/ServiceRecord/")) || Normal.Contains(TEXT("/Audio/")))
		{
			continue;
		}
		FString Text;
		FFileHelper::LoadFileToString(Text, *File);
		FRegexMatcher Bad(Forbidden, Text);
		while (Bad.FindNext())
		{
			++HardCoded;
			AddError(FString::Printf(TEXT("hard-coded text in %s at %d"), *FPaths::GetCleanFilename(File), Bad.GetMatchBeginning()));
		}
		FRegexMatcher K(KeyLiteral, Text);
		while (K.FindNext())
		{
			const FString Key = K.GetCaptureGroup(1);
			// Prefixes that the code completes with an id (verse.item.%s.name and the like) are
			// checked below from the data that supplies the ids.
			if (Key.EndsWith(TEXT(".")) || Key.StartsWith(TEXT("verse.qa")))
			{
				continue;
			}
			++Named;
			if (!Keys.Contains(Key))
			{
				// Console variable and command names share the verse. prefix only in lower case
				// by accident; every one of them is capitalised (Verse.Settings.*), so any
				// lower-case verse.* literal is a string key.
				++Unknown;
				AddError(FString::Printf(TEXT("%s names %s, which the strings catalogue lacks"), *FPaths::GetCleanFilename(File), *Key));
			}
		}
	}
	AddInfo(FString::Printf(TEXT("%d source files, %d string keys named"), Files.Num(), Named));
	TestEqual(TEXT("hard-coded user strings"), HardCoded, 0);
	TestEqual(TEXT("keys missing from the strings catalogue"), Unknown, 0);

	// Keys built from data.
	FVerseKeyMap Map;
	Map.LoadFile(FVerseKeyMap::DefaultPath());
	for (const FVerseKeyMap::FAction& A : Map.GetActions())
	{
		TestTrue(FString::Printf(TEXT("label %s"), *A.LabelKey), Keys.Contains(A.LabelKey));
	}
	FVerseArmouryModel Armoury;
	Armoury.LoadFile(FVerseArmouryModel::DefaultPath());
	for (const FVerseArmouryItem& Item : Armoury.GetLoadout())
	{
		for (const TCHAR* Field : {TEXT("name"), TEXT("role"), TEXT("short")})
		{
			const FString Key = FString::Printf(TEXT("verse.item.%s.%s"), *Item.ItemId.ToString(), Field);
			TestTrue(Key, Keys.Contains(Key));
		}
		const FString SlotKey = FString::Printf(TEXT("verse.armoury.slot.%s"), *StaticEnum<EVerseLoadoutSlot>()->GetNameStringByValue(int64(Item.Slot)).ToLower());
		TestTrue(SlotKey, Keys.Contains(SlotKey));
	}
	for (const FName& Tier : Armoury.GetTiers())
	{
		TestTrue(TEXT("tier name"), Keys.Contains(FString::Printf(TEXT("verse.tier.%s"), *Tier.ToString())));
		TestTrue(TEXT("tier description"), Keys.Contains(FString::Printf(TEXT("verse.tier.%s.desc"), *Tier.ToString())));
	}
	for (const TCHAR* Deck : {TEXT("bridge"), TEXT("ops"), TEXT("engineering"), TEXT("hangar")})
	{
		TestTrue(TEXT("deck name"), Keys.Contains(FString::Printf(TEXT("verse.deck.%s"), Deck)));
	}
	return true;
}

// A18.4 (layout): the 5 locales render without clipping at 1080p.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiNoClippingTest, "Verse.UI.Strings.NoClipping", Flags)
bool FVerseUiNoClippingTest::RunTest(const FString&)
{
	const FVerseTextMeasure Measure = FVerseHudPainter::DefaultMeasure();
	AddInfo(FSlateApplication::IsInitialized() ? TEXT("measuring with the Slate font cache") : TEXT("measuring with the estimate"));
	int32 Clipped = 0;
	for (const FString& Lang : FVerseUiStrings::SupportedLanguages())
	{
		FVerseUiStrings Strings;
		Strings.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir());
		Strings.SetLanguage(Lang);

		// HUD: a frame with every block, long names, through the real painter.
		FFakeVerseHudSource Source;
		Source.Names.Add(2, TEXT("Opponent"));
		Source.Bots.Add(2);
		Source.Pawn.bValid = true;
		Source.Pawn.Stance = EVerseStance::Prone;
		Source.Pawn.bSpawnProtected = true;
		Source.Pawn.SpawnProtectionRemaining = 1.9f;
		Source.Pawn.bHasWeapon = true;
		Source.Pawn.WeaponId = TEXT("breach_charge");
		Source.Pawn.Magazine = 888;
		Source.Pawn.MagazineSize = 999;
		Source.Pawn.Reserve = 888;
		Source.Pawn.bReloading = true;
		Source.Pawn.bTacticalReload = false;
		Source.Pawn.Gadgets = {{TEXT("bulwark"), 1, 1, 18.f}, {TEXT("breach_charge"), 2, 2, 0.f}};
		FVerseHudModel Model;
		Model.SetLocalPlayerId(1);
		FVerseHitEvent Wall;
		Wall.InstigatorId = 2;
		Wall.VictimId = 1;
		Wall.PenetrationCount = 2;
		Wall.bHeadshot = 1;
		Model.OnHit(Wall, 0.0);
		FVerseDeathEvent D;
		D.KillerId = 2;
		D.VictimId = 1;
		D.WeaponId = TEXT("breach_charge");
		D.Cause = EVerseDamageSource::Gadget;
		D.RespawnAt = 102.0;
		Model.OnDeath(D, 0.0);
		FVerseSetSummary Sum;
		Sum.Outcome = EVerseSetOutcome::Unfinished;
		Model.OnSetEnded(Sum, 0.0);
		for (int32 Mode = 0; Mode < 2; ++Mode)
		{
			FVerseHudFrame Frame;
			Frame.Model = &Model;
			Frame.Strings = &Strings;
			Frame.Source = &Source;
			Frame.Layout = FVerseUiLayout::Compute(FVector2D(1920, 1080), 0.025f, FMargin(0), 1.f);
			Source.GetPawnState(Frame.Pawn);
			Frame.bHasView = true;
			Frame.ServerTime = 100.0;
			Frame.bKillCam = Mode == 0;
			Frame.KillCamKillerId = 2;
			Frame.SkipKeyName = EKeys::Enter.GetDisplayName();
			FVerseHudDrawList List;
			FVerseHudPainter::Paint(Frame, List, Measure);
			for (const FVerseHudDrawList::FLabel& L : List.Labels)
			{
				const bool bFits = (L.MaxWidth <= 0.f || L.Size.X <= L.MaxWidth + 0.5f) && L.Position.X >= -0.5 && L.Position.X + L.Size.X <= 1920.5;
				if (!bFits)
				{
					++Clipped;
					AddError(FString::Printf(TEXT("%s: HUD %s \"%s\" is %.0f px in %.0f px"), *Lang, *L.Tag.ToString(), *L.Text.ToString(), L.Size.X, L.MaxWidth));
				}
			}
		}

		// Menus: the fixed-width boxes of SVerseUiRoot (1080p reference, the DPI curve scales them).
		TArray<FFixedBox> Boxes;
		for (const FString& Key : Strings.GetKeys())
		{
			if (Key.StartsWith(TEXT("verse.settings.")) && !Key.Contains(TEXT(".page.")) && !Key.Contains(TEXT(".quality.")) && !Key.Contains(TEXT(".gore.")) && Key != TEXT("verse.settings.title") && Key != TEXT("verse.settings.markers_note") && Key != TEXT("verse.settings.press_key"))
			{
				Boxes.Add({Key, 1000.f - 4.f - 56.f - 304.f - 20.f, 15, false});
			}
			if (Key.StartsWith(TEXT("verse.key.")))
			{
				Boxes.Add({Key, 1000.f - 4.f - 56.f - 240.f - 20.f, 15, false});
			}
			if (Key.StartsWith(TEXT("verse.settings.page.")))
			{
				Boxes.Add({Key, (1000.f - 60.f) / 5.f - 4.f - 5.f - 32.f, 15, true});
			}
			if (Key.StartsWith(TEXT("verse.settings.quality.")) || Key.StartsWith(TEXT("verse.settings.gore.")) || Key == TEXT("verse.ui.on") || Key == TEXT("verse.ui.off"))
			{
				Boxes.Add({Key, 200.f, 15, true});
			}
			if (Key.StartsWith(TEXT("verse.armoury.slot.")))
			{
				Boxes.Add({Key, 170.f, 12, true});
			}
			if (Key.StartsWith(TEXT("verse.tier.")) && !Key.EndsWith(TEXT(".desc")))
			{
				Boxes.Add({Key, (860.f - 60.f) / 4.f - 4.f - 5.f - 32.f, 15, true});
			}
			if (Key.StartsWith(TEXT("verse.end.row.")))
			{
				Boxes.Add({Key, (720.f - 60.f) * 0.5f, 15, false});
			}
			if (Key.StartsWith(TEXT("verse.menu.")) && Key != TEXT("verse.menu.title"))
			{
				Boxes.Add({Key, 460.f - 60.f - 5.f - 32.f, 15, true});
			}
			if (Key == TEXT("verse.armoury.start") || Key == TEXT("verse.end.next"))
			{
				Boxes.Add({Key, (860.f - 60.f) * 2.f / 3.f - 37.f, 15, true});
			}
			if (Key == TEXT("verse.end.leave"))
			{
				Boxes.Add({Key, (720.f - 60.f) / 3.f - 43.f, 15, true});
			}
		}
		// Settings press-key text and key names sit in the 240 px key button.
		Boxes.Add({TEXT("verse.settings.press_key"), 240.f - 37.f, 15, true});
		for (const FFixedBox& Box : Boxes)
		{
			const FVector2D Size = Measure(Strings.Get(Box.Key), Box.Size, Box.bBold);
			if (Size.X > Box.Width)
			{
				++Clipped;
				AddError(FString::Printf(TEXT("%s: %s \"%s\" is %.0f px in %.0f px"), *Lang, *Box.Key, *Strings.Get(Box.Key).ToString(), Size.X, Box.Width));
			}
		}
	}
	TestEqual(TEXT("clipped texts over 5 locales at 1080p"), Clipped, 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiArmouryTest, "Verse.UI.Menus.Armoury", Flags)
bool FVerseUiArmouryTest::RunTest(const FString&)
{
	FVerseUiTestWorld W;
	if (!TestNotNull(TEXT("UI subsystem"), W.Ui))
	{
		return false;
	}
	const FName SavedTier = W.Ui->GetUserSettings()->LastTier;
	FVerseArmouryModel& Armoury = W.Ui->GetArmoury();
	TestEqual(TEXT("loadout of combat-state 2.2"), Armoury.GetLoadout().Num(), 5);
	TestEqual(TEXT("primary is the rifle"), Armoury.GetLoadout()[0].ItemId, FName(TEXT("graveline")));
	TestEqual(TEXT("four tiers"), Armoury.GetTiers().Num(), 4);
	TestFalse(TEXT("unknown tier refused"), Armoury.SelectTier(TEXT("impossible")));

	FVerseStationUsedEvent Used;
	Used.Kind = TEXT("armoury");
	Used.StationId = TEXT("hangar.armoury.1");
	Used.UserId = W.Source->LocalId;
	UVerseEventHub::Get(W.World)->OnStationUsed.Broadcast(Used);
	TestEqual(TEXT("the armoury station opens the armoury"), W.Ui->GetScreen(), EVerseUiScreen::Armoury);

	Armoury.SelectTier(TEXT("normal"));
	Armoury.CycleTier(-1);
	TestEqual(TEXT("cycling wraps"), Armoury.GetSelectedTier(), FName(TEXT("adaptive")));
	W.Ui->StartDuelFromArmoury();
	TestEqual(TEXT("start duel asks for the chosen tier"), W.Game->Started.Num() > 0 ? W.Game->Started.Last() : FName(), FName(TEXT("adaptive")));
	TestEqual(TEXT("armoury closes"), W.Ui->GetScreen(), EVerseUiScreen::None);
	W.Ui->GetUserSettings()->LastTier = SavedTier;
	W.Ui->GetUserSettings()->SaveToDisk();
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiBarTest, "Verse.UI.Menus.Bar", Flags)
bool FVerseUiBarTest::RunTest(const FString&)
{
	const TArray<FName> Decks = {TEXT("bridge"), TEXT("ops"), TEXT("engineering"), TEXT("hangar")};
	TArray<FVerseBarEntry> Idle = FVerseBarModel::Build(Decks, TEXT("ops"), false);
	TestEqual(TEXT("quick duel, 4 decks, return"), Idle.Num(), 6);
	TestEqual(TEXT("first is quick duel"), Idle[0].Kind, EVerseBarEntryKind::QuickStartDuel);
	TestTrue(TEXT("current deck marked"), Idle[2].bActive);
	TestEqual(TEXT("last returns to the app"), Idle.Last().Kind, EVerseBarEntryKind::ReturnToApp);
	TArray<FVerseBarEntry> InDuel = FVerseBarModel::Build(Decks, TEXT("hangar"), true);
	TestEqual(TEXT("in a duel the first entry leaves it"), InDuel[0].LabelKey, FString(TEXT("verse.bar.leave_duel")));
	TestFalse(TEXT("other decks wait until the duel is left"), InDuel[1].bEnabled);

	FVerseUiTestWorld W;
	W.Ui->QuickStartDuel();
	TestEqual(TEXT("quick start uses the last tier"), W.Game->Started.Num(), 1);
	TestEqual(TEXT("quick start tier"), W.Game->Started[0], W.Ui->GetUserSettings()->LastTier);
	W.Ui->LeaveDuel();
	TestEqual(TEXT("leave"), W.Game->Left, 1);
	W.Ui->TravelToDeck(TEXT("engineering"));
	TestEqual(TEXT("deck navigation"), W.Game->CurrentDeck, FName(TEXT("engineering")));
	W.Ui->ReturnToApp(TEXT("esc_menu"));
	TestEqual(TEXT("return to app from the bar"), W.Bridge->Count(TEXT("focus.return_to_app")), 1);
	TestTrue(TEXT("Tab toggles the bar"), W.Ui->HandleKey(EKeys::Tab) && W.Ui->IsBarOpen());
	TestTrue(TEXT("Esc opens the menu"), W.Ui->HandleKey(EKeys::Escape) && W.Ui->GetScreen() == EVerseUiScreen::EscMenu);
	TestTrue(TEXT("Esc closes it"), W.Ui->HandleKey(EKeys::Escape) && W.Ui->GetScreen() == EVerseUiScreen::None);
	TestFalse(TEXT("Enter is free when no kill cam runs"), W.Ui->HandleKey(EKeys::Enter));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiEndScreenTest, "Verse.UI.Menus.EndOfSet", Flags)
bool FVerseUiEndScreenTest::RunTest(const FString&)
{
	FVerseSetSummary Summary;
	Summary.SetIndex = 3;
	Summary.BotTier = TEXT("adaptive");
	Summary.Outcome = EVerseSetOutcome::Won;
	Summary.Person.PlayerId = 1;
	Summary.Person.Kills = 10;
	Summary.Person.Deaths = 7;
	Summary.Person.ShotsFired = 200;
	Summary.Person.ShotsHit = 61;
	Summary.Opponent.PlayerId = 2;
	Summary.Opponent.bIsBot = true;
	Summary.Opponent.Kills = 7;
	Summary.Opponent.Deaths = 10;
	const FVerseEndScreen Screen = FVerseEndScreen::Build(Summary, 0.62f);
	TestEqual(TEXT("won title"), Screen.TitleKey, FString(TEXT("verse.end.won")));
	TestTrue(TEXT("adaptive s shown"), Screen.bShowSkill && FMath::IsNearlyEqual(Screen.Skill, 0.62f));
	TestEqual(TEXT("nine rows"), Screen.Rows.Num(), 9);
	TestEqual(TEXT("K/D"), Screen.Rows[2].Person.ToString(), FString(TEXT("1.43")));
	// The Verse language picks the number format, whatever the machine's culture is.
	TestEqual(TEXT("K/D in German"), FVerseEndScreen::Build(Summary, 0.62f, TEXT("de")).Rows[2].Person.ToString(), FString(TEXT("1,43")));
	FVerseSetSummary Hard = Summary;
	Hard.BotTier = TEXT("hard");
	TestFalse(TEXT("no s for a fixed tier"), FVerseEndScreen::Build(Hard, -1.f).bShowSkill);

	FVerseUiTestWorld W;
	W.Source->Bots.Add(2);
	W.Source->Skill = 0.62f;
	UVerseEventHub::Get(W.World)->OnSetEnded.Broadcast(Summary);
	TestEqual(TEXT("set end opens the end screen"), W.Ui->GetScreen(), EVerseUiScreen::EndOfSet);
	TestTrue(TEXT("end screen reads s from the bot's player state"), FMath::IsNearlyEqual(W.Ui->GetEndScreen().Skill, 0.62f));
	W.Ui->ContinueAfterSet();
	TestEqual(TEXT("next set closes it"), W.Ui->GetScreen(), EVerseUiScreen::None);
	FVerseSetSummary Left = Summary;
	Left.Outcome = EVerseSetOutcome::Unfinished;
	UVerseEventHub::Get(W.World)->OnSetEnded.Broadcast(Left);
	TestEqual(TEXT("an unfinished set (leaving) opens nothing"), W.Ui->GetScreen(), EVerseUiScreen::None);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
