#include "Bridge/VerseBridgeClient.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformProcess.h"
#include "Lifecycle/VerseLifecycle.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"

#if WITH_DEV_AUTOMATION_TESTS

namespace
{
	/** Runs scripts/unreal/fake_bridge.py (G0.11) with a dev discovery file; the test plays Verse. */
	struct FFakeBridge
	{
		FProcHandle Proc;
		FString Discovery;
		FString Report;
		FString Token;

		bool Start(const FString& Scenario, const FString& Extra = FString())
		{
			const FString Repo = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectDir(), TEXT(".."), TEXT("..")));
			const FString Dir = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Automation"), TEXT("Bridge")));
			IFileManager::Get().MakeDirectory(*Dir, true);
			const FString Id = FGuid::NewGuid().ToString(EGuidFormats::Digits);
			Discovery = FPaths::Combine(Dir, Id + TEXT(".json"));
			Report = FPaths::Combine(Dir, Id + TEXT(".report.json"));
			Token = Id + Id.Left(11);
			const FString Python = FPlatformMisc::GetEnvironmentVariable(TEXT("DODAIOS_PYTHON")).IsEmpty()
				? FString(PLATFORM_WINDOWS ? TEXT("python") : TEXT("python3"))
				: FPlatformMisc::GetEnvironmentVariable(TEXT("DODAIOS_PYTHON"));
			const FString Args = FString::Printf(TEXT("\"%s\" --scenario %s --speed 0 --once --token %s --discovery \"%s\" --report \"%s\" %s"),
				*FPaths::Combine(Repo, TEXT("scripts"), TEXT("unreal"), TEXT("fake_bridge.py")), *Scenario, *Token, *Discovery, *Report, *Extra);
			Proc = FPlatformProcess::CreateProc(*Python, *Args, false, true, true, nullptr, 0, *Repo, nullptr);
			const double Deadline = FPlatformTime::Seconds() + 20.0;
			while (FPlatformTime::Seconds() < Deadline && Proc.IsValid() && FPlatformProcess::IsProcRunning(Proc))
			{
				if (IFileManager::Get().FileExists(*Discovery))
				{
					return true;
				}
				FPlatformProcess::Sleep(0.05f);
			}
			return false;
		}

		void Stop()
		{
			if (Proc.IsValid())
			{
				const double Deadline = FPlatformTime::Seconds() + 5.0;
				while (FPlatformProcess::IsProcRunning(Proc) && FPlatformTime::Seconds() < Deadline)
				{
					FPlatformProcess::Sleep(0.05f);
				}
				if (FPlatformProcess::IsProcRunning(Proc))
				{
					FPlatformProcess::TerminateProc(Proc, false);
				}
				FPlatformProcess::CloseProc(Proc);
			}
		}
	};

	template <typename F>
	bool PumpUntil(FVerseBridgeClient& Client, double Seconds, F&& Done)
	{
		const double Deadline = FPlatformTime::Seconds() + Seconds;
		while (FPlatformTime::Seconds() < Deadline)
		{
			Client.Tick(FPlatformTime::Seconds());
			if (Done())
			{
				return true;
			}
			FPlatformProcess::Sleep(0.01f);
		}
		return false;
	}
}

