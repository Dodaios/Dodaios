#include "Anim/VerseAnimInstance.h"
#include "Anim/VerseAnimMath.h"
#include "Anim/VerseAnimRuntime.h"
#include "Anim/VerseFirstPerson.h"
#include "Anim/VerseHumanSkeleton.h"
#include "Animation/AnimSequence.h"
#include "Animation/AttributesRuntime.h"
#include "Animation/Skeleton.h"
#include "BoneContainer.h"
#include "BonePose.h"
#include "Camera/CameraComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformTime.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "Rendering/SkeletalMeshRenderData.h"

#if WITH_DEV_AUTOMATION_TESTS

namespace VerseAnimTest
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	USkeletalMesh* LoadMesh(const TCHAR* Path)
	{
		return LoadObject<USkeletalMesh>(nullptr, Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
	}

	USkeletalMesh* ReferenceMesh()
	{
		return LoadMesh(TEXT("/Game/Verse/Characters/Commander/SK_Commander_M.SK_Commander_M"));
	}

	/** A full bone container of a mesh plus the runtime's bone table. */
	struct FRig
	{
		TArray<FBoneIndexType> Required;
		FBoneContainer Container;
		FVerseAnimBones Bones;

		explicit FRig(USkeletalMesh& Mesh)
		{
			const int32 Num = Mesh.GetRefSkeleton().GetNum();
			for (int32 i = 0; i < Num; ++i)
			{
				Required.Add(static_cast<FBoneIndexType>(i));
			}
			Container.InitializeTo(Required, UE::Anim::FCurveFilterSettings(), Mesh);
			Bones.Build(Container);
		}

		int32 Index(const TCHAR* Name) const
		{
			const int32 MeshIndex = Container.GetPoseBoneIndexForBoneName(FName(Name));
			return MeshIndex == INDEX_NONE ? INDEX_NONE : Container.MakeCompactPoseIndex(FMeshPoseBoneIndex(MeshIndex)).GetInt();
		}

		void Evaluate(const FVerseAnimFrame& Frame, float IdleTime, TArray<FTransform>& OutCS, FVerseAnimEvalInfo* Info = nullptr,
			TArray<FTransform>* OutLocal = nullptr)
		{
			FMemMark Mark(FMemStack::Get());
			FCompactPose Pose;
			Pose.SetBoneContainer(&Container);
			FBlendedCurve Curve;
			Curve.InitFrom(Container);
			UE::Anim::FStackAttributeContainer Attributes;
			VerseAnim::EvaluateFrame(Frame, IdleTime, Bones, Pose, Curve, Attributes, Info);
			TArray<FTransform> Local;
			Local.SetNum(Pose.GetNumBones());
			for (int32 i = 0; i < Local.Num(); ++i)
			{
				Local[i] = Pose[FCompactPoseBoneIndex(i)];
			}
			VerseAnim::LocalToComponent(Bones.Parents, Local, OutCS);
			if (OutLocal)
			{
				*OutLocal = Local;
			}
		}
	};

	/** A frame of the state machine after `Seconds` of steady `Inputs`. */
	FVerseAnimFrame Settle(const FVerseAnimClipSet& Clips, const FVerseAnimInputs& Inputs, float Seconds, FVerseAnimStateMachine& Machine)
	{
		FVerseAnimFrame Frame;
		const int32 Steps = FMath::Max(1, FMath::RoundToInt(Seconds * 60.f));
		for (int32 i = 0; i < Steps; ++i)
		{
			Machine.Step(Inputs, 1.f / 60.f, Clips, Frame);
		}
		return Frame;
	}

	bool RequireAssets(FAutomationTestBase& Test, USkeletalMesh*& OutMesh, FVerseAnimClipSet& OutClips)
	{
		OutMesh = ReferenceMesh();
		if (!OutMesh)
		{
			Test.AddError(TEXT("SK_Commander_M is not imported (python art/verse/characters/import_characters.py)"));
			return false;
		}
		OutClips.Load();
		TArray<FString> Missing;
		if (!OutClips.IsComplete(&Missing))
		{
			Test.AddError(FString::Printf(TEXT("clips missing: %s"), *FString::Join(Missing, TEXT(", "))));
			return false;
		}
		return true;
	}

	/** Flat JSON object of numbers (the module has no Json dependency). */
	struct FReport
	{
		TArray<TPair<FString, double>> Fields;
		void SetNumberField(const FString& Key, double Value) { Fields.Emplace(Key, Value); }
	};

	void WriteProof(const FString& SubTask, const FString& File, const FReport& Report)
	{
		const FString Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/WP13"), SubTask);
		IFileManager::Get().MakeDirectory(*Dir, true);
		TArray<FString> Lines;
		for (const TPair<FString, double>& F : Report.Fields)
		{
			Lines.Add(FString::Printf(TEXT("  \"%s\": %.6f"), *F.Key, F.Value));
		}
		const FString Text = FString(TEXT("{\n")) + FString::Join(Lines, TEXT(",\n")) + TEXT("\n}\n");
		FFileHelper::SaveStringToFile(Text, *FPaths::Combine(Dir, File));
	}
}

