#include "Audio/VerseAudioSubsystem.h"
#include "Engine/PostProcessVolume.h"
#include "Events/VerseEventHub.h"
#include "HAL/IConsoleManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/ScopeExit.h"
#include "Qa/VerseQaRegistry.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Settings/VerseGameSettings.h"
#include "Settings/VerseUiSettings.h"
#include "Tests/UI/Fakes/VerseUiFakes.h"
#include "UObject/UnrealType.h"

#if WITH_DEV_AUTOMATION_TESTS

namespace VerseUiSettingsTest
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	/** The golden fixtures of G0.11 (bridge-protocol BW11). */
	TArray<TSharedPtr<FJsonValue>> Golden(const FString& Name)
	{
		FString Json;
		TArray<TSharedPtr<FJsonValue>> Out;
		const FString Path = FPaths::Combine(FPaths::ProjectDir(), TEXT("Tests"), TEXT("Data"), TEXT("bridge"), TEXT("messages"), Name + TEXT(".json"));
		if (FFileHelper::LoadFileToString(Json, *Path))
		{
			FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Out);
		}
		return Out;
	}

	/** Restores the person's Unreal user settings after a test changed them. */
	struct FUserSettingsGuard
	{
		UVerseUiUserSettings* Settings;
		float DuelFov;
		TArray<FVerseKeyBinding> Keys;
		int32 Scalability;
		float TextScale;
		FName Tier;
		FString Game;

		explicit FUserSettingsGuard(UVerseUiUserSettings* In)
			: Settings(In), DuelFov(In->DuelFov), Keys(In->KeyBindings), Scalability(In->Scalability), TextScale(In->TextScale), Tier(In->LastTier), Game(In->GameSettings)
		{
		}
		~FUserSettingsGuard()
		{
			Settings->DuelFov = DuelFov;
			Settings->KeyBindings = Keys;
			Settings->Scalability = Scalability;
			Settings->TextScale = TextScale;
			Settings->LastTier = Tier;
			Settings->GameSettings = Game;
			Settings->SaveToDisk();
		}
	};

	TArray<TSharedPtr<FJsonValue>> GoldenReplies(const FString& Name)
	{
		FString Json;
		TArray<TSharedPtr<FJsonValue>> Out;
		const FString Path = FPaths::Combine(FPaths::ProjectDir(), TEXT("Tests"), TEXT("Data"), TEXT("bridge"), TEXT("replies"), Name + TEXT(".json"));
		if (FFileHelper::LoadFileToString(Json, *Path))
		{
			FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Out);
		}
		return Out;
	}

	/** The data of the first golden frame that carries a game object. */
	TSharedPtr<FJsonObject> FirstWithGame(const TArray<TSharedPtr<FJsonValue>>& Frames)
	{
		for (const TSharedPtr<FJsonValue>& Frame : Frames)
		{
			const TSharedPtr<FJsonObject> Data = Frame->AsObject()->GetObjectField(TEXT("data"));
			if (Data->HasField(TEXT("game")))
			{
				return Data;
			}
		}
		return nullptr;
	}
}

using namespace VerseUiSettingsTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiAppSettingsJsonTest, "Verse.UI.Settings.Json", Flags)
bool FVerseUiAppSettingsJsonTest::RunTest(const FString&)
{
	const TArray<TSharedPtr<FJsonValue>> Welcome = Golden(TEXT("welcome"));
	if (!TestTrue(TEXT("welcome golden fixture present"), Welcome.Num() >= 2))
	{
		return false;
	}
	FVerseAppSettings A;
	A.ApplyJson(Welcome[1]->AsObject()->GetObjectField(TEXT("data"))->GetObjectField(TEXT("settings")));
	TestEqual(TEXT("gore from welcome"), A.Gore, EVerseGoreLevel::Reduced);
	TestEqual(TEXT("return key from welcome"), A.ReturnKey, EKeys::F10);
	TestEqual(TEXT("third-person FOV 70 (parity V-09)"), A.FovThird, 70.f);
	TestEqual(TEXT("first-person FOV 85 (parity V-09)"), A.FovFirst, 85.f);

	// Every settings.set the UI writes is a subset of welcome.settings (bridge-protocol 14).
	const TSharedPtr<FJsonObject> Full = Welcome[0]->AsObject()->GetObjectField(TEXT("data"))->GetObjectField(TEXT("settings"));
	FVerseAppSettings B = A;
	B.Gore = EVerseGoreLevel::Full;
	B.FovFirst = 90.f;
	B.ReturnKey = EKeys::F8;
	const TSharedRef<FJsonObject> Diff = A.Diff(B);
	TestEqual(TEXT("diff carries the 3 changes"), Diff->Values.Num(), 3);
	for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Diff->Values)
	{
		TestTrue(FString::Printf(TEXT("%s is a welcome.settings key"), *Pair.Key), Full->HasField(Pair.Key));
	}
	TestEqual(TEXT("view subset"), Diff->GetObjectField(TEXT("view"))->Values.Num(), 1);
	TestEqual(TEXT("no change, empty diff"), A.Diff(A)->Values.Num(), 0);

	// The settings.set and settings.changed golden fixtures apply cleanly.
	for (const TSharedPtr<FJsonValue>& Frame : Golden(TEXT("settings.changed")))
	{
		FVerseAppSettings C;
		C.ApplyJson(Frame->AsObject()->GetObjectField(TEXT("data")));
		if (Frame->AsObject()->GetObjectField(TEXT("data"))->HasField(TEXT("return_key")))
		{
			TestEqual(TEXT("settings.changed return key F9"), C.ReturnKey, EKeys::F9);
			TestTrue(TEXT("settings.changed reduced motion"), C.bReducedMotion);
		}
	}
	for (const TSharedPtr<FJsonValue>& Frame : Golden(TEXT("settings.set")))
	{
		FVerseAppSettings C;
		C.ApplyJson(Frame->AsObject()->GetObjectField(TEXT("data")));
		TestTrue(TEXT("settings.set fixture applies"), true);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiKeyMapTest, "Verse.UI.Settings.KeyMap", Flags)
