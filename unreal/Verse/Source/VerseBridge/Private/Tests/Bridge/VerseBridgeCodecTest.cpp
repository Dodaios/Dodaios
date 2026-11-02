#include "Bridge/VerseBridgeCodec.h"
#include "Bridge/VerseBridgeFeeds.h"
#include "Bridge/VerseCellsCodec.h"
#include "Bridge/VerseWsClient.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

#if WITH_DEV_AUTOMATION_TESTS

namespace
{
	FString BridgeDataDir()
	{
		return FPaths::Combine(FPaths::ProjectDir(), TEXT("Tests"), TEXT("Data"), TEXT("bridge"));
	}

	TArray<TSharedPtr<FJsonValue>> ReadArray(const FString& Path)
	{
		FString Text;
		TArray<TSharedPtr<FJsonValue>> Out;
		if (FFileHelper::LoadFileToString(Text, *Path))
		{
			TSharedRef<TJsonReader<TCHAR>> Reader = TJsonReaderFactory<TCHAR>::Create(Text);
			FJsonSerializer::Deserialize(Reader, Out);
		}
		return Out;
	}

	TArray<uint8> FromHex(const FString& Hex)
	{
		TArray<uint8> Out;
		for (int32 I = 0; I + 1 < Hex.Len(); I += 2)
		{
			Out.Add(uint8(FParse::HexDigit(Hex[I]) * 16 + FParse::HexDigit(Hex[I + 1])));
		}
		return Out;
	}

	FString ToHex(const TArray<uint8>& Bytes)
	{
		FString Out;
		for (uint8 B : Bytes)
		{
			Out += FString::Printf(TEXT("%02x"), B);
		}
		return Out;
	}
}

// A17.1 (C++ half): every golden message parses, re-encodes and parses back to the same frame.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBridgeGoldenMessagesTest, "Verse.Bridge.Codec.GoldenMessages",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseBridgeGoldenMessagesTest::RunTest(const FString& Parameters)
{
	TArray<FString> Files;
	IFileManager::Get().FindFiles(Files, *FPaths::Combine(BridgeDataDir(), TEXT("messages"), TEXT("*.json")), true, false);
	TestTrue(TEXT("golden message files found"), Files.Num() >= 40);
	int32 Frames = 0;
	for (const FString& File : Files)
	{
		for (const TSharedPtr<FJsonValue>& V : ReadArray(FPaths::Combine(BridgeDataDir(), TEXT("messages"), File)))
		{
			const FString Text = VerseBridgeJson::Write(V->AsObject());
			FVerseBridgeFrame A;
			FString Error;
			if (!TestTrue(FString::Printf(TEXT("%s parses (%s)"), *File, *Error), FVerseBridgeFrame::Parse(Text, A, &Error)))
			{
				continue;
			}
			FVerseBridgeFrame B;
			TestTrue(TEXT("re-encoded frame parses"), FVerseBridgeFrame::Parse(A.Encode(), B));
			TestEqual(TEXT("type"), B.Type, A.Type);
			TestEqual(TEXT("seq"), B.Seq, A.Seq);
			TestEqual(TEXT("base"), B.Base, A.Base);
			TestEqual(TEXT("id"), B.Id, A.Id);
			TestEqual(TEXT("re"), B.Re, A.Re);
			TestTrue(FString::Printf(TEXT("%s data round trip"), *File), VerseBridgeJson::Equal(A.Data, B.Data));
			TestTrue(FString::Printf(TEXT("%s equals the golden object"), *File), VerseBridgeJson::Equal(VerseBridgeJson::Read(A.Encode()), V->AsObject()));
			++Frames;
		}
	}
	AddInfo(FString::Printf(TEXT("%d golden frames round-tripped"), Frames));
	FVerseBridgeFrame Bad;
	TestFalse(TEXT("no type is malformed"), FVerseBridgeFrame::Parse(TEXT("{\"data\":{}}"), Bad));
	TestFalse(TEXT("array data is malformed"), FVerseBridgeFrame::Parse(TEXT("{\"type\":\"x\",\"data\":[]}"), Bad));
	TestFalse(TEXT("not JSON"), FVerseBridgeFrame::Parse(TEXT("nope"), Bad));
	return true;
}

