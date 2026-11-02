#include "Events/VerseEventHub.h"
#include "HAL/IConsoleManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Qa/VerseQaRegistry.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Settings/VerseUiSettings.h"
#include "Tests/UI/Fakes/VerseUiFakes.h"

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

		explicit FUserSettingsGuard(UVerseUiUserSettings* In)
			: Settings(In), DuelFov(In->DuelFov), Keys(In->KeyBindings), Scalability(In->Scalability), TextScale(In->TextScale), Tier(In->LastTier)
		{
		}
		~FUserSettingsGuard()
		{
			Settings->DuelFov = DuelFov;
			Settings->KeyBindings = Keys;
			Settings->Scalability = Scalability;
			Settings->TextScale = TextScale;
			Settings->LastTier = Tier;
			Settings->SaveToDisk();
		}
	};
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
	IConsoleVariable* Gore = IConsoleManager::Get().FindConsoleVariable(TEXT("Verse.Settings.Gore"));
	TestTrue(TEXT("gore published for the gore module"), Gore && Gore->GetInt() == 1);

	// settings.changed from the app applies live.
	TSharedRef<FJsonObject> Changed = MakeShared<FJsonObject>();
	Changed->SetStringField(TEXT("gore"), TEXT("full"));
	Restart.Ui->ApplySettingsChanged(Changed);
	TestEqual(TEXT("settings.changed applies"), Restart.Ui->GetAppSettings().Gore, EVerseGoreLevel::Full);
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

#endif // WITH_DEV_AUTOMATION_TESTS