bool FVerseUiKeyMapTest::RunTest(const FString&)
{
	FVerseKeyMap Map;
	FString Error;
	if (!TestTrue(TEXT("keys.json loads"), Map.LoadFile(FVerseKeyMap::DefaultPath(), &Error)))
	{
		AddError(Error);
		return false;
	}
	TSet<FKey> Used;
	for (const FVerseKeyMap::FAction& A : Map.GetActions())
	{
		TestFalse(FString::Printf(TEXT("default key of %s is unique"), *A.Action.ToString()), Used.Contains(A.DefaultKey));
		Used.Add(A.DefaultKey);
	}
	TestEqual(TEXT("F10 returns to the app"), Map.Route(EKeys::F10), EVerseUiCommand::ReturnToApp);
	TestEqual(TEXT("Esc opens the menu"), Map.Route(EKeys::Escape), EVerseUiCommand::EscMenu);
	TestEqual(TEXT("W is gameplay input"), Map.Route(EKeys::W), EVerseUiCommand::None);

	const FName Swapped = Map.Rebind(TEXT("reload"), EKeys::F);
	TestEqual(TEXT("rebinding to a used key swaps"), Swapped, FName(TEXT("interact")));
	TestEqual(TEXT("reload on F"), Map.GetKey(TEXT("reload")), EKeys::F);
	TestEqual(TEXT("interact took R"), Map.GetKey(TEXT("interact")), EKeys::R);
	TestEqual(TEXT("Esc cannot be bound"), Map.Rebind(TEXT("jump"), EKeys::Escape), FName(NAME_None));
	TestEqual(TEXT("jump unchanged"), Map.GetKey(TEXT("jump")), EKeys::SpaceBar);

	FVerseKeyMap Reloaded;
	Reloaded.LoadFile(FVerseKeyMap::DefaultPath());
	Reloaded.SetBindings(Map.GetBindings());
	TestEqual(TEXT("bindings round-trip"), Reloaded.GetKey(TEXT("reload")), EKeys::F);
	return true;
}

// A18.5: every setting keeps its value across a Verse restart.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiSettingsPersistTest, "Verse.UI.Settings.Persist", Flags)
bool FVerseUiSettingsPersistTest::RunTest(const FString&)
{
	TSharedPtr<FFakeVerseUiBridgePort> Backend = MakeShared<FFakeVerseUiBridgePort>();
	{
		FVerseUiTestWorld First(Backend);
		if (!TestNotNull(TEXT("UI subsystem"), First.Ui))
		{
			return false;
		}
		FUserSettingsGuard Guard(First.Ui->GetUserSettings());
		const EVerseGoreLevel GoreBefore = UVerseUiSubsystem::ReadGoreSetting();
		ON_SCOPE_EXIT { UVerseUiSubsystem::WriteGoreSetting(nullptr, GoreBefore); };
		First.Ui->ApplyWelcome(Backend->MakeWelcome());

		// Unreal-side settings.
		First.Ui->SetDuelFov(95.f);
		First.Ui->SetScalability(2);
		First.Ui->SetTextScale(1.3f);
		First.Ui->RebindKey(TEXT("reload"), EKeys::H);
		First.Ui->GetArmoury().SelectTier(TEXT("elite"));
		First.Ui->StartDuelFromArmoury();
		// App-backed settings.
		First.Ui->SetGore(EVerseGoreLevel::Reduced);
		First.Ui->SetReducedMotion(true);
		FVerseAppSettings Next = First.Ui->GetAppSettings();
		Next.FovThird = 75.f;
		Next.FovFirst = 90.f;
		Next.Sensitivity = 1.4f;
		Next.bInvertY = true;
		Next.Volume = 0.45f;
		Next.bUiSound = false;
		First.Ui->SetAppSettings(Next);

		// "Restart": a fresh settings object reads the user settings file back.
		UVerseUiUserSettings* Fresh = NewObject<UVerseUiUserSettings>();
		Fresh->ReloadFromDisk();
		TestEqual(TEXT("duel FOV persists"), Fresh->DuelFov, 95.f);
		TestEqual(TEXT("scalability persists"), Fresh->Scalability, 2);
		TestTrue(TEXT("text size persists"), FMath::IsNearlyEqual(Fresh->TextScale, 1.3f, 1e-4f));
		TestEqual(TEXT("last tier persists"), Fresh->LastTier, FName(TEXT("elite")));
		FVerseKeyMap Map;
		Map.LoadFile(FVerseKeyMap::DefaultPath());
		Map.SetBindings(Fresh->KeyBindings);
		TestEqual(TEXT("key binding persists"), Map.GetKey(TEXT("reload")), EKeys::H);

		// A new Verse process gets the app's stored settings in welcome.
		{
			FVerseUiTestWorld Second(MakeShared<FFakeVerseUiBridgePort>());
			Second.Ui->ApplyWelcome(Backend->MakeWelcome());
			const FVerseAppSettings& S = Second.Ui->GetAppSettings();
			TestEqual(TEXT("gore persists"), S.Gore, EVerseGoreLevel::Reduced);
			TestTrue(TEXT("reduced motion persists"), S.bReducedMotion);
			TestEqual(TEXT("third-person FOV persists"), S.FovThird, 75.f);
			TestEqual(TEXT("first-person FOV persists"), S.FovFirst, 90.f);
			TestTrue(TEXT("sensitivity persists"), FMath::IsNearlyEqual(S.Sensitivity, 1.4f, 1e-4f));
			TestTrue(TEXT("invert persists"), S.bInvertY);
			TestTrue(TEXT("volume persists"), FMath::IsNearlyEqual(S.Volume, 0.45f, 1e-4f));
			TestFalse(TEXT("interface sound persists"), S.bUiSound);
			TestEqual(TEXT("duel FOV restored in the new process"), Second.Ui->GetUserSettings()->DuelFov, 95.f);
			TestEqual(TEXT("armoury tier restored"), Second.Ui->GetArmoury().GetSelectedTier(), FName(TEXT("elite")));
			IConsoleVariable* Fov = IConsoleManager::Get().FindConsoleVariable(TEXT("Verse.Settings.DuelFov"));
			TestTrue(TEXT("duel FOV published for the camera owner"), Fov && FMath::IsNearlyEqual(Fov->GetFloat(), 95.f));
		}
	}
	return true;
}

