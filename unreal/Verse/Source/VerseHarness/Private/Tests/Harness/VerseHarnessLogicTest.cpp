#include "Balance/VerseBoutRecorder.h"
#include "Balance/VerseHarnessScenario.h"
#include "Balance/VerseModelController.h"
#include "Balance/VersePersonModels.h"
#include "Balance/VerseTrickOverrides.h"
#include "Capture/VerseCaptureDirector.h"
#include "Misc/AutomationTest.h"
#include "VerseHarnessJson.h"

#if WITH_DEV_AUTOMATION_TESTS

namespace VerseHarnessTestPrivate
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	FVersePerceptFrame Sighting(float DistanceM)
	{
		FVersePerceptFrame Frame;
		Frame.Self.EyeLocation = FVector::ZeroVector;
		Frame.Self.Magazine = 20;
		Frame.Self.bChambered = true;
		Frame.Self.Reserve = 60;
		FVerseSightPercept Sight;
		Sight.PelvisLocation = FVector(DistanceM * 100.0, 0.0, 0.0);
		Sight.VisibleMask = 0xFF;
		Frame.Sightings.Add(Sight);
		return Frame;
	}

	FVerseTrickConfig Trick(EVerseTrick Id)
	{
		FVerseTrickConfig Config;
		Config.Trick = Id;
		return Config;
	}

	bool Held(const FVerseInputFrame& Frame, EVerseInputButton Button) { return Frame.IsHeld(Button); }

	const TCHAR* ScenarioJson = TEXT(R"({
		"schema": "verse.scenario/1", "run": "r1", "job": 2, "map": "/Game/Verse/Decks/Hangar/LV_Hangar",
		"output": "C:/tmp/out", "maxWallS": 100, "trace": {"bearing": true, "fireAudit": true},
		"units": [{"pairing": "skilled+spray_vs_hard", "set": "elite", "match": 1, "seed": 4000000000, "bouts": 3,
			"a": {"kind": "model", "model": "skilled", "trick": "spray"}, "b": {"kind": "bot", "tier": "hard", "learning": false},
			"killsToWin": 15, "matchTimeLimitS": 600, "tierPatch": {"hard": {"ReactionMeanMs": 300}}}]
	})");
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHarnessScenarioParseTest, "Verse.Harness.Scenario.Parse", VerseHarnessTestPrivate::Flags)
bool FVerseHarnessScenarioParseTest::RunTest(const FString& Parameters)
{
	FVerseHarnessScenario S;
	FString Error;
	TestTrue(TEXT("valid scenario parses"), FVerseHarnessScenario::Parse(VerseHarnessTestPrivate::ScenarioJson, S, Error));
	TestEqual(TEXT("error"), Error, FString());
	TestEqual(TEXT("job"), S.Job, 2);
	TestTrue(TEXT("bearing trace"), S.bTraceBearing);
	if (!TestEqual(TEXT("units"), S.Units.Num(), 1))
	{
		return false;
	}
	const FVerseHarnessUnit& U = S.Units[0];
	TestEqual(TEXT("seed keeps 32 bits"), U.Seed, 4000000000u);
	TestEqual(TEXT("bouts"), U.Bouts, 3);
	TestEqual(TEXT("label A"), U.A.Label(), FString(TEXT("skilled+spray")));
	TestEqual(TEXT("label B"), U.B.Label(), FString(TEXT("hard-nolearn")));
	TestTrue(TEXT("patch carried"), U.TierPatchJson.Contains(TEXT("ReactionMeanMs")));

	FVerseHarnessScenario Bad;
	TestFalse(TEXT("wrong schema fails"), FVerseHarnessScenario::Parse(TEXT(R"({"schema":"x/1"})"), Bad, Error));
	TestFalse(TEXT("bot without tier fails"), FVerseHarnessScenario::Parse(TEXT(R"({"schema":"verse.scenario/1","run":"r",
		"map":"/Game/M","output":"o","units":[{"pairing":"p","match":0,"seed":1,"bouts":1,"a":{"kind":"bot"},
		"b":{"kind":"model","model":"skilled"}}]})"), Bad, Error));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHarnessPersonModelsTest, "Verse.Harness.PersonModels.Load", VerseHarnessTestPrivate::Flags)
bool FVerseHarnessPersonModelsTest::RunTest(const FString& Parameters)
{
	FVersePersonModelSet Set;
	FString Error;
	if (!TestTrue(TEXT("person_models.json loads: ") + Error, FVersePersonModelSet::LoadDefault(Set, Error)))
	{
		return false;
	}
	TestEqual(TEXT("17 tricks (bot.md 11.2)"), Set.Tricks.Num(), VerseTrickCount);
	const FVersePersonModel* Skilled = Set.Models.Find(TEXT("skilled"));
	const FVersePersonModel* Average = Set.Models.Find(TEXT("average"));
	if (TestNotNull(TEXT("skilled"), Skilled) && TestNotNull(TEXT("average"), Average))
	{
		TestEqual(TEXT("skilled reaction 225"), Skilled->ReactionMeanMs, 225.f);
		TestEqual(TEXT("skilled turn rate 1000"), Skilled->TurnRateDegS, 1000.f);
		TestEqual(TEXT("skilled recoil comp 0.8"), Skilled->RecoilPatternComp, 0.8f);
		TestEqual(TEXT("skilled head aim 0.3"), Skilled->HeadAimChance, 0.3f);
		TestEqual(TEXT("average reaction 270"), Average->ReactionMeanMs, 270.f);
		TestEqual(TEXT("average recoil comp 0.5"), Average->RecoilPatternComp, 0.5f);
	}
	for (int32 Index = 1; Index <= VerseTrickCount; ++Index)
	{
		const FName Name = VerseTrickName(EVerseTrick(Index));
		EVerseTrick Back = EVerseTrick::None;
		TestTrue(FString::Printf(TEXT("trick %s round-trips"), *Name.ToString()), VerseTrickFromName(Name, Back) && Back == EVerseTrick(Index));
		TestTrue(FString::Printf(TEXT("trick %s in the file"), *Name.ToString()), Set.Tricks.Contains(Name));
	}
	const FVerseTrickConfig* Wallspam = Set.Tricks.Find(TEXT("wallspam"));
	if (TestNotNull(TEXT("wallspam"), Wallspam))
	{
		TestTrue(TEXT("wallspam turns its own authority off"), Wallspam->Intent.bWallShotAuthorityOff);
	}
	EVerseTrick Unknown;
	TestFalse(TEXT("unknown id"), VerseTrickFromName(TEXT("teleport"), Unknown));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHarnessTricksTest, "Verse.Harness.Tricks.Overrides", VerseHarnessTestPrivate::Flags)
bool FVerseHarnessTricksTest::RunTest(const FString& Parameters)
{
	using namespace VerseHarnessTestPrivate;
	using B = EVerseInputButton;
	FVerseRng Rng(7);
	const FVerseInputFrame Empty;

	{
		FVerseTrickState State;
		const FVerseInputFrame Out = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Spray), Sighting(10), Empty, State, Rng, 0.0);
		TestTrue(TEXT("spray holds fire on sight"), Held(Out, B::Fire));
		TestTrue(TEXT("fire went down this tick"), Out.WasPressed(B::Fire));
		FVersePerceptFrame Dry = Sighting(10);
		Dry.Self.Magazine = 0;
		Dry.Self.bChambered = false;
		const FVerseInputFrame Again = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Spray), Dry, Empty, State, Rng, 0.1);
		TestTrue(TEXT("spray reloads on empty"), Held(Again, B::Reload));
		TestFalse(TEXT("held fire is not pressed again"), Again.WasPressed(B::Fire));
		FVerseInputFrame Brain;
		Brain.Buttons = uint32(B::Reload);
		const FVerseInputFrame NoTactical = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Spray), Sighting(10), Brain, State, Rng, 0.2);
		TestFalse(TEXT("spray never reloads a loaded magazine"), Held(NoTactical, B::Reload));
	}
	{
		FVerseTrickState State;
		FVerseInputFrame Brain;
		Brain.Buttons = uint32(B::Sprint) | uint32(B::Jump);
		const FVerseInputFrame Out = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Silent), FVersePerceptFrame(), Brain, State, Rng, 0.0);
		TestTrue(TEXT("silent crouches"), Held(Out, B::Crouch));
		TestFalse(TEXT("silent never sprints"), Held(Out, B::Sprint));
		TestFalse(TEXT("silent never jumps"), Held(Out, B::Jump));
	}
	{
		FVerseTrickState State;
		FVerseInputFrame Brain;
		Brain.Buttons = uint32(B::LeanLeft);
		const FVerseInputFrame Out = FVerseTrickOverrides::Apply(Trick(EVerseTrick::JumpPeek), Sighting(8), Brain, State, Rng, 0.0);
		TestTrue(TEXT("jumppeek jumps instead of leaning"), Held(Out, B::Jump) && !Held(Out, B::LeanLeft));
	}
	{
		FVerseTrickState State;
		int32 Flips = 0;
		bool bLast = false;
		for (int32 Tick = 0; Tick < 600; ++Tick)
		{
			const FVerseInputFrame Out = FVerseTrickOverrides::Apply(Trick(EVerseTrick::LeanSpam), Sighting(15), Empty, State, Rng, Tick / 60.0);
			const bool bRight = Held(Out, B::LeanRight);
			TestTrue(TEXT("exactly one lean"), bRight != Held(Out, B::LeanLeft));
			Flips += (Tick > 0 && bRight != bLast) ? 1 : 0;
			bLast = bRight;
		}
		// 10 s with a flip every 150-300 ms: between 33 and 67 flips.
		TestTrue(FString::Printf(TEXT("leanspam flips %d times in 10 s"), Flips), Flips >= 32 && Flips <= 68);
	}
	{
		FVerseTrickState State;
		const FVerseInputFrame Far = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Prone), Sighting(30), Empty, State, Rng, 0.0);
		const FVerseInputFrame Near = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Prone), Sighting(8), Empty, State, Rng, 0.1);
		TestTrue(TEXT("prone at long range"), Held(Far, B::Prone));
		TestFalse(TEXT("not prone up close"), Held(Near, B::Prone));
	}
	{
		FVerseTrickState State;
		FVerseInputFrame Brain;
		Brain.Buttons = uint32(B::Fire);
		const FVerseInputFrame Far = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Knife), Sighting(10), Brain, State, Rng, 0.0);
		const FVerseInputFrame Close = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Knife), Sighting(1.5f), Brain, State, Rng, 0.1);
		TestFalse(TEXT("knife never fires"), Held(Far, B::Fire) || Held(Close, B::Fire));
		TestFalse(TEXT("no strike out of reach"), Held(Far, B::Melee));
		TestTrue(TEXT("strike in reach"), Held(Close, B::Melee));
	}
	{
		FVerseTrickState State;
		FVerseInputFrame Brain;
		Brain.Move = FVector2f(1.f, 0.f);
		const FVerseInputFrame Out = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Kiter), Sighting(12), Brain, State, Rng, 0.0);
		TestEqual(TEXT("kiter backs off inside 30 m"), Out.Move.X, -1.f);
		const FVerseInputFrame Hider = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Hider), Sighting(12), Brain, State, Rng, 0.1);
		TestFalse(TEXT("hider does not shoot unhurt"), Held(Hider, B::Fire));
		TestEqual(TEXT("hider runs away"), Hider.Move.X, -1.f);
	}
	{
		FVerseTrickState State;
		const FVerseInputFrame Out = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Rusher), FVersePerceptFrame(), Empty, State, Rng, 0.0);
		TestTrue(TEXT("rusher sprints forward unseen"), Held(Out, B::Sprint) && Out.Move.X == 1.f);
		FVerseInputFrame Brain;
		Brain.Buttons = uint32(B::Sprint);
		Brain.Move = FVector2f(1.f, 0.f);
		FVerseTrickState SlideState;
		const FVerseInputFrame First = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Slider), FVersePerceptFrame(), Brain, SlideState, Rng, 0.0);
		const FVerseInputFrame Soon = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Slider), FVersePerceptFrame(), Brain, SlideState, Rng, 0.5);
		const FVerseInputFrame Later = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Slider), FVersePerceptFrame(), Brain, SlideState, Rng, 2.0);
		TestTrue(TEXT("slider slides on approach"), Held(First, B::Crouch));
		TestFalse(TEXT("slide cooldown"), Held(Soon, B::Crouch));
		TestTrue(TEXT("slides again after the cooldown"), Held(Later, B::Crouch));
	}
	{
		FVerseTrickState State;
		FVersePerceptFrame Ready;
		Ready.Self.GadgetCharges[0] = 1;
		const FVerseInputFrame Out = FVerseTrickOverrides::Apply(Trick(EVerseTrick::Turtle), Ready, Empty, State, Rng, 0.0);
		TestTrue(TEXT("turtle deploys the Bulwark when ready"), Held(Out, B::GadgetA));
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHarnessModelLimitsTest, "Verse.Harness.Model.Limits", VerseHarnessTestPrivate::Flags)
bool FVerseHarnessModelLimitsTest::RunTest(const FString& Parameters)
{
	FVersePersonModel Model;
	Model.TurnRateDegS = 600.f;
	FVerseInputFrame Brain;
	Brain.Buttons = uint32(EVerseInputButton::Fire) | uint32(EVerseInputButton::Ads);
	Brain.LookDeltaDeg = FVector2f(-50.f, 50.f);
	const FVerseInputFrame Reacting = AVerseModelController::ApplyPersonLimits(Model, Brain, true, 1.f / 60.f);
	TestFalse(TEXT("no fire before the reaction time"), Reacting.IsHeld(EVerseInputButton::Fire));
	TestEqual(TEXT("no look before the reaction time"), Reacting.LookDeltaDeg.Y, 0.f);
	const FVerseInputFrame Acting = AVerseModelController::ApplyPersonLimits(Model, Brain, false, 1.f / 60.f);
	TestTrue(TEXT("fires after reacting"), Acting.IsHeld(EVerseInputButton::Fire));
	TestEqual(TEXT("turn clamped to 10 deg per tick"), Acting.LookDeltaDeg.Y, 10.f);
	TestEqual(TEXT("both axes clamped"), Acting.LookDeltaDeg.X, -10.f);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHarnessBoutRecorderTest, "Verse.Harness.Bout.Recorder", VerseHarnessTestPrivate::Flags)
