#include "Dom/JsonObject.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Character.h"
#include "Misc/AutomationTest.h"
#include "Qa/VerseQaEngineCommands.h"
#include "Qa/VerseQaRegistry.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Parity.Q.*: the engine-level QA commands of parity.md section 19 (Dump Q-02, Tune and
// Materials Q-06, Viewmodel Q-08), run through the registry exactly as the console and the
// qa.exec bridge frame reach them.

#define VERSE_QA_PARITY_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseQaParity
{
	TSharedPtr<FJsonObject> Run(FAutomationTestBase& Test, const FString& Line)
	{
		UVerseQaRegistry* Registry = UVerseQaRegistry::Get();
		TSharedPtr<FJsonObject> Json;
		if (!Test.TestNotNull(TEXT("registry"), Registry))
		{
			return Json;
		}
		FString Result;
		Test.TestTrue(*FString::Printf(TEXT("'%s' is registered"), *Line), Registry->ExecuteLine(Line, Result));
		Test.TestTrue(*FString::Printf(TEXT("'%s' answers JSON: %s"), *Line, *Result),
			FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Result), Json) && Json.IsValid());
		return Json;
	}

	/** A transient game world that the commands see as the running game. */
	struct FScopedWorld
	{
		UWorld* World = nullptr;

		FScopedWorld()
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("VerseQaParityWorld"), GetTransientPackage());
			VerseQaEngine::SetWorldForTests(World);
		}

		~FScopedWorld()
		{
			VerseQaEngine::SetWorldForTests(nullptr);
			if (World != nullptr)
			{
				World->DestroyWorld(false);
			}
		}
	};
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityQ02Dump, "Verse.Parity.Q.02", VERSE_QA_PARITY_FLAGS)
bool FVerseParityQ02Dump::RunTest(const FString&)
{
	VerseQaParity::FScopedWorld Scoped;
	if (!TestNotNull(TEXT("world"), Scoped.World))
	{
		return false;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	ACharacter* A = Scoped.World->SpawnActor<ACharacter>(FVector(100, 200, 300), FRotator(0, 90, 0), Params);
	ACharacter* B = Scoped.World->SpawnActor<ACharacter>(FVector(-50, 0, 10), FRotator(0, -45, 0), Params);
	if (!TestNotNull(TEXT("pawns spawned"), A) || !TestNotNull(TEXT("second pawn"), B))
	{
		return false;
	}

	UVerseQaRegistry* Registry = UVerseQaRegistry::Get();
	if (!TestNotNull(TEXT("registry"), Registry))
	{
		return false;
	}
	TSharedPtr<FJsonObject> Dump = VerseQaParity::Run(*this, TEXT("Verse.QA.Dump"));
	if (!Dump.IsValid())
	{
		return false;
	}
	TestTrue(TEXT("camera key present (null without a player)"), Dump->HasField(TEXT("camera")));
	const TArray<TSharedPtr<FJsonValue>>* Pawns = nullptr;
	if (TestTrue(TEXT("pawns array"), Dump->TryGetArrayField(TEXT("pawns"), Pawns)))
	{
		TestEqual(TEXT("every pawn is listed"), Pawns->Num(), 2);
		bool bFoundA = false;
		for (const TSharedPtr<FJsonValue>& Value : *Pawns)
		{
			const TSharedPtr<FJsonObject> Pawn = Value->AsObject();
			const TArray<TSharedPtr<FJsonValue>>& Loc = Pawn->GetArrayField(TEXT("location_cm"));
			if (Loc.Num() == 3 && FMath::IsNearlyEqual(Loc[0]->AsNumber(), 100.0) && FMath::IsNearlyEqual(Loc[2]->AsNumber(), 300.0))
			{
				bFoundA = true;
				TestTrue(TEXT("yaw is reported"), FMath::IsNearlyEqual(Pawn->GetNumberField(TEXT("yaw")), 90.0, 0.01));
				TestEqual(TEXT("an unpossessed pawn has no controller"), Pawn->GetStringField(TEXT("controller")), FString(TEXT("none")));
			}
		}
		TestTrue(TEXT("pawn pose matches the actor"), bFoundA);
	}
	const TArray<TSharedPtr<FJsonValue>>* Crew = nullptr;
	TestTrue(TEXT("crew array exists even before the crew package registers"), Dump->TryGetArrayField(TEXT("crew"), Crew));

	// The crew package adds its statuses through a section; Dump carries them.
	Registry->RegisterDumpSection(TEXT("crew"), []() { return FString(TEXT("[{\"id\":\"a1\",\"duty\":\"working\"}]")); });
	TSharedPtr<FJsonObject> WithCrew = VerseQaParity::Run(*this, TEXT("Verse.QA.Dump"));
	Registry->UnregisterDumpSection(TEXT("crew"));
	if (WithCrew.IsValid() && TestTrue(TEXT("crew section"), WithCrew->TryGetArrayField(TEXT("crew"), Crew)))
	{
		TestEqual(TEXT("crew statuses"), Crew->Num(), 1);
		TestEqual(TEXT("crew duty"), (*Crew)[0]->AsObject()->GetStringField(TEXT("duty")), FString(TEXT("working")));
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityQ06Tune, "Verse.Parity.Q.06", VERSE_QA_PARITY_FLAGS)
bool FVerseParityQ06Tune::RunTest(const FString&)
{
	VerseQaParity::FScopedWorld Scoped;
	if (!TestNotNull(TEXT("world"), Scoped.World))
	{
		return false;
	}
	TSharedPtr<FJsonObject> Idle = VerseQaParity::Run(*this, TEXT("Verse.QA.Tune"));
	if (Idle.IsValid())
	{
		TestFalse(TEXT("nothing is overridden at first"), Idle->GetBoolField(TEXT("volume")));
	}

	TSharedPtr<FJsonObject> Set = VerseQaParity::Run(*this, TEXT("Verse.QA.Tune exposure=1.5 bloom=0.25"));
	if (Set.IsValid())
	{
		TestEqual(TEXT("exposure"), Set->GetNumberField(TEXT("exposure")), 1.5);
		TestEqual(TEXT("bloom"), Set->GetNumberField(TEXT("bloom")), 0.25);
		TestTrue(TEXT("a volume carries it"), Set->GetBoolField(TEXT("volume")));
	}
	int32 Volumes = 0;
	for (TActorIterator<APostProcessVolume> It(Scoped.World); It; ++It)
	{
		++Volumes;
		TestTrue(TEXT("exposure bias override"), It->Settings.bOverride_AutoExposureBias);
		TestEqual(TEXT("exposure bias value"), It->Settings.AutoExposureBias, 1.5f);
		TestTrue(TEXT("bloom override"), It->Settings.bOverride_BloomIntensity);
		TestEqual(TEXT("bloom value"), It->Settings.BloomIntensity, 0.25f);
		TestTrue(TEXT("unbound"), It->bUnbound);
	}
	TestEqual(TEXT("exactly one volume"), Volumes, 1);

	TSharedPtr<FJsonObject> Bad = VerseQaParity::Run(*this, TEXT("Verse.QA.Tune exposure=loud"));
	if (Bad.IsValid())
	{
		TestTrue(TEXT("bad input is an error object"), Bad->HasField(TEXT("error")));
	}

	TSharedPtr<FJsonObject> Reset = VerseQaParity::Run(*this, TEXT("Verse.QA.Tune reset"));
	if (Reset.IsValid())
	{
		TestFalse(TEXT("reset drops the volume"), Reset->GetBoolField(TEXT("volume")));
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityQ06Materials, "Verse.Parity.Q.06.Materials", VERSE_QA_PARITY_FLAGS)
bool FVerseParityQ06Materials::RunTest(const FString&)
{
	TSharedPtr<FJsonObject> All = VerseQaParity::Run(*this, TEXT("Verse.QA.Materials"));
	if (!All.IsValid())
	{
		return false;
	}
	TestTrue(TEXT("the engine has materials loaded"), All->GetNumberField(TEXT("total_loaded")) > 0.0);
	const TArray<TSharedPtr<FJsonValue>>* Names = nullptr;
	TestTrue(TEXT("names array"), All->TryGetArrayField(TEXT("names"), Names));
	TestTrue(TEXT("project materials never exceed all loaded ones"), All->GetNumberField(TEXT("count")) <= All->GetNumberField(TEXT("total_loaded")));

	TSharedPtr<FJsonObject> None = VerseQaParity::Run(*this, TEXT("Verse.QA.Materials no_such_material_anywhere"));
	if (None.IsValid())
	{
		TestEqual(TEXT("a filter that matches nothing"), None->GetNumberField(TEXT("count")), 0.0);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityQ08Viewmodel, "Verse.Parity.Q.08", VERSE_QA_PARITY_FLAGS)
bool FVerseParityQ08Viewmodel::RunTest(const FString&)
{
	UVerseQaRegistry* Registry = UVerseQaRegistry::Get();
	if (!TestNotNull(TEXT("registry"), Registry))
	{
		return false;
	}
	int32 Notified = 0;
	const FDelegateHandle Handle = Registry->OnViewmodelLayoutChanged.AddLambda([&Notified](const FVerseViewmodelLayout&) { ++Notified; });

	TSharedPtr<FJsonObject> Set = VerseQaParity::Run(*this, TEXT("Verse.QA.Viewmodel x=1.5 y=-2 z=3 scale=1.25 fov=60"));
	if (Set.IsValid())
	{
		TestEqual(TEXT("x"), Set->GetNumberField(TEXT("x")), 1.5);
		TestEqual(TEXT("y"), Set->GetNumberField(TEXT("y")), -2.0);
		TestEqual(TEXT("z"), Set->GetNumberField(TEXT("z")), 3.0);
		TestEqual(TEXT("scale"), Set->GetNumberField(TEXT("scale")), 1.25);
		TestEqual(TEXT("fov"), Set->GetNumberField(TEXT("fov")), 60.0);
	}
	TestEqual(TEXT("the viewmodel is told once"), Notified, 1);
	TestEqual(TEXT("the registry holds the layout"), Registry->GetViewmodelLayout().OffsetCm, FVector(1.5, -2.0, 3.0));

	TSharedPtr<FJsonObject> Read = VerseQaParity::Run(*this, TEXT("Verse.QA.Viewmodel"));
	if (Read.IsValid())
	{
		TestEqual(TEXT("a read changes nothing"), Read->GetNumberField(TEXT("scale")), 1.25);
	}
	TestEqual(TEXT("a read does not notify"), Notified, 1);

	TSharedPtr<FJsonObject> Bad = VerseQaParity::Run(*this, TEXT("Verse.QA.Viewmodel scale=0"));
	if (Bad.IsValid())
	{
		TestTrue(TEXT("a zero scale is refused"), Bad->HasField(TEXT("error")));
	}
	TestEqual(TEXT("a refused retune does not change the layout"), Registry->GetViewmodelLayout().Scale, 1.25f);

	TSharedPtr<FJsonObject> Reset = VerseQaParity::Run(*this, TEXT("Verse.QA.Viewmodel reset"));
	if (Reset.IsValid())
	{
		TestEqual(TEXT("reset restores the scale"), Reset->GetNumberField(TEXT("scale")), 1.0);
	}
	Registry->OnViewmodelLayoutChanged.Remove(Handle);
	return true;
}

#endif
