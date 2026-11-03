#include "Gadgets/VerseBreachCharge.h"

#include "Combat/VerseGadgetDefinition.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Damage/VerseDamageService.h"
#include "Destruction/VerseDestructionInterfaces.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Pawn.h"
#include "Net/UnrealNetwork.h"
#include "Gadgets/VerseBulwark.h"
#include "Stubs/VerseNullStubs.h"
#include "Projectiles/VersePlaceholderArt.h"
#include "VerseCollision.h"
#include "VerseGameplayTags.h"
#include "Weapons/VerseCombatEvents.h"

AVerseBreachCharge::AVerseBreachCharge()
{
	PrimaryActorTick.bCanEverTick = true;
	bReplicates = true;
	SetReplicatingMovement(false);

	Look = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Look"));
	SetRootComponent(Look);
	Look->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Look->SetRelativeScale3D(FVector(0.1, 0.3, 0.3));
}

void AVerseBreachCharge::BeginPlay()
{
	Super::BeginPlay();
	if (UStaticMesh* Box = VersePlaceholderArt::Mesh(VersePlaceholderArt::EShape::Box))
	{
		Look->SetStaticMesh(Box); // placeholder look until WP14
	}
}

void AVerseBreachCharge::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	DOREPLIFETIME_CONDITION(AVerseBreachCharge, SpawnEvent, COND_InitialOnly);
}

void AVerseBreachCharge::InitCharge(const UVerseGadgetDefinition& Def, AActor* InOwnerPawn, uint16 InPieceIndex,
	const FVector& SurfaceNormal, double PlantCompleteTime)
{
	Definition = &Def;
	OwnerPawn = InOwnerPawn;
	OwnerId = VerseCombatIds::IdOf(InOwnerPawn);
	PieceIndex = InPieceIndex;
	Normal = SurfaceNormal.GetSafeNormal(UE_SMALL_NUMBER, FVector::UpVector);
	DetonateAt = PlantCompleteTime + Def.Lifetime; // Lifetime is the fuse for a breach charge
	bArmed = true;
	bDetonated = false;
	Raise(EVerseGadgetEventKind::Plant);
	VerseCombatEvents::RaiseNoise(this, VerseTags::Noise_Gadget_BreachPlant, OwnerId, GetActorLocation());
}

void AVerseBreachCharge::Raise(EVerseGadgetEventKind Kind)
{
	FVerseGadgetEvent E;
	E.Kind = Kind;
	E.GadgetId = Definition ? Definition->GadgetId : FName(TEXT("breach_charge"));
	E.OwnerId = OwnerId;
	E.Location = GetActorLocation();
	E.ServerTime = VerseCombatEvents::ServerTime(this);
	VerseCombatEvents::RaiseGadget(this, E);
	if (Kind == EVerseGadgetEventKind::Plant)
	{
		SpawnEvent = E; // reaches clients with the actor's first bunch (OnRep_SpawnEvent)
		return;
	}
	MulticastGadgetEvent(E);
}

void AVerseBreachCharge::OnRep_SpawnEvent()
{
	if (!HasAuthority())
	{
		VerseCombatEvents::RaiseGadget(this, SpawnEvent);
	}
}

void AVerseBreachCharge::MulticastGadgetEvent_Implementation(const FVerseGadgetEvent& Event)
{
	if (!HasAuthority())
	{
		VerseCombatEvents::RaiseGadget(this, Event);
	}
}

FVector AVerseBreachCharge::PelvisOf(const AActor* Pawn)
{
	if (!Pawn)
	{
		return FVector::ZeroVector;
	}
	if (const USkeletalMeshComponent* Mesh = Pawn->FindComponentByClass<USkeletalMeshComponent>())
	{
		const int32 Bone = Mesh->GetBoneIndex(TEXT("Hips"));
		if (Bone != INDEX_NONE)
		{
			return Mesh->GetBoneLocation(TEXT("Hips"));
		}
	}
	return Pawn->GetActorLocation();
}

void AVerseBreachCharge::ServerAdvance(double Now)
{
	if (HasAuthority() && bArmed && !bDetonated && Now >= DetonateAt)
	{
		Detonate(Now);
	}
}

