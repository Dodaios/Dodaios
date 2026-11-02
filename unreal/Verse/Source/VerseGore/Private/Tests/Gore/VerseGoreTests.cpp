#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Camera/PlayerCameraManager.h"
#include "Components/DecalComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "GameFramework/PlayerController.h"
#include "Gore/VerseGoreActor.h"
#include "HAL/FileManager.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/FileHelper.h"
#include "Tests/Gore/VerseGoreTestWorld.h"
#include "VerseCollision.h"
#include "VerseRng.h"

using namespace VerseGoreTest;

namespace VerseGoreTestPrivate
{
	FVerseHitEvent Hit(EVerseHitZone Zone, const FVector& Feet, const FVector& Shooter, int32 Victim, uint16 Shot, float Damage = 30.f, bool bKill = false)
	{
		return FVerseGoreSyntheticStream::MakeHit(Zone, Feet, Shooter, 1, Victim, Damage, Shot, 0.f, bKill);
	}

	TArray<FVector> DropletPositions(const UVerseGoreSubsystem* Gore)
	{
		TArray<FVector> Result;
		const AVerseGoreActor* Actor = Gore->GetGoreActor();
		if (!Actor)
		{
			return Result;
		}
		for (int32 Index = 0; Index < Actor->Droplets->GetInstanceCount(); ++Index)
		{
			FTransform Transform;
			Actor->Droplets->GetInstanceTransform(Index, Transform, true);
			Result.Add(Transform.GetLocation());
		}
		return Result;
	}

	UMaterialInstanceDynamic* BodyMid(USkeletalMeshComponent* Mesh)
	{
		for (int32 Slot = 0; Slot < Mesh->GetNumMaterials(); ++Slot)
		{
			if (UMaterialInstanceDynamic* Mid = Cast<UMaterialInstanceDynamic>(Mesh->GetMaterial(Slot)))
			{
				return Mid;
			}
		}
		return nullptr;
	}
}

using namespace VerseGoreTestPrivate;

// WP05.1: the listener skips a process without a viewport, and binds when forced.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreListenerTest, "Verse.Gore.Listener.SkipsWithoutViewport", VERSE_GORE_TEST_FLAGS)
bool FVerseGoreListenerTest::RunTest(const FString&)
{
	FWorld W(false);
	if (!TestTrue(TEXT("world, hub and gore subsystem exist"), W.IsValid()))
	{
		return false;
	}
	const bool bCanRender = UVerseGoreSubsystem::ProcessCanShowGore();
	TestEqual(TEXT("active only where the process can render"), W.Gore->IsActive(), bCanRender);
	W.Hub->OnHit.Broadcast(Hit(EVerseHitZone::UpperTorso, FVector::ZeroVector, FVector(-500, 0, 150), 2, 1));
	TestEqual(TEXT("hits handled follow the active flag"), W.Gore->GetBudget().HitsHandled, bCanRender ? 1 : 0);
	if (!bCanRender)
	{
		TestNull(TEXT("no gore actor without a viewport"), W.Gore->GetGoreActor());
	}

	W.Gore->SetForceActive(true);
	TestTrue(TEXT("forced on"), W.Gore->IsActive());
	W.Hub->OnHit.Broadcast(Hit(EVerseHitZone::UpperTorso, FVector::ZeroVector, FVector(-500, 0, 150), 2, 2));
	TestTrue(TEXT("forced gore handles hub hits"), W.Gore->GetBudget().HitsHandled >= 1);
	TestNotNull(TEXT("gore actor spawned on demand"), W.Gore->GetGoreActor());
	if (!bCanRender)
	{
		W.Gore->SetForceActive(false);
		TestFalse(TEXT("unforced again"), W.Gore->IsActive());
		TestEqual(TEXT("going inactive purges droplets"), W.Gore->GetBudget().Droplets, 0);
	}
	return true;
}

