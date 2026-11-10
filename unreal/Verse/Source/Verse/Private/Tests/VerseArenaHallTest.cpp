#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/RectLight.h"
#include "Engine/SpotLight.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/WorldSettings.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "VerseArenaGraybox.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Arena.HallPart: the hangar deck view stands in the dressed hall (layout layer "base") from
// its first frame; the duel swaps it for the full graybox (hall and arena) and gets it back after.

namespace VerseArenaHallTest
{
	struct FLayerCounts
	{
		int32 BaseBoxes = 0;
		int32 BaseRamps = 0;
		int32 BaseLights = 0;
		int32 Lights = 0;
	};

	bool CountLayers(FLayerCounts& Out)
	{
		FString Text;
		TSharedPtr<FJsonObject> Root;
		if (!FFileHelper::LoadFileToString(Text, *AVerseArenaGraybox::DefaultJsonPath())
			|| !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root)
		{
			return false;
		}
		auto IsBase = [](const TSharedPtr<FJsonValue>& V)
		{
			FString Layer;
			return V->AsObject()->TryGetStringField(TEXT("layer"), Layer) && Layer == TEXT("base");
		};
		for (const TSharedPtr<FJsonValue>& V : Root->GetArrayField(TEXT("boxes")))
		{
			Out.BaseBoxes += IsBase(V) ? 1 : 0;
		}
		for (const TSharedPtr<FJsonValue>& V : Root->GetArrayField(TEXT("ramps")))
		{
			Out.BaseRamps += IsBase(V) ? 1 : 0;
		}
		for (const TSharedPtr<FJsonValue>& V : Root->GetArrayField(TEXT("lights")))
		{
			Out.BaseLights += IsBase(V) ? 1 : 0;
			++Out.Lights;
		}
		return true;
	}

	int32 LiveLights(UWorld* World)
	{
		int32 N = 0;
		for (TActorIterator<ASpotLight> It(World); It; ++It)
		{
			N += IsValid(*It) && !It->IsActorBeingDestroyed() ? 1 : 0;
		}
		for (TActorIterator<ARectLight> It(World); It; ++It)
		{
			N += IsValid(*It) && !It->IsActorBeingDestroyed() ? 1 : 0;
		}
		return N;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseArenaHallPartTest, "Verse.Arena.HallPart", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseArenaHallPartTest::RunTest(const FString&)
{
	using namespace VerseArenaHallTest;
	FLayerCounts Counts;
	if (!TestTrue(TEXT("graybox JSON reads"), CountLayers(Counts)))
	{
		return false;
	}
	TestTrue(TEXT("the JSON names hall and arena lights"), Counts.BaseLights > 0 && Counts.BaseLights < Counts.Lights);

	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, MakeUniqueObjectName(GetTransientPackage(), UWorld::StaticClass(), TEXT("VerseArenaHallTest")));
	FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
	Context.SetCurrentWorld(World);
	World->InitializeActorsForPlay(FURL());
	World->BeginPlay();
	if (!World->GetBegunPlay())
	{
		// No game mode here: begin play by hand so spawned actors get BeginPlay and EndPlay.
		World->GetWorldSettings()->NotifyBeginPlay();
	}

	AVerseArenaGraybox* Hall = AVerseArenaGraybox::BuildHall(*World);
	if (TestNotNull(TEXT("the deck view gets a hall"), Hall))
	{
		TestTrue(TEXT("it is the hall part"), Hall->GetPart() == EVerseGrayboxPart::Hall);
		TestEqual(TEXT("hall: the base layer's boxes and ramps only"), Hall->NumBoxes(), Counts.BaseBoxes + Counts.BaseRamps);
		TestEqual(TEXT("hall: no spawn points"), Hall->NumSpawns(), 0);
		TestEqual(TEXT("hall: nothing breaks"), Hall->NumPieces(), 0);
		TestEqual(TEXT("hall: truss and armoury lights, none of the arena's practicals"), LiveLights(World), Counts.BaseLights);
		TestTrue(TEXT("the duel's graybox is not there yet"), AVerseArenaGraybox::Find(*World) == nullptr);
		TestTrue(TEXT("a second hall request keeps the first"), AVerseArenaGraybox::BuildHall(*World) == Hall);
	}

	AVerseArenaGraybox* Full = AVerseArenaGraybox::BuildIfMissing(*World);
	if (TestNotNull(TEXT("the duel builds its graybox"), Full))
	{
		TestTrue(TEXT("it is the full graybox"), Full->GetPart() == EVerseGrayboxPart::Full);
		TestTrue(TEXT("the hall gave way to it"), AVerseArenaGraybox::FindHall(*World) == nullptr);
		TestTrue(TEXT("full: spawn points"), Full->NumSpawns() > 0);
		TestTrue(TEXT("full: more than the hall"), Full->NumBoxes() > Counts.BaseBoxes);
		TestEqual(TEXT("full: every light"), LiveLights(World), Counts.Lights);
		TestTrue(TEXT("no hall while the duel's graybox stands"), AVerseArenaGraybox::BuildHall(*World) == nullptr);
		Full->Destroy();
	}

	AVerseArenaGraybox* Again = AVerseArenaGraybox::BuildHall(*World);
	TestTrue(TEXT("after the duel the hall stands again"), Again && Again->GetPart() == EVerseGrayboxPart::Hall);

	World->EndPlay(EEndPlayReason::Quit);
	GEngine->DestroyWorldContext(World);
	World->DestroyWorld(false);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