// A18.5: rebinding the return key to F8 makes F8 send focus.return_to_app and F10 do nothing.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiReturnKeyTest, "Verse.UI.Settings.ReturnKey", Flags)
bool FVerseUiReturnKeyTest::RunTest(const FString&)
{
	FVerseUiTestWorld W;
	if (!TestNotNull(TEXT("UI subsystem"), W.Ui))
	{
		return false;
	}
	FUserSettingsGuard Guard(W.Ui->GetUserSettings());
	W.Ui->ApplyWelcome(W.Bridge->MakeWelcome());
	TestTrue(TEXT("F10 returns by default"), W.Ui->HandleKey(EKeys::F10));
	TestEqual(TEXT("one return frame"), W.Bridge->Count(TEXT("focus.return_to_app")), 1);
	W.Bridge->Frames.Reset();

	W.Ui->SetReturnKey(EKeys::F8);
	TestEqual(TEXT("one settings.set for the rebind"), W.Bridge->Count(TEXT("settings.set")), 1);
	FString Key;
	TestTrue(TEXT("settings.set carries return_key F8"),
		W.Bridge->Last(TEXT("settings.set"))->Data->TryGetStringField(TEXT("return_key"), Key) && Key == TEXT("F8"));

	TestTrue(TEXT("F8 is used"), W.Ui->HandleKey(EKeys::F8));
	const FFakeVerseUiBridgePort::FFrame* Return = W.Bridge->Last(TEXT("focus.return_to_app"));
	TestTrue(TEXT("F8 sends focus.return_to_app {reason: return_key}"), Return && Return->Data->GetStringField(TEXT("reason")) == TEXT("return_key"));
	const int32 Before = W.Bridge->Frames.Num();
	TestFalse(TEXT("F10 is not used any more"), W.Ui->HandleKey(EKeys::F10));
	TestEqual(TEXT("F10 sends nothing"), W.Bridge->Frames.Num(), Before);

	// The app's echo (settings.changed) keeps it, and the next welcome carries it.
	FVerseUiTestWorld Restart;
	Restart.Ui->ApplyWelcome(W.Bridge->MakeWelcome());
	TestEqual(TEXT("return key after restart"), Restart.Ui->GetKeyMap().GetKey(FVerseKeyMap::ReturnAction()), EKeys::F8);
	TestTrue(TEXT("F8 after restart"), Restart.Ui->HandleKey(EKeys::F8));
	TestFalse(TEXT("F10 after restart"), Restart.Ui->HandleKey(EKeys::F10));
	return true;
}

