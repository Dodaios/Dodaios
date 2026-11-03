#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Core/VerseUiStrings.h"
#include "EnhancedActionKeyMapping.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Character.h"
#include "InputAction.h"
#include "InputMappingContext.h"
#include "InputModifiers.h"
#include "Internationalization/Culture.h"
#include "Internationalization/Internationalization.h"
#include "Misc/AutomationTest.h"
#include "Misc/ScopeExit.h"
#include "Scalability.h"
#include "Settings/VerseUiInputRemap.h"
#include "Tests/UI/Fakes/VerseUiFakes.h"

#if WITH_DEV_AUTOMATION_TESTS

// The UI's seams to the packages around it: key bindings into Enhanced Input (WP01), the kill
// cam proxy on a real character, pause, leave and reset (parity D-09, D-10, T-01), scalability
// at start, numbers in the Verse language, the kill cam under a lagged connection.

namespace VerseUiSeamsTest
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	UInputAction* MakeAction(UObject* Outer, const TCHAR* Name)
	{
		UInputAction* Action = NewObject<UInputAction>(Outer, Name);
		Action->ValueType = EInputActionValueType::Boolean;
		return Action;
	}

	FVerseSetSummary MakeSet(int32 Index, EVerseSetOutcome Outcome, int32 Kills, int32 Deaths)
	{
		FVerseSetSummary Set;
		Set.SetIndex = Index;
		Set.Outcome = Outcome;
		Set.BotTier = TEXT("hard");
		Set.Person.PlayerId = 1;
		Set.Person.Kills = Kills;
		Set.Person.Deaths = Deaths;
		Set.Person.Headshots = 2;
		Set.Person.BestStreak = Kills;
		Set.Opponent.PlayerId = 2;
		Set.Opponent.bIsBot = true;
		Set.Opponent.Kills = Deaths;
		Set.Opponent.Deaths = Kills;
		return Set;
	}
}

using namespace VerseUiSeamsTest;

// A rebind changes the key the input owner's mapping context actually uses (WP18.8).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiInputRemapTest, "Verse.UI.Settings.InputRemap", Flags)
bool FVerseUiInputRemapTest::RunTest(const FString&)
{
	// The layout of WP01's IMC_VersePerson (VerseInputFrameBuilder.cpp): actions by name, a
	// keyboard and a gamepad key for jump, modifiers on the move keys.
	UInputMappingContext* Context = NewObject<UInputMappingContext>(GetTransientPackage(), TEXT("IMC_VerseUiRemapTest"));
	UInputAction* Move = MakeAction(Context, TEXT("IA_Move"));
	UInputAction* Jump = MakeAction(Context, TEXT("IA_Jump"));
	UInputAction* Crouch = MakeAction(Context, TEXT("IA_Crouch"));
	Context->MapKey(Move, EKeys::W);
	FEnhancedActionKeyMapping& Back = Context->MapKey(Move, EKeys::S);
	Back.Modifiers.Add(NewObject<UInputModifierNegate>(Context));
	Context->MapKey(Jump, EKeys::SpaceBar);
	Context->MapKey(Jump, EKeys::Gamepad_FaceButton_Bottom);
	Context->MapKey(Crouch, EKeys::LeftControl);
	Context->MapKey(Crouch, EKeys::C);

	FVerseKeyMap KeyMap;
	FString Error;
	if (!TestTrue(TEXT("keys.json loads"), KeyMap.LoadFile(FVerseKeyMap::DefaultPath(), &Error)))
	{
		AddError(Error);
		return false;
	}
	const FVerseKeyMap::FAction* JumpAction = KeyMap.FindAction(TEXT("jump"));
	TestTrue(TEXT("jump names WP01's IA_Jump"), JumpAction && JumpAction->InputAction == FName(TEXT("IA_Jump")));

	FVerseUiInputRemap Remap;
	TestFalse(TEXT("default keys change nothing"), Remap.Apply(Context, KeyMap));
	TestEqual(TEXT("bound mappings: move forward, move back, jump, crouch"), Remap.NumBound(Context), 4);

	KeyMap.Rebind(TEXT("jump"), EKeys::F);
	KeyMap.Rebind(TEXT("move_back"), EKeys::Down);
	TestTrue(TEXT("rebinds apply"), Remap.Apply(Context, KeyMap));
	const TArray<FEnhancedActionKeyMapping>& M = Context->GetMappings();
	TestEqual(TEXT("IA_Jump now on F"), M[2].Key, EKeys::F);
	TestEqual(TEXT("the gamepad jump stays"), M[3].Key, EKeys::Gamepad_FaceButton_Bottom);
	TestEqual(TEXT("move back now on Down"), M[1].Key, EKeys::Down);
	TestEqual(TEXT("the move-back mapping keeps its negate modifier"), M[1].Modifiers.Num(), 1);
	TestEqual(TEXT("the second crouch key stays"), M[5].Key, EKeys::C);

	// Interact took F before: the swap gives it jump's old key; the mapping follows a second rebind.
	KeyMap.Rebind(TEXT("jump"), EKeys::SpaceBar);
	TestTrue(TEXT("rebinding back applies"), Remap.Apply(Context, KeyMap));
	TestEqual(TEXT("IA_Jump back on space"), Context->GetMappings()[2].Key, EKeys::SpaceBar);

	// Fire defaults to a mouse button; a rebind can return to it.
	KeyMap.Rebind(TEXT("fire"), EKeys::K);
	KeyMap.Rebind(TEXT("fire"), EKeys::LeftMouseButton);
	TestEqual(TEXT("fire can be bound back to the left mouse button"), KeyMap.GetKey(TEXT("fire")), EKeys::LeftMouseButton);
	return true;
}