// 17.11 against the G0.11 fake bridge: hello, welcome, subscribe, snapshots and deltas with
// base checks, a command with exactly one reply, ping and pong.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBridgeClientFakeBridgeTest, "Verse.Bridge.Client.FakeBridge",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseBridgeClientFakeBridgeTest::RunTest(const FString& Parameters)
{
	FFakeBridge Fake;
	if (!Fake.Start(TEXT("roster_churn")))
	{
		AddWarning(TEXT("fake_bridge.py did not start (python missing?); skipped"));
		Fake.Stop();
		return true;
	}
	FVerseBridgeClient::FDiscovery Discovery;
	FVerseBridgeClient::Discover(Discovery, Fake.Discovery);
	TestEqual(TEXT("token from the discovery file"), Discovery.Token, Fake.Token);
	FVerseBridgeClient Client;
	Client.Subscribe({TEXT("roster")});
	int32 RosterChanges = 0;
	Client.Roster.OnChanged.AddLambda([&RosterChanges]() { ++RosterChanges; });
	Client.Start(Discovery);
	TestTrue(TEXT("linked"), PumpUntil(Client, 10.0, [&] { return Client.IsLinked(); }));
	TestTrue(TEXT("welcome carries the protocol"), Client.GetWelcome().IsValid() && VerseBridgeJson::Str(Client.GetWelcome(), TEXT("protocol")) == VerseBridge::Protocol);
	TestTrue(TEXT("roster snapshot and deltas"), PumpUntil(Client, 10.0, [&] { return Client.Roster.HasSnapshot() && RosterChanges >= 3; }));
	int32 Replies = 0;
	bool bOk = false;
	TSharedPtr<FJsonObject> Action = MakeShared<FJsonObject>();
	Action->SetStringField(TEXT("action"), TEXT("inspection"));
	Action->SetStringField(TEXT("ref"), TEXT("hangar"));
	Client.SendCommand(TEXT("progression.action"), Action, [&](bool bReplyOk, const TSharedPtr<FJsonObject>&, const FString&) { ++Replies; bOk = bReplyOk; });
	TestTrue(TEXT("one reply"), PumpUntil(Client, 5.0, [&] { return Replies > 0; }));
	PumpUntil(Client, 1.5, [] { return false; });
	TestEqual(TEXT("exactly one reply"), Replies, 1);
	TestTrue(TEXT("still linked after pings"), Client.IsLinked());
	AddInfo(FString::Printf(TEXT("agents %d, panes %d, last seq %lld"), Client.Roster.GetAgents().Num(), Client.Roster.GetPanes().Num(), Client.GetLastSeq()));
	Client.Stop();
	Fake.Stop();
	FString Report;
	if (FFileHelper::LoadFileToString(Report, *Fake.Report))
	{
		AddInfo(Report.Left(400));
	}
	return true;
}

// Reconnect backoff of contract section 1: 250 ms, 1 s, 2 s, 4 s, then every 5 s.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBridgeBackoffTest, "Verse.Bridge.Client.Backoff",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseBridgeBackoffTest::RunTest(const FString& Parameters)
{
	TestEqual(TEXT("1"), FVerseBridgeClient::BackoffFor(1), 0.25);
	TestEqual(TEXT("2"), FVerseBridgeClient::BackoffFor(2), 1.0);
	TestEqual(TEXT("3"), FVerseBridgeClient::BackoffFor(3), 2.0);
	TestEqual(TEXT("4"), FVerseBridgeClient::BackoffFor(4), 4.0);
	TestEqual(TEXT("5"), FVerseBridgeClient::BackoffFor(5), 5.0);
	TestEqual(TEXT("9"), FVerseBridgeClient::BackoffFor(9), 5.0);
	TestEqual(TEXT("dead link"), FVerseBridgeClient::DeadLink, 5.0);
	TestEqual(TEXT("ping"), FVerseBridgeClient::PingInterval, 1.0);
	return true;
}

namespace
{
	struct FFakeHost : IVerseLifecycleHost
	{
		TArray<FString> Calls;
		double Clock = 100.0;
		bool bVisible = false;
		bool bRendering = true;
		float MaxFps = 0.f;
		bool bExit = false;
		virtual void ShowWindow(const FVerseMonitor& M, const FString& Token) override { Calls.Add(TEXT("show")); bVisible = true; }
		virtual void HideWindow() override { Calls.Add(TEXT("hide")); bVisible = false; }
		virtual void SetRendering(bool bOn) override { bRendering = bOn; }
		virtual void SetMaxFps(float Fps) override { MaxFps = Fps; }
		virtual void SetMuted(bool) override {}
		virtual void SetPaused(bool) override {}
		virtual void SetLowScalability(bool bLow) override { Calls.Add(bLow ? TEXT("low") : TEXT("normal")); }
		virtual void AllowForeground(int32 Pid) override { Calls.Add(FString::Printf(TEXT("allow:%d"), Pid)); }
		virtual bool SaveState() override { Calls.Add(TEXT("save")); return true; }
		virtual void RequestExit() override { bExit = true; }
		virtual double Now() const override { return Clock; }
	};

	FVerseBridgeFrame Server(const TCHAR* Type, const TCHAR* Json = TEXT("{}"))
	{
		FVerseBridgeFrame F;
		F.Type = Type;
		F.Seq = 2;
		F.Data = VerseBridgeJson::Read(Json);
		return F;
	}
}