// WP05.1: synthetic streams are deterministic and shaped as the contract says.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreSyntheticTest, "Verse.Gore.Synthetic.Streams", VERSE_GORE_TEST_FLAGS)
bool FVerseGoreSyntheticTest::RunTest(const FString&)
{
	FVerseGoreSyntheticParams Params;
	Params.Kind = EVerseGoreSyntheticKind::Hits;
	Params.Seed = 7;
	const TArray<FVerseGoreSyntheticEvent> A = FVerseGoreSyntheticStream::Build(Params);
	const TArray<FVerseGoreSyntheticEvent> B = FVerseGoreSyntheticStream::Build(Params);
	TestEqual(TEXT("same seed, same length"), A.Num(), B.Num());
	bool bSame = A.Num() == B.Num();
	for (int32 I = 0; bSame && I < A.Num(); ++I)
	{
		bSame = A[I].Hit.Zone == B[I].Hit.Zone && FVector(A[I].Hit.ImpactWorld).Equals(B[I].Hit.ImpactWorld, 0.0)
			&& FVector(A[I].Hit.Direction).Equals(B[I].Hit.Direction, 0.0) && A[I].Time == B[I].Time;
	}
	TestTrue(TEXT("same seed, same events"), bSame);
	Params.Seed = 8;
	const TArray<FVerseGoreSyntheticEvent> C = FVerseGoreSyntheticStream::Build(Params);
	bool bDiffer = false;
	for (int32 I = 0; I < FMath::Min(A.Num(), C.Num()); ++I)
	{
		bDiffer |= A[I].Hit.Zone != C[I].Hit.Zone || !FVector(A[I].Hit.Direction).Equals(C[I].Hit.Direction, 1e-6);
	}
	TestTrue(TEXT("another seed, other events"), bDiffer);
	for (const FVerseGoreSyntheticEvent& Event : A)
	{
		if (Event.Hit.Zone == EVerseHitZone::None || Event.Hit.Bone.IsNone() || Event.Hit.Damage <= 0.f)
		{
			AddError(TEXT("synthetic hit without zone, bone or damage"));
			break;
		}
	}

	Params.Kind = EVerseGoreSyntheticKind::Storm;
	Params.DurationSeconds = 60.0;
	TestEqual(TEXT("gore_storm is 30 hits/s for 60 s"), FVerseGoreSyntheticStream::Build(Params).Num(), 1800);

	Params.Kind = EVerseGoreSyntheticKind::Finisher;
	const TArray<FVerseGoreSyntheticEvent> F = FVerseGoreSyntheticStream::Build(Params);
	int32 Phases = 0, Deaths = 0;
	for (const FVerseGoreSyntheticEvent& Event : F)
	{
		if (Event.Type == FVerseGoreSyntheticEvent::EType::Finisher)
		{
			++Phases;
			if (Event.Finisher.Phase == EVerseFinisherPhase::Takedown)
			{
				TestEqual(TEXT("Takedown at 0.25 s"), Event.Time, 0.25);
			}
			if (Event.Finisher.Phase == EVerseFinisherPhase::Recover)
			{
				TestEqual(TEXT("Recover at 2.1 s"), Event.Time, 2.1);
			}
		}
		Deaths += Event.Type == FVerseGoreSyntheticEvent::EType::Death ? 1 : 0;
	}
	TestEqual(TEXT("finisher stream phases"), Phases, 5);
	TestEqual(TEXT("finisher stream death"), Deaths, 1);

	// Playback goes through the hub.
	FWorld W;
	int32 HubHits = 0;
	W.Hub->OnHit.AddLambda([&HubHits](const FVerseHitEvent&) { ++HubHits; });
	Params.Kind = EVerseGoreSyntheticKind::Hits;
	Params.DurationSeconds = 2.0;
	Params.RatePerSecond = 5.0;
	W.Gore->PlaySynthetic(Params);
	W.Advance(2.5);
	TestEqual(TEXT("played hits reach the hub"), HubHits, 10);
	TestEqual(TEXT("and gore"), W.Gore->GetBudget().HitsHandled, 10);
	TestFalse(TEXT("stream finished"), W.Gore->IsPlayingSynthetic());
	return true;
}

