#include "LagComp/VerseLagCompensation.h"

#include "Components/SkeletalMeshComponent.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "PhysicsEngine/SkeletalBodySetup.h"

// ---------------------------------------------------------------------------------------------
// History

FVerseHitBodyHistory::FVerseHitBodyHistory(int32 InCapacity)
	: Capacity(FMath::Max(2, InCapacity))
{
	Ring.SetNum(Capacity);
}

const FVerseHitBodyPose& FVerseHitBodyHistory::At(int32 IndexFromOldest) const
{
	const int32 Oldest = (Head - Count + Capacity) % Capacity;
	return Ring[(Oldest + IndexFromOldest) % Capacity];
}

void FVerseHitBodyHistory::Push(FVerseHitBodyPose&& Pose)
{
	Ring[Head] = MoveTemp(Pose);
	Head = (Head + 1) % Capacity;
	Count = FMath::Min(Count + 1, Capacity);
}

double FVerseHitBodyHistory::OldestTime() const
{
	return Count > 0 ? At(0).Time : 0.0;
}

double FVerseHitBodyHistory::NewestTime() const
{
	return Count > 0 ? At(Count - 1).Time : 0.0;
}

bool FVerseHitBodyHistory::Sample(double Time, FVerseHitBodyPose& Out) const
{
	if (Count == 0)
	{
		return false;
	}
	if (Count == 1 || Time <= At(0).Time)
	{
		Out = At(0);
		return true;
	}
	if (Time >= At(Count - 1).Time)
	{
		Out = At(Count - 1);
		return true;
	}
	// Binary search for the pair around Time.
	int32 Lo = 0;
	int32 Hi = Count - 1;
	while (Hi - Lo > 1)
	{
		const int32 Mid = (Lo + Hi) / 2;
		if (At(Mid).Time <= Time)
		{
			Lo = Mid;
		}
		else
		{
			Hi = Mid;
		}
	}
	const FVerseHitBodyPose& P0 = At(Lo);
	const FVerseHitBodyPose& P1 = At(Hi);
	const double Span = P1.Time - P0.Time;
	const float Alpha = Span > 0.0 ? float((Time - P0.Time) / Span) : 0.f;

	Out.Time = Time;
	Out.Root.Blend(P0.Root, P1.Root, Alpha);
	Out.Capsules.Reset(P0.Capsules.Num());
	for (int32 I = 0; I < P0.Capsules.Num(); ++I)
	{
		const FVerseHitCapsule& C0 = P0.Capsules[I];
		// Bodies are matched by bone; a body missing in the later pose holds its earlier place.
		const FVerseHitCapsule* C1 = P1.Capsules.IsValidIndex(I) && P1.Capsules[I].Bone == C0.Bone
			? &P1.Capsules[I]
			: P1.Capsules.FindByPredicate([&C0](const FVerseHitCapsule& C) { return C.Bone == C0.Bone; });
		FVerseHitCapsule& C = Out.Capsules.Add_GetRef(C0);
		if (C1)
		{
			C.A = FMath::Lerp(C0.A, C1->A, double(Alpha));
			C.B = FMath::Lerp(C0.B, C1->B, double(Alpha));
			C.Radius = FMath::Lerp(C0.Radius, C1->Radius, Alpha);
			C.BoneTransform.Blend(C0.BoneTransform, C1->BoneTransform, Alpha);
		}
	}
	return true;
}

// ---------------------------------------------------------------------------------------------
// Subsystem

UVerseLagCompSubsystem* UVerseLagCompSubsystem::Get(const UObject* WorldContextObject)
{
	const UWorld* World = WorldContextObject ? WorldContextObject->GetWorld() : nullptr;
	return World ? World->GetSubsystem<UVerseLagCompSubsystem>() : nullptr;
}

void UVerseLagCompSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	PostTickHandle = FWorldDelegates::OnWorldPostActorTick.AddUObject(this, &UVerseLagCompSubsystem::OnPostActorTick);
}

void UVerseLagCompSubsystem::Deinitialize()
{
	FWorldDelegates::OnWorldPostActorTick.Remove(PostTickHandle);
	Targets.Reset();
	Super::Deinitialize();
}

void UVerseLagCompSubsystem::OnPostActorTick(UWorld* World, ELevelTick, float)
{
	if (World != GetWorld() || !World || World->GetNetMode() == NM_Client)
	{
		return;
	}
	Record(World->GetTimeSeconds());
}

void UVerseLagCompSubsystem::RegisterTarget(AActor* Target, FVerseHitBodyProvider Provider)
{
	if (!Target || !Provider)
	{
		return;
	}
	UnregisterTarget(Target);
	FTarget& T = Targets.AddDefaulted_GetRef();
	T.Actor = Target;
	T.Provider = MoveTemp(Provider);
}