// The kill cam proxy stands where the character's mesh stands (mesh offset kept).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiKillCamProxyTest, "Verse.UI.KillCam.Proxy", Flags)
bool FVerseUiKillCamProxyTest::RunTest(const FString&)
{
	FVerseUiTestWorld W;
	if (!TestNotNull(TEXT("UI subsystem"), W.Ui))
	{
		return false;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	ACharacter* Killer = W.World->SpawnActor<ACharacter>(FVector(300.0, -120.0, 92.0), FRotator(0.0, 35.0, 0.0), Params);
	if (!TestNotNull(TEXT("character"), Killer))
	{
		return false;
	}
	// AVerseCharacter's mesh offset (WP01): -half height in Z, -90 deg yaw.
	const float HalfHeight = Killer->GetCapsuleComponent()->GetUnscaledCapsuleHalfHeight();
	Killer->GetMesh()->SetRelativeLocationAndRotation(FVector(0.0, 0.0, -HalfHeight), FRotator(0.0, -90.0, 0.0));
	Killer->CacheInitialMeshOffset(Killer->GetMesh()->GetRelativeLocation(), Killer->GetMesh()->GetRelativeRotation());
	// A network smoothing offset on the live mesh must not be copied.
	Killer->GetMesh()->SetRelativeLocation(FVector(0.0, 0.0, -HalfHeight + 7.0));

	AActor* Proxy = W.Ui->SpawnKillCamProxy(W.World, Params, Killer, Killer->GetMesh());
	if (!TestNotNull(TEXT("proxy"), Proxy))
	{
		return false;
	}
	USkeletalMeshComponent* Copy = Proxy->FindComponentByClass<USkeletalMeshComponent>();
	if (!TestNotNull(TEXT("proxy mesh"), Copy))
	{
		return false;
	}
	TestTrue(TEXT("proxy root is not the mesh"), Proxy->GetRootComponent() != Copy);
	const FTransform Expected = FTransform(Killer->GetBaseRotationOffset(), Killer->GetBaseTranslationOffset()) * Killer->GetActorTransform();
	AddInfo(FString::Printf(TEXT("proxy mesh %s, character mesh base %s"), *Copy->GetComponentLocation().ToString(), *Expected.GetLocation().ToString()));
	TestTrue(TEXT("feet on the floor: proxy mesh within 1 cm of the character's mesh base"), FVector::Dist(Copy->GetComponentLocation(), Expected.GetLocation()) < 1.0);
	TestTrue(TEXT("facing: proxy mesh yaw equals the character's mesh yaw"),
		FMath::Abs(FRotator::NormalizeAxis(Copy->GetComponentRotation().Yaw - Expected.Rotator().Yaw)) < 0.5);
	Proxy->Destroy();
	Killer->Destroy();
	return true;
}

// Escape mid-match pauses, the end-of-set screen pauses, leaving shows the summary (D-09, D-10).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiPauseLeaveTest, "Verse.UI.Menus.PauseLeave", Flags)
bool FVerseUiPauseLeaveTest::RunTest(const FString&)
{
	FVerseUiTestWorld W;
	if (!TestNotNull(TEXT("UI subsystem"), W.Ui))
	{
		return false;
	}
	W.Ui->ApplyWelcome(W.Bridge->MakeWelcome());
	W.Ui->QuickStartDuel();
	TestTrue(TEXT("duel running"), W.Game->bDuel);
	TestTrue(TEXT("Esc opens the menu"), W.Ui->HandleKey(EKeys::Escape));
	TestEqual(TEXT("Esc menu"), W.Ui->GetScreen(), EVerseUiScreen::EscMenu);
	TestTrue(TEXT("Escape mid-match pauses"), W.Game->bIsPaused);
	W.Ui->ShowScreen(EVerseUiScreen::Settings);
	TestTrue(TEXT("still paused in settings"), W.Game->bIsPaused);
	W.Ui->HandleKey(EKeys::Escape);
	W.Ui->HandleKey(EKeys::Escape);
	TestEqual(TEXT("closed"), W.Ui->GetScreen(), EVerseUiScreen::None);
	TestFalse(TEXT("resume releases the pause"), W.Game->bIsPaused);

	UVerseEventHub* Hub = UVerseEventHub::Get(W.World);
	if (!TestNotNull(TEXT("hub"), Hub))
	{
		return false;
	}
	Hub->OnSetEnded.Broadcast(MakeSet(1, EVerseSetOutcome::Won, 10, 4));
	TestEqual(TEXT("end-of-set screen"), W.Ui->GetScreen(), EVerseUiScreen::EndOfSet);
	TestTrue(TEXT("the end-of-set screen holds the match"), W.Game->bIsPaused);
	W.Ui->ContinueAfterSet();
	TestFalse(TEXT("next set resumes"), W.Game->bIsPaused);
	Hub->OnSetEnded.Broadcast(MakeSet(2, EVerseSetOutcome::Lost, 6, 10));
	W.Ui->ContinueAfterSet();

	// Leave mid-set: notice, summary over both sets, "again" starts a new session.
	W.Ui->HandleKey(EKeys::Escape);
	W.Ui->LeaveDuel();
	TestEqual(TEXT("leave shows the session summary"), W.Ui->GetScreen(), EVerseUiScreen::SessionSummary);
	TestTrue(TEXT("left mid-set (verse.duel.notice.left)"), W.Ui->GetSession().bLeftMidSet);
	TestFalse(TEXT("leaving releases the pause"), W.Game->bIsPaused);
	TestEqual(TEXT("one leave"), W.Game->Left, 1);
	TestEqual(TEXT("sets won"), W.Ui->GetSession().SetsWon, 1);
	TestEqual(TEXT("sets lost"), W.Ui->GetSession().SetsLost, 1);
	TestEqual(TEXT("session kills summed"), W.Ui->GetSession().Totals.Person.Kills, 16);
	TestEqual(TEXT("best streak is the best set"), W.Ui->GetSession().Totals.Person.BestStreak, 10);
	TestEqual(TEXT("summary title"), W.Ui->GetSessionScreen().TitleKey, FString(TEXT("verse.duel.result.cancelled")));
	TestTrue(TEXT("summary has rows"), W.Ui->GetSessionScreen().Rows.Num() > 0);
	TestEqual(TEXT("app string for the notice"), W.Ui->GetStrings().Get(TEXT("verse.duel.notice.left")).ToString(), FString(TEXT("You left the duel.")));
	W.Ui->QuickStartDuel();
	TestEqual(TEXT("again starts a duel"), W.Game->Started.Num(), 2);
	TestEqual(TEXT("again starts a new session"), W.Ui->GetSession().NumSets(), 0);

	// Leaving from the end-of-set screen is not mid-set.
	Hub->OnSetEnded.Broadcast(MakeSet(1, EVerseSetOutcome::Won, 10, 2));
	W.Ui->LeaveDuel();
	TestFalse(TEXT("leave from the end-of-set screen is not mid-set"), W.Ui->GetSession().bLeftMidSet);
	return true;
}

// parity T-01: reset restores sensitivity 1, invert off, quality auto, FOV 70/85, volume 0.7, view third.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiResetTest, "Verse.UI.Settings.Reset", Flags)
bool FVerseUiResetTest::RunTest(const FString&)
{
	FVerseUiTestWorld W;
	if (!TestNotNull(TEXT("UI subsystem"), W.Ui))
	{
		return false;
	}
	UVerseUiUserSettings* User = W.Ui->GetUserSettings();
	const int32 ScalabilityBefore = User->Scalability;
	ON_SCOPE_EXIT { User->Scalability = ScalabilityBefore; User->SaveToDisk(); };
	const EVerseGoreLevel GoreBefore = UVerseUiSubsystem::ReadGoreSetting();
	ON_SCOPE_EXIT { UVerseUiSubsystem::WriteGoreSetting(nullptr, GoreBefore); };
	W.Ui->ApplyWelcome(W.Bridge->MakeWelcome());
	FVerseAppSettings Changed = W.Ui->GetAppSettings();
	Changed.Sensitivity = 2.3f;
	Changed.bInvertY = true;
	Changed.Quality = TEXT("low");
	Changed.FovThird = 90.f;
	Changed.FovFirst = 100.f;
	Changed.Volume = 0.2f;
	Changed.ViewMode = TEXT("first");
	Changed.Gore = EVerseGoreLevel::Reduced;
	W.Ui->SetAppSettings(Changed);
	W.Ui->SetScalability(1);
	W.Bridge->Frames.Reset();

	W.Ui->ResetSettings();
	const FVerseAppSettings& S = W.Ui->GetAppSettings();
	TestEqual(TEXT("sensitivity 1"), S.Sensitivity, 1.f);
	TestFalse(TEXT("invert off"), S.bInvertY);
	TestEqual(TEXT("quality auto"), S.Quality, FString(TEXT("auto")));
	TestEqual(TEXT("FOV third 70"), S.FovThird, 70.f);
	TestEqual(TEXT("FOV first 85"), S.FovFirst, 85.f);
	TestTrue(TEXT("volume 0.7"), FMath::IsNearlyEqual(S.Volume, 0.7f));
	TestEqual(TEXT("view third"), S.ViewMode, FString(TEXT("third")));
	TestEqual(TEXT("Unreal quality auto"), User->Scalability, -1);
	TestEqual(TEXT("gore is not a view setting: unchanged"), S.Gore, EVerseGoreLevel::Reduced);
	TestEqual(TEXT("one settings.set for the reset"), W.Bridge->Count(TEXT("settings.set")), 1);
	return true;
}

// The saved quality level applies (at start and from the menu); auto maps to the engine defaults.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiScalabilityTest, "Verse.UI.Settings.Scalability", Flags)
bool FVerseUiScalabilityTest::RunTest(const FString&)
{
	const Scalability::FQualityLevels Before = Scalability::GetQualityLevels();
	ON_SCOPE_EXIT { Scalability::SetQualityLevels(Before); };
	UVerseUiSubsystem::ApplyScalabilityLevel(1);
	TestEqual(TEXT("level 1 applied"), Scalability::GetQualityLevels().GetSingleQualityLevel(), 1);
	UVerseUiSubsystem::ApplyScalabilityLevel(-1);
	const Scalability::FQualityLevels Defaults;
	TestTrue(TEXT("auto applies the engine's default levels"), Scalability::GetQualityLevels() == Defaults);
	return true;
}

// Numbers follow the Verse language, not the machine's culture.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiNumberCultureTest, "Verse.UI.Strings.NumberCulture", Flags)
bool FVerseUiNumberCultureTest::RunTest(const FString&)
{
	FInternationalization& I18n = FInternationalization::Get();
	const FString Before = I18n.GetCurrentCulture()->GetName();
	ON_SCOPE_EXIT { I18n.SetCurrentCulture(Before); };
	if (!I18n.GetCulture(TEXT("de")).IsValid())
	{
		AddWarning(TEXT("no German culture data in this build; culture switch not tested"));
		return true;
	}
	I18n.SetCurrentCulture(TEXT("de"));

	FVerseUiStrings Strings;
	Strings.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir());
	Strings.SetLanguage(TEXT("en"));
	TestEqual(TEXT("adaptive s in English on a German machine"), Strings.Number(0.62, 2).ToString(), FString(TEXT("0.62")));
	TestEqual(TEXT("percent in English"), Strings.Percent(0.45).ToString(), FString(TEXT("45%")));
	TestEqual(TEXT("sensitivity in English"), Strings.Number(1.4, 1).ToString(), FString(TEXT("1.4")));
	Strings.SetLanguage(TEXT("de"));
	TestEqual(TEXT("adaptive s in German"), Strings.Number(0.62, 2).ToString(), FString(TEXT("0,62")));

	return true;
}