// A18.5: a gore change sends one settings.set and the next welcome carries it.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiGoreSettingTest, "Verse.UI.Settings.Gore", Flags)
bool FVerseUiGoreSettingTest::RunTest(const FString&)
{
	FVerseUiTestWorld W;
	if (!TestNotNull(TEXT("UI subsystem"), W.Ui))
	{
		return false;
	}
	const EVerseGoreLevel Before = UVerseUiSubsystem::ReadGoreSetting();
	ON_SCOPE_EXIT { UVerseUiSubsystem::WriteGoreSetting(nullptr, Before); };
	W.Ui->ApplyWelcome(W.Bridge->MakeWelcome());
	W.Bridge->Frames.Reset();
	W.Ui->SetGore(EVerseGoreLevel::Reduced);
	TestEqual(TEXT("exactly one settings.set"), W.Bridge->Count(TEXT("settings.set")), 1);
	TestEqual(TEXT("frame data"), FFakeVerseUiBridgePort::ToString(W.Bridge->Frames[0].Data), FString(TEXT("{\"gore\":\"reduced\"}")));
	W.Ui->SetGore(EVerseGoreLevel::Reduced);
	TestEqual(TEXT("setting the same value again sends nothing"), W.Bridge->Count(TEXT("settings.set")), 1);

	const TSharedRef<FJsonObject> Welcome = W.Bridge->MakeWelcome();
	TestEqual(TEXT("the next welcome carries gore reduced"), Welcome->GetObjectField(TEXT("settings"))->GetStringField(TEXT("gore")), FString(TEXT("reduced")));
	FVerseUiTestWorld Restart;
	Restart.Ui->ApplyWelcome(Welcome);
	TestEqual(TEXT("restarted Verse reads gore reduced"), Restart.Ui->GetAppSettings().Gore, EVerseGoreLevel::Reduced);
	// VerseGore reads UVerseSettings::GoreLevel from GameUserSettings (combat-state 8, WP05).
	TestEqual(TEXT("UVerseSettings GoreLevel as VerseGore reads it"), UVerseUiSubsystem::ReadGoreSetting(), EVerseGoreLevel::Reduced);
	if (UClass* VerseSettings = FindObject<UClass>(nullptr, TEXT("/Script/Verse.VerseSettings")))
	{
		const FEnumProperty* Prop = FindFProperty<FEnumProperty>(VerseSettings, TEXT("GoreLevel"));
		TestTrue(TEXT("UVerseSettings default object carries Reduced"),
			Prop && Prop->GetUnderlyingProperty()->GetSignedIntPropertyValue(Prop->ContainerPtrToValuePtr<void>(VerseSettings->GetDefaultObject())) == int64(EVerseGoreLevel::Reduced));
	}
	else
	{
		AddWarning(TEXT("Verse module not loaded: UVerseSettings default object not checked"));
	}

	// settings.changed from the app applies live.
	TSharedRef<FJsonObject> Changed = MakeShared<FJsonObject>();
	Changed->SetStringField(TEXT("gore"), TEXT("full"));
	Restart.Ui->ApplySettingsChanged(Changed);
	TestEqual(TEXT("settings.changed applies"), Restart.Ui->GetAppSettings().Gore, EVerseGoreLevel::Full);
	TestEqual(TEXT("settings.changed reaches VerseGore's setting"), UVerseUiSubsystem::ReadGoreSetting(), EVerseGoreLevel::Full);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiDuelFovTest, "Verse.UI.Settings.DuelFov", Flags)
bool FVerseUiDuelFovTest::RunTest(const FString&)
{
	UVerseUiUserSettings* Defaults = NewObject<UVerseUiUserSettings>();
	TestEqual(TEXT("default duel FOV 100 (bot.md 3.1)"), Defaults->DuelFov, 100.f);
	Defaults->DuelFov = 140.f;
	Defaults->Clamp();
	TestEqual(TEXT("clamped to 110"), Defaults->DuelFov, 110.f);
	Defaults->DuelFov = 40.f;
	Defaults->Clamp();
	TestEqual(TEXT("clamped to 80"), Defaults->DuelFov, 80.f);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiQaStatsTest, "Verse.UI.QA.Stats", Flags)
bool FVerseUiQaStatsTest::RunTest(const FString&)
{
	FVerseUiTestWorld W;
	UVerseQaRegistry* Registry = UVerseQaRegistry::Get();
	if (!TestNotNull(TEXT("QA registry"), Registry))
	{
		return false;
	}
	FString Result;
	TestTrue(TEXT("Verse.QA.Stats is registered"), Registry->Execute(TEXT("Verse.QA.Stats"), {}, Result));
	TSharedPtr<FJsonObject> Json;
	TestTrue(TEXT("returns JSON"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Result), Json) && Json.IsValid());
	if (Json.IsValid())
	{
		for (const TCHAR* Field : {TEXT("fps"), TEXT("frame_ms"), TEXT("tier"), TEXT("state")})
		{
			TestTrue(FString::Printf(TEXT("field %s (parity Q-01)"), Field), Json->HasField(Field));
		}
	}
	return true;
}