// A17.1 (C++ half): cells.bin/1 vectors encode to the exact bytes and decode back; bad ones fail.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBridgeCellsVectorsTest, "Verse.Bridge.Codec.CellsVectors",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseBridgeCellsVectorsTest::RunTest(const FString& Parameters)
{
	FString Text;
	if (!TestTrue(TEXT("vectors file"), FFileHelper::LoadFileToString(Text, *FPaths::Combine(BridgeDataDir(), TEXT("cells"), TEXT("vectors.json")))))
	{
		return false;
	}
	const TSharedPtr<FJsonObject> Root = VerseBridgeJson::Read(Text);
	int32 Valid = 0;
	for (const TSharedPtr<FJsonValue>& V : *VerseBridgeJson::Arr(Root, TEXT("valid")))
	{
		const TSharedPtr<FJsonObject> Vec = V->AsObject();
		const FString Name = VerseBridgeJson::Str(Vec, TEXT("name"));
		const TSharedPtr<FJsonObject> Frame = VerseBridgeJson::Obj(Vec, TEXT("frame"));
		FVerseCellsFrame FromJson;
		FString Error;
		if (!TestTrue(FString::Printf(TEXT("%s json form reads (%s)"), *Name, *Error), FVerseCellsFrame::FromJson(VerseBridgeJson::Obj(Frame, TEXT("data")), FromJson, &Error)))
		{
			continue;
		}
		FromJson.Ref = uint16(VerseBridgeJson::Int(Vec, TEXT("ref")));
		FromJson.Seq = uint32(VerseBridgeJson::Int(Frame, TEXT("seq")));
		FromJson.Base = uint32(VerseBridgeJson::Int(Frame, TEXT("base")));
		const FString Hex = VerseBridgeJson::Str(Vec, TEXT("bin_hex"));
		TestEqual(FString::Printf(TEXT("%s encodes to the golden bytes"), *Name), ToHex(FromJson.Encode()), Hex);
		FVerseCellsFrame Decoded;
		if (TestTrue(FString::Printf(TEXT("%s decodes"), *Name), FVerseCellsFrame::Decode(FromHex(Hex), Decoded, &Error)))
		{
			TestEqual(TEXT("decoded re-encodes identically"), ToHex(Decoded.Encode()), Hex);
			TestEqual(TEXT("rows"), Decoded.RowsChanged.Num(), FromJson.RowsChanged.Num());
			for (int32 R = 0; R < FMath::Min(Decoded.RowsChanged.Num(), FromJson.RowsChanged.Num()); ++R)
			{
				for (int32 U = 0; U < FMath::Min(Decoded.RowsChanged[R].Runs.Num(), FromJson.RowsChanged[R].Runs.Num()); ++U)
				{
					TestEqual(TEXT("run text"), Decoded.RowsChanged[R].Runs[U].Text, FromJson.RowsChanged[R].Runs[U].Text);
				}
			}
		}
		++Valid;
	}
	TestTrue(TEXT("valid vectors"), Valid >= 5);
	for (const TSharedPtr<FJsonValue>& V : *VerseBridgeJson::Arr(Root, TEXT("invalid")))
	{
		const TSharedPtr<FJsonObject> Vec = V->AsObject();
		FVerseCellsFrame Decoded;
		TestFalse(FString::Printf(TEXT("%s is rejected"), *VerseBridgeJson::Str(Vec, TEXT("name"))),
			FVerseCellsFrame::Decode(FromHex(VerseBridgeJson::Str(Vec, TEXT("bin_hex"))), Decoded));
	}
	return true;
}