using namespace VerseAnimTest;

// A13.1: bone names match art-pipeline 12.1, at most 200 bones.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAnimSkeletonBonesTest, "Verse.Anim.Skeleton.BoneNames", VerseAnimTest::Flags)
bool FVerseAnimSkeletonBonesTest::RunTest(const FString& Parameters)
{
	const USkeleton* Skeleton = LoadObject<USkeleton>(nullptr, VerseHuman::SkeletonPath, nullptr, LOAD_NoWarn | LOAD_Quiet);
	if (!TestNotNull(TEXT("SKEL_Verse_Human is imported"), Skeleton))
	{
		return false;
	}
	const FReferenceSkeleton& Ref = Skeleton->GetReferenceSkeleton();
	TestTrue(FString::Printf(TEXT("%d bones, at most %d"), Ref.GetNum(), VerseHuman::MaxBones), Ref.GetNum() <= VerseHuman::MaxBones);
	const TConstArrayView<TPair<FName, FName>> Bones = VerseHuman::Bones();
	TestEqual(TEXT("bone count equals art-pipeline 12.1"), Ref.GetNum(), Bones.Num());
	int32 Matched = 0;
	for (const TPair<FName, FName>& Bone : Bones)
	{
		const int32 Index = Ref.FindBoneIndex(Bone.Key);
		if (!TestTrue(FString::Printf(TEXT("bone %s exists"), *Bone.Key.ToString()), Index != INDEX_NONE))
		{
			continue;
		}
		const int32 Parent = Ref.GetParentIndex(Index);
		const FName ParentName = Parent == INDEX_NONE ? NAME_None : Ref.GetBoneName(Parent);
		if (TestEqual(FString::Printf(TEXT("parent of %s"), *Bone.Key.ToString()), ParentName.ToString(), Bone.Value.ToString()))
		{
			++Matched;
		}
	}
	TestEqual(TEXT("100 % of the frozen bones match"), Matched, Bones.Num());
	return true;
}

// A13.1: every character mesh is on SKEL_Verse_Human with PHYS_Verse_Human and at most 8 influences.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAnimMeshesTest, "Verse.Anim.Skeleton.Meshes", VerseAnimTest::Flags)
bool FVerseAnimMeshesTest::RunTest(const FString& Parameters)
{
	for (const TCHAR* Path : VerseHuman::MeshPaths())
	{
		USkeletalMesh* Mesh = LoadMesh(Path);
		if (!TestNotNull(FString::Printf(TEXT("%s is imported"), Path), Mesh))
		{
			continue;
		}
		TestEqual(FString::Printf(TEXT("%s skeleton"), Path), Mesh->GetSkeleton() ? Mesh->GetSkeleton()->GetPathName() : FString(),
			FString(VerseHuman::SkeletonPath));
		const UPhysicsAsset* Physics = Mesh->GetPhysicsAsset();
		TestTrue(FString::Printf(TEXT("%s uses PHYS_Verse_Human"), Path), Physics && Physics->GetPathName() == VerseHuman::PhysicsPath);
		const FSkeletalMeshRenderData* Render = Mesh->GetResourceForRendering();
		if (TestTrue(FString::Printf(TEXT("%s has render data"), Path), Render && Render->LODRenderData.Num() > 0))
		{
			const uint32 Influences = Render->LODRenderData[0].GetVertexBufferMaxBoneInfluences();
			TestTrue(FString::Printf(TEXT("%s: %u influences per vertex, at most %d"), Path, Influences, VerseHuman::MaxInfluences),
				Influences <= static_cast<uint32>(VerseHuman::MaxInfluences));
		}
	}
	return true;
}