// settings.game: the catalogue copy, parsing with defaults and refusals, the diff the menu sends,
// and the golden welcome / settings.changed / settings.set frames that carry a game object.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiGameSettingsJsonTest, "Verse.UI.Settings.GameJson", Flags)
bool FVerseUiGameSettingsJsonTest::RunTest(const FString&)
{
	const FVerseGameSettingsCatalogue& Catalogue = FVerseGameSettingsCatalogue::Get();
	if (!TestTrue(TEXT("Data/ui/game_settings.json loads"), Catalogue.GetSettings().Num() > 80))
	{
		return false;
	}
	TestEqual(TEXT("seven tabs, as in the app"), Catalogue.GetTabs().Num(), 7);
	TestEqual(TEXT("nine quality groups"), Catalogue.GetPresetGroups().Num(), 9);
	const FVerseGameSettingDef* Master = Catalogue.Find(TEXT("audio.master"));
	TestTrue(TEXT("audio.master keeps its legacy place view.volume"), Master && Master->Path == TEXT("view.volume"));

	// Every label and option the in-game menu shows is in the strings (the app's verse_settings chunk).
	FVerseUiStrings Strings;
	Strings.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir());
	const TSet<FString> Keys(Strings.GetKeys());
	TestTrue(TEXT("restart note"), Keys.Contains(TEXT("verse_settings.restart")));
	for (const FString& Tab : Catalogue.GetTabs())
	{
		TestTrue(FString::Printf(TEXT("tab %s"), *Tab), Keys.Contains(TEXT("verse_settings.tabs.") + Tab));
	}
	for (const FVerseGameSettingDef& Def : Catalogue.GetSettings())
	{
		if (Def.Kind == EVerseGameSettingKind::Key)
		{
			continue;
		}
		TestTrue(FString::Printf(TEXT("label %s"), *Def.Id), Keys.Contains(TEXT("verse_settings.s.") + Def.Id + TEXT(".label")));
		TestTrue(FString::Printf(TEXT("section %s"), *Def.Section), Keys.Contains(TEXT("verse_settings.sections.") + Def.Section));
		for (const FString& Option : Def.Options)
		{
			if (!FChar::IsDigit(Option[0]))
			{
				TestTrue(FString::Printf(TEXT("option %s of %s"), *Option, *Def.Id), Keys.Contains(TEXT("verse_settings.o.") + Option));
			}
		}
	}

	// Defaults, refusals, legacy ids.
	FVerseGameSettings Game;
	TestEqual(TEXT("default shadows"), Game.GetString(TEXT("graphics.shadows")), FString(TEXT("high")));
	TestEqual(TEXT("default jump key"), Game.GetString(TEXT("keybinds.jump")), FString(TEXT("SpaceBar")));
	TestEqual(TEXT("default duel FOV 100 (bot.md 3.1)"), Game.GetNumber(TEXT("controls.fov_duel")), 100.0);
	TSharedRef<FJsonObject> Bad = MakeShared<FJsonObject>();
	Bad->SetStringField(TEXT("graphics.shadows"), TEXT("ultra"));
	Bad->SetNumberField(TEXT("hud.opacity"), 5.0);
	Bad->SetNumberField(TEXT("hud.hit_markers"), 1.0);
	Bad->SetNumberField(TEXT("nope"), 1.0);
	Bad->SetNumberField(TEXT("audio.master"), 0.2);
	Bad->SetStringField(TEXT("keybinds.fire"), TEXT("Escape"));
	TestEqual(TEXT("unknown ids, bad values and legacy ids are ignored"), Game.ApplyJson(Bad), 0);
	TestEqual(TEXT("shadows stay high"), Game.GetString(TEXT("graphics.shadows")), FString(TEXT("high")));
	TestFalse(TEXT("a legacy id has no settings.game value"), Game.GetValue(TEXT("audio.master")).IsValid());
	TestFalse(TEXT("Escape cannot be bound"), Game.SetString(TEXT("keybinds.fire"), TEXT("Escape")));

	// welcome.settings.game (golden): every catalogue value, flat by id.
	const TArray<TSharedPtr<FJsonValue>> Welcome = Golden(TEXT("welcome"));
	const TSharedPtr<FJsonObject> WelcomeSettings = Welcome.Num() >= 2 ? Welcome[1]->AsObject()->GetObjectField(TEXT("data"))->GetObjectField(TEXT("settings")) : nullptr;
	if (!TestTrue(TEXT("welcome golden fixture carries settings.game"), WelcomeSettings.IsValid() && WelcomeSettings->HasField(TEXT("game"))))
	{
		return false;
	}
	FVerseAppSettings A;
	A.ApplyJson(WelcomeSettings);
	TestEqual(TEXT("welcome shadows medium"), A.Game.GetString(TEXT("graphics.shadows")), FString(TEXT("medium")));
	TestEqual(TEXT("welcome crosshair cyan"), A.Game.GetString(TEXT("hud.crosshair_color")), FString(TEXT("cyan")));
	TestEqual(TEXT("welcome duel FOV 95"), A.Game.GetNumber(TEXT("controls.fov_duel")), 95.0);
	const TSharedPtr<FJsonObject> WelcomeGame = WelcomeSettings->GetObjectField(TEXT("game"));
	TestEqual(TEXT("ToJson carries exactly the ids welcome carries"), A.ToJson()->GetObjectField(TEXT("game"))->Values.Num(), WelcomeGame->Values.Num());

	// The diff the in-game menu sends: only the changed ids, under game.
	FVerseAppSettings B = A;
	B.Game.SetString(TEXT("graphics.shadows"), TEXT("low"));
	B.Game.SetString(TEXT("keybinds.jump"), TEXT("C"));
	const TSharedRef<FJsonObject> Diff = A.Diff(B);
	TestEqual(TEXT("diff has only game"), Diff->Values.Num(), 1);
	const TSharedPtr<FJsonObject> GameDiff = Diff->GetObjectField(TEXT("game"));
	TestEqual(TEXT("two game ids"), GameDiff->Values.Num(), 2);
	for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : GameDiff->Values)
	{
		TestTrue(FString::Printf(TEXT("%s is a welcome.settings.game id"), *Pair.Key), WelcomeGame->HasField(Pair.Key));
	}

	// Golden settings.changed with a game subset applies over welcome and leaves the rest.
	const TSharedPtr<FJsonObject> Changed = FirstWithGame(Golden(TEXT("settings.changed")));
	if (TestNotNull(TEXT("settings.changed golden frame with game"), Changed.Get()))
	{
		FVerseAppSettings C = A;
		C.ApplyJson(Changed);
		TestEqual(TEXT("shadows low"), C.Game.GetString(TEXT("graphics.shadows")), FString(TEXT("low")));
		TestTrue(TEXT("motion blur on"), C.Game.GetBool(TEXT("graphics.motion_blur")));
		TestFalse(TEXT("kill cam off"), C.Game.GetBool(TEXT("gameplay.kill_cam")));
		TestEqual(TEXT("duel FOV 105"), C.Game.GetNumber(TEXT("controls.fov_duel")), 105.0);
		TestEqual(TEXT("jump on C"), C.Game.GetString(TEXT("keybinds.jump")), FString(TEXT("C")));
		TestEqual(TEXT("untouched ids stay"), C.Game.GetString(TEXT("hud.crosshair_color")), FString(TEXT("cyan")));
		TestEqual(TEXT("the diff back is exactly the changed subset"), A.Diff(C)->GetObjectField(TEXT("game"))->Values.Num(), Changed->GetObjectField(TEXT("game"))->Values.Num());
	}

	// Golden settings.set (requests and replies) apply cleanly; the reply carries the stored game.
	const TSharedPtr<FJsonObject> Set = FirstWithGame(Golden(TEXT("settings.set")));
	if (TestNotNull(TEXT("settings.set golden frame with game"), Set.Get()))
	{
		FVerseAppSettings C;
		C.ApplyJson(Set);
		TestEqual(TEXT("preset low"), C.Game.GetString(TEXT("graphics.preset")), FString(TEXT("low")));
		TestEqual(TEXT("foliage low"), C.Game.GetString(TEXT("graphics.foliage")), FString(TEXT("low")));
	}
	for (const TSharedPtr<FJsonValue>& Exchange : GoldenReplies(TEXT("settings.set")))
	{
		const TSharedPtr<FJsonObject> Reply = Exchange->AsObject()->GetObjectField(TEXT("reply"))->GetObjectField(TEXT("data"));
		const TSharedPtr<FJsonObject>* Result = nullptr;
		if (Reply->GetBoolField(TEXT("ok")) && Reply->TryGetObjectField(TEXT("result"), Result))
		{
			const TSharedPtr<FJsonObject> Stored = (*Result)->GetObjectField(TEXT("settings"));
			if (Stored->HasField(TEXT("game")))
			{
				FVerseAppSettings C;
				C.ApplyJson(Stored);
				TestEqual(TEXT("stored crosshair green"), C.Game.GetString(TEXT("hud.crosshair_color")), FString(TEXT("green")));
				TestEqual(TEXT("stored duel FOV 90"), C.Game.GetNumber(TEXT("controls.fov_duel")), 90.0);
			}
		}
	}
	return true;
}

