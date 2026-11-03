#include "Crew/VerseCrewPawn.h"

#include "Components/CapsuleComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/SceneComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/SpotLightComponent.h"
#include "Components/TextRenderComponent.h"
#include "Engine/SkeletalMesh.h"

namespace
{
	constexpr float PawnCapsuleHalfHeightCm = 90.f;
	constexpr float PawnCapsuleRadiusCm = 35.f;
}

AVerseCrewPawn::AVerseCrewPawn()
{
	PrimaryActorTick.bCanEverTick = false;
	SetCanBeDamaged(false);
	bReplicates = false;
	AutoPossessAI = EAutoPossessAI::Disabled;

	Capsule = CreateDefaultSubobject<UCapsuleComponent>(TEXT("Capsule"));
	Capsule->InitCapsuleSize(PawnCapsuleRadiusCm, PawnCapsuleHalfHeightCm);
	Capsule->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
	Capsule->SetCollisionResponseToAllChannels(ECR_Ignore);
	Capsule->SetCollisionResponseToChannel(ECC_Visibility, ECR_Block);
	Capsule->SetGenerateOverlapEvents(false);
	Capsule->SetCanEverAffectNavigation(false);
	Capsule->SetHiddenInGame(true);
	RootComponent = Capsule;

	Body = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Body"));
	Body->SetupAttachment(Capsule);
	Body->SetRelativeLocation(FVector(0.f, 0.f, -PawnCapsuleHalfHeightCm));
	// An imported mesh's front is local +Y (contracts/coordinates.md 3.3); the pawn's forward is +X.
	Body->SetRelativeRotation(FRotator(0.f, -90.f, 0.f));
	Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Body->SetGenerateOverlapEvents(false);
	Body->SetCanEverAffectNavigation(false);
	Body->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::OnlyTickPoseWhenRendered;

	BeaconLight = CreateDefaultSubobject<UPointLightComponent>(TEXT("Beacon"));
	BeaconLight->SetupAttachment(Capsule);
	BeaconLight->SetRelativeLocation(FVector(0.f, 0.f, 125.f));
	BeaconLight->SetCastShadows(false);
	BeaconLight->SetAttenuationRadius(140.f);
	BeaconLight->SetIntensityUnits(ELightUnits::Lumens);
	BeaconLight->SetIntensity(0.f);
	BeaconLight->SetVisibility(false);

	Ring = CreateDefaultSubobject<USpotLightComponent>(TEXT("Ring"));
	Ring->SetupAttachment(Capsule);
	Ring->SetRelativeLocation(FVector(0.f, 0.f, -PawnCapsuleHalfHeightCm + 60.f));
	Ring->SetRelativeRotation(FRotator(-90.f, 0.f, 0.f));
	Ring->SetCastShadows(false);
	Ring->SetAttenuationRadius(120.f);
	Ring->SetInnerConeAngle(18.f);
	Ring->SetOuterConeAngle(26.f);
	Ring->SetIntensityUnits(ELightUnits::Lumens);
	Ring->SetIntensity(60.f);

	Nameplate = CreateDefaultSubobject<UTextRenderComponent>(TEXT("Nameplate"));
	Nameplate->SetupAttachment(Capsule);
	Nameplate->SetRelativeLocation(FVector(0.f, 0.f, 145.f));
	Nameplate->SetHorizontalAlignment(EHTA_Center);
	Nameplate->SetWorldSize(16.f);
	Nameplate->SetTextRenderColor(FColor(232, 220, 196));
	Nameplate->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Nameplate->SetHiddenInGame(true);
}

void AVerseCrewPawn::SetupMember(const FVerseCrewMember& Member, const FVerseCrewLook& Look, USkeletalMesh* Mesh, const FVerseCrewTuning& Tuning)
{
	MemberId = Member.Id;
	CrewRole = Member.Role;
	// A pooled pawn already wears the mesh; setting it again rebuilds its render state.
	if (Mesh && Body->GetSkeletalMeshAsset() != Mesh)
	{
		Body->SetSkeletalMeshAsset(Mesh);
	}
	BeaconLight->SetRelativeLocation(FVector(0.f, 0.f, Tuning.BeaconHeightCm - PawnCapsuleHalfHeightCm));
	Nameplate->SetRelativeLocation(FVector(0.f, 0.f, Tuning.NameplateHeightCm - PawnCapsuleHalfHeightCm));
	// Names are data from the roster, never a literal of this module (parity N-02).
	Nameplate->SetText(FText::AsCultureInvariant(Member.Name));
	ApplyLook(Look);
#if WITH_EDITOR
	SetActorLabel(FString::Printf(TEXT("Crew_%s"), *Member.Id.Replace(TEXT(":"), TEXT("_"))));
#endif
}

