#include "Audio/VerseAudioSubsystem.h"
#include "Core/VerseUiStrings.h"
#include "HAL/IConsoleManager.h"
#include "Internationalization/Regex.h"
#include "Misc/AutomationTest.h"
#include "ServiceRecord/VerseServiceRecordModel.h"
#include "Settings/VerseUiSettings.h"
#include "Tests/Audio/Fakes/VerseAudioFakes.h"
#include "Tests/UI/Fakes/VerseUiFakes.h"

#if WITH_DEV_AUTOMATION_TESTS

// Parity rows of work stream S13 (settings, strings): N-04, N-06, R-12, R-14, T-02, V-21, Z-14.
// Tests are named after the row: Verse.Parity.<Section>.<Id>.

namespace VerseParityS13
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	const TCHAR* const Languages[] = {TEXT("en"), TEXT("de"), TEXT("es"), TEXT("pt"), TEXT("zh")};

	/** Every placeholder name any catalogue string uses, with a sample value. */
	FFormatNamedArguments SampleArguments()
	{
		FFormatNamedArguments Args;
		for (const TCHAR* Name : {TEXT("n"), TEXT("count"), TEXT("reason"), TEXT("skill"), TEXT("person"), TEXT("opponent"),
				 TEXT("set"), TEXT("won"), TEXT("lost"), TEXT("tier"), TEXT("seconds"), TEXT("killer"), TEXT("weapon"),
				 TEXT("victim"), TEXT("player"), TEXT("reserve"), TEXT("key"), TEXT("target")})
		{
			Args.Add(Name, FText::FromString(TEXT("7")));
		}
		return Args;
	}

	TArray<FString> PlaceholdersOf(const FString& Text)
	{
		TArray<FString> Names;
		const FRegexPattern Pattern(TEXT("\\{([A-Za-z0-9_]+)\\}"));
		FRegexMatcher Matcher(Pattern, Text);
		while (Matcher.FindNext())
		{
			Names.AddUnique(Matcher.GetCaptureGroup(1));
		}
		Names.Sort();
		return Names;
	}

	FVerseUiStrings LoadStrings()
	{
		FVerseUiStrings Strings;
		Strings.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir());
		return Strings;
	}
}

using namespace VerseParityS13;

// N-06: every key with a placeholder renders with sample values and no braces left, in 5 locales;
// a translation keeps exactly the placeholders of the English text.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityN06, "Verse.Parity.N.06", Flags)
bool FVerseParityN06::RunTest(const FString&)
{
	FVerseUiStrings Strings = LoadStrings();
	const TArray<FString> Keys = Strings.GetKeys();
	if (!TestTrue(TEXT("catalogue loaded"), Keys.Num() > 100))
	{
		return false;
	}
	// A sample value for every placeholder the English catalogue uses: a fixed list fell behind the
	// strings ({fps}, {ms}, {value}, {action} were added later) and reported braces for keys whose
	// callers pass those arguments.
	FFormatNamedArguments Args = SampleArguments();
	for (const FString& Key : Keys)
	{
		for (const FString& Name : PlaceholdersOf(Strings.GetIn(Key, TEXT("en"))))
		{
			if (!Args.Contains(Name))
			{
				Args.Add(Name, FText::FromString(TEXT("7")));
			}
		}
	}
	int32 WithPlaceholder = 0;
	for (const FString& Key : Keys)
	{
		const TArray<FString> English = PlaceholdersOf(Strings.GetIn(Key, TEXT("en")));
		for (const TCHAR* Lang : Languages)
		{
			const FString Raw = Strings.GetIn(Key, Lang);
			TestFalse(FString::Printf(TEXT("%s has text in %s"), *Key, Lang), Raw.IsEmpty());
			TestTrue(FString::Printf(TEXT("%s keeps the English placeholders in %s"), *Key, Lang), PlaceholdersOf(Raw) == English);
			Strings.SetLanguage(Lang);
			const FString Filled = Strings.Format(Key, Args).ToString();
			TestFalse(FString::Printf(TEXT("%s (%s) has braces left: %s"), *Key, Lang, *Filled), Filled.Contains(TEXT("{")) || Filled.Contains(TEXT("}")));
		}
		WithPlaceholder += English.Num() > 0 ? 1 : 0;
	}
	TestTrue(TEXT("some keys carry placeholders"), WithPlaceholder > 10);
	return true;
}

