#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Internationalization/Regex.h"
#include "Stream/VerseConsoleStreamDriver.h"
#include "Stream/VerseStreamArbiter.h"
#include "Stream/VerseStreamInputPolicy.h"
#include "Stream/VerseStreamKey.h"
#include "Stream/VerseStreamSession.h"
#include "Stream/VerseStreamSubsystem.h"
#include "Fakes/FakeStreamDriver.h"
#include "Fakes/FakeStreamLink.h"
#include "HAL/IConsoleManager.h"

// WP20 tests: Verse.Stream.* (logic with fakes) and Verse.Contract.Stream.* (bridge fixtures).

namespace
{
	constexpr EAutomationTestFlags TestFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	TArray<uint8> Ascii(const char* Text)
	{
		return TArray<uint8>(reinterpret_cast<const uint8*>(Text), FCStringAnsi::Strlen(Text));
	}

	struct FHarness
	{
		TSharedRef<FFakeStreamDriver> Driver = MakeShared<FFakeStreamDriver>();
		TSharedRef<FFakeStreamLink> Link = MakeShared<FFakeStreamLink>();
		FVerseStreamSession Session;
		TArray<bool> PanelStates;

		FHarness()
			: Session(Driver, Link, [] { return FString(TEXT("ws://127.0.0.1:8765/api/verse/signal?role=streamer&key=k")); })
		{
			Session.OnPanelStateChanged = [this](bool bEnter) { PanelStates.Add(bEnter); };
		}
	};

	const FVersePanelGeometry Panel{ 480, 320, 1.5f };

	// The module links Core and Engine only, so the fixtures are read with Core's regex: their
	// `data` objects are flat (no nested braces), which is all these tests need.
	bool LoadFixture(const FString& Relative, FString& OutText)
	{
		return FFileHelper::LoadFileToString(OutText, *FPaths::Combine(FPaths::ProjectDir(), Relative));
	}

	/** Fields of a flat JSON object body (`"w": 480, "visible": true, "state": "x"`), quotes removed. */
	TMap<FString, FString> ParseFields(const FString& Body)
	{
		TMap<FString, FString> Out;
		FRegexMatcher Matcher(FRegexPattern(TEXT("\"(\\w+)\"\\s*:\\s*(\"[^\"]*\"|[^,}\\s]+)")), Body);
		while (Matcher.FindNext())
		{
			Out.Add(Matcher.GetCaptureGroup(1), Matcher.GetCaptureGroup(2).TrimQuotes());
		}
		return Out;
	}

	bool PanelFields(const TMap<FString, FString>& Fields, bool& bOutVisible, FVersePanelGeometry& OutGeometry)
	{
		if (!Fields.Contains(TEXT("w")) || !Fields.Contains(TEXT("h")))
		{
			return false;
		}
		const FString* Visible = Fields.Find(TEXT("visible"));
		bOutVisible = Visible == nullptr || *Visible == TEXT("true");
		OutGeometry.W = FCString::Atoi(*Fields.FindRef(TEXT("w")));
		OutGeometry.H = FCString::Atoi(*Fields.FindRef(TEXT("h")));
		OutGeometry.Dpr = Fields.Contains(TEXT("dpr")) ? FCString::Atof(*Fields.FindRef(TEXT("dpr"))) : 1.0f;
		return true;
	}

