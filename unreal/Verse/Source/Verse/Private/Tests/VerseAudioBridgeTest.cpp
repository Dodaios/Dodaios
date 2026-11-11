#include "Audio/VerseAudioTypes.h"
#include "Misc/AutomationTest.h"
#include "PhysicalMaterials/PhysicalMaterial.h"
#include "UObject/Package.h"
#include "VerseAudioBridge.h"

#if WITH_DEV_AUTOMATION_TESTS

// The footstep surface of a floor: deck plating and unknown floors are metal, the hall floor and
// structural walls (PM_Verse_*) concrete, catwalk gratings grating.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePrimaryFootstepSurfaceTest, "Verse.Primary.Audio.FootstepSurface",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FVersePrimaryFootstepSurfaceTest::RunTest(const FString&)
{
	auto Material = [](const TCHAR* Name) { return NewObject<UPhysicalMaterial>(GetTransientPackage(), MakeUniqueObjectName(GetTransientPackage(), UPhysicalMaterial::StaticClass(), Name)); };
	TestEqual(TEXT("no material: metal plating"), UVerseAudioBridge::SurfaceOf(nullptr), EVerseFootSurface::Metal);
	TestEqual(TEXT("PM_Verse_HallFloor: concrete"), UVerseAudioBridge::SurfaceOf(Material(TEXT("PM_Verse_HallFloor"))), EVerseFootSurface::Concrete);
	TestEqual(TEXT("PM_Verse_StructuralBeam: metal"), UVerseAudioBridge::SurfaceOf(Material(TEXT("PM_Verse_StructuralBeam"))), EVerseFootSurface::Metal);
	TestEqual(TEXT("a catwalk grating"), UVerseAudioBridge::SurfaceOf(Material(TEXT("PM_CatwalkGrating"))), EVerseFootSurface::Grating);
	TestEqual(TEXT("deck plating"), UVerseAudioBridge::SurfaceOf(Material(TEXT("PM_DeckPlate"))), EVerseFootSurface::Metal);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
