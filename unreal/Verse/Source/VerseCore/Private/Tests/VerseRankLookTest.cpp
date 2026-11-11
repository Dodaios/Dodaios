#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Ranks/VerseRankLook.h"

// Verse.Ranks.Look: the ladder of progression/ranks.ts and applyLook of actors/look.ts on an
// officer body (SK_Commander_M is the three.js SK_Officer_M): tier colours by slot name, lit
// plate tiles in the tier's colour with a glow, empty sockets dark.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseRanksLookTest, "Verse.Ranks.Look", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseRanksLookTest::RunTest(const FString&)
{
	using namespace VerseRanks;
	TestEqual(TEXT("level 0 is still a recruit"), FString(ForLevel(0).Id), FString(TEXT("recruit")));
	TestEqual(TEXT("level 24 is a commander"), FString(ForLevel(24).Id), FString(TEXT("commander")));
	TestEqual(TEXT("level 50 is fleet admiral"), FString(ForLevel(99).Id), FString(TEXT("fleet_admiral")));
	TestEqual(TEXT("lit slots of 101|010"), LitSlots(TEXT("101|010")), TArray<int32>({ 0, 2, 4 }));

	USkeletalMesh* Mesh = LoadObject<USkeletalMesh>(nullptr, TEXT("/Game/Verse/Characters/Commander/SK_Commander_M.SK_Commander_M"), nullptr, LOAD_NoWarn | LOAD_Quiet);
	if (!TestNotNull(TEXT("SK_Commander_M"), Mesh))
	{
		return false;
	}
	USkeletalMeshComponent* Body = NewObject<USkeletalMeshComponent>(GetTransientPackage());
	Body->SetSkeletalMeshAsset(Mesh);
	TestEqual(TEXT("an unknown tier sets nothing"), ApplyLook(Body, TEXT("pirate"), TEXT("111|111")), 0);
	// Commodore: command tier, plate 101|010.
	const int32 Set = ApplyLevel(Body, 33);
	TestTrue(TEXT("uniform, trousers, trim and the six tiles"), Set >= 9);
	auto Tint = [Body](const TCHAR* Slot, const TCHAR* Param)
	{
		FLinearColor Out = FLinearColor::Transparent;
		const int32 Index = Body->GetMaterialIndex(FName(Slot));
		if (const UMaterialInstanceDynamic* Mid = Cast<UMaterialInstanceDynamic>(Body->GetMaterial(Index)))
		{
			Mid->GetVectorParameterValue(FHashedMaterialParameterInfo(Param), Out);
		}
		return Out;
	};
	const FTier* Command = FindTier(TEXT("command"));
	TestTrue(TEXT("command uniform"), Tint(TEXT("M_Uniform"), TEXT("BaseTint")).Equals(Linear(Command->Uniform), 1e-3f));
	TestTrue(TEXT("command gold trim"), Tint(TEXT("M_Trim"), TEXT("BaseTint")).Equals(Linear(Command->Trim), 1e-3f));
	TestTrue(TEXT("tile 1 lit in the tier colour"), Tint(TEXT("M_RankTile_1"), TEXT("BaseTint")).Equals(Linear(Command->Tile), 1e-3f));
	TestTrue(TEXT("tile 1 glows"), Tint(TEXT("M_RankTile_1"), TEXT("EmissiveColor")).GetLuminance() > 0.5f);
	TestTrue(TEXT("tile 2 is an empty socket"), Tint(TEXT("M_RankTile_2"), TEXT("BaseTint")).Equals(TileUnlit(), 1e-3f));
	TestTrue(TEXT("tile 2 is dark"), Tint(TEXT("M_RankTile_2"), TEXT("EmissiveColor")).GetLuminance() < 1e-4f);
	TestTrue(TEXT("tile 5 lit (bottom middle)"), Tint(TEXT("M_RankTile_5"), TEXT("EmissiveColor")).GetLuminance() > 0.5f);
	// A promotion to flag rank repaints the same body.
	ApplyLevel(Body, 50);
	TestTrue(TEXT("flag uniform after a promotion"), Tint(TEXT("M_Uniform"), TEXT("BaseTint")).Equals(Linear(FindTier(TEXT("flag"))->Uniform), 1e-3f));
	TestTrue(TEXT("every tile lit at fleet admiral"), Tint(TEXT("M_RankTile_2"), TEXT("EmissiveColor")).GetLuminance() > 0.5f);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