// R-14: the 15 rank words exist as verse.ranks.rank.<id> in 5 locales and differ from the id.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityR14, "Verse.Parity.R.14", Flags)
bool FVerseParityR14::RunTest(const FString&)
{
	FVerseUiStrings Strings = LoadStrings();
	const TArray<FVerseRankRow>& Ladder = FVerseServiceRecordModel::Ladder();
	TestEqual(TEXT("15 ranks"), Ladder.Num(), 15);
	for (const FVerseRankRow& Rank : Ladder)
	{
		const FString Key = FString::Printf(TEXT("verse.ranks.rank.%s"), *Rank.Id.ToString());
		TSet<FString> Words;
		for (const TCHAR* Lang : Languages)
		{
			const FString Word = Strings.GetIn(Key, Lang);
			TestFalse(FString::Printf(TEXT("%s in %s"), *Key, Lang), Word.IsEmpty());
			TestFalse(TEXT("a word, not the id"), Word.Equals(Rank.Id.ToString(), ESearchCase::CaseSensitive));
			Words.Add(Word);
		}
		TestTrue(FString::Printf(TEXT("%s is translated"), *Key), Words.Num() > 1);
	}
	Strings.SetLanguage(TEXT("de"));
	TestEqual(TEXT("German rank word"), Strings.Get(TEXT("verse.ranks.rank.lieutenant")).ToString(), FString(TEXT("Leutnant")));
	return true;
}

// N-04: settings.changed {lang, strings} re-texts every key without a restart; a bridge string
// wins over the catalogue until the language changes again.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityN04, "Verse.Parity.N.04", Flags)
bool FVerseParityN04::RunTest(const FString&)
{
	FVerseUiTestWorld T;
	if (!TestNotNull(TEXT("UI subsystem"), T.Ui))
	{
		return false;
	}
	T.Ui->ApplyWelcome(T.Bridge->MakeWelcome(TEXT("en")));
	const FVerseUiStrings& Live = T.Ui->GetStrings();
	TestEqual(TEXT("starts in English"), Live.GetLanguage(), FString(TEXT("en")));
	const FString Before = Live.Get(TEXT("verse.settings.quality")).ToString();

	for (const TCHAR* Lang : {TEXT("de"), TEXT("es"), TEXT("pt"), TEXT("zh"), TEXT("en")})
	{
		TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("lang"), Lang);
		T.Ui->ApplySettingsChanged(Data);
		TestEqual(TEXT("language switched live"), Live.GetLanguage(), FString(Lang));
		int32 Wrong = 0;
		for (const FString& Key : Live.GetKeys())
		{
			Wrong += Live.Get(Key).ToString() == Live.GetIn(Key, Lang) ? 0 : 1;
		}
		TestEqual(FString::Printf(TEXT("every key re-texted in %s"), Lang), Wrong, 0);
	}
	TestEqual(TEXT("back to English text"), Live.Get(TEXT("verse.settings.quality")).ToString(), Before);

	TSharedRef<FJsonObject> WithStrings = MakeShared<FJsonObject>();
	WithStrings->SetStringField(TEXT("lang"), TEXT("de"));
	TSharedRef<FJsonObject> Table = MakeShared<FJsonObject>();
	Table->SetStringField(TEXT("verse.menu.resume"), TEXT("Weiter geht's"));
	WithStrings->SetObjectField(TEXT("strings"), Table);
	T.Ui->ApplySettingsChanged(WithStrings);
	TestEqual(TEXT("bridge string wins live"), Live.Get(TEXT("verse.menu.resume")).ToString(), FString(TEXT("Weiter geht's")));
	return true;
}

// T-02: the panel names the tier in effect, also under Auto, in every locale.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityT02, "Verse.Parity.T.02", Flags)
bool FVerseParityT02::RunTest(const FString&)
{
	TestEqual(TEXT("a chosen level wins"), FVerseRenderTier::Resolve(2, 4), 2);
	TestEqual(TEXT("auto shows the engine's level"), FVerseRenderTier::Resolve(-1, 3), 3);
	TestEqual(TEXT("auto with an odd engine level is custom"), FVerseRenderTier::Resolve(-1, 9), -1);
	TestEqual(TEXT("auto with no engine level is custom"), FVerseRenderTier::Resolve(-1, -1), -1);

	FVerseUiStrings Strings = LoadStrings();
	for (const TCHAR* Lang : Languages)
	{
		Strings.SetLanguage(Lang);
		TSet<FString> Names;
		for (int32 Level = -1; Level <= 4; ++Level)
		{
			const FText Tier = Strings.Get(FVerseRenderTier::KeyFor(Level));
			Names.Add(Tier.ToString());
			FFormatNamedArguments Args;
			Args.Add(TEXT("tier"), Tier);
			const FString Line = Strings.Format(TEXT("verse.settings.render_tier"), Args).ToString();
			TestTrue(FString::Printf(TEXT("%s level %d: the line names the tier"), Lang, Level), Line.Contains(Tier.ToString()));
			TestFalse(TEXT("no braces left"), Line.Contains(TEXT("{")));
		}
		TestEqual(FString::Printf(TEXT("%s: 6 distinct tier words"), Lang), Names.Num(), 6);
	}
	return true;
}