bool FVerseHarnessBoutRecorderTest::RunTest(const FString& Parameters)
{
	FVerseBoutRecorder R(10, 20, 2, 600.0);
	R.OnRespawn(10, 0.0);
	R.OnRespawn(20, 0.0);
	FVerseFireEvent Fire;
	Fire.ShooterId = 10;
	R.OnFire(Fire, 4.0);
	FVerseHitEvent Hit;
	Hit.InstigatorId = 10;
	Hit.VictimId = 20;
	Hit.DistanceM = 22.f;
	Hit.bHeadshot = 1;
	Hit.PenetrationCount = 1;
	R.OnHit(Hit, 4.0);
	FVerseDeathEvent Death;
	Death.KillerId = 10;
	Death.VictimId = 20;
	R.OnDeath(Death, 5.0);
	R.OnRespawn(20, 8.0);
	TestFalse(TEXT("one kill of two is not over"), R.IsOver(8.0));
	FVerseReloadEvent Reload;
	Reload.PlayerId = 10;
	R.OnReload(Reload, 6.0);
	R.OnDeath(Death, 9.0);
	TestTrue(TEXT("over at KillsToWin"), R.IsOver(9.0));
	TestTrue(TEXT("A wins"), R.Winner() == EVerseSide::A);
	TestEqual(TEXT("kills"), R.Kills().Num(), 2);
	const FVerseBoutKill& First = R.Kills()[0];
	TestTrue(TEXT("headshot wall kill classified"), First.bHeadshot && First.bWall);
	TestEqual(TEXT("range from the killing hit"), First.RangeM, 22.f);
	TestEqual(TEXT("ttk from first hit"), First.TtkS, 1.f);
	TestFalse(TEXT("5 s into a life is no spawn kill"), First.bSpawnKill);
	TestTrue(TEXT("1 s after respawn is a spawn kill"), R.Kills()[1].bSpawnKill);
	TestEqual(TEXT("contact time A"), R.Side(EVerseSide::A).TimeToContactS[0], 4.f);
	TestEqual(TEXT("shots"), R.Side(EVerseSide::A).Shots, 1);
	TestEqual(TEXT("reload in fight"), R.Side(EVerseSide::A).ReloadsInFight, 1);
	TestEqual(TEXT("deaths B"), R.Side(EVerseSide::B).Deaths, 2);

	FVerseBoutRecorder Idle(1, 2, 15, 600.0);
	Idle.SamplePosition(EVerseSide::A, FVector::ZeroVector, true, 0.0);
	Idle.SamplePosition(EVerseSide::A, FVector(10, 0, 0), true, 16.0);
	TestEqual(TEXT("stuck after 15 s without 50 cm"), Idle.Side(EVerseSide::A).StuckEvents, 1);
	TestTrue(TEXT("time limit ends a bout"), Idle.IsOver(600.0));
	TestTrue(TEXT("no kills is a draw"), Idle.Winner() == EVerseSide::None);

	const FString Line = R.ToJsonLine(TEXT("hard_vs_normal"), 0, 3, 99, 1, 9.0, 120.0, {0.5f, 0.52f});
	TestTrue(TEXT("schema"), Line.Contains(TEXT("\"schema\":\"verse.bout/1\"")));
	TestTrue(TEXT("winner"), Line.Contains(TEXT("\"winner\":\"A\"")));
	TestTrue(TEXT("spawn side"), Line.Contains(TEXT("\"spawnSideA\":1")));
	TestFalse(TEXT("one line"), Line.Contains(TEXT("\n")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHarnessCaptureScriptTest, "Verse.Harness.Capture.Script", VerseHarnessTestPrivate::Flags)
bool FVerseHarnessCaptureScriptTest::RunTest(const FString& Parameters)
{
	FVerseCaptureScript S;
	FString Error;
	const bool bOk = FVerseCaptureScript::Parse(TEXT(R"({"schema":"verse.capture/1","id":"p","warmupS":2,
		"flythrough":{"durationS":10,"keys":[{"t":10,"location":[100,0,0],"rotation":[0,90,0],"fovDeg":60},
		{"t":0,"location":[0,0,0],"rotation":[0,0,0],"fovDeg":90}]},"shots":[{"id":"mid","atS":5}]})"), S, Error);
	if (!TestTrue(TEXT("parses: ") + Error, bOk))
	{
		return false;
	}
	TestEqual(TEXT("keys sorted"), S.Keys[0].T, 0.0);
	const FVerseCaptureView Mid = S.Sample(5.0);
	TestEqual(TEXT("halfway location"), Mid.Location.X, 50.0);
	TestEqual(TEXT("halfway yaw"), Mid.Rotation.Yaw, 45.0);
	TestEqual(TEXT("clamped after the end"), S.Sample(99.0).Location.X, 100.0);
	TestEqual(TEXT("shot"), S.Shots[0].Id, FString(TEXT("mid")));
	FVerseCaptureScript Bad;
	TestFalse(TEXT("needs views or keys"), FVerseCaptureScript::Parse(TEXT(R"({"schema":"verse.capture/1"})"), Bad, Error));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHarnessJsonTest, "Verse.Harness.Json.RoundTrip", VerseHarnessTestPrivate::Flags)
bool FVerseHarnessJsonTest::RunTest(const FString& Parameters)
{
	FString Error;
	const TSharedPtr<FVerseJson> Doc = FVerseJson::Parse(TEXT("{\"a\": [1, 2.5, -3e2], \"s\": \"x\\\"y\\n\", \"b\": true, \"n\": null, \"o\": {}}"), Error);
	if (!TestTrue(TEXT("parses: ") + Error, Doc.IsValid()))
	{
		return false;
	}
	const TArray<TSharedPtr<FVerseJson>>* A = Doc->ArrayField(TEXT("a"));
	TestTrue(TEXT("array"), A && A->Num() == 3 && (*A)[2]->Number == -300.0);
	TestEqual(TEXT("escapes"), Doc->StringOr(TEXT("s")), FString(TEXT("x\"y\n")));
	bool B = false;
	TestTrue(TEXT("bool"), Doc->TryBool(TEXT("b"), B) && B);
	TestEqual(TEXT("compact round trip"), Doc->ToString(), FString(TEXT("{\"a\":[1,2.5,-300],\"s\":\"x\\\"y\\n\",\"b\":true,\"n\":null,\"o\":{}}")));
	TestFalse(TEXT("trailing garbage fails"), FVerseJson::Parse(TEXT("{} x"), Error).IsValid());
	TestFalse(TEXT("unterminated fails"), FVerseJson::Parse(TEXT("{\"a\": [1, 2"), Error).IsValid());
	FVerseJsonWriter W;
	W.Str(TEXT("k"), TEXT("v")).Num(TEXT("n"), 0.25).Null(TEXT("z"));
	TestEqual(TEXT("writer"), W.Close(), FString(TEXT("{\"k\":\"v\",\"n\":0.25,\"z\":null}")));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