	EVersePanelStreamState StateFromName(const FString& Name)
	{
		for (EVersePanelStreamState Candidate : { EVersePanelStreamState::Stopped, EVersePanelStreamState::Starting,
				 EVersePanelStreamState::Streaming, EVersePanelStreamState::Failed })
		{
			if (Name == VerseStream::StateName(Candidate))
			{
				return Candidate;
			}
		}
		return EVersePanelStreamState::Stopped;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseStreamKeyShaTest, "Verse.Stream.Key.Sha256", TestFlags)
bool FVerseStreamKeyShaTest::RunTest(const FString& Parameters)
{
	using namespace VerseStreamKey;
	TestEqual(TEXT("empty"), ToHex(Sha256(TArray<uint8>())), FString(TEXT("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")));
	TestEqual(TEXT("abc"), ToHex(Sha256(Ascii("abc"))), FString(TEXT("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")));
	TestEqual(TEXT("two blocks"), ToHex(Sha256(Ascii("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"))),
		FString(TEXT("248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1")));
	TArray<uint8> Million;
	Million.Init('a', 1000000);
	TestEqual(TEXT("one million a"), ToHex(Sha256(Million)), FString(TEXT("cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseStreamKeyHmacTest, "Verse.Stream.Key.Hmac", TestFlags)
bool FVerseStreamKeyHmacTest::RunTest(const FString& Parameters)
{
	using namespace VerseStreamKey;
	TArray<uint8> Key1;
	Key1.Init(0x0b, 20);
	TestEqual(TEXT("RFC 4231 case 1"), ToHex(HmacSha256(Key1, Ascii("Hi There"))),
		FString(TEXT("b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7")));
	TestEqual(TEXT("RFC 4231 case 2"), ToHex(HmacSha256(Ascii("Jefe"), Ascii("what do ya want for nothing?"))),
		FString(TEXT("5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843")));
	TArray<uint8> Key6;
	Key6.Init(0xaa, 131);
	TestEqual(TEXT("RFC 4231 case 6"), ToHex(HmacSha256(Key6, Ascii("Test Using Larger Than Block-Size Key - Hash Key First"))),
		FString(TEXT("60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractStreamKeyTest, "Verse.Contract.Stream.StreamerKey", TestFlags)
bool FVerseContractStreamKeyTest::RunTest(const FString& Parameters)
{
	// Same values as dodaios/verse_host/signal.py derive_streamer_key.
	TestEqual(TEXT("ascii token"), VerseStreamKey::DeriveStreamerKey(FString::ChrN(64, TEXT('t'))),
		FString(TEXT("ad9a012513c9dd8ada0b0bcdccea36ce0b9501e8022fe1540a1364416c0785e8")));
	FString Utf8Token = TEXT("launch-token-");
	Utf8Token.AppendChar(TCHAR(0xE4));
	TestEqual(TEXT("utf-8 token"), VerseStreamKey::DeriveStreamerKey(Utf8Token),
		FString(TEXT("66d3b2cd8308d6b1158433447ca692652d279655b72859cf4ab8e373bec1295a")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseStreamSignalUrlTest, "Verse.Stream.Key.SignalUrl", TestFlags)
bool FVerseStreamSignalUrlTest::RunTest(const FString& Parameters)
{
	using VerseStreamKey::BuildSignalUrl;
	const FString Token = FString::ChrN(64, TEXT('t'));
	const FString Key = VerseStreamKey::DeriveStreamerKey(Token);
	TestEqual(TEXT("ipv4"), BuildSignalUrl(TEXT("ws://127.0.0.1:8765/api/verse/bridge"), Token),
		TEXT("ws://127.0.0.1:8765/api/verse/signal?role=streamer&key=") + Key);
	TestEqual(TEXT("ipv6"), BuildSignalUrl(TEXT("ws://[::1]:8765/api/verse/bridge"), Token),
		TEXT("ws://[::1]:8765/api/verse/signal?role=streamer&key=") + Key);
	TestTrue(TEXT("token never in the URL"), !BuildSignalUrl(TEXT("ws://127.0.0.1:8765/api/verse/bridge"), Token).Contains(Token));
	TestTrue(TEXT("no token"), BuildSignalUrl(TEXT("ws://127.0.0.1:8765/api/verse/bridge"), FString()).IsEmpty());
	TestTrue(TEXT("not loopback"), BuildSignalUrl(TEXT("ws://192.168.1.5:8765/api/verse/bridge"), Token).IsEmpty());
	TestTrue(TEXT("lookalike host"), BuildSignalUrl(TEXT("ws://127.0.0.1.example.com:80/api/verse/bridge"), Token).IsEmpty());
	TestTrue(TEXT("other loopback address"), !BuildSignalUrl(TEXT("ws://127.0.0.2:80/api/verse/bridge"), Token).IsEmpty());
	TestTrue(TEXT("bad octet"), BuildSignalUrl(TEXT("ws://127.0.0.256:80/api/verse/bridge"), Token).IsEmpty());
	TestTrue(TEXT("wrong path"), BuildSignalUrl(TEXT("ws://127.0.0.1:8765/api/other"), Token).IsEmpty());
	TestTrue(TEXT("wrong scheme"), BuildSignalUrl(TEXT("http://127.0.0.1:8765/api/verse/bridge"), Token).IsEmpty());
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseStreamRenderSizeTest, "Verse.Stream.Arbiter.RenderSize", TestFlags)
bool FVerseStreamRenderSizeTest::RunTest(const FString& Parameters)
{
	TestTrue(TEXT("A20.2 reference size"), (FVersePanelGeometry{ 960, 600, 1.0f }).RenderSize() == FIntPoint(960, 600));
	TestTrue(TEXT("dpr scales"), (FVersePanelGeometry{ 480, 320, 1.5f }).RenderSize() == FIntPoint(720, 480));
	TestTrue(TEXT("even sides"), (FVersePanelGeometry{ 481, 321, 1.0f }).RenderSize() == FIntPoint(480, 320));
	const FIntPoint Capped = (FVersePanelGeometry{ 2000, 1300, 2.0f }).RenderSize();
	TestTrue(TEXT("capped width"), Capped.X <= VerseStream::MaxRenderW);
	TestTrue(TEXT("capped height"), Capped.Y <= VerseStream::MaxRenderH && Capped.Y >= VerseStream::MaxRenderH - 2);
	TestTrue(TEXT("minimum"), (FVersePanelGeometry{ 20, 10, 1.0f }).RenderSize() == FIntPoint(VerseStream::MinRenderW, VerseStream::MinRenderH));
	TestTrue(TEXT("invalid"), (FVersePanelGeometry{ 0, 10, 1.0f }).RenderSize() == FIntPoint::ZeroValue);
	TestFalse(TEXT("dpr bound"), (FVersePanelGeometry{ 100, 100, 9.0f }).IsValid());
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseStreamSessionStartStopTest, "Verse.Stream.Session.StartStop", TestFlags)
bool FVerseStreamSessionStartStopTest::RunTest(const FString& Parameters)
{
	FHarness H;
	H.Session.OnPanelVisibility(true, Panel);
	TestEqual(TEXT("one start"), H.Driver->Starts.Num(), 1);
	TestTrue(TEXT("render size"), H.Driver->Starts[0].RenderSize == FIntPoint(720, 480));
	TestEqual(TEXT("30 fps"), H.Driver->Starts[0].Fps, 30);
	TestEqual(TEXT("8 Mbit/s cap"), H.Driver->Starts[0].MaxBitrateBps, 8'000'000);
	TestEqual(TEXT("hardware H.264"), H.Driver->Starts[0].Codec, FString(TEXT("H264")));
	TestTrue(TEXT("signal URL passed"), H.Driver->Starts[0].SignalUrl.Contains(TEXT("/api/verse/signal")));
	TestEqual(TEXT("reports starting then streaming"), H.Link->Sent.Num(), 2);
	TestTrue(TEXT("starting first"), H.Link->Sent[0].State == EVersePanelStreamState::Starting);
	TestTrue(TEXT("streaming"), H.Link->Last(EVersePanelStreamState::Streaming));
	TestTrue(TEXT("enters Panel"), H.PanelStates == TArray<bool>({ true }));

	H.Session.OnPanelVisibility(true, Panel);
	TestEqual(TEXT("visible twice starts once"), H.Driver->Starts.Num(), 1);

	H.Session.OnPanelVisibility(false, FVersePanelGeometry{ 0, 0, 1.5f });
	TestEqual(TEXT("stopped once"), H.Driver->Stops, 1);
	TestTrue(TEXT("reports stopped"), H.Link->Last(EVersePanelStreamState::Stopped));
	TestTrue(TEXT("A20.1 stop within 1 s"), H.Session.GetLastStopLatencySeconds() < VerseStream::StopDeadlineSeconds);
	TestTrue(TEXT("leaves Panel"), H.PanelStates == TArray<bool>({ true, false }));
	TestFalse(TEXT("driver idle"), H.Driver->IsStreaming());
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseStreamSessionHideWhileStartingTest, "Verse.Stream.Session.HideWhileStarting", TestFlags)
bool FVerseStreamSessionHideWhileStartingTest::RunTest(const FString& Parameters)
{
	FHarness H;
	H.Driver->bAnswerAtOnce = false;
	H.Session.OnPanelVisibility(true, Panel);
	TestTrue(TEXT("starting"), H.Session.GetState() == EVersePanelStreamState::Starting);
	H.Session.OnPanelVisibility(false, FVersePanelGeometry());
	TestTrue(TEXT("stopped at once"), H.Session.GetState() == EVersePanelStreamState::Stopped);
	H.Driver->Complete();
	TestTrue(TEXT("late start is undone"), !H.Driver->IsStreaming());
	TestTrue(TEXT("still reports stopped"), H.Link->Last(EVersePanelStreamState::Stopped));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseStreamSessionFullViewTest, "Verse.Stream.Session.FullViewWins", TestFlags)
bool FVerseStreamSessionFullViewTest::RunTest(const FString& Parameters)
{
	FHarness H;
	H.Session.OnPanelVisibility(true, Panel);
	H.Session.OnFullViewVisible(true);
	TestTrue(TEXT("A20.4 stream stopped while the full view shows"), !H.Driver->IsStreaming());
	TestTrue(TEXT("panel learns why"), H.Link->Last(EVersePanelStreamState::Stopped, VerseStream::ErrorFullViewOpen));
	H.Session.OnPanelResize(FVersePanelGeometry{ 600, 400, 1.0f });
	TestEqual(TEXT("no resize while stopped"), H.Driver->Resizes.Num(), 0);
	H.Session.OnFullViewVisible(false);
	TestEqual(TEXT("restarts after the full view hides"), H.Driver->Starts.Num(), 2);
	TestTrue(TEXT("at the new size"), H.Driver->Starts[1].RenderSize == FIntPoint(600, 400));
	TestTrue(TEXT("streaming again"), H.Link->Last(EVersePanelStreamState::Streaming));

	FHarness Cold;
	Cold.Session.OnFullViewVisible(true);
	Cold.Session.OnPanelVisibility(true, Panel);
	TestEqual(TEXT("never starts under the full view"), Cold.Driver->Starts.Num(), 0);
	TestTrue(TEXT("reports full view"), Cold.Link->Last(EVersePanelStreamState::Stopped, VerseStream::ErrorFullViewOpen));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseStreamSessionFailureTest, "Verse.Stream.Session.Failure", TestFlags)
bool FVerseStreamSessionFailureTest::RunTest(const FString& Parameters)
{
	FHarness H;
	H.Driver->bStartSucceeds = false;
	H.Session.OnPanelVisibility(true, Panel);
	TestTrue(TEXT("failed with the driver's error"), H.Link->Last(EVersePanelStreamState::Failed, TEXT("encoder_unavailable")));
	H.Session.OnPanelResize(FVersePanelGeometry{ 500, 300, 1.0f });
	TestEqual(TEXT("no retry loop on resize"), H.Driver->Starts.Num(), 1);
	H.Session.OnPanelVisibility(false, FVersePanelGeometry());
	H.Driver->bStartSucceeds = true;
	H.Session.OnPanelVisibility(true, Panel);
	TestEqual(TEXT("a new showing retries"), H.Driver->Starts.Num(), 2);
	TestTrue(TEXT("streaming"), H.Link->Last(EVersePanelStreamState::Streaming));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseStreamSessionResizeTest, "Verse.Stream.Session.Resize", TestFlags)
bool FVerseStreamSessionResizeTest::RunTest(const FString& Parameters)
{
	FHarness H;
	H.Session.OnPanelResize(FVersePanelGeometry{ 560, 360, 1.5f });
	TestEqual(TEXT("hidden panel ignores resize"), H.Driver->Resizes.Num(), 0);
	H.Session.OnPanelVisibility(true, Panel);
	H.Session.OnPanelResize(FVersePanelGeometry{ 560, 360, 1.5f });
	H.Session.OnPanelResize(FVersePanelGeometry{ 560, 360, 1.5f });
	H.Session.OnPanelResize(FVersePanelGeometry{ 560, 360, 2.0f });
	TestEqual(TEXT("one resize per change"), H.Driver->Resizes.Num(), 2);
	TestTrue(TEXT("render pixels"), H.Driver->Resizes.Last() == FIntPoint(1120, 720));
	TestEqual(TEXT("no restart on resize"), H.Driver->Starts.Num(), 1);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseStreamInputPolicyTest, "Verse.Stream.Input.Policy", TestFlags)
bool FVerseStreamInputPolicyTest::RunTest(const FString& Parameters)
{
	using namespace VerseStreamInput;
	TestTrue(TEXT("W down"), IsAllowedMessage(TArray<uint8>{ KeyDown, 87, 0 }));
	TestTrue(TEXT("left arrow up"), IsAllowedMessage(TArray<uint8>{ KeyUp, 37 }));
	TestFalse(TEXT("space (jump) blocked"), IsAllowedMessage(TArray<uint8>{ KeyDown, 32, 0 }));
	TestFalse(TEXT("R (reload) blocked"), IsAllowedMessage(TArray<uint8>{ KeyDown, 82, 0 }));
	TestFalse(TEXT("shift (sprint) blocked"), IsAllowedMessage(TArray<uint8>{ KeyDown, 16, 0 }));
	TestFalse(TEXT("F (interact) blocked"), IsAllowedMessage(TArray<uint8>{ KeyDown, 70, 0 }));
	TestFalse(TEXT("escape blocked"), IsAllowedMessage(TArray<uint8>{ KeyDown, 27, 0 }));
	TestTrue(TEXT("mouse move"), IsAllowedMessage(TArray<uint8>{ MouseMove, 0, 128, 0, 128, 1, 0, 255, 255 }));
	TestTrue(TEXT("main button"), IsAllowedMessage(TArray<uint8>{ MouseDown, 0, 0, 1, 0, 1 }));
	TestFalse(TEXT("extra button"), IsAllowedMessage(TArray<uint8>{ MouseDown, 3, 0, 1, 0, 1 }));
	TestTrue(TEXT("wheel"), IsAllowedMessage(TArray<uint8>{ MouseWheel, 120, 0, 0, 1, 0, 1 }));
	TestFalse(TEXT("console command"), IsAllowedMessage(TArray<uint8>{ Command, 0, 0 }));
	TestFalse(TEXT("ui interaction"), IsAllowedMessage(TArray<uint8>{ UIInteraction, 0, 0 }));
	TestFalse(TEXT("text entry"), IsAllowedMessage(TArray<uint8>{ TextboxEntry, 0, 0 }));
	TestFalse(TEXT("stream control from the panel"), IsAllowedMessage(TArray<uint8>{ StopStreaming }));
	TestFalse(TEXT("bitrate request"), IsAllowedMessage(TArray<uint8>{ AverageBitrateRequest }));
	TestFalse(TEXT("gamepad"), IsAllowedMessage(TArray<uint8>{ 90, 0, 0, 0 }));
	TestFalse(TEXT("touch"), IsAllowedMessage(TArray<uint8>{ 80, 1, 0, 0, 0, 0, 0, 0, 0 }));
	TestFalse(TEXT("short message"), IsAllowedMessage(TArray<uint8>{ MouseMove, 0, 0 }));
	TestFalse(TEXT("empty"), IsAllowedMessage(TArray<uint8>()));
	TestTrue(TEXT("key frame request"), IsAllowedMessage(TArray<uint8>{ IFrameRequest }));
	TestFalse(TEXT("no duel in the panel"), AllowsDuelEntryInPanel);

	const FString Filter = BuildKeyFilter();
	TArray<FString> Names;
	Filter.ParseIntoArray(Names, TEXT(","));
	TestTrue(TEXT("filter drops space"), Names.Contains(TEXT("SpaceBar")));
	TestTrue(TEXT("filter drops R"), Names.Contains(TEXT("R")));
	TestTrue(TEXT("filter drops escape"), Names.Contains(TEXT("Escape")));
	TestFalse(TEXT("filter keeps W"), Names.Contains(TEXT("W")));
	TestFalse(TEXT("filter keeps the arrows"), Names.Contains(TEXT("Left")) || Names.Contains(TEXT("Up")));
	TestFalse(TEXT("filter leaves the mouse"), Names.Contains(TEXT("LeftMouseButton")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseStreamDriverSettingsTest, "Verse.Stream.Driver.Settings", TestFlags)
bool FVerseStreamDriverSettingsTest::RunTest(const FString& Parameters)
{
	FVerseStreamConfig Config;
	Config.SignalUrl = TEXT("ws://127.0.0.1:1/api/verse/signal?role=streamer&key=k");
	TMap<FString, FString> Map;
	for (const TPair<FString, FString>& Pair : FVerseConsoleStreamDriver::SettingsFor(Config))
	{
		Map.Add(Pair.Key, Pair.Value);
	}
	TestEqual(TEXT("url"), Map.FindRef(TEXT("PixelStreaming2.ConnectionURL")), Config.SignalUrl);
	TestEqual(TEXT("fps"), Map.FindRef(TEXT("PixelStreaming2.WebRTC.Fps")), FString(TEXT("30")));
	TestEqual(TEXT("bitrate cap"), Map.FindRef(TEXT("PixelStreaming2.WebRTC.MaxBitrate")), FString(TEXT("8000000")));
	TestEqual(TEXT("codec"), Map.FindRef(TEXT("PixelStreaming2.Encoder.Codec")), FString(TEXT("H264")));
	TestEqual(TEXT("no STUN, no relay"), Map.FindRef(TEXT("PixelStreaming2.WebRTC.PortAllocatorFlags")), FString(TEXT("DISABLE_STUN,DISABLE_RELAY")));
	TestEqual(TEXT("no console commands from the panel"), Map.FindRef(TEXT("PixelStreaming2.AllowPixelStreamingCommands")), FString(TEXT("false")));
	TestFalse(TEXT("key filter set"), Map.FindRef(TEXT("PixelStreaming2.KeyFilter")).IsEmpty());

	// The plugin is enabled in Verse.uproject: its console surface must be what the driver drives.
	FVerseConsoleStreamDriver Driver;
	if (!Driver.IsAvailable())
	{
		AddWarning(TEXT("PixelStreaming2 console surface not present in this process (plugin unsupported here)"));
	}
	else
	{
		for (const TPair<FString, FString>& Pair : FVerseConsoleStreamDriver::SettingsFor(Config))
		{
			TestNotNull(*FString::Printf(TEXT("console variable %s exists"), *Pair.Key), IConsoleManager::Get().FindConsoleVariable(*Pair.Key));
		}
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractStreamStateTest, "Verse.Contract.Stream.StateMessages", TestFlags)
bool FVerseContractStreamStateTest::RunTest(const FString& Parameters)
{
	FString Text;
	if (!TestTrue(TEXT("golden panel.stream_state loads"), LoadFixture(TEXT("Tests/Data/bridge/messages/panel.stream_state.json"), Text)))
	{
		return false;
	}
	int32 Frames = 0;
	FRegexMatcher Data(FRegexPattern(TEXT("\"data\"\\s*:\\s*\\{([^}]*)\\}")), Text);
	while (Data.FindNext())
	{
		++Frames;
		const TMap<FString, FString> Fields = ParseFields(Data.GetCaptureGroup(1));
		const FString State = Fields.FindRef(TEXT("state"));
		const FString Error = Fields.FindRef(TEXT("error"));
		const FString Expected = Error.IsEmpty() ? FString::Printf(TEXT("{\"state\":\"%s\"}"), *State)
												 : FString::Printf(TEXT("{\"state\":\"%s\",\"error\":\"%s\"}"), *State, *Error);
		TestEqual(*FString::Printf(TEXT("%s round trip"), *State), VerseStream::StreamStateJson(StateFromName(State), Error), Expected);
		TestEqual(TEXT("only state and error"), Fields.Num(), Error.IsEmpty() ? 1 : 2);
	}
	TestTrue(TEXT("fixture has frames"), Frames >= 2);
	TestEqual(TEXT("error codes are sanitised"), VerseStream::SanitizeErrorCode(TEXT("Bad \"code\"\n<x>")), FString(TEXT("badcodex")));

	for (const TCHAR* Name : { TEXT("panel.visibility"), TEXT("panel.resize") })
	{
		FString Messages;
		if (!TestTrue(*FString::Printf(TEXT("%s fixture loads"), Name), LoadFixture(FString::Printf(TEXT("Tests/Data/bridge/messages/%s.json"), Name), Messages)))
		{
			continue;
		}
		FRegexMatcher Body(FRegexPattern(TEXT("\"data\"\\s*:\\s*\\{([^}]*)\\}")), Messages);
		int32 Count = 0;
		while (Body.FindNext())
		{
			++Count;
			bool bVisible = false;
			FVersePanelGeometry Geometry;
			TestTrue(*FString::Printf(TEXT("%s parses"), Name), PanelFields(ParseFields(Body.GetCaptureGroup(1)), bVisible, Geometry));
			TestTrue(*FString::Printf(TEXT("%s visible frames carry a valid size"), Name), !bVisible || Geometry.IsValid());
		}
		TestTrue(*FString::Printf(TEXT("%s has frames"), Name), Count > 0);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractStreamPanelScenarioTest, "Verse.Contract.Stream.PanelScenario", TestFlags)
bool FVerseContractStreamPanelScenarioTest::RunTest(const FString& Parameters)
{
	// Plays the fake bridge's `panel` scenario (G0.11) into the session and checks its expects.
	FString Text;
	if (!TestTrue(TEXT("scenario loads"), LoadFixture(TEXT("Tests/Data/bridge/scenarios/panel.json"), Text)))
	{
		return false;
	}
	FHarness H;
	int32 Frames = 0;
	int32 Expects = 0;
	FRegexMatcher Steps(FRegexPattern(TEXT("\"(frame|expect)\"\\s*:\\s*\\{\"type\"\\s*:\\s*\"([a-z._]+)\"\\s*,\\s*\"data\"\\s*:\\s*\\{([^}]*)\\}\\}(\\s*,\\s*\"timeout_ms\"\\s*:\\s*(\\d+))?")), Text);
	while (Steps.FindNext())
	{
		const FString Kind = Steps.GetCaptureGroup(1);
		const FString Type = Steps.GetCaptureGroup(2);
		const TMap<FString, FString> Fields = ParseFields(Steps.GetCaptureGroup(3));
		if (Kind == TEXT("frame"))
		{
			++Frames;
			bool bVisible = true;
			FVersePanelGeometry Geometry;
			TestTrue(TEXT("frame parses"), PanelFields(Fields, bVisible, Geometry));
			if (Type == TEXT("panel.visibility"))
			{
				H.Session.OnPanelVisibility(bVisible, Geometry);
			}
			else if (Type == TEXT("panel.resize"))
			{
				H.Session.OnPanelResize(Geometry);
			}
			continue;
		}
		++Expects;
		const FString Want = Fields.FindRef(TEXT("state"));
		TestEqual(TEXT("expected stream state"), FString(VerseStream::StateName(H.Session.GetState())), Want);
		const FString Timeout = Steps.GetCaptureGroup(5);
		if (Want == TEXT("stopped") && !Timeout.IsEmpty())
		{
			TestTrue(TEXT("stopped inside the scenario's deadline"), H.Session.GetLastStopLatencySeconds() * 1000.0 < FCString::Atod(*Timeout));
		}
	}
	TestEqual(TEXT("all frames played"), Frames, 4);
	TestEqual(TEXT("both expects ran"), Expects, 2);
	TestEqual(TEXT("one resize per distinct size"), H.Driver->Resizes.Num(), 2);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseStreamPanelCameraTest, "Verse.Stream.PanelCamera.Find", TestFlags)
bool FVerseStreamPanelCameraTest::RunTest(const FString& Parameters)
{
	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false);
	if (!TestNotNull(TEXT("world"), World))
	{
		return false;
	}
	FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
	Context.SetCurrentWorld(World);
	TestNull(TEXT("no camera in an empty deck"), UVerseStreamSubsystem::FindPanelCamera(World));
	AActor* Plain = World->SpawnActor<AActor>();
	AActor* Camera = World->SpawnActor<AActor>();
	Camera->Tags.Add(UVerseStreamSubsystem::PanelCameraTag);
	TestTrue(TEXT("finds the tagged actor"), UVerseStreamSubsystem::FindPanelCamera(World) == Camera);
	TestTrue(TEXT("not the plain one"), Plain != Camera);
	TestNull(TEXT("null world"), UVerseStreamSubsystem::FindPanelCamera(nullptr));
	World->DestroyWorld(false);
	GEngine->DestroyWorldContext(World);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