// Every catalogue clip is imported on the skeleton; mantle and finisher carry root motion.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAnimClipsTest, "Verse.Anim.Clips.Complete", VerseAnimTest::Flags)
bool FVerseAnimClipsTest::RunTest(const FString& Parameters)
{
	int32 Found = 0;
	for (const TCHAR* Name : VerseHuman::ClipNames())
	{
		const FString Path = VerseHuman::ClipPath(Name);
		const UAnimSequence* Clip = LoadObject<UAnimSequence>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
		if (!TestNotNull(FString::Printf(TEXT("%s is imported"), *Path), Clip))
		{
			continue;
		}
		++Found;
		TestEqual(FString::Printf(TEXT("%s skeleton"), Name), Clip->GetSkeleton() ? Clip->GetSkeleton()->GetPathName() : FString(),
			FString(VerseHuman::SkeletonPath));
		const FString N(Name);
		if (N.StartsWith(TEXT("A_Mantle_")) || N.StartsWith(TEXT("A_Finisher_")))
		{
			TestTrue(FString::Printf(TEXT("%s has root motion"), Name), Clip->HasRootMotion());
		}
	}
	TestEqual(TEXT("every catalogue clip"), Found, VerseHuman::ClipNames().Num());
	return true;
}

// A13.2: finisher markers within one frame (30 fps) of the phase times of combat-state 7.4.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAnimFinisherMarkersTest, "Verse.Anim.Finisher.Markers", VerseAnimTest::Flags)
bool FVerseAnimFinisherMarkersTest::RunTest(const FString& Parameters)
{
	for (const TCHAR* Name : {TEXT("A_Finisher_Attacker"), TEXT("A_Finisher_Victim")})
	{
		const UAnimSequence* Clip = LoadObject<UAnimSequence>(nullptr, *VerseHuman::ClipPath(Name), nullptr, LOAD_NoWarn | LOAD_Quiet);
		if (!TestNotNull(FString::Printf(TEXT("%s is imported"), Name), Clip))
		{
			continue;
		}
		TestTrue(FString::Printf(TEXT("%s lasts 2.5 s"), Name), FMath::IsNearlyEqual(Clip->GetPlayLength(), 2.5f, 1.f / 30.f));
		for (const TPair<FName, float>& Marker : VerseHuman::FinisherMarkers())
		{
			const FAnimSyncMarker* Found = Clip->AuthoredSyncMarkers.FindByPredicate(
				[&Marker](const FAnimSyncMarker& M) { return M.MarkerName == Marker.Key; });
			if (TestNotNull(FString::Printf(TEXT("%s marker %s"), Name, *Marker.Key.ToString()), Found))
			{
				TestTrue(FString::Printf(TEXT("%s %s at %.4f s, want %.4f s"), Name, *Marker.Key.ToString(), Found->Time, Marker.Value),
					FMath::Abs(Found->Time - Marker.Value) <= 1.f / 30.f + 1e-4f);
			}
		}
	}
	return true;
}