// The menu writes through the app settings: one settings.set per change, a preset sets every
// quality group, one group turns it custom, a key swap travels in one patch, legacy ids keep their place.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiGameSettingsWriteTest, "Verse.UI.Settings.GameWrite", Flags)
bool FVerseUiGameSettingsWriteTest::RunTest(const FString&)
{
	TSharedPtr<FFakeVerseUiBridgePort> Backend = MakeShared<FFakeVerseUiBridgePort>();
	FVerseUiTestWorld W(Backend);
	if (!TestNotNull(TEXT("UI subsystem"), W.Ui))
	{
		return false;
	}
	FUserSettingsGuard Guard(W.Ui->GetUserSettings());
	W.Ui->ApplyWelcome(Backend->MakeWelcome());
	Backend->Frames.Reset();

	TestTrue(TEXT("preset low accepted"), W.Ui->SetGameSetting(TEXT("graphics.preset"), MakeShared<FJsonValueString>(TEXT("low"))));
	TestEqual(TEXT("one settings.set for the preset"), Backend->Count(TEXT("settings.set")), 1);
	const TSharedPtr<FJsonObject> PresetFrame = Backend->Frames.Last().Data;
	TestEqual(TEXT("the frame carries only game"), PresetFrame->Values.Num(), 1);
	TestEqual(TEXT("preset plus nine groups"), PresetFrame->GetObjectField(TEXT("game"))->Values.Num(), 10);
	TestEqual(TEXT("shadows follow the preset"), W.Ui->GetGameString(TEXT("graphics.shadows")), FString(TEXT("low")));

	Backend->Frames.Reset();
	W.Ui->SetGameSetting(TEXT("graphics.shadows"), MakeShared<FJsonValueString>(TEXT("epic")));
	TestEqual(TEXT("one group change"), FFakeVerseUiBridgePort::ToString(Backend->Frames.Last().Data),
		FString(TEXT("{\"game\":{\"graphics.preset\":\"custom\",\"graphics.shadows\":\"epic\"}}")));

	Backend->Frames.Reset();
	TestFalse(TEXT("a value the catalogue refuses"), W.Ui->SetGameSetting(TEXT("graphics.shadows"), MakeShared<FJsonValueString>(TEXT("ultra"))));
	TestFalse(TEXT("an unknown id"), W.Ui->SetGameSetting(TEXT("graphics.nope"), MakeShared<FJsonValueBoolean>(true)));
	TestEqual(TEXT("nothing sent for refusals"), Backend->Frames.Num(), 0);

	// Legacy ids write their old place.
	W.Ui->SetGameSetting(TEXT("controls.view_mode"), MakeShared<FJsonValueString>(TEXT("first")));
	TestEqual(TEXT("controls.view_mode writes view.mode"), FFakeVerseUiBridgePort::ToString(Backend->Frames.Last().Data), FString(TEXT("{\"view\":{\"mode\":\"first\"}}")));
	TestEqual(TEXT("read back through the one API"), W.Ui->GetGameString(TEXT("controls.view_mode")), FString(TEXT("first")));

	// A rebind onto a used key swaps both in one patch (the app store refuses a key bound twice).
	Backend->Frames.Reset();
	W.Ui->RebindKey(TEXT("jump"), EKeys::F);
	TestEqual(TEXT("one settings.set for the swap"), Backend->Count(TEXT("settings.set")), 1);
	const TSharedPtr<FJsonObject> Keys = Backend->Frames.Last().Data->GetObjectField(TEXT("game"));
	TestEqual(TEXT("jump on F"), Keys->GetStringField(TEXT("keybinds.jump")), FString(TEXT("F")));
	TestEqual(TEXT("interact took SpaceBar"), Keys->GetStringField(TEXT("keybinds.interact")), FString(TEXT("SpaceBar")));
	TestEqual(TEXT("two keys in the patch"), Keys->Values.Num(), 2);
	TestEqual(TEXT("the key map follows"), W.Ui->GetKeyMap().GetKey(TEXT("jump")), EKeys::F);

	// Duel FOV, quality, text size and tier are app settings now; the ini only mirrors them.
	W.Ui->SetDuelFov(88.f);
	W.Ui->GetArmoury().SelectTier(TEXT("normal"));
	W.Ui->StartDuelFromArmoury();
	TestEqual(TEXT("duel FOV in settings.game"), W.Ui->GetGameNumber(TEXT("controls.fov_duel")), 88.0);
	TestEqual(TEXT("tier in settings.game"), W.Ui->GetGameString(TEXT("gameplay.bot_tier")), FString(TEXT("normal")));
	UVerseUiUserSettings* Fresh = NewObject<UVerseUiUserSettings>();
	Fresh->ReloadFromDisk();
	TestEqual(TEXT("ini mirrors the duel FOV"), Fresh->DuelFov, 88.f);
	TestEqual(TEXT("ini mirrors the tier"), Fresh->LastTier, FName(TEXT("normal")));
	TestTrue(TEXT("ini caches settings.game"), Fresh->GameSettings.Contains(TEXT("\"graphics.shadows\":\"epic\"")));

	// The app is the truth: a restarted Verse takes welcome over its cache.
	FVerseUiTestWorld Restart;
	Restart.Ui->ApplyWelcome(Backend->MakeWelcome());
	TestEqual(TEXT("shadows after restart"), Restart.Ui->GetGameString(TEXT("graphics.shadows")), FString(TEXT("epic")));
	TestEqual(TEXT("jump after restart"), Restart.Ui->GetKeyMap().GetKey(TEXT("jump")), EKeys::F);
	TestEqual(TEXT("duel FOV after restart"), Restart.Ui->GetGameNumber(TEXT("controls.fov_duel")), 88.0);
	TestEqual(TEXT("armoury tier after restart"), Restart.Ui->GetArmoury().GetSelectedTier(), FName(TEXT("normal")));
	return true;
}