// Feeds: snapshot + partial deltas + removals, unknown enum fallback, screens gap detection.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBridgeFeedsTest, "Verse.Bridge.Feeds",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseBridgeFeedsTest::RunTest(const FString& Parameters)
{
	FVerseRosterFeed Roster;
	int32 Changes = 0;
	Roster.OnChanged.AddLambda([&Changes]() { ++Changes; });
	for (const TSharedPtr<FJsonValue>& V : ReadArray(FPaths::Combine(BridgeDataDir(), TEXT("messages"), TEXT("roster.snapshot.json"))))
	{
		Roster.ApplySnapshot(VerseBridgeJson::Obj(V->AsObject(), TEXT("data")));
		break;
	}
	TestTrue(TEXT("snapshot applied"), Roster.HasSnapshot() && Roster.GetAgents().Num() > 0);
	FVerseAgent Mara;
	TestTrue(TEXT("agent found"), Roster.FindAgent(TEXT("ag_7f1"), Mara));
	TestEqual(TEXT("duty"), Mara.Duty, FString(TEXT("waiting")));
	const TSharedPtr<FJsonObject> Delta = VerseBridgeJson::Read(TEXT(
		"{\"upsert\":{\"agents\":[{\"agent_id\":\"ag_7f1\",\"duty\":\"dancing\",\"run_state\":\"working\"}],\"panes\":[]},"
		"\"remove\":{\"agents\":[],\"panes\":[\"ws_91:T1\"]},\"commander\":null}"));
	Roster.ApplyDelta(Delta);
	TestTrue(TEXT("agent still found"), Roster.FindAgent(TEXT("ag_7f1"), Mara));
	TestEqual(TEXT("unknown duty falls back to idle"), Mara.Duty, FString(TEXT("idle")));
	TestEqual(TEXT("partial upsert keeps the name"), Mara.Name, FString(TEXT("Mara")));
	FVersePane Pane;
	TestFalse(TEXT("pane removed"), Roster.FindPane(TEXT("ws_91:T1"), Pane));
	TestEqual(TEXT("two change notices"), Changes, 2);

	FVerseScreensFeed Screens;
	Screens.Bind(VerseBridgeJson::Read(TEXT("{\"bound\":[{\"pane_id\":\"ws_91:T1\",\"ref\":1}],\"dropped\":[],\"missing\":[]}")));
	FVerseCellsFrame Snap;
	Snap.bSnapshot = true;
	Snap.Ref = 1;
	Snap.Seq = 10;
	Snap.Cols = 20;
	Snap.Rows = 4;
	TestTrue(TEXT("snapshot applies"), Screens.ApplyFrame(Snap));
	FVerseCellsFrame Gap = Snap;
	Gap.bSnapshot = false;
	Gap.Seq = 14;
	Gap.Base = 12;
	TestFalse(TEXT("a delta on the wrong base is a gap"), Screens.ApplyFrame(Gap));
	Gap.Base = 10;
	TestTrue(TEXT("a delta on the last frame applies"), Screens.ApplyFrame(Gap));

	TestEqual(TEXT("accept key (RFC 6455 example)"), FVerseWsClient::AcceptFor(TEXT("dGhlIHNhbXBsZSBub25jZQ==")), FString(TEXT("s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")));
	FString Host, Path;
	int32 Port = 0;
	TestTrue(TEXT("loopback url"), FVerseWsClient::ParseUrl(TEXT("ws://127.0.0.1:8765/api/verse/bridge"), Host, Port, Path));
	TestEqual(TEXT("port"), Port, 8765);
	TestEqual(TEXT("path"), Path, FString(TEXT("/api/verse/bridge")));
	TestFalse(TEXT("remote hosts are refused"), FVerseWsClient::ParseUrl(TEXT("ws://10.0.0.2:8765/x"), Host, Port, Path));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