// A13.3: the off hand within 0.5 cm of SOCKET_Support in every idle and ADS pose of every weapon.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAnimOffHandTest, "Verse.Anim.OffHandIK", VerseAnimTest::Flags)
bool FVerseAnimOffHandTest::RunTest(const FString& Parameters)
{
	USkeletalMesh* Mesh = nullptr;
	FVerseAnimClipSet Clips;
	if (!RequireAssets(*this, Mesh, Clips))
	{
		return false;
	}
	FRig Rig(*Mesh);
	FReport Report;
	for (const EVerseAnimWeapon Weapon : {EVerseAnimWeapon::Rifle, EVerseAnimWeapon::Pistol})
	{
		for (const float Ads : {0.f, 1.f})
		{
			FVerseAnimInputs In;
			In.Weapon = Weapon;
			In.Ads = Ads;
			FVerseAnimStateMachine Machine;
			float Worst = 0.f;
			float WorstRaw = 0.f;
			const UAnimSequence* Clip = Ads > 0.f ? Clips.Weapons[static_cast<int32>(Weapon)].Ads : Clips.Weapons[static_cast<int32>(Weapon)].Idle;
			const int32 Frames = FMath::RoundToInt(Clip->GetPlayLength() * 30.f);
			for (int32 f = 0; f <= Frames; ++f)
			{
				FVerseAnimFrame Frame = Settle(Clips, In, f == 0 ? 0.5f : 1.f / 30.f, Machine);
				Frame.SupportInWeapon = FTransform(VerseHuman::ReferenceSupport(Weapon == EVerseAnimWeapon::Pistol));
				Frame.bFootIK = false;
				FVerseAnimEvalInfo Info;
				TArray<FTransform> CS;
				Rig.Evaluate(Frame, Machine.GetIdleTime(), CS, &Info);
				Worst = FMath::Max(Worst, Info.OffHandError);
				FVerseAnimFrame Raw = Frame;
				Raw.OffHandAlpha = 0.f;
				Rig.Evaluate(Raw, Machine.GetIdleTime(), CS);
				const FVector Want = (Frame.SupportInWeapon * CS[Rig.Bones.WeaponR]).GetLocation();
				WorstRaw = FMath::Max(WorstRaw, static_cast<float>(FVector::Dist(Want, CS[Rig.Bones.HandL].GetLocation())));
			}
			const FString Key = FString::Printf(TEXT("%s_%s"), Weapon == EVerseAnimWeapon::Rifle ? TEXT("Rifle") : TEXT("Pistol"),
				Ads > 0.f ? TEXT("ADS") : TEXT("Idle"));
			Report.SetNumberField(Key + TEXT("_error_cm"), Worst);
			Report.SetNumberField(Key + TEXT("_clip_error_cm"), WorstRaw);
			TestTrue(FString::Printf(TEXT("%s: off hand %.3f cm from SOCKET_Support (clip alone %.3f cm), at most 0.5"), *Key, Worst, WorstRaw),
				Worst <= 0.5f);
		}
	}
	// Weapon_R in the rifle hold is root-aligned (a weapon built like a character attaches with identity).
	{
		FVerseAnimInputs In;
		FVerseAnimStateMachine Machine;
		FVerseAnimFrame Frame = Settle(Clips, In, 1.f / 60.f, Machine);
		Frame.bFootIK = false;
		Frame.OffHandAlpha = 0.f;
		Frame.AimPitch = 0.f;
		TArray<FTransform> CS;
		Rig.Evaluate(Frame, 0.f, CS);
		const FQuat Weapon = CS[Rig.Bones.WeaponR].GetRotation();
		const FQuat Root = Rig.Bones.Root != INDEX_NONE ? CS[Rig.Bones.Root].GetRotation() : FQuat::Identity;
		const float Degrees = FMath::RadiansToDegrees(Weapon.AngularDistance(Root));
		Report.SetNumberField(TEXT("weapon_r_vs_root_deg"), Degrees);
		AddInfo(FString::Printf(TEXT("Weapon_R vs Root in the rifle idle: %.2f deg; barrel %s"), Degrees,
			*Weapon.GetAxisY().ToString()));
		TestTrue(TEXT("Weapon_R is root-aligned in the rifle idle (within 3 deg)"), Degrees <= 3.f);
	}
	WriteProof(TEXT("13.10"), TEXT("offhand_ik.json"), Report);
	return true;
}