// V-21: the view last chosen is kept (default third); a new process gets it back from the app config.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV21, "Verse.Parity.V.21", Flags)
bool FVerseParityV21::RunTest(const FString&)
{
	TestEqual(TEXT("default view is third"), FVerseAppSettings().ViewMode, FString(TEXT("third")));
	TSharedPtr<FFakeVerseUiBridgePort> Backend = MakeShared<FFakeVerseUiBridgePort>();
	for (const TCHAR* View : {TEXT("first"), TEXT("overview"), TEXT("third")})
	{
		{
			FVerseUiTestWorld First(Backend);
			if (!TestNotNull(TEXT("UI subsystem"), First.Ui))
			{
				return false;
			}
			First.Ui->ApplyWelcome(Backend->MakeWelcome());
			FVerseAppSettings Next = First.Ui->GetAppSettings();
			Next.ViewMode = View;
			First.Ui->SetAppSettings(Next);
		}
		FVerseUiTestWorld Second(MakeShared<FFakeVerseUiBridgePort>());
		Second.Ui->ApplyWelcome(Backend->MakeWelcome());
		TestEqual(FString::Printf(TEXT("relaunch restores %s"), View), Second.Ui->GetAppSettings().ViewMode, FString(View));
		IConsoleVariable* Var = IConsoleManager::Get().FindConsoleVariable(TEXT("Verse.Settings.ViewMode"));
		TestTrue(TEXT("view published for the deck camera"), Var && Var->GetString() == View);
	}
	// Settings reset returns the view to third.
	FVerseUiTestWorld Reset(Backend);
	Reset.Ui->ApplyWelcome(Backend->MakeWelcome());
	FVerseAppSettings Other = Reset.Ui->GetAppSettings();
	Other.ViewMode = TEXT("first");
	Reset.Ui->SetAppSettings(Other);
	Reset.Ui->ResetSettings();
	TestEqual(TEXT("reset returns to third"), Reset.Ui->GetAppSettings().ViewMode, FString(TEXT("third")));
	return true;
}

// Z-14 and R-12 (wiring): settings.changed {ui_sound}, {level_sound} and {volume} reach the audio subsystem.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityZ14, "Verse.Parity.Z.14", Flags)
bool FVerseParityZ14::RunTest(const FString&)
{
	FVerseUiTestWorld T;
	if (!TestNotNull(TEXT("UI subsystem"), T.Ui))
	{
		return false;
	}
	UVerseAudioSubsystem* Audio = T.World->GetSubsystem<UVerseAudioSubsystem>();
	if (!TestNotNull(TEXT("audio subsystem in the same world"), Audio))
	{
		return false;
	}
	TSharedPtr<FFakeVerseAudioSink> Sink = MakeShared<FFakeVerseAudioSink>();
	Audio->SetSink(Sink);
	T.Ui->ApplyWelcome(T.Bridge->MakeWelcome());
	TestTrue(TEXT("welcome: sound on"), Sink->Master > 0.f);

	TSharedRef<FJsonObject> Off = MakeShared<FJsonObject>();
	Off->SetBoolField(TEXT("ui_sound"), false);
	T.Ui->ApplySettingsChanged(Off);
	TestEqual(TEXT("settings.changed {ui_sound:false} mutes the Verse"), Sink->Master, 0.f);
	TSharedRef<FJsonObject> On = MakeShared<FJsonObject>();
	On->SetBoolField(TEXT("ui_sound"), true);
	T.Ui->ApplySettingsChanged(On);
	TestTrue(TEXT("{ui_sound:true} unmutes"), Sink->Master > 0.f);

	auto SetVolume = [&T](double V)
	{
		TSharedRef<FJsonObject> View = MakeShared<FJsonObject>();
		View->SetNumberField(TEXT("volume"), V);
		TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetObjectField(TEXT("view"), View);
		T.Ui->ApplySettingsChanged(Data);
	};
	SetVolume(0.25);
	TestTrue(TEXT("volume reaches the master gain"), FMath::IsNearlyEqual(Sink->Master, 0.25f, 1e-3f));
	SetVolume(0.0);
	TestEqual(TEXT("volume 0 silences"), Sink->Master, 0.f);

	// R-12: the bell switch.
	TestTrue(TEXT("bell on by default"), Audio->IsLevelSoundEnabled());
	TSharedRef<FJsonObject> Bell = MakeShared<FJsonObject>();
	Bell->SetBoolField(TEXT("level_sound"), false);
	T.Ui->ApplySettingsChanged(Bell);
	TestFalse(TEXT("{level_sound:false} switches the bell off"), Audio->IsLevelSoundEnabled());
	TestTrue(TEXT("the bell switch leaves the UI sound alone"), Audio->IsUiSoundEnabled());
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