void AVerseCrewPawn::ApplyLook(const FVerseCrewLook& Look)
{
	RankId = Look.RankId;
	Uniform = Look.Uniform;
	// Custom primitive data for the crew material of WP13: 0-2 tile colour, 3 accent hue,
	// 4-9 the six plate slots.
	Body->SetCustomPrimitiveDataFloat(0, Look.Tile.R);
	Body->SetCustomPrimitiveDataFloat(1, Look.Tile.G);
	Body->SetCustomPrimitiveDataFloat(2, Look.Tile.B);
	Body->SetCustomPrimitiveDataFloat(3, Look.AccentHue);
	for (int32 Slot = 0; Slot < 6; ++Slot)
	{
		Body->SetCustomPrimitiveDataFloat(4 + Slot, Look.PlateLit.IsValidIndex(Slot) && Look.PlateLit[Slot] ? 1.f : 0.f);
	}
}

void AVerseCrewPawn::ApplyDuty(const FVerseCrewDutyLook& Look)
{
	DutyLook = Look;
	Duty = Look.Duty;
	Beacon = Look.Beacon;
	BeaconLight->SetLightColor(Look.Colour);
	BeaconLight->SetVisibility(Look.Beacon != EVerseCrewBeacon::None);
	BeaconLight->SetIntensity(Look.Beacon == EVerseCrewBeacon::None ? 0.f : 250.f);
	// The ring is grey off duty (parity E-11).
	Ring->SetLightColor(Look.bOnDuty ? Look.Colour : FLinearColor(0.35f, 0.36f, 0.38f));
	Body->SetCustomPrimitiveDataFloat(10, static_cast<float>(static_cast<uint8>(Look.Duty)));
}

void AVerseCrewPawn::SetActivity(EVerseCrewActivity NewActivity, const FVerseCrewTuning& Tuning)
{
	if (Activity == NewActivity)
	{
		return;
	}
	Activity = NewActivity;
	const bool bSit = NewActivity == EVerseCrewActivity::SitType || NewActivity == EVerseCrewActivity::SitRest
		|| NewActivity == EVerseCrewActivity::Listen || NewActivity == EVerseCrewActivity::Talk;
	const bool bSleep = NewActivity == EVerseCrewActivity::Sleep;
	FVector Offset(0.f, 0.f, -PawnCapsuleHalfHeightCm);
	FRotator Rotation(0.f, -90.f, 0.f);
	if (bSit)
	{
		Offset.Z -= Tuning.SitDropCm;
	}
	if (bSleep)
	{
		Offset.Z = -PawnCapsuleHalfHeightCm + 20.f;
		Rotation = FRotator(0.f, -90.f, 90.f);
	}
	Body->SetRelativeLocationAndRotation(Offset, Rotation);
}

void AVerseCrewPawn::SetSelected(bool bInSelected)
{
	bSelected = bInSelected;
	Nameplate->SetHiddenInGame(!bInSelected);
}

void AVerseCrewPawn::UpdateBeacon(double Seconds)
{
	if (Beacon != EVerseCrewBeacon::SlowPulse || DutyLook.PulseSeconds <= 0.f)
	{
		return;
	}
	const double Phase = FMath::Fmod(Seconds, static_cast<double>(DutyLook.PulseSeconds)) / DutyLook.PulseSeconds;
	const float Wave = 0.5f + 0.5f * FMath::Cos(static_cast<float>(Phase) * 2.f * PI);
	BeaconLight->SetIntensity(60.f + 190.f * Wave);
}

// ---------------------------------------------------------------------------------------------

AVerseCompanionDrone::AVerseCompanionDrone()
{
	PrimaryActorTick.bCanEverTick = false;
	bReplicates = false;
	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	RootComponent = Root;
	Glow = CreateDefaultSubobject<UPointLightComponent>(TEXT("Glow"));
	Glow->SetupAttachment(Root);
	Glow->SetCastShadows(false);
	Glow->SetAttenuationRadius(160.f);
	Glow->SetIntensityUnits(ELightUnits::Lumens);
	Glow->SetIntensity(180.f);
	Glow->SetLightColor(FLinearColor::FromSRGBColor(FColor(200, 162, 74)));
}