// A13.4: on 30 deg slopes and stairs no foot penetrates the floor by more than 1 cm.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAnimFootIKTest, "Verse.Anim.FootIK", VerseAnimTest::Flags)
bool FVerseAnimFootIKTest::RunTest(const FString& Parameters)
{
	USkeletalMesh* Mesh = nullptr;
	FVerseAnimClipSet Clips;
	if (!RequireAssets(*this, Mesh, Clips))
	{
		return false;
	}
	FRig Rig(*Mesh);
	const int32 Ball[2] = {Rig.Index(TEXT("Ball_L")), Rig.Index(TEXT("Ball_R"))};
	// Sole points in each foot's frame, from the reference pose (heel under the ankle, ball, toe tip).
	TArray<FTransform> RefLocal;
	TArray<FTransform> RefCS;
	for (int32 i = 0; i < Rig.Bones.Parents.Num(); ++i)
	{
		RefLocal.Add(Rig.Container.GetRefPoseTransform(FCompactPoseBoneIndex(i)));
	}
	VerseAnim::LocalToComponent(Rig.Bones.Parents, RefLocal, RefCS);
	TArray<FVector> Sole[2];
	for (int32 s = 0; s < 2; ++s)
	{
		const FTransform Foot = RefCS[Rig.Bones.Foot[s]];
		const FVector Ankle = Foot.GetLocation();
		const FVector BallP = RefCS[Ball[s]].GetLocation();
		for (const FVector& P : {FVector(Ankle.X, Ankle.Y, 0.0), FVector(BallP.X, BallP.Y, 0.0)})
		{
			Sole[s].Add(Foot.InverseTransformPosition(P));
		}
	}
	struct FFloor
	{
		const TCHAR* Name;
		TFunction<double(const FVector&)> Height;
		FVector Normal;
	};
	const double Slope = FMath::Tan(FMath::DegreesToRadians(30.0));
	const FVector Fwd = VerseAnim::MeshForward;
	const FVector Side = VerseAnim::MeshRight;
	TArray<FFloor> Floors;
	Floors.Add({TEXT("slope up 30 deg"), [=](const FVector& P) { return Slope * FVector::DotProduct(P, Fwd); },
		FVector(-Fwd * FMath::Sin(FMath::DegreesToRadians(30.0)) + FVector::UpVector * FMath::Cos(FMath::DegreesToRadians(30.0)))});
	Floors.Add({TEXT("slope down 30 deg"), [=](const FVector& P) { return -Slope * FVector::DotProduct(P, Fwd); },
		FVector(Fwd * FMath::Sin(FMath::DegreesToRadians(30.0)) + FVector::UpVector * FMath::Cos(FMath::DegreesToRadians(30.0)))});
	Floors.Add({TEXT("side slope 30 deg"), [=](const FVector& P) { return Slope * FVector::DotProduct(P, Side); },
		FVector(-Side * FMath::Sin(FMath::DegreesToRadians(30.0)) + FVector::UpVector * FMath::Cos(FMath::DegreesToRadians(30.0)))});
	Floors.Add({TEXT("stairs 18 cm"), [=](const FVector& P) { return FVector::DotProduct(P, Fwd) > 2.0 ? 18.0 : 0.0; }, FVector::UpVector});
	Floors.Add({TEXT("stairs down 18 cm"), [=](const FVector& P) { return FVector::DotProduct(P, Fwd) > 2.0 ? -18.0 : 0.0; }, FVector::UpVector});
	FReport Report;
	for (const FFloor& Floor : Floors)
	{
		FVerseAnimInputs In;
		FVerseAnimStateMachine Machine;
		FVerseAnimFrame Frame = Settle(Clips, In, 0.5f, Machine);
		Frame.OffHandAlpha = 0.f;
		TArray<FTransform> Flat;
		Frame.bFootIK = false;
		Rig.Evaluate(Frame, Machine.GetIdleTime(), Flat);
		Frame.bFootIK = true;
		for (int32 s = 0; s < 2; ++s)
		{
			const FVector Ankle = Flat[Rig.Bones.Foot[s]].GetLocation();
			Frame.FloorOffset[s] = static_cast<float>(Floor.Height(Ankle));
			Frame.FloorNormal[s] = Floor.Normal.GetSafeNormal();
		}
		TArray<FTransform> CS;
		FVerseAnimEvalInfo Info;
		Rig.Evaluate(Frame, Machine.GetIdleTime(), CS, &Info);
		double Worst = 0.0;
		for (int32 s = 0; s < 2; ++s)
		{
			for (const FVector& Local : Sole[s])
			{
				const FVector P = CS[Rig.Bones.Foot[s]].TransformPosition(Local);
				Worst = FMath::Max(Worst, Floor.Height(P) - P.Z);
			}
		}
		Report.SetNumberField(Floor.Name, Worst);
		TestTrue(FString::Printf(TEXT("%s: deepest sole point %.2f cm below the floor (pelvis %.1f cm), at most 1"), Floor.Name, Worst, Info.PelvisDrop),
			Worst <= 1.0);
	}
	WriteProof(TEXT("13.10"), TEXT("foot_ik.json"), Report);
	return true;
}

// WP13.10: lean spreads over Spine_01..03 by their shares and tilts towards the leaning side.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAnimLeanTest, "Verse.Anim.Lean", VerseAnimTest::Flags)
bool FVerseAnimLeanTest::RunTest(const FString& Parameters)
{
	USkeletalMesh* Mesh = nullptr;
	FVerseAnimClipSet Clips;
	if (!RequireAssets(*this, Mesh, Clips))
	{
		return false;
	}
	FRig Rig(*Mesh);
	FVerseAnimStateMachine Machine;
	FVerseAnimInputs In;
	FVerseAnimFrame Frame = Settle(Clips, In, 0.2f, Machine);
	Frame.bFootIK = false;
	Frame.OffHandAlpha = 0.f;
	TArray<FTransform> Upright;
	Rig.Evaluate(Frame, Machine.GetIdleTime(), Upright);
	for (const float Lean : {1.f, -1.f})
	{
		Frame.Lean = Lean;
		TArray<FTransform> CS;
		Rig.Evaluate(Frame, Machine.GetIdleTime(), CS);
		const FVector Shift = CS[Rig.Bones.Head].GetLocation() - Upright[Rig.Bones.Head].GetLocation();
		const double Towards = FVector::DotProduct(Shift, VerseAnim::MeshRight) * Lean;
		TestTrue(FString::Printf(TEXT("lean %.0f moves the head %.1f cm to that side"), Lean, Towards), Towards > 15.0);
		double Previous = 0.0;
		double Cumulative = 0.0;
		for (int32 k = 0; k < 3; ++k)
		{
			const int32 Bone = Rig.Bones.Spine[k];
			const FQuat Delta = CS[Bone].GetRotation() * Upright[Bone].GetRotation().Inverse();
			const double Angle = FMath::RadiansToDegrees(Delta.GetAngle());
			Cumulative += Rig.Bones.SpineShare[k] * FVerseAnimStateMachine::LeanMaxDeg;
			TestTrue(FString::Printf(TEXT("spine %d turned %.2f deg, want %.2f"), k + 1, Angle, Cumulative),
				FMath::Abs(Angle - Cumulative) < 0.5);
			TestTrue(TEXT("each spine bone adds to the lean"), Angle >= Previous - 1e-3);
			Previous = Angle;
		}
	}
	return true;
}