// settings.changed {game} applies live: key map, HUD (crosshair, markers, damage numbers),
// kill cam switch, camera effects, quality plan, audio buses, text size and the console variables.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiGameSettingsApplyTest, "Verse.UI.Settings.GameApply", Flags)
bool FVerseUiGameSettingsApplyTest::RunTest(const FString&)
{
	FVerseUiTestWorld W;
	if (!TestNotNull(TEXT("UI subsystem"), W.Ui))
	{
		return false;
	}
	FUserSettingsGuard Guard(W.Ui->GetUserSettings());
	W.Ui->ApplyWelcome(W.Bridge->MakeWelcome());
	const TSharedPtr<FJsonObject> Changed = FirstWithGame(Golden(TEXT("settings.changed")));
	if (!TestNotNull(TEXT("settings.changed golden frame with game"), Changed.Get()))
	{
		return false;
	}
	W.Bridge->Frames.Reset();
	W.Ui->ApplySettingsChanged(Changed);
	TestEqual(TEXT("an applied settings.changed is not echoed"), W.Bridge->Count(TEXT("settings.set")), 0);

	TestEqual(TEXT("jump on C"), W.Ui->GetKeyMap().GetKey(TEXT("jump")), EKeys::C);
	IConsoleVariable* Fov = IConsoleManager::Get().FindConsoleVariable(TEXT("Verse.Settings.DuelFov"));
	TestTrue(TEXT("duel FOV published"), Fov && FMath::IsNearlyEqual(Fov->GetFloat(), 105.f));
	IConsoleVariable* Generic = IConsoleManager::Get().FindConsoleVariable(TEXT("Verse.Settings.Game.gameplay.kill_cam"));
	TestTrue(TEXT("every id published as Verse.Settings.Game.<id>"), Generic && Generic->GetString() == TEXT("0"));

	const FVerseGraphicsPlan& Plan = W.Ui->GetGraphicsPlan();
	TestEqual(TEXT("shadow group low"), Plan.Quality.ShadowQuality, 0);
	TestEqual(TEXT("TSR"), Plan.AntiAliasingMethod, 4);
	TestTrue(TEXT("motion blur on in the plan"), Plan.bMotionBlur);
	if (APostProcessVolume* Volume = W.Ui->GetSettingsPostProcess())
	{
		TestTrue(TEXT("unbound"), Volume->bUnbound);
		TestFalse(TEXT("motion blur on: the level's own amount"), bool(Volume->Settings.bOverride_MotionBlurAmount));
		TestTrue(TEXT("film grain off: overridden to 0"), Volume->Settings.bOverride_FilmGrainIntensity && Volume->Settings.FilmGrainIntensity == 0.f);
	}
	else
	{
		AddError(TEXT("no settings post-process volume in the game world"));
	}

	if (UVerseAudioSubsystem* Audio = UVerseAudioSubsystem::Get(W.World))
	{
		TestTrue(TEXT("ambience bus at 0.8"), FMath::IsNearlyEqual(Audio->GetUserBusGain(EVerseAudioBus::Ambience), 0.8f));
		TestTrue(TEXT("weapons bus at effects 1.0"), FMath::IsNearlyEqual(Audio->GetUserBusGain(EVerseAudioBus::Weapons), 1.f));
		TSharedRef<FJsonObject> Night = MakeShared<FJsonObject>();
		TSharedRef<FJsonObject> NightGame = MakeShared<FJsonObject>();
		NightGame->SetStringField(TEXT("audio.mix"), TEXT("night"));
		NightGame->SetNumberField(TEXT("audio.effects"), 0.6);
		Night->SetObjectField(TEXT("game"), NightGame);
		W.Ui->ApplySettingsChanged(Night);
		TestTrue(TEXT("night mode: weapons 6 dB under effects"), FMath::IsNearlyEqual(Audio->GetUserBusGain(EVerseAudioBus::Weapons), 0.3f));
		TestTrue(TEXT("foley follows effects"), FMath::IsNearlyEqual(Audio->GetUserBusGain(EVerseAudioBus::Foley), 0.6f));
	}

	// HUD: crosshair style circle (golden), hit markers off, damage numbers on, opacity.
	TSharedRef<FJsonObject> Hud = MakeShared<FJsonObject>();
	TSharedRef<FJsonObject> HudGame = MakeShared<FJsonObject>();
	HudGame->SetBoolField(TEXT("hud.hit_markers"), false);
	HudGame->SetBoolField(TEXT("hud.damage_numbers"), true);
	HudGame->SetStringField(TEXT("hud.performance_stats"), TEXT("full"));
	Hud->SetObjectField(TEXT("game"), HudGame);
	W.Ui->ApplySettingsChanged(Hud);
	W.Game->bDuel = true;
	W.Source->LocalId = 1;
	FVerseHitEvent Hit;
	Hit.InstigatorId = 1;
	Hit.VictimId = 2;
	Hit.Damage = 37.f;
	UVerseEventHub::Get(W.World)->OnHit.Broadcast(Hit);
	FVerseHudDrawList List;
	W.Ui->BuildHudFrame(FVector2D(1920, 1080), List);
	TestTrue(TEXT("crosshair drawn"), List.bCrosshairVisible);
	TestEqual(TEXT("circle: 24 outline + 24 ring segments, outlined dot"), List.CountTag(TEXT("crosshair")), 24 + 24 + 2);
	TestEqual(TEXT("hit markers off"), List.CountTag(TEXT("marker.hit")), 0);
	const FVerseHudDrawList::FLabel* Number = List.FindLabel(TEXT("damage.number"));
	TestTrue(TEXT("damage number 37"), Number && Number->Text.ToString() == TEXT("37"));
	TestNotNull(TEXT("performance stats"), List.FindLabel(TEXT("performance")));

	// Text size and HUD size reach the layout.
	W.Ui->SetTextScale(1.3f);
	TestTrue(TEXT("text size 1.3"), FMath::IsNearlyEqual(W.Ui->ComputeLayout(FVector2D(1920, 1080)).TextScale, 1.3f, 1e-3f));

	// Kill cam off: a local death starts no replay.
	FVerseDeathEvent Death;
	Death.VictimId = 1;
	Death.KillerId = 2;
	UVerseEventHub::Get(W.World)->OnDeath.Broadcast(Death);
	TestFalse(TEXT("kill cam off: no replay"), W.Ui->GetKillCam().IsPlaying());
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