// WP05.2: bursts scale with zone and damage and fly along the bolt.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreBurstTest, "Verse.Gore.Burst.ZoneAndDirection", VERSE_GORE_TEST_FLAGS)
bool FVerseGoreBurstTest::RunTest(const FString&)
{
	FWorld W;
	const FVector Shooter(-800.0, 0.0, 150.0);
	W.Gore->HandleHit(Hit(EVerseHitZone::Head, FVector::ZeroVector, Shooter, 2, 1, 60.f));
	const int32 Head = W.Gore->GetBudget().DropletsSpawned;
	W.Gore->Purge();
	W.Gore->ResetBudget();
	W.Gore->HandleHit(Hit(EVerseHitZone::Leg, FVector::ZeroVector, Shooter, 2, 2, 22.f));
	const int32 Leg = W.Gore->GetBudget().DropletsSpawned;
	TestTrue(FString::Printf(TEXT("head burst (%d) heavier than leg burst (%d)"), Head, Leg), Head > Leg && Leg > 0);
	W.Gore->Purge();

	const FVerseHitEvent Torso = Hit(EVerseHitZone::UpperTorso, FVector::ZeroVector, Shooter, 2, 3, 30.f);
	W.Gore->HandleHit(Torso);
	W.Advance(0.1);
	const TArray<FVector> Positions = DropletPositions(W.Gore);
	TestTrue(TEXT("droplets drawn as instances"), Positions.Num() > 0);
	FVector Centroid = FVector::ZeroVector;
	for (const FVector& P : Positions)
	{
		Centroid += P;
	}
	Centroid /= FMath::Max(1, Positions.Num());
	const double Along = FVector::DotProduct((Centroid - FVector(Torso.ImpactWorld)).GetSafeNormal(), FVector(Torso.Direction));
	TestTrue(FString::Printf(TEXT("spray follows the bolt (dot %.2f)"), Along), Along > 0.3);
	W.Advance(1.0);
	TestEqual(TEXT("droplets die out"), W.Gore->GetBudget().Droplets, 0);
	return true;
}

// WP05.3: spatter lands on the wall behind the body and drips onto the floor.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreSpatterTest, "Verse.Gore.Spatter.WallAndFloor", VERSE_GORE_TEST_FLAGS)
bool FVerseGoreSpatterTest::RunTest(const FString&)
{
	FWorld W;
	W.AddRoom(150.0);
	W.Gore->HandleHit(Hit(EVerseHitZone::Head, FVector::ZeroVector, FVector(-800.0, 0.0, 168.0), 2, 1, 60.f));
	int32 OnWall = 0, OnFloor = 0;
	for (const UDecalComponent* Decal : W.Gore->GetSpatterDecals())
	{
		const FVector L = Decal->GetComponentLocation();
		if (FMath::IsNearlyEqual(L.X, 150.0, 2.0))
		{
			++OnWall;
			TestTrue(TEXT("wall decal projects into the wall"), Decal->GetForwardVector().X > 0.9);
		}
		else if (FMath::IsNearlyEqual(L.Z, 0.0, 2.0))
		{
			++OnFloor;
			TestTrue(TEXT("floor decal projects down"), Decal->GetForwardVector().Z < -0.9);
		}
	}
	TestTrue(FString::Printf(TEXT("spatter on the wall (%d)"), OnWall), OnWall >= 1);
	TestEqual(TEXT("one drip on the floor"), OnFloor, 1);

	// No wall in range: no wall spatter.
	FWorld Open;
	Open.AddBox(FVector(0.0, 0.0, -10.0), FVector(2000.0, 2000.0, 20.0));
	Open.Gore->HandleHit(Hit(EVerseHitZone::Head, FVector::ZeroVector, FVector(-800.0, 0.0, 168.0), 2, 1, 60.f));
	TestTrue(TEXT("open floor: only floor decals"), Open.Gore->GetSpatterDecals().Num() >= 1);
	for (const UDecalComponent* Decal : Open.Gore->GetSpatterDecals())
	{
		TestTrue(TEXT("every decal is on the floor"), FMath::IsNearlyEqual(Decal->GetComponentLocation().Z, 0.0, 2.0));
	}
	return true;
}

// WP05.3 / A5.4: the decal pool is capped and recycles oldest first.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreRecycleTest, "Verse.Gore.Spatter.Recycle", VERSE_GORE_TEST_FLAGS)
bool FVerseGoreRecycleTest::RunTest(const FString&)
{
	FWorld W;
	W.AddRoom(150.0);
	const int32 Cap = W.Gore->GetTuning().MaxSpatterDecals;
	TestEqual(TEXT("A5.4 cap"), Cap, 256);
	UDecalComponent* First = nullptr;
	uint16 Shot = 1;
	while (W.Gore->GetBudget().DecalsSpawned < Cap)
	{
		W.Gore->HandleHit(Hit(EVerseHitZone::UpperTorso, FVector::ZeroVector, FVector(-800.0, 0.0, 132.0), 2, Shot++));
		if (!First && W.Gore->GetSpatterDecals().Num() > 0)
		{
			First = W.Gore->GetSpatterDecals()[0];
		}
		if (Shot > 2000)
		{
			break;
		}
	}
	TestEqual(TEXT("ring filled to the cap"), W.Gore->GetBudget().SpatterDecals, Cap);
	W.Gore->HandleHit(Hit(EVerseHitZone::UpperTorso, FVector::ZeroVector, FVector(-800.0, 0.0, 132.0), 2, Shot++));
	TestEqual(TEXT("never above the cap"), W.Gore->GetBudget().SpatterDecals, Cap);
	TestTrue(TEXT("recycling counted"), W.Gore->GetBudget().DecalsRecycled > 0);
	const TArray<UDecalComponent*> Ordered = W.Gore->GetSpatterDecals();
	TestTrue(TEXT("the oldest decal was the first reused"), Ordered.Contains(First) && Ordered[0] != First);
	for (int32 I = 0; I < 2000; ++I)
	{
		W.Gore->HandleHit(Hit(EVerseHitZone::Head, FVector::ZeroVector, FVector(-800.0, 0.0, 168.0), 2, Shot++, 60.f));
	}
	TestEqual(TEXT("peak stays at the cap"), W.Gore->GetBudget().PeakSpatterDecals, Cap);
	return true;
}