// WP13.10: the state machine follows IVerseMovementQuery-style inputs through every state.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAnimStateMachineTest, "Verse.Anim.StateMachine", VerseAnimTest::Flags)
bool FVerseAnimStateMachineTest::RunTest(const FString& Parameters)
{
	USkeletalMesh* Mesh = nullptr;
	FVerseAnimClipSet Clips;
	if (!RequireAssets(*this, Mesh, Clips))
	{
		return false;
	}
	FVerseAnimStateMachine M;
	FVerseAnimInputs In;
	FVerseAnimFrame F = Settle(Clips, In, 0.5f, M);
	TestTrue(TEXT("idle on the ground"), M.GetState() == EVerseLocoState::Ground);
	TestTrue(TEXT("idle: no move blend"), F.MoveAlpha < 0.01f);
	In.LocalVelocity = FVector(450.0, 0.0, 0.0);
	F = Settle(Clips, In, 0.6f, M);
	TestTrue(TEXT("walking forward blends the move clips in"), F.MoveAlpha > 0.95f);
	TestTrue(TEXT("forward heading is 0"), FMath::Abs(F.HeadingDeg) < 1.f);
	In.LocalVelocity = FVector(0.0, 450.0, 0.0);
	F = Settle(Clips, In, 0.2f, M);
	TestTrue(FString::Printf(TEXT("moving right is heading -90 (got %.1f)"), F.HeadingDeg), FMath::IsNearlyEqual(F.HeadingDeg, -90.f, 1.f));
	In.bSprinting = true;
	In.LocalVelocity = FVector(650.0, 0.0, 0.0);
	F = Settle(Clips, In, 0.5f, M);
	TestTrue(TEXT("sprint blends in and lowers the weapon layer"), F.SprintAlpha > 0.95f && F.UpperAlpha < 0.05f);
	In.bSprinting = false;
	In.bAirborne = true;
	F = Settle(Clips, In, 0.1f, M);
	TestTrue(TEXT("airborne starts with the jump"), M.GetState() == EVerseLocoState::JumpStart);
	F = Settle(Clips, In, 0.4f, M);
	TestTrue(TEXT("then falls"), M.GetState() == EVerseLocoState::Fall);
	In.bAirborne = false;
	F = Settle(Clips, In, 1.f / 60.f, M);
	TestTrue(TEXT("touchdown lands"), M.GetState() == EVerseLocoState::Land);
	F = Settle(Clips, In, 0.5f, M);
	TestTrue(TEXT("back on the ground after the land"), M.GetState() == EVerseLocoState::Ground);
	In.LocalVelocity = FVector::ZeroVector;
	In.Stance = EVerseStance::Crouch;
	F = Settle(Clips, In, 0.5f, M);
	TestTrue(TEXT("crouch crossfades to the crouch set"), F.StanceWeight[1] > 0.99f);
	In.Stance = EVerseStance::Prone;
	F = Settle(Clips, In, 0.1f, M);
	TestTrue(TEXT("going prone plays the enter clip"), M.GetState() == EVerseLocoState::ProneEnter);
	F = Settle(Clips, In, 0.8f, M);
	TestTrue(TEXT("then lies prone"), M.GetState() == EVerseLocoState::Ground && F.StanceWeight[2] > 0.99f);
	TestFalse(TEXT("no foot IK while prone"), F.bFootIK);
	In.Stance = EVerseStance::Stand;
	F = Settle(Clips, In, 0.1f, M);
	TestTrue(TEXT("standing up plays the exit clip"), M.GetState() == EVerseLocoState::ProneExit);
	F = Settle(Clips, In, 0.7f, M);
	In.Stance = EVerseStance::Slide;
	F = Settle(Clips, In, 0.1f, M);
	TestTrue(TEXT("slide plays the slide clip"), M.GetState() == EVerseLocoState::Slide && F.Special == Clips.Slide);
	In.Stance = EVerseStance::Stand;
	In.bMantling = true;
	In.bMantleHigh = true;
	F = Settle(Clips, In, 0.1f, M);
	TestTrue(TEXT("mantle plays the high mantle with the arms its own"), M.GetState() == EVerseLocoState::Mantle
		&& F.Special == Clips.MantleHigh && F.UpperAlpha == 0.f && F.OffHandAlpha == 0.f);
	In.bMantling = false;
	In.Action = EVerseAnimAction::ReloadTactical;
	In.ActionTime = 0.5f;
	F = Settle(Clips, In, 1.f / 60.f, M);
	TestTrue(TEXT("a reload plays its clip on the upper body"), F.Action == Clips.Weapons[1].ReloadTactical && F.ActionWeight > 0.9f);
	return true;
}