// A18.2 under a lagged link: the client's server clock and the replicated poses lag by the same
// one-way trip (AGameStateBase), updates come at 30 Hz and are extrapolated in between.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiKillCamLaggedTest, "Verse.UI.KillCam.Lagged", Flags)
bool FVerseUiKillCamLaggedTest::RunTest(const FString&)
{
	FVerseUiTestWorld W;
	UVerseEventHub* Hub = W.World ? UVerseEventHub::Get(W.World) : nullptr;
	if (!TestNotNull(TEXT("UI subsystem"), W.Ui) || !TestNotNull(TEXT("hub"), Hub))
	{
		return false;
	}
	auto Path = [](double T)
	{
		const double A = 650.0 * T / 600.0;
		return FVector(600.0 * FMath::Cos(A), 600.0 * FMath::Sin(A), 90.0);
	};
	auto Velocity = [](double T)
	{
		const double A = 650.0 * T / 600.0;
		return FVector(-650.0 * FMath::Sin(A), 650.0 * FMath::Cos(A), 0.0);
	};
	const double OneWay = 0.030;   // PktLag 60: 30 ms each way
	const double UpdateDt = 1.0 / 30.0;
	const int32 Person = 1;
	const int32 Killer = 2;
	W.Source->LocalId = Person;
	FRandomStream Rng(11);

	// True server time T; the client's server clock reads T - OneWay (plus a little jitter).
	double T = 40.0;
	const double DeathAt = 46.0;
	auto Feed = [&](double TrueTime)
	{
		const double Clock = TrueTime - OneWay + Rng.FRandRange(-0.004, 0.004);
		const double LastUpdate = FMath::FloorToDouble((TrueTime - OneWay) / UpdateDt) * UpdateDt;
		const FVector Shown = Path(LastUpdate) + Velocity(LastUpdate) * (Clock - LastUpdate);
		W.Source->ServerTime = Clock;
		W.Source->Poses = {{Killer, Shown, FRotator::ZeroRotator}};
	};
	while (T < DeathAt + OneWay)
	{
		Feed(T);
		if (FMath::Fmod(T, 0.5) < 0.02)
		{
			FVerseFireEvent Fire;
			Fire.ShooterId = Killer;
			Fire.Origin = Path(T - OneWay);
			Fire.Direction = FVector(1.0, 0.0, 0.0);
			Fire.ServerTime = T - OneWay;
			Hub->OnFire.Broadcast(Fire);
		}
		W.Ui->Tick(0.016f);
		const double Step = Rng.FRandRange(0.012, 0.030);
		T += Step;
		W.Now += Step;
	}
	FVerseDeathEvent Death;
	Death.KillerId = Killer;
	Death.VictimId = Person;
	Death.ServerTime = DeathAt;
	Death.RespawnAt = DeathAt + 3.0;
	Hub->OnDeath.Broadcast(Death);

	const FVerseKillCamPlayer& Cam = W.Ui->GetKillCam();
	TestTrue(TEXT("kill cam playing"), Cam.IsPlaying());
	double WorstCm = 0.0;
	int32 Samples = 0;
	bool bSawBolt = false;
	while (Cam.IsPlaying() && Samples < 1000)
	{
		const double Step = Rng.FRandRange(0.012, 0.030);
		T += Step;
		W.Now += Step;
		Feed(T);
		W.Ui->Tick(float(Step));
		bSawBolt |= W.Ui->GetReplayBolts().Num() > 0;
		FVector Pose;
		FRotator Aim;
		if (Cam.GetKillerPose(Pose, Aim))
		{
			// The server log at the replayed server time.
			WorstCm = FMath::Max(WorstCm, FVector::Distance(Pose, Path(Cam.GetReplayTime())));
			++Samples;
		}
	}
	AddInfo(FString::Printf(TEXT("one-way %.0f ms, 30 Hz updates: worst replay error %.2f cm over %d frames"), OneWay * 1000.0, WorstCm, Samples));
	TestTrue(TEXT("frames sampled"), Samples > 50);
	TestTrue(TEXT("killer path within 10 cm of the server log at 60 ms round trip"), WorstCm <= 10.0);
	TestTrue(TEXT("replayed fire events draw bolts"), bSawBolt);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
