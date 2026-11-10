#include "Misc/AutomationTest.h"
#include "VerseViewmodelComponent.h"

#if WITH_DEV_AUTOMATION_TESTS

/**
 * The near plane must never cut the held weapon. The first-person scale draws the viewmodel at
 * ViewmodelScale of its distance, so a part closer than NearPlane / ViewmodelScale is clipped.
 * With the engine default of 10 cm that was 40 cm: the whole sight vanished while aiming and only
 * the barrel tip stayed on screen.
 */
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseViewmodelFramingTest, "Verse.Primary.ViewmodelFraming",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseViewmodelFramingTest::RunTest(const FString&)
{
	const double ClipCm = double(GNearClippingPlane) / double(UVerseViewmodelComponent::ViewmodelScale);
	TestTrue(FString::Printf(TEXT("near plane %.2f cm keeps the viewmodel whole from %.1f cm"), GNearClippingPlane, ClipCm), ClipCm <= 6.0);
	for (const TCHAR* Id : {TEXT("graveline"), TEXT("tallow"), TEXT("skitter"), TEXT("longsight"), TEXT("hookbill")})
	{
		const FVerseViewmodelPose Pose = UVerseViewmodelComponent::PoseFor(FName(Id));
		TestTrue(FString::Printf(TEXT("%s: sight in front of the near plane while aiming"), Id), Pose.SightDistance > ClipCm + 4.0);
		TestTrue(FString::Printf(TEXT("%s: grip in front of the near plane at the hip"), Id), Pose.HipOffset.X > ClipCm + 10.0);
		// Big and readable at the hip, but right of and below the crosshair.
		TestTrue(FString::Printf(TEXT("%s: held close enough to read"), Id), Pose.HipOffset.X <= 30.0);
		TestTrue(FString::Printf(TEXT("%s: right of the crosshair"), Id), Pose.HipOffset.Y > 4.0);
		TestTrue(FString::Printf(TEXT("%s: below the crosshair"), Id), Pose.HipOffset.Z < -8.0);
	}
	// The Graveline's reflex frame (4 cm across) must leave the target clear: at most a sixth
	// of the viewmodel's horizontal field of view.
	const FVerseViewmodelPose Rifle = UVerseViewmodelComponent::PoseFor(FName(TEXT("graveline")));
	const double FrameDeg = 2.0 * FMath::RadiansToDegrees(FMath::Atan(2.0 / Rifle.SightDistance));
	TestTrue(FString::Printf(TEXT("graveline: reflex frame spans %.1f of %.0f degrees"), FrameDeg, UVerseViewmodelComponent::ViewmodelFov),
		FrameDeg <= UVerseViewmodelComponent::ViewmodelFov / 6.0);
	return true;
}

#endif