// A13.6: animation for 2 FPS characters plus 12 crew at most 0.4 ms of game thread.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAnimCostTest, "Verse.Anim.Cost", VerseAnimTest::Flags)
bool FVerseAnimCostTest::RunTest(const FString& Parameters)
{
	USkeletalMesh* Mesh = nullptr;
	FVerseAnimClipSet Clips;
	if (!RequireAssets(*this, Mesh, Clips))
	{
		return false;
	}
	FRig Rig(*Mesh);
	const UAnimSequence* Crew = LoadObject<UAnimSequence>(nullptr, *VerseHuman::ClipPath(TEXT("A_Crew_Sit_Type")), nullptr, LOAD_NoWarn | LOAD_Quiet);
	FVerseAnimStateMachine Fps[2];
	FVerseAnimInputs FpsIn[2];
	FpsIn[0].LocalVelocity = FVector(400.0, 150.0, 0.0);
	FpsIn[0].Lean = 0.6f;
	FpsIn[0].AimPitch = 12.f;
	FpsIn[1].Ads = 1.f;
	FpsIn[1].Action = EVerseAnimAction::ReloadTactical;
	FpsIn[1].ActionTime = 0.6f;
	const int32 Frames = 240;
	TArray<FTransform> CS;
	// Warm up (clip decompression caches).
	for (int32 w = 0; w < 10; ++w)
	{
		FVerseAnimFrame F;
		Fps[0].Step(FpsIn[0], 1.f / 60.f, Clips, F);
		Rig.Evaluate(F, Fps[0].GetIdleTime(), CS);
	}
	double GameThread = 0.0;
	double Evaluation = 0.0;
	int32 Samples = 0;
	for (int32 f = 0; f < Frames; ++f)
	{
		FVerseAnimFrame Frame[2];
		const double T0 = FPlatformTime::Seconds();
		for (int32 c = 0; c < 2; ++c)
		{
			Fps[c].Step(FpsIn[c], 1.f / 60.f, Clips, Frame[c]);
			Frame[c].bFootIK = true;
		}
		FVerseAnimFrame CrewFrame;
		CrewFrame.Override = Crew;
		const double T1 = FPlatformTime::Seconds();
		for (int32 c = 0; c < 2; ++c)
		{
			FVerseAnimEvalInfo Info;
			Rig.Evaluate(Frame[c], Fps[c].GetIdleTime(), CS, &Info);
			Samples += Info.Samples;
		}
		for (int32 c = 0; c < 12; ++c)
		{
			CrewFrame.OverrideTime = (f + c * 7) / 60.f;
			CrewFrame.bOverrideLoop = true;
			Rig.Evaluate(CrewFrame, 0.f, CS);
		}
		const double T2 = FPlatformTime::Seconds();
		GameThread += T1 - T0;
		Evaluation += T2 - T1;
	}
	const double GameMs = GameThread * 1000.0 / Frames;
	const double EvalMs = Evaluation * 1000.0 / Frames;
	FReport Report;
	Report.SetNumberField(TEXT("fps_characters"), 2);
	Report.SetNumberField(TEXT("crew"), 12);
	Report.SetNumberField(TEXT("frames"), Frames);
	Report.SetNumberField(TEXT("state_update_ms_per_frame"), GameMs);
	Report.SetNumberField(TEXT("evaluation_ms_per_frame_single_thread"), EvalMs);
	Report.SetNumberField(TEXT("total_ms_per_frame_single_thread"), GameMs + EvalMs);
	Report.SetNumberField(TEXT("fps_samples_per_frame"), static_cast<double>(Samples) / Frames);
	Report.SetNumberField(TEXT("budget_ms"), 0.4);
	WriteProof(TEXT("13.10"), TEXT("anim_cost.json"), Report);
	AddInfo(FString::Printf(TEXT("state %.3f ms + evaluation %.3f ms per frame for 2 FPS + 12 crew"), GameMs, EvalMs));
	// Even with evaluation on the game thread (no worker threads) the whole cost stays in budget.
	TestTrue(FString::Printf(TEXT("animation %.3f ms per frame, at most 0.4"), GameMs + EvalMs), GameMs + EvalMs <= 0.4);
	return true;
}

