#include "Duel/Tests/Fakes/FakeDuelResultSink.h"
#include "Duel/VerseDuelReporter.h"
#include "Duel/VerseDuelResultCodec.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Bridge.Duel.*: the duel.result reporter of WP21.6 against the G0.11 golden fixtures and a
// fake bridge sink. Synthetic FVerseSetSummary events stand in for WP11's ruleset.

#define VERSE_DUEL_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseDuelTest
{
	using namespace VerseDuel;

	/** The set of the contract's example (bridge-protocol.md 10, golden messages/duel.result.json[0]). */
	FVerseSetSummary GoldenSet()
	{
		FVerseSetSummary Set;
		Set.MatchId = TEXT("m_01JD…");
		Set.SessionId = TEXT("s_01JD…");
		Set.SetIndex = 3;
		Set.RulesetId = FName(TEXT("endless/1"));
		Set.BotTier = FName(TEXT("hard"));
		Set.Outcome = EVerseSetOutcome::Won;
		Set.StartedAtUnix = 1793612200.0;
		Set.EndedAtUnix = 1793612500.0;
		Set.MatchTimeS = 296.4f;
		FVerseSetLine& P = Set.Person;
		P.Kills = 10;
		P.Deaths = 7;
		P.Headshots = 4;
		P.Finishers = 1;
		P.MeleeKills = 1;
		P.ShotsFired = 540;
		P.ShotsHit = 201;
		P.DamageDealt = 2760;
		P.DamageTaken = 2210;
		P.WallsBreached = 2;
		P.BulwarksPlaced = 3;
		P.BestStreak = 4;
		P.PerWeapon.Add(FName(TEXT("graveline")), FIntVector4(8, 4, 410, 152));
		Set.Opponent.bIsBot = true;
		Set.Opponent.Kills = 7;
		return Set;
	}

	FVerseSetSummary SetNamed(const FString& MatchId, EVerseSetOutcome Outcome)
	{
		FVerseSetSummary Set = GoldenSet();
		Set.MatchId = MatchId;
		Set.Outcome = Outcome;
		return Set;
	}

	FBuildStamp GoldenBuild()
	{
		FBuildStamp Build;
		Build.Version = TEXT("0.1.0");
		Build.Changelist = TEXT("a1b2c3d");
		return Build;
	}

	/** A fresh pending folder under Saved/Automation, removed by the caller through Cleanup. */
	FString TempDir()
	{
		return FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Automation"), TEXT("WP21"), FGuid::NewGuid().ToString(EGuidFormats::Digits));
	}

	void Cleanup(const FString& Dir)
	{
		IFileManager::Get().DeleteDirectory(*Dir, false, true);
	}

	int32 FilesIn(const FString& Dir)
	{
		TArray<FString> Files;
		IFileManager::Get().FindFiles(Files, *FPaths::Combine(Dir, TEXT("*.json")), true, false);
		return Files.Num();
	}

	TSharedRef<FDuelReporter> MakeReporter(const FString& Dir, const FString& LaunchId, const TSharedPtr<FFakeDuelResultSink>& Sink)
	{
		FDuelReporter::FConfig Config;
		Config.PendingDir = Dir;
		Config.LaunchId = LaunchId;
		Config.Build = GoldenBuild();
		TSharedRef<FDuelReporter> Reporter = MakeShared<FDuelReporter>(MoveTemp(Config));
		Reporter->SetSink(Sink);
		return Reporter;
	}

	/** JSON equality with numbers compared to a millionth (a float match time round-trips). */
	bool SameJson(FAutomationTestBase& Test, const FString& Path, const TSharedPtr<FJsonValue>& A, const TSharedPtr<FJsonValue>& B)
	{
		if (!A.IsValid() || !B.IsValid())
		{
			Test.AddError(FString::Printf(TEXT("%s: missing value"), *Path));
			return false;
		}
		if (A->Type != B->Type)
		{
			Test.AddError(FString::Printf(TEXT("%s: type %d vs %d"), *Path, int32(A->Type), int32(B->Type)));
			return false;
		}
		switch (A->Type)
		{
		case EJson::Number:
			if (!FMath::IsNearlyEqual(A->AsNumber(), B->AsNumber(), 1e-6 * FMath::Max(1.0, FMath::Abs(B->AsNumber()))))
			{
				Test.AddError(FString::Printf(TEXT("%s: %f vs %f"), *Path, A->AsNumber(), B->AsNumber()));
				return false;
			}
			return true;
		case EJson::String:
			if (A->AsString() != B->AsString())
			{
				Test.AddError(FString::Printf(TEXT("%s: '%s' vs '%s'"), *Path, *A->AsString(), *B->AsString()));
				return false;
			}
			return true;
		case EJson::Boolean:
			return A->AsBool() == B->AsBool() || (Test.AddError(Path + TEXT(": bool differs")), false);
		case EJson::Array:
		{
			const TArray<TSharedPtr<FJsonValue>>& X = A->AsArray();
			const TArray<TSharedPtr<FJsonValue>>& Y = B->AsArray();
			if (X.Num() != Y.Num())
			{
				Test.AddError(FString::Printf(TEXT("%s: %d vs %d items"), *Path, X.Num(), Y.Num()));
				return false;
			}
			bool bSame = true;
			for (int32 I = 0; I < X.Num(); ++I)
			{
				bSame &= SameJson(Test, FString::Printf(TEXT("%s[%d]"), *Path, I), X[I], Y[I]);
			}
			return bSame;
		}
		case EJson::Object:
		{
			const TSharedPtr<FJsonObject> X = A->AsObject();
			const TSharedPtr<FJsonObject> Y = B->AsObject();
			bool bSame = X->Values.Num() == Y->Values.Num();
			if (!bSame)
			{
				TArray<FString> KX, KY;
				X->Values.GetKeys(KX);
				Y->Values.GetKeys(KY);
				Test.AddError(FString::Printf(TEXT("%s: keys {%s} vs {%s}"), *Path, *FString::Join(KX, TEXT(",")), *FString::Join(KY, TEXT(","))));
			}
			for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Y->Values)
			{
				bSame &= SameJson(Test, Path + TEXT(".") + Pair.Key, X->TryGetField(Pair.Key), Pair.Value);
			}
			return bSame;
		}
		default:
			return true;
		}
	}

	TSharedPtr<FJsonObject> GoldenData(FAutomationTestBase& Test, int32 Index)
	{
		const FString Path = FPaths::Combine(FPaths::ProjectDir(), TEXT("Tests/Data/bridge/messages/duel.result.json"));
		FString Text;
		if (!Test.TestTrue(TEXT("golden duel.result fixture is readable"), FFileHelper::LoadFileToString(Text, *Path)))
		{
			return nullptr;
		}
		TArray<TSharedPtr<FJsonValue>> Frames;
		const TSharedRef<TJsonReader<TCHAR>> Reader = TJsonReaderFactory<TCHAR>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Frames) || !Frames.IsValidIndex(Index))
		{
			Test.AddError(TEXT("golden duel.result fixture does not parse"));
			return nullptr;
		}
		return Frames[Index]->AsObject()->GetObjectField(TEXT("data"));
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDuelCodecGoldenTest, "Verse.Bridge.Duel.Codec.Golden", VERSE_DUEL_TEST_FLAGS)
bool FVerseDuelCodecGoldenTest::RunTest(const FString& Parameters)
{
	using namespace VerseDuelTest;
	const TSharedPtr<FJsonObject> Golden = GoldenData(*this, 0);
	if (!Golden.IsValid())
	{
		return false;
	}
	const TSharedRef<FJsonObject> Mine = EncodeResult(GoldenSet(), EEndReason::SetComplete, GoldenBuild());
	SameJson(*this, TEXT("data"), MakeShared<FJsonValueObject>(Mine), MakeShared<FJsonValueObject>(Golden));
	// The text round trip keeps every field (what the pending file holds).
	const TSharedPtr<FJsonObject> Back = FromJsonString(ToJsonString(Mine));
	TestTrue(TEXT("round trip parses"), Back.IsValid());
	if (Back.IsValid())
	{
		SameJson(*this, TEXT("round_trip"), MakeShared<FJsonValueObject>(Back), MakeShared<FJsonValueObject>(Golden));
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDuelCodecOutcomesTest, "Verse.Bridge.Duel.Codec.Outcomes", VERSE_DUEL_TEST_FLAGS)
bool FVerseDuelCodecOutcomesTest::RunTest(const FString& Parameters)
{
	using namespace VerseDuelTest;
	FVerseSetSummary Left = SetNamed(TEXT("m_left"), EVerseSetOutcome::Unfinished);
	Left.BotTier = FName(TEXT("adaptive"));
	Left.Person.PerWeapon.Add(FName(TEXT("Side Arm-K")), FIntVector4(1, 0, 20, 9));
	const TSharedRef<FJsonObject> Data = EncodeResult(Left, DefaultEndReason(Left), GoldenBuild());
	TestEqual(TEXT("unfinished outcome"), Data->GetStringField(TEXT("outcome")), FString(TEXT("unfinished")));
	TestEqual(TEXT("left mid-set"), Data->GetStringField(TEXT("end_reason")), FString(TEXT("player_left")));
	const TSharedPtr<FJsonObject> Opponent = Data->GetObjectField(TEXT("opponent"));
	TestEqual(TEXT("adaptive bot starts on hard"), Opponent->GetStringField(TEXT("tier")), FString(TEXT("hard")));
	TestTrue(TEXT("adaptive flag"), Opponent->GetBoolField(TEXT("adaptive")));
	const TArray<TSharedPtr<FJsonValue>>& Weapons = Data->GetArrayField(TEXT("weapons"));
	TestEqual(TEXT("two weapons"), Weapons.Num(), 2);
	TestEqual(TEXT("wire ids sort and sanitise"), Weapons[1]->AsObject()->GetStringField(TEXT("weapon_id")), FString(TEXT("side_arm_k")));

	// A finished set always completed, whatever reason the caller had in mind.
	const TSharedRef<FJsonObject> Won = EncodeResult(GoldenSet(), EEndReason::AppQuit, GoldenBuild());
	TestEqual(TEXT("won is set_complete"), Won->GetStringField(TEXT("end_reason")), FString(TEXT("set_complete")));
	const TSharedRef<FJsonObject> Quit = EncodeResult(Left, EEndReason::VerseQuit, GoldenBuild());
	TestEqual(TEXT("quit mid-set"), Quit->GetStringField(TEXT("end_reason")), FString(TEXT("verse_quit")));

	FVerseSetSummary Versus = GoldenSet();
	Versus.Opponent.bIsBot = false;
	const TSharedPtr<FJsonObject> Player = EncodeResult(Versus, EEndReason::SetComplete, GoldenBuild())->GetObjectField(TEXT("opponent"));
	TestEqual(TEXT("person opponent"), Player->GetStringField(TEXT("kind")), FString(TEXT("player")));
	TestFalse(TEXT("no tier for a person"), Player->HasField(TEXT("tier")));

	EEndReason Parsed = EEndReason::SetComplete;
	TestTrue(TEXT("crash_recovered parses"), ParseEndReason(TEXT("crash_recovered"), Parsed) && Parsed == EEndReason::CrashRecovered);
	TestFalse(TEXT("unknown reason refused"), ParseEndReason(TEXT("meteor"), Parsed));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDuelOnePerSetTest, "Verse.Bridge.Duel.OneResultPerSet", VERSE_DUEL_TEST_FLAGS)
bool FVerseDuelOnePerSetTest::RunTest(const FString& Parameters)
{
	using namespace VerseDuelTest;
	const FString Dir = TempDir();
	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("VerseDuelTestWorld"));
	UVerseEventHub* Hub = World ? World->GetSubsystem<UVerseEventHub>() : nullptr;
	if (!TestNotNull(TEXT("game world has the hub"), Hub))
	{
		return false;
	}
	TSharedPtr<FFakeDuelResultSink> Sink = MakeShared<FFakeDuelResultSink>();
	TSharedRef<FDuelReporter> Reporter = MakeReporter(Dir, TEXT("launch-a"), Sink);
	Reporter->Bind(*Hub);

	Hub->OnSetEnded.Broadcast(SetNamed(TEXT("set-1"), EVerseSetOutcome::Won));
	Hub->OnSetEnded.Broadcast(SetNamed(TEXT("set-2"), EVerseSetOutcome::Lost));
	Hub->OnSetEnded.Broadcast(SetNamed(TEXT("set-2"), EVerseSetOutcome::Lost));  // raised twice: still one result
	Reporter->NotifyQuitting(EEndReason::VerseQuit);
	Hub->OnSetEnded.Broadcast(SetNamed(TEXT("set-3"), EVerseSetOutcome::Unfinished));

	TestEqual(TEXT("one duel.result per set"), Sink->Sent.Num(), 3);
	TArray<FString> Reasons;
	for (const FFakeDuelResultSink::FSent& Sent : Sink->Sent)
	{
		Reasons.Add(Sent.Data->GetStringField(TEXT("match_id")) + TEXT(":") + Sent.Data->GetStringField(TEXT("outcome")) + TEXT(":") + Sent.Data->GetStringField(TEXT("end_reason")));
	}
	TestEqual(TEXT("results in order"), FString::Join(Reasons, TEXT(",")),
		FString(TEXT("set-1:won:set_complete,set-2:lost:set_complete,set-3:unfinished:verse_quit")));
	TestEqual(TEXT("stored results leave no pending file"), FilesIn(Dir), 0);

	Reporter->Unbind();
	Hub->OnSetEnded.Broadcast(SetNamed(TEXT("set-4"), EVerseSetOutcome::Won));
	TestEqual(TEXT("unbound reporter hears nothing"), Sink->Sent.Num(), 3);

	World->DestroyWorld(false);
	Cleanup(Dir);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDuelCrashRecoveryTest, "Verse.Bridge.Duel.CrashRecovery", VERSE_DUEL_TEST_FLAGS)