void UVerseLagCompSubsystem::RegisterSkeletalTarget(AActor* Target, USkeletalMeshComponent* Mesh)
{
	if (!Target || !Mesh)
	{
		return;
	}
	TWeakObjectPtr<USkeletalMeshComponent> WeakMesh = Mesh;
	TWeakObjectPtr<AActor> WeakActor = Target;
	RegisterTarget(Target, [WeakMesh, WeakActor](FTransform& OutRoot, TArray<FVerseHitCapsule>& Out)
	{
		const USkeletalMeshComponent* M = WeakMesh.Get();
		const AActor* A = WeakActor.Get();
		if (!M || !A)
		{
			return;
		}
		OutRoot = A->GetActorTransform();
		const UPhysicsAsset* Phys = M->GetPhysicsAsset();
		if (!Phys)
		{
			return;
		}
		for (const TObjectPtr<USkeletalBodySetup>& Body : Phys->SkeletalBodySetups)
		{
			if (!Body)
			{
				continue;
			}
			const int32 BoneIndex = M->GetBoneIndex(Body->BoneName);
			if (BoneIndex == INDEX_NONE)
			{
				continue;
			}
			const FTransform BoneWorld = M->GetBoneTransform(BoneIndex);
			const EVerseHitZone Zone = ZoneForBone(Body->BoneName);
			const float Scale = float(BoneWorld.GetScale3D().GetAbsMax());
			for (const FKSphylElem& Sphyl : Body->AggGeom.SphylElems)
			{
				const FTransform Elem = Sphyl.GetTransform() * BoneWorld;
				const FVector Axis = Elem.GetUnitAxis(EAxis::Z) * (0.5 * Sphyl.Length * Scale);
				FVerseHitCapsule& C = Out.AddDefaulted_GetRef();
				C.Bone = Body->BoneName;
				C.Zone = Zone;
				C.A = Elem.GetLocation() - Axis;
				C.B = Elem.GetLocation() + Axis;
				C.Radius = Sphyl.Radius * Scale;
				C.BoneTransform = BoneWorld;
			}
			for (const FKSphereElem& Sphere : Body->AggGeom.SphereElems)
			{
				const FVector Centre = BoneWorld.TransformPosition(Sphere.Center);
				FVerseHitCapsule& C = Out.AddDefaulted_GetRef();
				C.Bone = Body->BoneName;
				C.Zone = Zone;
				C.A = Centre;
				C.B = Centre;
				C.Radius = Sphere.Radius * Scale;
				C.BoneTransform = BoneWorld;
			}
		}
	});
}

void UVerseLagCompSubsystem::UnregisterTarget(AActor* Target)
{
	Targets.RemoveAll([Target](const FTarget& T) { return !T.Actor.IsValid() || T.Actor.Get() == Target; });
}

void UVerseLagCompSubsystem::Record(double Now)
{
	Targets.RemoveAll([](const FTarget& T) { return !T.Actor.IsValid(); });
	for (FTarget& T : Targets)
	{
		if (T.History.Num() > 0 && T.History.NewestTime() >= Now)
		{
			continue; // one snapshot per server time
		}
		FVerseHitBodyPose Pose;
		Pose.Time = Now;
		T.Provider(Pose.Root, Pose.Capsules);
		T.History.Push(MoveTemp(Pose));
	}
}

double UVerseLagCompSubsystem::ClampRewindTime(double Now, double ViewTime)
{
	return FMath::Clamp(ViewTime, Now - MaxRewindS, Now);
}

bool UVerseLagCompSubsystem::GetPoseAt(const AActor* Target, double Time, FVerseHitBodyPose& Out) const
{
	for (const FTarget& T : Targets)
	{
		if (T.Actor.Get() == Target)
		{
			return T.History.Sample(Time, Out);
		}
	}
	return false;
}

bool UVerseLagCompSubsystem::TraceRewound(const FVector& Start, const FVector& End, double Now, double ViewTime,
	const AActor* Ignore, FVerseRewindHit& Out) const
{
	return TraceAt(Start, End, ClampRewindTime(Now, ViewTime), Ignore, Out);
}

bool UVerseLagCompSubsystem::TraceAt(const FVector& Start, const FVector& End, double Time, const AActor* Ignore,
	FVerseRewindHit& Out) const
{
	bool bHit = false;
	FVerseHitBodyPose Pose;
	for (const FTarget& T : Targets)
	{
		AActor* Actor = T.Actor.Get();
		if (!Actor || Actor == Ignore || !T.History.Sample(Time, Pose))
		{
			continue;
		}
		FVerseRewindHit Candidate;
		if (TracePose(Pose, Start, End, Candidate) && (!bHit || Candidate.Distance < Out.Distance))
		{
			Out = Candidate;
			Out.Actor = Actor;
			Out.PoseTime = Time;
			bHit = true;
		}
	}
	return bHit;
}