// WP05.4: bone-space impacts become wound slots on the body material, 16 at most.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreWoundTest, "Verse.Gore.Wounds.MaskSlots", VERSE_GORE_TEST_FLAGS)
bool FVerseGoreWoundTest::RunTest(const FString&)
{
	FWorld W;
	UMaterialInterface* BodyMaterial = LoadObject<UMaterialInterface>(nullptr, WoundMaterialPath);
	TestNotNull(TEXT("WP13 fake body material with wound parameters"), BodyMaterial);
	USkeletalMeshComponent* Body = W.AddBody(2, FVector::ZeroVector, BodyMaterial);
	if (!TestNotNull(TEXT("test human loaded"), Body->GetSkeletalMeshAsset()))
	{
		return false;
	}
	TArray<FVector> Expected;
	for (int32 I = 0; I < 20; ++I)
	{
		FVerseHitEvent Event = Hit(EVerseHitZone::UpperTorso, FVector::ZeroVector, FVector(-800.0, 0.0, 132.0), 2, uint16(I + 1));
		Event.ImpactBoneLocal = FVector_NetQuantize10(FVector(2.0 * I, 1.0, -3.0));
		W.Gore->HandleHit(Event);
		FVector RefPose;
		TestTrue(TEXT("bone exists in the reference skeleton"),
			UVerseGoreSubsystem::BoneLocalToRefPose(Body, Event.Bone, FVector(Event.ImpactBoneLocal), RefPose));
		Expected.Add(RefPose);
	}
	const TArray<FVector4f> Wounds = W.Gore->GetWounds(Body);
	TestEqual(TEXT("16 wounds per character at most"), Wounds.Num(), 16);
	TestEqual(TEXT("four oldest recycled"), W.Gore->GetBudget().WoundsRecycled, 4);
	for (int32 I = 0; I < Wounds.Num(); ++I)
	{
		TestTrue(FString::Printf(TEXT("wound %d is hit %d in reference pose"), I, I + 4),
			FVector(Wounds[I].X, Wounds[I].Y, Wounds[I].Z).Equals(Expected[I + 4], 0.1));
		TestTrue(TEXT("radius in range"), Wounds[I].W >= 2.5f && Wounds[I].W <= 6.f);
	}
	if (UMaterialInstanceDynamic* Mid = BodyMid(Body))
	{
		float Count = 0.f;
		Mid->GetScalarParameterValue(VerseGoreParams::WoundCount, Count);
		TestEqual(TEXT("material wound count"), Count, 16.f);
		FLinearColor Newest;
		Mid->GetVectorParameterValue(VerseGoreParams::WoundSlot(15), Newest);
		TestTrue(TEXT("newest wound in the last slot"), FVector(Newest.R, Newest.G, Newest.B).Equals(Expected[19], 0.1));
	}
	else
	{
		AddError(TEXT("no dynamic material with wound parameters on the body"));
	}

	// Death with a respawn delay clears the body's wounds when it respawns.
	FVerseDeathEvent Death;
	Death.VictimId = 2;
	Death.ServerTime = 10.f;
	Death.RespawnAt = 13.f;
	W.Gore->HandleDeath(Death);
	W.Advance(2.9);
	TestEqual(TEXT("wounds stay until respawn"), W.Gore->GetWounds(Body).Num(), 16);
	W.Advance(0.2);
	TestEqual(TEXT("respawn clears wounds"), W.Gore->GetWounds(Body).Num(), 0);
	return true;
}