bool FVerseDuelCrashRecoveryTest::RunTest(const FString& Parameters)
{
	using namespace VerseDuelTest;
	const FString Dir = TempDir();
	{
		// Launch A: the set ends, the result goes out, and Verse dies before any reply.
		TSharedPtr<FFakeDuelResultSink> Dead = MakeShared<FFakeDuelResultSink>();
		Dead->bAnswerAtOnce = false;
		TSharedRef<FDuelReporter> A = MakeReporter(Dir, TEXT("launch-a"), Dead);
		A->HandleSetEnded(SetNamed(TEXT("m-crash"), EVerseSetOutcome::Won));
		TestEqual(TEXT("sent once before the crash"), Dead->Sent.Num(), 1);
		TestEqual(TEXT("the pending result is on disk"), FilesIn(Dir), 1);
		// The process dies: the reporter goes away without a reply; a late reply is harmless.
	}
	TestEqual(TEXT("the pending result survives the crash"), FilesIn(Dir), 1);

	// Launch B: the bridge says welcome; the leftover goes out at once as crash_recovered.
	TSharedPtr<FFakeDuelResultSink> Sink = MakeShared<FFakeDuelResultSink>();
	Sink->bAnswerAtOnce = false;
	TSharedRef<FDuelReporter> B = MakeReporter(Dir, TEXT("launch-b"), Sink);
	const double Welcome = FPlatformTime::Seconds();
	B->HandleWelcome();
	if (!TestEqual(TEXT("one result sent on welcome"), Sink->Sent.Num(), 1))
	{
		Cleanup(Dir);
		return false;
	}
	const FFakeDuelResultSink::FSent& Sent = Sink->Sent[0];
	TestTrue(TEXT("A21.4: sent within 10 s of welcome"), Sent.AtSeconds - Welcome < 10.0);
	TestEqual(TEXT("same match id"), Sent.Data->GetStringField(TEXT("match_id")), FString(TEXT("m-crash")));
	TestEqual(TEXT("end_reason crash_recovered"), Sent.Data->GetStringField(TEXT("end_reason")), FString(TEXT("crash_recovered")));
	TestEqual(TEXT("outcome kept"), Sent.Data->GetStringField(TEXT("outcome")), FString(TEXT("won")));

	// A second welcome while the first send is in flight sends nothing new.
	B->HandleWelcome();
	TestEqual(TEXT("no double send in flight"), Sink->Sent.Num(), 1);
	// No reply (link dropped): kept, and the next welcome sends it again.
	Sink->AnswerHeld(ESendResult::Failed);
	TestEqual(TEXT("kept after a failed send"), FilesIn(Dir), 1);
	B->HandleWelcome();
	TestEqual(TEXT("re-sent on the next welcome"), Sink->Sent.Num(), 2);
	Sink->AnswerHeld(ESendResult::Stored);
	TestEqual(TEXT("stored: the pending file is gone"), FilesIn(Dir), 0);
	TestEqual(TEXT("nothing pending"), B->PendingMatchIds().Num(), 0);

	// A result the server refuses is dropped, never retried forever.
	Sink->bAnswerAtOnce = true;
	Sink->Answer = ESendResult::Rejected;
	B->HandleSetEnded(SetNamed(TEXT("m-bad"), EVerseSetOutcome::Lost));
	TestEqual(TEXT("rejected result dropped"), FilesIn(Dir), 0);

	// Without a link the result waits on disk and goes out on the welcome of the same launch.
	Sink->Answer = ESendResult::Stored;
	Sink->bReady = false;
	B->HandleSetEnded(SetNamed(TEXT("m-offline"), EVerseSetOutcome::Lost));
	TestEqual(TEXT("offline: pending on disk"), FilesIn(Dir), 1);
	const int32 Before = Sink->Sent.Num();
	Sink->bReady = true;
	B->HandleWelcome();
	TestEqual(TEXT("sent on welcome"), Sink->Sent.Num(), Before + 1);
	TestEqual(TEXT("same launch keeps its own reason"), Sink->Sent.Last().Data->GetStringField(TEXT("end_reason")), FString(TEXT("set_complete")));
	TestEqual(TEXT("then gone"), FilesIn(Dir), 0);

	Cleanup(Dir);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