bool UVerseLagCompSubsystem::TracePose(const FVerseHitBodyPose& Pose, const FVector& Start, const FVector& End, FVerseRewindHit& Out)
{
	const FVector Delta = End - Start;
	const double Len = Delta.Size();
	if (Len <= UE_DOUBLE_SMALL_NUMBER)
	{
		return false;
	}
	const FVector Dir = Delta / Len;
	bool bHit = false;
	for (const FVerseHitCapsule& C : Pose.Capsules)
	{
		const double T = RayCapsule(Start, Dir, C.A, C.B, C.Radius);
		if (T >= 0.0 && T <= Len && (!bHit || T < Out.Distance))
		{
			bHit = true;
			Out.Distance = T;
			Out.Bone = C.Bone;
			Out.Zone = C.Zone;
			Out.ImpactWorld = Start + Dir * T;
			Out.ImpactBoneLocal = C.BoneTransform.InverseTransformPosition(Out.ImpactWorld);
		}
	}
	return bHit;
}

double UVerseLagCompSubsystem::RayCapsule(const FVector& Ro, const FVector& Rd, const FVector& Pa, const FVector& Pb, double R)
{
	// Start inside the capsule: hit at 0.
	const FVector Ba = Pb - Pa;
	const double Baba = FVector::DotProduct(Ba, Ba);
	{
		const double Along = Baba > 0.0 ? FMath::Clamp(FVector::DotProduct(Ro - Pa, Ba) / Baba, 0.0, 1.0) : 0.0;
		if (FVector::DistSquared(Ro, Pa + Ba * Along) <= R * R)
		{
			return 0.0;
		}
	}
	auto Sphere = [&Ro, &Rd, R](const FVector& C) -> double
	{
		const FVector Oc = Ro - C;
		const double B = FVector::DotProduct(Rd, Oc);
		const double Cc = FVector::DotProduct(Oc, Oc) - R * R;
		const double H = B * B - Cc;
		if (H < 0.0)
		{
			return -1.0;
		}
		const double T = -B - FMath::Sqrt(H);
		return T >= 0.0 ? T : -1.0;
	};
	if (Baba <= UE_DOUBLE_SMALL_NUMBER)
	{
		return Sphere(Pa);
	}
	const FVector Oa = Ro - Pa;
	const double Bard = FVector::DotProduct(Ba, Rd);
	const double Baoa = FVector::DotProduct(Ba, Oa);
	const double Rdoa = FVector::DotProduct(Rd, Oa);
	const double Oaoa = FVector::DotProduct(Oa, Oa);
	const double A = Baba - Bard * Bard;
	double Best = -1.0;
	if (A > UE_DOUBLE_SMALL_NUMBER)
	{
		const double B = Baba * Rdoa - Baoa * Bard;
		const double C = Baba * Oaoa - Baoa * Baoa - R * R * Baba;
		const double H = B * B - A * C;
		if (H >= 0.0)
		{
			const double T = (-B - FMath::Sqrt(H)) / A;
			const double Y = Baoa + T * Bard;
			if (T >= 0.0 && Y > 0.0 && Y < Baba)
			{
				return T; // cylinder body
			}
		}
	}
	// End caps.
	const double Ta = Sphere(Pa);
	const double Tb = Sphere(Pb);
	if (Ta >= 0.0)
	{
		Best = Ta;
	}
	if (Tb >= 0.0 && (Best < 0.0 || Tb < Best))
	{
		Best = Tb;
	}
	return Best;
}

EVerseHitZone UVerseLagCompSubsystem::ZoneForBone(FName Bone)
{
	const FString S = Bone.ToString();
	if (S == TEXT("Head") || S == TEXT("Camera"))
	{
		return EVerseHitZone::Head;
	}
	if (S == TEXT("Neck"))
	{
		return EVerseHitZone::Neck;
	}
	if (S == TEXT("Spine_02") || S == TEXT("Spine_03") || S.StartsWith(TEXT("Clavicle")))
	{
		return EVerseHitZone::UpperTorso;
	}
	if (S == TEXT("Spine_01") || S == TEXT("Hips") || S == TEXT("Pelvis"))
	{
		return EVerseHitZone::LowerTorso;
	}
	if (S.StartsWith(TEXT("UpperArm")) || S.StartsWith(TEXT("LowerArm")) || S.StartsWith(TEXT("Hand")))
	{
		return EVerseHitZone::Arm;
	}
	if (S.StartsWith(TEXT("Thigh")) || S.StartsWith(TEXT("Calf")) || S.StartsWith(TEXT("Foot")) || S.StartsWith(TEXT("Ball")))
	{
		return EVerseHitZone::Leg;
	}
	return EVerseHitZone::UpperTorso;
}