// WP05.5: pools grow over 4 s under the body and are capped at 16.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGorePoolTest, "Verse.Gore.Pools.Growth", VERSE_GORE_TEST_FLAGS)
bool FVerseGorePoolTest::RunTest(const FString&)
{
	FWorld W;
	W.AddBox(FVector(0.0, 0.0, -10.0), FVector(4000.0, 4000.0, 20.0));
	W.AddBody(2, FVector::ZeroVector);
	FVerseDeathEvent Death;
	Death.VictimId = 2;
	W.Gore->HandleDeath(Death);
	TArray<UDecalComponent*> Pools = W.Gore->GetPoolDecals();
	if (!TestEqual(TEXT("one pool"), Pools.Num(), 1))
	{
		return false;
	}
	UDecalComponent* Pool = Pools[0];
	TestTrue(TEXT("pool lies on the floor"), FMath::IsNearlyEqual(Pool->GetComponentLocation().Z, 0.0, 2.0));
	auto Radius = [Pool]() { return Pool->DecalSize.Y * Pool->GetComponentScale().Y; };
	const double Full = W.Gore->GetTuning().PoolRadiusCm;
	TestTrue(TEXT("starts small"), Radius() < Full * 0.15);
	W.Advance(2.0);
	const double Mid = Radius();
	TestTrue(FString::Printf(TEXT("half way at 2 s (%.1f cm)"), Mid), Mid > Full * 0.4 && Mid < Full * 0.95);
	W.Advance(2.0);
	TestTrue(FString::Printf(TEXT("full at 4 s (%.1f cm)"), Radius()), FMath::IsNearlyEqual(Radius(), Full, Full * 0.02));
	W.Gore->HandleDeath(Death);
	TestEqual(TEXT("a second death within 3 s is the same pool"), W.Gore->GetPoolDecals().Num(), 1);

	for (int32 Id = 10; Id < 30; ++Id)
	{
		W.AddBody(Id, FVector(150.0 * (Id - 10), 400.0, 0.0));
		Death.VictimId = Id;
		W.Gore->HandleDeath(Death);
	}
	TestEqual(TEXT("16 pools at most"), W.Gore->GetPoolDecals().Num(), 16);
	TestEqual(TEXT("oldest recycled"), W.Gore->GetBudget().PoolsRecycled, 5);
	TestFalse(TEXT("the first pool was recycled first"), W.Gore->GetPoolDecals().Contains(Pool));
	return true;
}

// WP05.6: the finisher bleeds on Takedown and Kill, with one pool.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreFinisherTest, "Verse.Gore.Finisher.Full", VERSE_GORE_TEST_FLAGS)
bool FVerseGoreFinisherTest::RunTest(const FString&)
{
	FWorld W;
	W.AddBox(FVector(0.0, 0.0, -10.0), FVector(2000.0, 2000.0, 20.0));
	USkeletalMeshComponent* Body = W.AddBody(2, FVector::ZeroVector);
	FVerseGoreSyntheticParams Params;
	Params.Kind = EVerseGoreSyntheticKind::Finisher;
	Params.VictimId = 2;
	W.Gore->PlaySynthetic(Params);
	W.Advance(0.2);
	TestEqual(TEXT("nothing before Takedown"), W.Gore->GetBudget().DropletsSpawned, 0);
	W.Advance(0.1);
	const int32 AfterTakedown = W.Gore->GetBudget().DropletsSpawned;
	TestTrue(TEXT("Takedown bleeds"), AfterTakedown > 0);
	W.Advance(1.55);
	TestTrue(TEXT("Kill bleeds harder"), W.Gore->GetBudget().DropletsSpawned >= AfterTakedown + 40);
	TestEqual(TEXT("throat wound"), W.Gore->GetWounds(Body).Num(), 1);
	W.Advance(1.0);
	TestEqual(TEXT("kill and death make one pool"), W.Gore->GetPoolDecals().Num(), 1);
	TestFalse(TEXT("Full never cuts to black"), W.Gore->GetCutToBlack().Count > 0);
	return true;
}