// WP13.5: the owner's body hides the head and renders first person; the world body is the shadow body.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAnimFirstPersonTest, "Verse.Anim.FirstPerson.Setup", VerseAnimTest::Flags)
bool FVerseAnimFirstPersonTest::RunTest(const FString& Parameters)
{
	USkeletalMesh* Mesh = ReferenceMesh();
	if (!TestNotNull(TEXT("SK_Commander_M is imported"), Mesh))
	{
		return false;
	}
	USkeletalMeshComponent* World = NewObject<USkeletalMeshComponent>(GetTransientPackage());
	USkeletalMeshComponent* Owner = NewObject<USkeletalMeshComponent>(GetTransientPackage());
	UCameraComponent* Camera = NewObject<UCameraComponent>(GetTransientPackage());
	World->SetSkeletalMesh(Mesh);
	Owner->SetSkeletalMesh(Mesh);
	UVerseFirstPersonLibrary::ConfigureOwnerView(Owner, World, Camera);
	TestTrue(TEXT("owner body renders first person"), Owner->FirstPersonPrimitiveType == EFirstPersonPrimitiveType::FirstPerson);
	TestTrue(TEXT("world body is the world-space representation"), World->FirstPersonPrimitiveType == EFirstPersonPrimitiveType::WorldSpaceRepresentation);
	TestTrue(TEXT("owner body hides the head"), Owner->IsBoneHiddenByName(UVerseFirstPersonLibrary::HiddenBone));
	TestFalse(TEXT("world body keeps the head"), World->IsBoneHiddenByName(UVerseFirstPersonLibrary::HiddenBone));
	TestTrue(TEXT("camera scales first-person primitives"), Camera->bEnableFirstPersonScale && Camera->FirstPersonScale < 1.f);
	TestTrue(TEXT("camera has a first-person field of view"), Camera->bEnableFirstPersonFieldOfView);
	TestFalse(TEXT("the owner body casts no shadow (the world body does)"), Owner->CastShadow);
	return true;
}

// Pure solver checks that need no asset.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAnimMathTest, "Verse.Anim.Math.TwoBone", VerseAnimTest::Flags)
bool FVerseAnimMathTest::RunTest(const FString& Parameters)
{
	for (int32 Case = 0; Case < 200; ++Case)
	{
		FRandomStream Rng(1000 + Case);
		FTransform Upper(FQuat::Identity, FVector(0, 0, 100));
		FTransform Lower(FQuat::Identity, FVector(0, 30, 70));
		FTransform End(FQuat::Identity, FVector(0, 0, 40));
		const FVector Target(Rng.FRandRange(-30, 30), Rng.FRandRange(-30, 30), Rng.FRandRange(50, 80));
		const double L1 = FVector::Dist(Upper.GetLocation(), Lower.GetLocation());
		const double L2 = FVector::Dist(Lower.GetLocation(), End.GetLocation());
		const float Miss = VerseAnim::SolveTwoBone(Upper, Lower, End, Target);
		TestTrue(TEXT("upper length kept"), FMath::IsNearlyEqual(FVector::Dist(Upper.GetLocation(), Lower.GetLocation()), L1, 1e-3));
		TestTrue(TEXT("lower length kept"), FMath::IsNearlyEqual(FVector::Dist(Lower.GetLocation(), End.GetLocation()), L2, 1e-3));
		TestTrue(FString::Printf(TEXT("reachable target hit (%.4f cm)"), Miss), Miss < 0.01f);
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
