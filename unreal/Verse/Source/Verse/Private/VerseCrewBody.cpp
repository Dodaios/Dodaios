#include "VerseCrewBody.h"

#include "Anim/VerseAnimInstance.h"
#include "Anim/VerseAnimTypes.h"
#include "Components/SkeletalMeshComponent.h"
#include "Crew/VerseCrewPawn.h"
#include "Crew/VerseCrewTypes.h"
#include "Engine/SkeletalMesh.h"
#include "Ranks/VerseRankLook.h"

namespace VerseCrewBodyPrivate
{
	/** `library.model(kind)`: the kind's models in the contract's order (F before M), by seed. */
	const TCHAR* Officers[] = {
		TEXT("/Game/Verse/Characters/Commander/SK_Commander_F.SK_Commander_F"),
		TEXT("/Game/Verse/Characters/Commander/SK_Commander_M.SK_Commander_M"),
	};
	const TCHAR* Technicians[] = {
		TEXT("/Game/Verse/Characters/Crew/SK_Crew_F.SK_Crew_F"),
		TEXT("/Game/Verse/Characters/Crew/SK_Crew_M.SK_Crew_M"),
	};
	/** The mesh faces +Y in its own space (coordinates.md 3.3). */
	const FRotator MeshBaseRotation(0.f, -90.f, 0.f);

	/** The crew pawn's capsule half height (VerseCrewPawn.cpp): the floor under the pawn. */
	constexpr float CapsuleHalfHeightCm = 90.f;

	const VerseRanks::FRank* RankById(const FString& Id)
	{
		for (const VerseRanks::FRank& Rank : VerseRanks::Ladder())
		{
			if (Id == Rank.Id)
			{
				return &Rank;
			}
		}
		return nullptr;
	}
}

UVerseCrewBody::UVerseCrewBody()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.TickGroup = TG_PostPhysics;
}

USkeletalMesh* UVerseCrewBody::MeshFor(const AVerseCrewPawn& Pawn)
{
	using namespace VerseCrewBodyPrivate;
	const bool bTechnician = Pawn.CrewRole == EVerseCrewRole::Technician;
	const TCHAR* const* Paths = bTechnician ? Technicians : Officers;
	const uint32 Seed = VerseCrew::Hash32(Pawn.MemberId);
	return LoadObject<USkeletalMesh>(nullptr, Paths[Seed % 2u], nullptr, LOAD_NoWarn | LOAD_Quiet);
}

FName UVerseCrewBody::ClipFor(EVerseCrewActivity Activity)
{
	switch (Activity)
	{
	case EVerseCrewActivity::SitType:
		return TEXT("A_Crew_Sit_Type");
	case EVerseCrewActivity::SitRest:
		return TEXT("A_Crew_Sit_Idle");
	case EVerseCrewActivity::Listen:
		return TEXT("A_Crew_Listen");
	case EVerseCrewActivity::Talk:
		return TEXT("A_Crew_Talk");
	case EVerseCrewActivity::Sleep:
		return TEXT("A_Crew_Bunk");
	case EVerseCrewActivity::StandAlert:
		return TEXT("A_Crew_Stand_Type");
	case EVerseCrewActivity::Walk:
		return TEXT("A_Crew_Walk");
	default:
		// stand_wait, stand_guard, stand_rest: three.js falls back to its idle (no wave clip here).
		return TEXT("A_Crew_Stand");
	}
}

UVerseCrewBody* UVerseCrewBody::Dress(AVerseCrewPawn* Pawn)
{
	if (Pawn == nullptr || Pawn->Body == nullptr)
	{
		return nullptr;
	}
	if (UVerseCrewBody* Existing = Pawn->FindComponentByClass<UVerseCrewBody>())
	{
		return Existing;
	}
	USkeletalMesh* Mesh = MeshFor(*Pawn);
	if (Mesh == nullptr)
	{
		return nullptr;
	}
	USkeletalMeshComponent* Body = Pawn->Body;
	Body->SetSkeletalMeshAsset(Mesh);
	Body->SetAnimInstanceClass(UVerseAnimInstance::StaticClass());
	UVerseCrewBody* Component = NewObject<UVerseCrewBody>(Pawn, TEXT("CrewBody"));
	Component->RegisterComponent();
	Component->AddTickPrerequisiteActor(Pawn);
	Component->Redress(*Pawn);
	return Component;
}

void UVerseCrewBody::Redress(AVerseCrewPawn& Pawn)
{
	using namespace VerseCrewBodyPrivate;
	DressedRank = Pawn.RankId;
	const VerseRanks::FRank* Rank = RankById(Pawn.RankId);
	if (Rank == nullptr)
	{
		Rank = &VerseRanks::ForLevel(1);
	}
	// Technicians wear the deck's work uniform whatever their record (useCrewLife.ts).
	const FName Tier = Pawn.CrewRole == EVerseCrewRole::Technician ? FName(TEXT("deck")) : FName(Rank->Tier);
	VerseRanks::ApplyLook(Pawn.Body, Tier, Rank->Plate);
}

void UVerseCrewBody::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	Animate(DeltaTime);
}

void UVerseCrewBody::Animate(float DeltaTime)
{
	using namespace VerseCrewBodyPrivate;
	AVerseCrewPawn* Pawn = Cast<AVerseCrewPawn>(GetOwner());
	USkeletalMeshComponent* Body = Pawn ? Pawn->Body.Get() : nullptr;
	if (Body == nullptr || DeltaTime <= 0.f)
	{
		return;
	}
	if (Pawn->RankId != DressedRank)
	{
		Redress(*Pawn);
	}
	// The clips carry the pose: root on the floor for sitting (the seat is in the clip), on the
	// mattress for the bunk. Undo the test body's drop and roll the pawn applies (SetActivity).
	const bool bSleep = Pawn->Activity == EVerseCrewActivity::Sleep;
	const FVector Offset = Body->GetRelativeLocation();
	const float FloorZ = -CapsuleHalfHeightCm;
	Body->SetRelativeLocationAndRotation(FVector(Offset.X, Offset.Y, bSleep ? Offset.Z : FloorZ), MeshBaseRotation);

	const FVector Location = Pawn->GetActorLocation();
	const float Speed = bHasLast ? static_cast<float>(FVector::Dist2D(Location, LastLocation) / 100.0 / DeltaTime) : 0.f;
	LastLocation = Location;
	bHasLast = true;
	bWalking = Speed > WalkAbove || (bWalking && Speed > 0.5f * WalkAbove) || Pawn->Activity == EVerseCrewActivity::Walk;
	const FName Next = bWalking ? FName(TEXT("A_Crew_Walk")) : ClipFor(Pawn->Activity);
	if (Next != Clip)
	{
		Clip = Next;
		// Crew idling side by side must not breathe in step (actor.ts play).
		ClipTime = static_cast<float>(VerseCrew::Hash32(Pawn->MemberId) % 1000u) / 1000.f;
	}
	ClipTime += DeltaTime * (bWalking ? FMath::Max(0.3f, Speed / ClipWalkSpeed) : 1.f);
	ClipTime = FMath::Fmod(ClipTime, 3600.f);
	if (UVerseAnimInstance* Anim = Cast<UVerseAnimInstance>(Body->GetAnimInstance()))
	{
		FVerseAnimInputs Inputs;
		Inputs.Weapon = EVerseAnimWeapon::None;
		Inputs.bOverrideLoop = true;
		Inputs.OverrideClip = Clip;
		Inputs.OverrideTime = ClipTime;
		Anim->SetExternalInputs(Inputs);
	}
}