// WP05.7 / A5.5: Reduced leaves no blood; the finisher cuts to black from Takedown to Recover.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreReducedTest, "Verse.Gore.Reduced.NoBlood", VERSE_GORE_TEST_FLAGS)
bool FVerseGoreReducedTest::RunTest(const FString&)
{
	FWorld W;
	W.AddRoom(150.0);
	USkeletalMeshComponent* Body = W.AddBody(2, FVector::ZeroVector, LoadObject<UMaterialInterface>(nullptr, WoundMaterialPath));
	W.Gore->SetGoreLevel(EVerseGoreLevel::Reduced);
	FVerseGoreSyntheticParams Params;
	Params.Seed = 5;
	Params.VictimId = 2;
	Params.DurationSeconds = 1000.0 / 30.0 + 0.01;
	Params.RatePerSecond = 30.0;
	TArray<FVerseGoreSyntheticEvent> Events = FVerseGoreSyntheticStream::Build(Params);
	Events.SetNum(1000);
	for (const FVerseGoreSyntheticEvent& Event : Events)
	{
		W.Hub->OnHit.Broadcast(Event.Hit);
		W.Gore->AdvanceTime(1.f / 30.f);
	}
	FVerseDeathEvent Death;
	Death.VictimId = 2;
	W.Hub->OnDeath.Broadcast(Death);
	const FVerseGoreBudget& B = W.Gore->GetBudget();
	TestEqual(TEXT("1,000 hits handled"), B.HitsHandled, 1000);
	TestEqual(TEXT("0 blood decals"), B.DecalsSpawned, 0);
	TestEqual(TEXT("0 pools"), W.Gore->GetPoolDecals().Num(), 0);
	TestEqual(TEXT("0 blood particles"), B.DropletsSpawned, 0);
	TestEqual(TEXT("0 wounds"), W.Gore->GetWounds(Body).Num(), 0);
	TestEqual(TEXT("a neutral flash per hit"), B.FlashesSpawned, 1000);

	// Cut to black, with a local viewer.
	APlayerController* Viewer = W.World->SpawnActor<APlayerController>();
	TestNotNull(TEXT("viewer with a camera manager"), Viewer ? Viewer->PlayerCameraManager.Get() : nullptr);
	FVerseFinisherEvent Finisher;
	Finisher.AttackerId = 1;
	Finisher.VictimId = 2;
	Finisher.Phase = EVerseFinisherPhase::Locked;
	W.Hub->OnFinisher.Broadcast(Finisher);
	TestFalse(TEXT("Locked does not cut yet"), W.Gore->GetCutToBlack().bActive);
	Finisher.Phase = EVerseFinisherPhase::Takedown;
	const uint64 TakedownFrame = GFrameCounter;
	W.Hub->OnFinisher.Broadcast(Finisher);
	TestTrue(TEXT("cut to black on Takedown"), W.Gore->GetCutToBlack().bActive);
	TestTrue(TEXT("cut starts within 1 frame of Takedown"), W.Gore->GetCutToBlack().StartFrame - TakedownFrame <= 1);
	if (Viewer && Viewer->PlayerCameraManager)
	{
		TestEqual(TEXT("viewer faded to black"), Viewer->PlayerCameraManager->FadeAmount, 1.f);
	}
	Finisher.Phase = EVerseFinisherPhase::Kill;
	W.Hub->OnFinisher.Broadcast(Finisher);
	TestEqual(TEXT("Kill draws nothing in Reduced"), W.Gore->GetBudget().DropletsSpawned, 0);
	TestTrue(TEXT("still black through Kill"), W.Gore->GetCutToBlack().bActive);
	Finisher.Phase = EVerseFinisherPhase::Recover;
	const uint64 RecoverFrame = GFrameCounter;
	W.Hub->OnFinisher.Broadcast(Finisher);
	TestFalse(TEXT("cut ends on Recover"), W.Gore->GetCutToBlack().bActive);
	TestTrue(TEXT("cut ends within 1 frame of Recover"), W.Gore->GetCutToBlack().EndFrame - RecoverFrame <= 1);
	if (Viewer && Viewer->PlayerCameraManager)
	{
		TestFalse(TEXT("viewer fade released"), Viewer->PlayerCameraManager->bEnableFading);
	}

	// Aborted ends the cut too; a lost Recover times out.
	Finisher.Phase = EVerseFinisherPhase::Takedown;
	W.Hub->OnFinisher.Broadcast(Finisher);
	Finisher.Phase = EVerseFinisherPhase::Aborted;
	W.Hub->OnFinisher.Broadcast(Finisher);
	TestFalse(TEXT("Aborted ends the cut"), W.Gore->GetCutToBlack().bActive);
	Finisher.Phase = EVerseFinisherPhase::Takedown;
	W.Hub->OnFinisher.Broadcast(Finisher);
	W.Advance(4.5);
	TestFalse(TEXT("timeout ends a cut without Recover"), W.Gore->GetCutToBlack().bActive);
	return true;
}

