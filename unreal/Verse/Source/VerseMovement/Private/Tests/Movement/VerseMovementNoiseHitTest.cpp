#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "Fixture/VerseMovementCourse.h"
#include "Noise/VerseAudibilityTable.h"
#include "PhysicsEngine/BodyInstance.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "PhysicsEngine/SkeletalBodySetup.h"
#include "Tests/Movement/VerseMovementTestWorld.h"
#include "VerseCharacter.h"
#include "VerseCharacterMovement.h"
#include "VerseCollision.h"
#include "VerseGameplayTags.h"
#include "VerseHitZones.h"
#include "UObject/StrongObjectPtr.h"

namespace
{
	constexpr EAutomationTestFlags NoiseTestFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;
	using namespace VerseMovementCourse;

	/** Collects the hub's noise events of one pawn session. */
	struct FNoiseLog
	{
		TArray<FVerseNoiseEvent> Events;
		FDelegateHandle Handle;
		UVerseEventHub* Hub = nullptr;

		explicit FNoiseLog(UWorld* World) : Hub(UVerseEventHub::Get(World))
		{
			if (Hub)
			{
				Handle = Hub->OnNoise.AddLambda([this](const FVerseNoiseEvent& Event) { Events.Add(Event); });
			}
		}
		~FNoiseLog()
		{
			if (Hub)
			{
				Hub->OnNoise.Remove(Handle);
			}
		}
		int32 Count(const FGameplayTag& Tag) const
		{
			return Events.FilterByPredicate([&Tag](const FVerseNoiseEvent& Event) { return Event.Noise == Tag; }).Num();
		}
	};

	void Run(FVerseMovementTestWorld& W, AVerseCharacter& Pawn, uint32 Buttons, const FVector2f& Move, float Seconds, float TurnDegPerSec = 0.f)
	{
		uint32 Prev = 0;
		const int32 Ticks = FMath::RoundToInt(Seconds / FVerseMovementTestWorld::Dt);
		for (int32 Tick = 0; Tick < Ticks; ++Tick)
		{
			W.Drive(Pawn, VerseTestFrame(Move, Buttons, Prev, FVector2f(0.f, TurnDegPerSec * FVerseMovementTestWorld::Dt)));
			Prev = Buttons;
			W.Tick();
		}
	}
}

