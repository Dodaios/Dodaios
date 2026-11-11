#include "Decks/VerseDeckLife.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Decks.Life.Assets: everything the deck look pass loads by path at runtime resolves, so a
// renamed read-out or clutter piece fails here instead of leaving a deck dark or bare.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDeckLifeAssetsTest, "Verse.Decks.Life.Assets",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ClientContext | EAutomationTestFlags::EngineFilter)

bool FVerseDeckLifeAssetsTest::RunTest(const FString& Parameters)
{
	for (const TCHAR* Deck : { TEXT("bridge"), TEXT("ops"), TEXT("engineering"), TEXT("hangar") })
	{
		const TArray<FName> Layouts = AVerseDeckLife::ReadoutsFor(Deck);
		TestTrue(FString::Printf(TEXT("%s has read-outs"), Deck), Layouts.Num() > 0);
		for (const FName Layout : Layouts)
		{
			const FString Path = FString::Printf(TEXT("/Game/Verse/Materials/Instances/Props/MI_Readout_%s.MI_Readout_%s"), *Layout.ToString(), *Layout.ToString());
			TestNotNull(*Path, LoadObject<UMaterialInterface>(nullptr, *Path));
		}
	}
	for (const TCHAR* Piece : { TEXT("SM_Clutter_Tablet"), TEXT("SM_Clutter_Mug"), TEXT("SM_Clutter_DataPads"), TEXT("SM_Clutter_Headset"),
			 TEXT("SM_Clutter_Toolkit"), TEXT("SM_Clutter_CableCoil"), TEXT("SM_Clutter_HoloGlobe"), TEXT("SM_Clutter_GuideStrip"),
			 TEXT("SM_Clutter_WallDisplay") })
	{
		const FString Path = FString::Printf(TEXT("/Game/Verse/Kit/Props/%s.%s"), Piece, Piece);
		const UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *Path);
		TestNotNull(*Path, Mesh);
	}
	return true;
}

#endif