// WP05.7: switching to Reduced live purges existing gore.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreLiveSwitchTest, "Verse.Gore.Reduced.LiveSwitchPurges", VERSE_GORE_TEST_FLAGS)
bool FVerseGoreLiveSwitchTest::RunTest(const FString&)
{
	FWorld W;
	W.AddRoom(150.0);
	USkeletalMeshComponent* Body = W.AddBody(2, FVector::ZeroVector, LoadObject<UMaterialInterface>(nullptr, WoundMaterialPath));
	for (uint16 Shot = 1; Shot <= 20; ++Shot)
	{
		W.Gore->HandleHit(Hit(EVerseHitZone::UpperTorso, FVector::ZeroVector, FVector(-800.0, 0.0, 132.0), 2, Shot));
	}
	FVerseDeathEvent Death;
	Death.VictimId = 2;
	W.Gore->HandleDeath(Death);
	TestTrue(TEXT("Full drew decals"), W.Gore->GetSpatterDecals().Num() > 0);
	TestTrue(TEXT("Full drew a pool"), W.Gore->GetPoolDecals().Num() > 0);
	TestTrue(TEXT("Full drew wounds"), W.Gore->GetWounds(Body).Num() > 0);
	TestTrue(TEXT("Full drew droplets"), W.Gore->GetBudget().Droplets > 0);

	W.Gore->SetGoreLevel(EVerseGoreLevel::Reduced);
	TestEqual(TEXT("decals purged"), W.Gore->GetSpatterDecals().Num(), 0);
	TestEqual(TEXT("pools purged"), W.Gore->GetPoolDecals().Num(), 0);
	TestEqual(TEXT("wounds purged"), W.Gore->GetWounds(Body).Num(), 0);
	TestEqual(TEXT("droplets purged"), W.Gore->GetBudget().Droplets, 0);
	TestEqual(TEXT("no droplet instances left"), W.Gore->GetGoreActor()->Droplets->GetInstanceCount(), 0);
	if (UMaterialInstanceDynamic* Mid = BodyMid(Body))
	{
		float Count = -1.f;
		Mid->GetScalarParameterValue(VerseGoreParams::WoundCount, Count);
		TestEqual(TEXT("body material wound count reset"), Count, 0.f);
	}
	W.Gore->SetGoreLevel(EVerseGoreLevel::Full);
	W.Gore->HandleHit(Hit(EVerseHitZone::UpperTorso, FVector::ZeroVector, FVector(-800.0, 0.0, 132.0), 2, 99));
	TestTrue(TEXT("Full again draws again"), W.Gore->GetSpatterDecals().Num() > 0);
	return true;
}

// A5.3: 1,000 traces on every channel through decals, pools and blood particles hit nothing of gore.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreNoCollisionTest, "Verse.Gore.NoCollision", VERSE_GORE_TEST_FLAGS)
bool FVerseGoreNoCollisionTest::RunTest(const FString&)
{
	FWorld W;
	W.AddRoom(150.0);
	for (int32 Id = 2; Id < 6; ++Id)
	{
		W.AddBody(Id, FVector(-60.0 * Id, 80.0 * (Id - 3), 0.0));
	}
	uint16 Shot = 1;
	for (int32 Id = 2; Id < 6; ++Id)
	{
		for (int32 I = 0; I < 12; ++I)
		{
			const EVerseHitZone Zone = EVerseHitZone(1 + (I % 6));
			W.Gore->HandleHit(Hit(Zone, FVector(-60.0 * Id, 80.0 * (Id - 3), 0.0), FVector(-900.0, 0.0, 150.0), Id, Shot++, 35.f));
		}
		FVerseDeathEvent Death;
		Death.VictimId = Id;
		W.Gore->HandleDeath(Death);
	}
	W.Advance(0.12);

	TArray<FVector> Points;
	for (const UDecalComponent* Decal : W.Gore->GetSpatterDecals())
	{
		Points.Add(Decal->GetComponentLocation());
	}
	for (const UDecalComponent* Decal : W.Gore->GetPoolDecals())
	{
		Points.Add(Decal->GetComponentLocation());
	}
	Points.Append(DropletPositions(W.Gore));
	TestTrue(FString::Printf(TEXT("gore to probe (%d points)"), Points.Num()), Points.Num() > 50);
	AVerseGoreActor* Actor = W.Gore->GetGoreActor();
	if (!TestNotNull(TEXT("gore actor"), Actor) || Points.Num() == 0)
	{
		return false;
	}
	TestFalse(TEXT("gore actor never replicates"), Actor->GetIsReplicated());
	TInlineComponentArray<UPrimitiveComponent*> Primitives(Actor);
	for (const UPrimitiveComponent* Primitive : Primitives)
	{
		TestEqual(FString::Printf(TEXT("%s has no collision"), *Primitive->GetName()), Primitive->GetCollisionEnabled(), ECollisionEnabled::NoCollision);
	}

	FVerseRng Rng(42);
	int32 GoreHits = 0, Traces = 0;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseGoreNoCollisionTest), true);
	for (int32 I = 0; I < 1000; ++I)
	{
		const FVector Point = Points[I % Points.Num()];
		const FVector Dir = Rng.UnitVector();
		for (int32 Channel = 0; Channel < int32(ECC_OverlapAll_Deprecated); ++Channel)
		{
			FHitResult HitResult;
			++Traces;
			if (W.World->LineTraceSingleByChannel(HitResult, Point - Dir * 60.0, Point + Dir * 60.0, ECollisionChannel(Channel), Params)
				&& HitResult.GetActor() == Actor)
			{
				++GoreHits;
			}
		}
	}
	TestEqual(FString::Printf(TEXT("%d traces on every channel hit gore"), Traces), GoreHits, 0);
	TestTrue(TEXT("sight and bolt channels included"), int32(VerseCollision::Sight) < int32(ECC_OverlapAll_Deprecated)
		&& int32(VerseCollision::Bolt) < int32(ECC_OverlapAll_Deprecated));
	return true;
}