// 17.12: the lifecycle state machine against a fake engine host.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseLifecycleStatesTest, "Verse.Bridge.Lifecycle.States",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseLifecycleStatesTest::RunTest(const FString& Parameters)
{
	FFakeHost Host;
	FVerseBridgeClient Client;
	FVerseLifecycleController L(Host, Client);
	TestTrue(TEXT("boots"), L.GetState() == EVerseLifecycleState::Booting);
	int32 Duels = 0;
	L.OnQuickStartDuel.AddLambda([&Duels]() { ++Duels; });
	L.HandleFrame(Server(TEXT("lifecycle.show"), TEXT("{\"monitor\":{\"x\":0,\"y\":0,\"w\":2560,\"h\":1440,\"dpi\":144},\"reason\":\"quick_start_duel\"}")));
	TestTrue(TEXT("visible"), L.GetState() == EVerseLifecycleState::Visible);
	TestEqual(TEXT("quick start"), Duels, 1);
	L.HandleFrame(Server(TEXT("gpu.yield"), TEXT("{\"by\":\"local_model\"}")));
	TestTrue(TEXT("visible drops to low"), Host.Calls.Contains(TEXT("low")));
	L.HandleFrame(Server(TEXT("gpu.free"), TEXT("{\"by\":\"local_model\"}")));
	TestTrue(TEXT("back to normal"), Host.Calls.Contains(TEXT("normal")));
	L.HandleFrame(Server(TEXT("settings.changed"), TEXT("{\"return_key\":\"F9\"}")));
	TestEqual(TEXT("return key rebinds live"), L.GetReturnKey(), FString(TEXT("F9")));
	L.ReturnToApp();
	TestTrue(TEXT("return key -> dormant"), L.GetState() == EVerseLifecycleState::Dormant);
	TestTrue(TEXT("foreground allowed before hiding"), Host.Calls.IndexOfByKey(TEXT("allow:0")) < Host.Calls.FindLast(TEXT("hide")));
	TestFalse(TEXT("dormant renders nothing"), Host.bRendering);
	TestEqual(TEXT("dormant ticks at 2 Hz"), Host.MaxFps, 2.f);
	L.HandleFrame(Server(TEXT("panel.visibility"), TEXT("{\"visible\":true,\"w\":480,\"h\":320,\"dpr\":1.5}")));
	TestTrue(TEXT("panel"), L.GetState() == EVerseLifecycleState::Panel);
	L.HandleFrame(Server(TEXT("lifecycle.show"), TEXT("{\"monitor\":{\"x\":0,\"y\":0,\"w\":1920,\"h\":1080,\"dpi\":96},\"reason\":\"verse_view\"}")));
	TestTrue(TEXT("panel -> visible"), L.GetState() == EVerseLifecycleState::Visible);
	L.HandleFrame(Server(TEXT("focus.app_took")));
	TestTrue(TEXT("app took focus while the panel streams"), L.GetState() == EVerseLifecycleState::Panel);
	L.HandleFrame(Server(TEXT("panel.visibility"), TEXT("{\"visible\":false,\"w\":0,\"h\":0,\"dpr\":1}")));
	TestTrue(TEXT("panel hidden -> dormant"), L.GetState() == EVerseLifecycleState::Dormant);
	TestTrue(TEXT("show measured"), L.GetLastShowSeconds() >= 0.0);
	L.HandleFrame(Server(TEXT("gpu.yield"), TEXT("{\"by\":\"blender_cook\"}")));
	TestTrue(TEXT("dormant quits at once on gpu.yield"), L.GetState() == EVerseLifecycleState::Exiting);
	TestTrue(TEXT("state saved"), Host.Calls.Contains(TEXT("save")));
	TestTrue(TEXT("exit requested"), Host.bExit);
	L.HandleFrame(Server(TEXT("lifecycle.show"), TEXT("{\"monitor\":{\"x\":0,\"y\":0,\"w\":1,\"h\":1,\"dpi\":96},\"reason\":\"verse_view\"}")));
	TestTrue(TEXT("exiting is final"), L.GetState() == EVerseLifecycleState::Exiting);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