void AVerseBreachCharge::Detonate(double Now)
{
	if (!HasAuthority() || bDetonated || !Definition)
	{
		return;
	}
	bDetonated = true;
	bArmed = false;
	DetonatedTime = Now;
	LastVictims.Reset();

	UWorld* World = GetWorld();
	const FVector Centre = GetActorLocation();
	AActor* OwnerActor = OwnerPawn.Get();

	Raise(EVerseGadgetEventKind::Detonate);
	VerseCombatEvents::RaiseNoise(this, VerseTags::Noise_Gadget_BreachDetonate, OwnerId, Centre);

	// Pawns: pelvis within PawnRadius and in line of sight on VerseBolt from the charge.
	const double RadiusCm = double(Definition->PawnRadius) * 100.0;
	UVerseDamageService* DamageService = UVerseDamageService::Get(this);
	if (World && RadiusCm > 0.0)
	{
		for (TActorIterator<APawn> It(World); It; ++It)
		{
			APawn* Pawn = *It;
			if (!Pawn || (Pawn == OwnerActor && !Definition->bSelfDamage))
			{
				continue;
			}
			const FVector Pelvis = PelvisOf(Pawn);
			const double R = FVector::Dist(Pelvis, Centre);
			if (R >= RadiusCm)
			{
				continue;
			}
			// Start a hair off the surface so the planted piece itself does not count as cover.
			const FVector From = Centre + Normal * 2.0;
			FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseBreachSight), false, this);
			Params.AddIgnoredActor(Pawn);
			FHitResult Hit;
			const bool bBlocked = R > 2.0 && World->LineTraceSingleByChannel(Hit, From, Pelvis, VerseCollision::Bolt, Params);
			if (bBlocked)
			{
				continue;
			}
			const float DistanceM = float(R / 100.0);
			const float Damage = Definition->PawnDamageAt(DistanceM);
			if (Damage <= 0.f)
			{
				continue;
			}
			FVerseHitEvent HitEvent;
			HitEvent.WeaponId = Definition->GadgetId;
			HitEvent.Source = EVerseDamageSource::Gadget;
			HitEvent.Zone = EVerseHitZone::LowerTorso; // zone multiplier 1.0: the damage is already final
			HitEvent.Bone = TEXT("Hips");
			HitEvent.ImpactWorld = Pelvis;
			HitEvent.Direction = (Pelvis - Centre).GetSafeNormal(UE_SMALL_NUMBER, Normal);
			HitEvent.DistanceM = DistanceM;
			HitEvent.Damage = Damage;
			if (DamageService)
			{
				DamageService->ApplyHit(OwnerActor, Pawn, HitEvent);
			}
			FVerseBreachVictim& V = LastVictims.AddDefaulted_GetRef();
			V.Pawn = Pawn;
			V.DistanceM = DistanceM;
			V.Damage = HitEvent.Damage;
		}
	}

	// The target piece goes to its breach result (destruction.md 3.2).
	FVersePieceDamage Piece;
	Piece.PieceIndex = PieceIndex;
	Piece.Amount = 0.f; // the breach result does not depend on hp; the cause decides
	Piece.Cause = EVerseFractureCause::Breach;
	Piece.Location = Centre;
	Piece.Direction = -Normal;
	Piece.InstigatorId = OwnerId;
	Piece.BreachRadiusCm = Definition->PieceBreachRadius;
	IVersePieceDamage* Target = PieceDamage ? PieceDamage : static_cast<IVersePieceDamage*>(GetMutableDefault<UVerseNullPieceDamage>());
	Target->ApplyPieceDamage(Piece);

	for (AVerseBulwark* Bulwark : AVerseBulwark::FindWithin(World, Centre, BulwarkClearRadiusCm))
	{
		Bulwark->RemoveBulwark(EVerseGadgetEventKind::Destroyed);
	}

	if (OnDetonated)
	{
		OnDetonated(this);
	}
	Destroy();
}

void AVerseBreachCharge::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	ServerAdvance(VerseCombatEvents::ServerTime(this));
}
