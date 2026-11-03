#include "CoreMinimal.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Destruction/VersePenetrationTable.h"
#include "Engine/Level.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Materials/Material.h"
#include "Materials/MaterialInterface.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Penetration/VersePenetrationMath.h"
#include "Penetration/VersePenetrationPhysicalMaterial.h"
#include "Penetration/VersePenetrationTableImport.h"
#include "Tests/Penetration/Fakes/VerseWP03Fakes.h"

namespace
{
	constexpr EAutomationTestFlags WP03Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	FString TagValue(const AActor& Actor, const FString& Prefix)
	{
		for (const FName& Tag : Actor.Tags)
		{
			const FString Text = Tag.ToString();
			if (Text.StartsWith(Prefix))
			{
				return Text.RightChop(Prefix.Len());
			}
		}
		return FString();
	}
}

// The committed WP03 content (Content/Verse/Test/WP03/Python/wp03_content.py): the cooked
// table matches the JSON, the world physical materials resolve to their rows, the hole
// materials carry their parameters, and the fixture map holds every material at 0.5x, 1x and
// 3x reference thickness plus the hole angle rig and a container row.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePenetrationAssetsTest, "Verse.Destruction.Penetration.Assets", WP03Flags)

bool FVersePenetrationAssetsTest::RunTest(const FString& Parameters)
{
	// WP03.2: DA_PenetrationTable is what the game loads; it must equal the JSON.
	const UVersePenetrationTable* Asset = Cast<UVersePenetrationTable>(VersePenetrationImport::TableAssetPath().TryLoad());
	if (TestNotNull(TEXT("DA_PenetrationTable exists"), Asset))
	{
		FString Text;
		TArray<FVersePenetrationRow> JsonRows;
		TArray<FString> Errors;
		TestTrue(TEXT("penetration.json parses"), FFileHelper::LoadFileToString(Text, *VersePenetrationImport::DefaultTablePath())
			&& VersePenetrationImport::ParseTableJson(Text, JsonRows, Errors));
		const TArray<FString> Diffs = VersePenetrationImport::DiffRows(Asset->Rows, JsonRows);
		TestTrue(FString::Printf(TEXT("DA_PenetrationTable equals penetration.json (%s)"), *FString::Join(Diffs, TEXT("; "))), Diffs.IsEmpty());
		TestTrue(TEXT("the runtime loads the asset"), VersePenetrationImport::LoadRuntimeTable(GetTransientPackage()) == Asset);
	}

	// WP03.7: the three world surfaces by their shipped physical materials.
	const TPair<EVerseWorldSurface, EVersePenetrationMaterial> Surfaces[] = {
		{EVerseWorldSurface::HallFloor, EVersePenetrationMaterial::Concrete},
		{EVerseWorldSurface::StructuralWall, EVersePenetrationMaterial::Concrete},
		{EVerseWorldSurface::StructuralBeam, EVersePenetrationMaterial::ArmorSteel},
	};
	for (const TPair<EVerseWorldSurface, EVersePenetrationMaterial>& Surface : Surfaces)
	{
		const FString Name = VersePenetration::PhysicalMaterialName(Surface.Key);
		const FSoftObjectPath Path(FString::Printf(TEXT("/Game/Verse/Destruction/_Holes/PhysicalMaterials/%s.%s"), *Name, *Name));
		const UObject* PhysMat = Path.TryLoad();
		if (TestNotNull(*FString::Printf(TEXT("%s exists"), *Name), PhysMat))
		{
			TestTrue(*FString::Printf(TEXT("%s resolves to its row"), *Name), VersePenetration::ResolveWorldMaterial(PhysMat) == Surface.Value);
		}
	}

	// WP03.6: the rim decal and the test surface master carry the parameters the renderer sets.
	const UMaterialInterface* Rim = LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/Verse/Destruction/_Holes/M_HoleRim_Decal.M_HoleRim_Decal"));
	if (TestNotNull(TEXT("M_HoleRim_Decal exists"), Rim))
	{
		float Glow = -1.f;
		FLinearColor Color;
		TestTrue(TEXT("rim decal has RimGlow"), Rim->GetScalarParameterValue(FHashedMaterialParameterInfo(TEXT("RimGlow")), Glow));
		TestTrue(TEXT("rim decal has RimGlowColor"), Rim->GetVectorParameterValue(FHashedMaterialParameterInfo(TEXT("RimGlowColor")), Color));
		TestTrue(TEXT("rim decal is a deferred decal"), Rim->GetMaterial()->MaterialDomain == EMaterialDomain::MD_DeferredDecal);
	}
	const UMaterialInterface* Surface = LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/Verse/Test/WP03/M_WP03_HoleSurface.M_WP03_HoleSurface"));
	if (TestNotNull(TEXT("M_WP03_HoleSurface exists"), Surface))
	{
		UTexture* Mask = nullptr;
		TestTrue(TEXT("test surface has HoleMask"), Surface->GetTextureParameterValue(FHashedMaterialParameterInfo(TEXT("HoleMask")), Mask));
	}
	const UStaticMesh* Box = LoadObject<UStaticMesh>(nullptr, TEXT("/Game/Verse/Test/WP03/SM_WP03_Box.SM_WP03_Box"));
	if (TestNotNull(TEXT("SM_WP03_Box exists"), Box))
	{
		TestTrue(TEXT("SM_WP03_Box is a 100 cm cube"), Box->GetBoundingBox().GetSize().Equals(FVector(100.0), 0.01));
	}

	// WP03.8: the fixture map.
	const UWorld* Map = LoadObject<UWorld>(nullptr, TEXT("/Game/Verse/Test/WP03/LV_WP03_Penetration.LV_WP03_Penetration"));
	if (!TestNotNull(TEXT("LV_WP03_Penetration exists"), Map) || !Map->PersistentLevel)
	{
		return false;
	}
	const UVersePenetrationTable* Contract = GetDefault<UVersePenetrationTable>();
	TSet<FString> Found;
	int32 Rig = 0;
	int32 Row = 0;
	for (const AActor* Actor : Map->PersistentLevel->Actors)
	{
		if (!Actor)
		{
			continue;
		}
		const FString Wire = TagValue(*Actor, TEXT("verse.wp03.wire:"));
		const FString Thickness = TagValue(*Actor, TEXT("verse.wp03.thickness_cm:"));
		if (Wire.IsEmpty() || Thickness.IsEmpty())
		{
			continue;
		}
		const FString Label = Actor->GetName();
		const FString Role = TagValue(*Actor, TEXT("verse.wp03.role:"));
		Rig += Role == TEXT("hole_rig") ? 1 : 0;
		Row += Role == TEXT("container_row") ? 1 : 0;
		const float ThicknessCm = FCString::Atof(*Thickness);
		TestTrue(*FString::Printf(TEXT("%s: scale gives the tagged thickness"), *Label),
			VerseWP03Test::Near(Actor->GetActorScale3D().X * 100.0, ThicknessCm, 1e-3));
		const FVersePenetrationRow* RowData = Contract->FindRow(uint8(FCString::Atoi(*Wire)));
		if (RowData)
		{
			for (const float Factor : {0.5f, 1.f, 3.f})
			{
				if (VerseWP03Test::Near(ThicknessCm, RowData->RefThicknessCm * Factor, 1e-3))
				{
					Found.Add(FString::Printf(TEXT("%s@%g"), *Wire, Factor));
				}
			}
		}
	}
	for (int32 Wire = 0; Wire < VersePenetration::FrozenMaterialIds().Num(); ++Wire)
	{
		for (const float Factor : {0.5f, 1.f, 3.f})
		{
			TestTrue(*FString::Printf(TEXT("fixture map has material %d at %gx"), Wire, Factor), Found.Contains(FString::Printf(TEXT("%d@%g"), Wire, Factor)));
		}
	}
	TestEqual(TEXT("hole angle rig: sheet and panel"), Rig, 2);
	TestEqual(TEXT("container row: three walls"), Row, 3);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