// A1.8: footstep tags per stance match DA_Audibility's ranges (walk 4 m, run 10 m, sprint 20 m);
// crouch walk and prone crawl emit nothing over 60 s; slide, land and mantle raise their tags.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementNoiseTest, "Verse.Movement.Noise", NoiseTestFlags)
bool FVerseMovementNoiseTest::RunTest(const FString& Parameters)
{
	using namespace VerseTags;
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	if (!TestNotNull(TEXT("event hub"), UVerseEventHub::Get(W.GetWorld()))) return false;
	const TStrongObjectPtr<UVerseAudibilityTable> Audibility(NewObject<UVerseAudibilityTable>());
	const FVector Open(-2400.f, OpenFloorY, 0.f);
	AVerseCharacter* Pawn = W.SpawnPawn(Open, 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	const FVerseMovementTuningValues& T = Pawn->GetVerseMovement()->Tuning();

	struct FCase { const TCHAR* Name; uint32 Buttons; FVector2f Move; FGameplayTag Tag; float RangeM; float Stride; };
	const FCase Cases[] = {
		{TEXT("walk"), 0u, FVector2f(0.5f, 0.f), Noise_Footstep_Walk, 4.f, T.WalkStride},
		{TEXT("run"), 0u, FVector2f(1.f, 0.f), Noise_Footstep_Run, 10.f, T.RunStride},
		{TEXT("sprint"), uint32(EVerseInputButton::Sprint), FVector2f(1.f, 0.f), Noise_Footstep_Sprint, 20.f, T.SprintStride},
	};
	for (const FCase& Case : Cases)
	{
		W.Place(*Pawn, Open, 0.f);
		Run(W, *Pawn, 0u, FVector2f::ZeroVector, 0.5f);
		FNoiseLog Log(W.GetWorld());
		const FVector Start = Pawn->GetActorLocation();
		Run(W, *Pawn, Case.Buttons, Case.Move, 5.f);
		const float Travel = FVector::Dist2D(Start, Pawn->GetActorLocation());
		const int32 Expected = FMath::FloorToInt(Travel / (Case.Stride * 100.f));
		const int32 Own = Log.Count(Case.Tag);
		AddInfo(FString::Printf(TEXT("%s: %d events (%d of the stance tag) over %.1f m"), Case.Name, Log.Events.Num(), Own, Travel / 100.f));
		TestTrue(FString::Printf(TEXT("%s raises its footstep tag"), Case.Name), Own >= Expected - 2 && Own <= Expected + 2);
		TestTrue(FString::Printf(TEXT("%s raises only its tag (after the first stride)"), Case.Name), Log.Events.Num() - Own <= 2);
		TestEqual(FString::Printf(TEXT("%s audible range matches DA_Audibility"), Case.Name), Audibility->GetAudibleRangeM(Case.Tag, 1.f), Case.RangeM);
		if (Log.Events.Num())
		{
			TestEqual(TEXT("noise at the feet"), float(Log.Events.Last().Location.Z), float(FVerseMovementTestWorld::Feet(*Pawn).Z), 5.f);
		}
	}

	for (const uint32 Quiet : {uint32(EVerseInputButton::Crouch), uint32(EVerseInputButton::Prone)})
	{
		W.Place(*Pawn, Open + FVector(2400.f, 0.f, 0.f), 0.f);
		Run(W, *Pawn, Quiet, FVector2f::ZeroVector, 1.f);
		FNoiseLog Log(W.GetWorld());
		const FVector Start = Pawn->GetActorLocation();
		float Travel = 0.f;
		FVector Last = Start;
		const int32 Ticks = FMath::RoundToInt(60.f / FVerseMovementTestWorld::Dt);
		uint32 Prev = Quiet;
		for (int32 Tick = 0; Tick < Ticks; ++Tick)
		{
			W.Drive(*Pawn, VerseTestFrame(FVector2f(1.f, 0.f), Quiet, Prev, FVector2f(0.f, 30.f * FVerseMovementTestWorld::Dt)));
			W.Tick();
			Travel += FVector::Dist2D(Last, Pawn->GetActorLocation());
			Last = Pawn->GetActorLocation();
		}
		const TCHAR* Name = Quiet == uint32(EVerseInputButton::Crouch) ? TEXT("crouch walk") : TEXT("prone crawl");
		AddInfo(FString::Printf(TEXT("%s: %d events over %.1f m in 60 s"), Name, Log.Events.Num(), Travel / 100.f));
		TestTrue(FString::Printf(TEXT("%s really moved"), Name), Travel > 2000.f);
		TestEqual(FString::Printf(TEXT("%s emits no noise in 60 s"), Name), Log.Events.Num(), 0);
		Run(W, *Pawn, 0u, FVector2f::ZeroVector, 1.2f);
	}

	{
		// Land from the 4 m drop.
		W.Place(*Pawn, FVector(1300.f, DropY, DropHeight), 0.f);
		Run(W, *Pawn, 0u, FVector2f::ZeroVector, 0.3f);
		FNoiseLog Log(W.GetWorld());
		Run(W, *Pawn, 0u, FVector2f(1.f, 0.f), 2.f);
		TestEqual(TEXT("one land noise from the 4 m drop"), Log.Count(Noise_Move_Land), 1);
		TestEqual(TEXT("land range 12 m"), Audibility->GetAudibleRangeM(Noise_Move_Land, 1.f), 12.f);
	}
	{
		// Slide.
		W.Place(*Pawn, Open, 0.f);
		Run(W, *Pawn, 0u, FVector2f::ZeroVector, 0.5f);
		Run(W, *Pawn, uint32(EVerseInputButton::Sprint), FVector2f(1.f, 0.f), 1.5f);
		FNoiseLog Log(W.GetWorld());
		uint32 Prev = uint32(EVerseInputButton::Sprint);
		const uint32 Buttons = uint32(EVerseInputButton::Sprint) | uint32(EVerseInputButton::Crouch);
		for (int32 Tick = 0; Tick < 30; ++Tick)
		{
			W.Drive(*Pawn, VerseTestFrame(FVector2f(1.f, 0.f), Buttons, Prev));
			Prev = Buttons;
			W.Tick();
		}
		TestEqual(TEXT("one slide noise"), Log.Count(Noise_Move_Slide), 1);
		Run(W, *Pawn, 0u, FVector2f::ZeroVector, 1.5f);
	}
	{
		// Mantle the 1.0 m ledge.
		W.Place(*Pawn, FVector(LedgeFaceX - 80.f, LedgeLaneY(1), 0.f), 0.f);
		Run(W, *Pawn, 0u, FVector2f::ZeroVector, 0.3f);
		FNoiseLog Log(W.GetWorld());
		Run(W, *Pawn, uint32(EVerseInputButton::Jump), FVector2f(1.f, 0.f), 1.f);
		TestEqual(TEXT("one mantle noise"), Log.Count(Noise_Move_Mantle), 1);
		TestEqual(TEXT("mantle range 12 m"), Audibility->GetAudibleRangeM(Noise_Move_Mantle, 1.f), 12.f);
	}
	return true;
}

// WP01.11: bone to hit zone table from the physics asset; lean and prone move the hit bodies.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementHitZonesTest, "Verse.Movement.HitZones", NoiseTestFlags)
bool FVerseMovementHitZonesTest::RunTest(const FString& Parameters)
{
	TestEqual(TEXT("Head"), int32(VerseHitZones::ZoneForBoneName(TEXT("Head"))), int32(EVerseHitZone::Head));
	TestEqual(TEXT("Neck"), int32(VerseHitZones::ZoneForBoneName(TEXT("Neck"))), int32(EVerseHitZone::Neck));
	TestEqual(TEXT("Spine_03"), int32(VerseHitZones::ZoneForBoneName(TEXT("Spine_03"))), int32(EVerseHitZone::UpperTorso));
	TestEqual(TEXT("Spine_01"), int32(VerseHitZones::ZoneForBoneName(TEXT("Spine_01"))), int32(EVerseHitZone::LowerTorso));
	TestEqual(TEXT("Hips"), int32(VerseHitZones::ZoneForBoneName(TEXT("Hips"))), int32(EVerseHitZone::LowerTorso));
	TestEqual(TEXT("LowerArm_L"), int32(VerseHitZones::ZoneForBoneName(TEXT("LowerArm_L"))), int32(EVerseHitZone::Arm));
	TestEqual(TEXT("Calf_R"), int32(VerseHitZones::ZoneForBoneName(TEXT("Calf_R"))), int32(EVerseHitZone::Leg));
	TestEqual(TEXT("Root has no zone"), int32(VerseHitZones::ZoneForBoneName(TEXT("Root"))), int32(EVerseHitZone::None));

	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	const FVector Open(0.f, OpenFloorY, 0.f);
	AVerseCharacter* Pawn = W.SpawnPawn(Open, 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	USkeletalMeshComponent* Mesh = Pawn->GetMesh();
	if (!TestNotNull(TEXT("SK_Test_Human on the pawn"), Mesh->GetSkeletalMeshAsset()) || !TestNotNull(TEXT("physics asset"), Mesh->GetPhysicsAsset()))
	{
		return false;
	}
	TMap<FName, EVerseHitZone> Table;
	FString Error;
	TestTrue(FString::Printf(TEXT("every physics body has a zone (%s)"), *Error), VerseHitZones::BuildTable(Mesh->GetPhysicsAsset(), Mesh->GetSkeletalMeshAsset(), Table, Error));
	TSet<EVerseHitZone> Zones;
	for (const TPair<FName, EVerseHitZone>& Entry : Table)
	{
		Zones.Add(Entry.Value);
	}
	for (const EVerseHitZone Zone : {EVerseHitZone::Head, EVerseHitZone::Neck, EVerseHitZone::UpperTorso, EVerseHitZone::LowerTorso, EVerseHitZone::Arm, EVerseHitZone::Leg})
	{
		TestTrue(FString::Printf(TEXT("table covers zone %d"), int32(Zone)), Zones.Contains(Zone));
	}

	auto BodyLocation = [Mesh](FName Bone)
	{
		const FBodyInstance* Body = Mesh->GetBodyInstance(Bone);
		return Body ? Body->GetUnrealWorldTransform().GetLocation() : Mesh->GetBoneLocation(Bone);
	};
	// Scan: one trace from the front every 5 cm of height; the zone hit first at each height.
	auto Scan = [&W, Pawn](const FVector& Through, TMap<EVerseHitZone, FVector2f>& OutRange, FString& OutProfile)
	{
		OutRange.Reset();
		OutProfile.Reset();
		const float Floor = FVerseMovementTestWorld::Feet(*Pawn).Z;
		const FVector Forward = Pawn->GetActorForwardVector();
		for (float Height = 2.5f; Height < 200.f; Height += 5.f)
		{
			const FVector Point(Through.X, Through.Y, Floor + Height);
			FHitResult Hit;
			const bool bHit = W.GetWorld()->LineTraceSingleByChannel(Hit, Point + Forward * 300.f, Point - Forward * 300.f,
				VerseCollision::HitBody, FCollisionQueryParams(SCENE_QUERY_STAT(VerseHitZoneScan), false));
			const EVerseHitZone Zone = bHit ? VerseHitZones::ZoneForHit(Hit) : EVerseHitZone::None;
			OutProfile += FString::Printf(TEXT("%d"), int32(Zone));
			if (bHit && FMath::IsNearlyEqual(FMath::Fmod(Height, 40.f), 2.5f))
			{
				OutProfile += FString::Printf(TEXT("[%s %s z%.0f]"), *Hit.BoneName.ToString(), *GetNameSafe(Hit.GetComponent()), Hit.ImpactPoint.Z - Floor);
			}
			if (Zone != EVerseHitZone::None)
			{
				FVector2f& Range = OutRange.FindOrAdd(Zone, FVector2f(Height, Height));
				Range.X = FMath::Min(Range.X, Height);
				Range.Y = FMath::Max(Range.Y, Height);
			}
		}
	};
	Run(W, *Pawn, 0u, FVector2f::ZeroVector, 0.5f);
	for (const USkeletalBodySetup* Setup : Mesh->GetPhysicsAsset()->SkeletalBodySetups)
	{
		const FBodyInstance* Instance = Setup ? Mesh->GetBodyInstance(Setup->BoneName) : nullptr;
		const FKSphylElem* Sphyl = Setup && Setup->AggGeom.SphylElems.Num() ? &Setup->AggGeom.SphylElems[0] : nullptr;
		AddInfo(FString::Printf(TEXT("body %s: at %s, capsule r %.1f len %.1f, bounds %s"), Setup ? *Setup->BoneName.ToString() : TEXT("?"),
			Instance ? *(Instance->GetUnrealWorldTransform().GetLocation() - Pawn->GetActorLocation()).ToCompactString() : TEXT("-"),
			Sphyl ? Sphyl->Radius : -1.f, Sphyl ? Sphyl->Length : -1.f, Instance ? *Instance->GetBodyBounds().GetExtent().ToCompactString() : TEXT("-")));
	}
	const FVector Head = BodyLocation(TEXT("Head"));
	// G0.9's PHYS_Test_Human currently carries 100x scaled bodies (bone scale from the import), so
	// one body covers the whole pawn. Trace checks need sane bodies; body motion checks do not.
	const FBodyInstance* HeadBody = Mesh->GetBodyInstance(TEXT("Head"));
	const bool bTraceable = HeadBody && HeadBody->GetBodyBounds().GetExtent().Z < 50.f;
	if (!bTraceable)
	{
		AddWarning(TEXT("PHYS_Test_Human hit bodies are oversized (G0.9 import scale); zone-by-trace checks skipped until the rig is fixed"));
	}
	const bool bHasCamera = Mesh->GetBoneIndex(TEXT("Camera")) != INDEX_NONE;
	const FVector CameraBone = bHasCamera ? Mesh->GetBoneLocation(TEXT("Camera")) : FVector::ZeroVector;
	TMap<EVerseHitZone, FVector2f> Standing;
	FString Profile;
	Scan(Pawn->GetActorLocation(), Standing, Profile);
	AddInfo(FString::Printf(TEXT("standing zone profile, 5 cm steps from the floor: %s"), *Profile));
	for (const EVerseHitZone Zone : {EVerseHitZone::Head, EVerseHitZone::UpperTorso, EVerseHitZone::LowerTorso, EVerseHitZone::Leg})
	{
		if (bTraceable) TestTrue(FString::Printf(TEXT("standing: a front trace hits zone %d"), int32(Zone)), Standing.Contains(Zone));
	}
	if (bTraceable && Standing.Contains(EVerseHitZone::Head) && Standing.Contains(EVerseHitZone::Leg) && Standing.Contains(EVerseHitZone::LowerTorso))
	{
		TestTrue(TEXT("head zone sits above the lower torso"), Standing[EVerseHitZone::Head].Y > Standing[EVerseHitZone::LowerTorso].Y);
		TestTrue(TEXT("lower torso sits above the legs"), Standing[EVerseHitZone::LowerTorso].X > Standing[EVerseHitZone::Leg].X);
		TestTrue(TEXT("standing head above 1.4 m"), Standing[EVerseHitZone::Head].Y > 140.f);
	}

	Run(W, *Pawn, uint32(EVerseInputButton::LeanRight), FVector2f::ZeroVector, 0.5f);
	const FVector LeanHead = BodyLocation(TEXT("Head"));
	const float Moved = (LeanHead - Head) | Pawn->GetActorRightVector();
	AddInfo(FString::Printf(TEXT("lean right moved the head body %.1f cm to the right"), Moved));
	TestTrue(TEXT("lean moves the head body at least 25 cm"), Moved >= 25.f);
	TMap<EVerseHitZone, FVector2f> LeanSide;
	Scan(LeanHead, LeanSide, Profile);
	AddInfo(FString::Printf(TEXT("leaning: profile through the leaned head: %s"), *Profile));
	if (bTraceable)
	{
		TestTrue(TEXT("leaning: the head is hit where the leaned head is"), LeanSide.Contains(EVerseHitZone::Head));
	}
	if (bHasCamera)
	{
		TestTrue(TEXT("the Camera bone (bot eye) moves with the lean"), ((Mesh->GetBoneLocation(TEXT("Camera")) - CameraBone) | Pawn->GetActorRightVector()) >= 25.f);
	}
	Run(W, *Pawn, 0u, FVector2f::ZeroVector, 0.5f);

	Run(W, *Pawn, uint32(EVerseInputButton::Prone), FVector2f::ZeroVector, 1.5f);
	const FVector ProneHead = BodyLocation(TEXT("Head"));
	const float Feet = FVerseMovementTestWorld::Feet(*Pawn).Z;
	AddInfo(FString::Printf(TEXT("prone head body %.1f cm above the floor"), ProneHead.Z - Feet));
	TestTrue(TEXT("prone lays the head body below 50 cm"), ProneHead.Z - Feet < 50.f);
	TestTrue(TEXT("prone moves the head body forward"), ((ProneHead - Pawn->GetActorLocation()) | Pawn->GetActorForwardVector()) > 10.f);
	TMap<EVerseHitZone, FVector2f> Prone;
	Scan(Pawn->GetActorLocation(), Prone, Profile);
	AddInfo(FString::Printf(TEXT("prone profile through the capsule: %s"), *Profile));
	for (const TPair<EVerseHitZone, FVector2f>& Entry : Prone)
	{
		if (bTraceable) TestTrue(FString::Printf(TEXT("prone: zone %d stays below 60 cm"), int32(Entry.Key)), Entry.Value.Y < 60.f);
	}
	// Legs trail behind the capsule: a side trace there hits a leg (mesh body or prone body box).
	const FVector Behind = Pawn->GetActorLocation() - Pawn->GetActorForwardVector() * 110.f;
	bool bLeg = false;
	for (float Height = 2.5f; Height < 45.f && !bLeg; Height += 5.f)
	{
		const FVector Point(Behind.X, Behind.Y, Feet + Height);
		FHitResult Hit;
		const FVector Side = Pawn->GetActorRightVector() * 300.f;
		bLeg = W.GetWorld()->LineTraceSingleByChannel(Hit, Point + Side, Point - Side, VerseCollision::HitBody,
			FCollisionQueryParams(SCENE_QUERY_STAT(VerseProneLegs), false)) && VerseHitZones::ZoneForHit(Hit) == EVerseHitZone::Leg;
	}
	if (bTraceable)
	{
		TestTrue(TEXT("the prone legs behind the capsule can be hit"), bLeg);
	}
	// The prone body box is ours: it lies behind the capsule while prone.
	const FBox ProneBox = Pawn->GetProneBody()->Bounds.GetBox();
	TestTrue(TEXT("prone body box is active while prone"), Pawn->GetProneBody()->GetCollisionEnabled() == ECollisionEnabled::QueryOnly);
	TestTrue(TEXT("prone body box lies behind the capsule, under 0.45 m"), ProneBox.IsInsideXY(Behind) && ProneBox.Max.Z - Feet < 45.f);
	// Body motion: every body sits below 60 cm while prone.
	for (const USkeletalBodySetup* Setup : Mesh->GetPhysicsAsset()->SkeletalBodySetups)
	{
		const FVector At = BodyLocation(Setup->BoneName);
		TestTrue(FString::Printf(TEXT("prone: body %s below 60 cm"), *Setup->BoneName.ToString()), At.Z - Feet < 60.f);
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