// A5.4: gore_storm (30 hits/s for 60 s) stays inside the caps and the game-thread budget.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreBudgetTest, "Verse.Gore.Budget.Storm", VERSE_GORE_TEST_FLAGS)
bool FVerseGoreBudgetTest::RunTest(const FString&)
{
	FWorld W;
	W.AddRoom(150.0);
	W.AddBody(2, FVector::ZeroVector, LoadObject<UMaterialInterface>(nullptr, WoundMaterialPath));
	for (int32 Id = 10; Id < 30; ++Id)
	{
		W.AddBody(Id, FVector(-120.0 * (Id - 9), 300.0, 0.0));
	}
	// Warm-up hit: the first decal creation and asset loads are not part of the steady budget.
	W.Gore->HandleHit(Hit(EVerseHitZone::UpperTorso, FVector::ZeroVector, FVector(-800.0, 0.0, 132.0), 2, 60000));
	W.Gore->ResetBudget();

	FVerseGoreSyntheticParams Params;
	Params.Kind = EVerseGoreSyntheticKind::Storm;
	Params.DurationSeconds = 60.0;
	Params.VictimId = 2;
	Params.Seed = 11;
	W.Gore->PlaySynthetic(Params);
	FVerseDeathEvent Death;
	for (int32 Frame = 0; Frame < 60 * 61; ++Frame)
	{
		W.Gore->AdvanceTime(1.f / 60.f);
		if (Frame % 150 == 0)
		{
			Death.VictimId = 10 + (Frame / 150) % 20;   // a death every 2.5 s on another body
			W.Hub->OnDeath.Broadcast(Death);
		}
	}
	const FVerseGoreBudget& B = W.Gore->GetBudget();
	TestEqual(TEXT("1,800 storm hits"), B.HitsHandled, 1800);
	TestTrue(FString::Printf(TEXT("spatter decals peak %d <= 256"), B.PeakSpatterDecals), B.PeakSpatterDecals <= 256 && B.PeakSpatterDecals > 0);
	TestTrue(FString::Printf(TEXT("pools peak %d <= 16"), B.PeakPools), B.PeakPools <= 16 && B.PeakPools > 0);
	TestTrue(FString::Printf(TEXT("wounds peak %d <= 16"), B.PeakWoundsOnOneCharacter), B.PeakWoundsOnOneCharacter <= 16 && B.PeakWoundsOnOneCharacter > 0);
	TestTrue(FString::Printf(TEXT("game thread per hit %.4f ms <= 0.05 ms"), B.HitMeanMs), B.HitMeanMs <= 0.05);

	const FString Dir = ProofDir(TEXT("5.8"));
	IFileManager::Get().MakeDirectory(*Dir, true);
	TestTrue(TEXT("budget JSON written"), W.Gore->WriteBudgetJson(FPaths::Combine(Dir, TEXT("budget_gore_storm_nullrhi.json"))));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
