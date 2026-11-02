#include "Gadgets/VerseBulwark.h"

#include "Combat/VerseGadgetDefinition.h"
#include "Components/BoxComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Damage/VerseDamageService.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/App.h"
#include "Net/UnrealNetwork.h"
#include "UObject/ConstructorHelpers.h"
#include "VerseCollision.h"
#include "VerseGameplayTags.h"
#include "Weapons/VerseCombatEvents.h"

namespace
{
	const FLinearColor BulwarkAmber(1.0f, 0.55f, 0.08f, 0.35f);
}

AVerseBulwark::AVerseBulwark()
{
	PrimaryActorTick.bCanEverTick = true;
	bReplicates = true;
	SetReplicatingMovement(false);

	Field = CreateDefaultSubobject<UBoxComponent>(TEXT("Field"));
	SetRootComponent(Field);
	Field->SetBoxExtent(FVector(5.f, 90.f, 70.f));
	Field->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
	Field->SetCollisionObjectType(ECC_WorldDynamic);
	Field->SetCollisionResponseToAllChannels(ECR_Ignore);
	Field->SetCollisionResponseToChannel(ECC_Pawn, ECR_Block);
	Field->SetCollisionResponseToChannel(VerseCollision::Bolt, ECR_Block);
	Field->SetCollisionResponseToChannel(VerseCollision::Sight, ECR_Ignore);
	Field->SetCollisionResponseToChannel(ECC_Visibility, ECR_Ignore);
	Field->SetCollisionResponseToChannel(ECC_Camera, ECR_Ignore);
	Field->SetGenerateOverlapEvents(false);

	Look = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Look"));
	Look->SetupAttachment(Field);
	Look->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Look->SetCastShadow(false);
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cube(TEXT("/Game/Verse/Test/WP02/SM_WP02_Box.SM_WP02_Box"));
	if (Cube.Succeeded())
	{
		Look->SetStaticMesh(Cube.Object);
	}
}

void AVerseBulwark::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	DOREPLIFETIME(AVerseBulwark, Health);
	DOREPLIFETIME(AVerseBulwark, MaxHealth);
	DOREPLIFETIME_CONDITION(AVerseBulwark, SpawnEvent, COND_InitialOnly);
}

void AVerseBulwark::InitBulwark(const UVerseGadgetDefinition& Def, AActor* InOwnerPawn, double Now)
{
	Definition = &Def;
	OwnerPawn = InOwnerPawn;
	OwnerId = VerseCombatIds::IdOf(InOwnerPawn);
	MaxHealth = Def.MaxHealth;
	Health = Def.MaxHealth;
	ExpireAt = Now + Def.Lifetime;
	NextHumAt = Now + HumIntervalS;
	bActive = true;

	// Size is w x h x d in metres; the actor stands on the floor, local X faces the deployer's front.
	const FVector Half(Def.Size.Z * 50.0, Def.Size.X * 50.0, Def.Size.Y * 50.0);
	Field->SetBoxExtent(Half);
	Look->SetRelativeScale3D(FVector(Def.Size.Z, Def.Size.X, Def.Size.Y));
	Look->SetRelativeLocation(FVector::ZeroVector);
	AddActorWorldOffset(FVector(0.0, 0.0, Half.Z));

	if (FApp::CanEverRender() && Look->GetMaterial(0))
	{
		if (UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Look->GetMaterial(0), this))
		{
			Mid->SetVectorParameterValue(TEXT("Color"), BulwarkAmber);
			Look->SetMaterial(0, Mid);
		}
	}

	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		DeathHandle = Hub->OnDeath.AddUObject(this, &AVerseBulwark::OnOwnerDeath);
	}
	Raise(EVerseGadgetEventKind::Deploy);
	VerseCombatEvents::RaiseNoise(this, VerseTags::Noise_Gadget_BulwarkDeploy, OwnerId, GetActorLocation());
}

void AVerseBulwark::Raise(EVerseGadgetEventKind Kind)
{
	FVerseGadgetEvent E;
	E.Kind = Kind;
	E.GadgetId = Definition ? Definition->GadgetId : FName(TEXT("bulwark"));
	E.OwnerId = OwnerId;
	E.Location = GetActorLocation();
	E.ServerTime = VerseCombatEvents::ServerTime(this);
	VerseCombatEvents::RaiseGadget(this, E);
	if (Kind == EVerseGadgetEventKind::Deploy)
	{
		SpawnEvent = E; // reaches clients with the actor's first bunch (OnRep_SpawnEvent)
		return;
	}
	MulticastGadgetEvent(E);
}

void AVerseBulwark::OnRep_SpawnEvent()
{
	if (!HasAuthority())
	{
		VerseCombatEvents::RaiseGadget(this, SpawnEvent);
	}
}

void AVerseBulwark::MulticastGadgetEvent_Implementation(const FVerseGadgetEvent& Event)
{
	if (!HasAuthority())
	{
		VerseCombatEvents::RaiseGadget(this, Event);
	}
}

void AVerseBulwark::ApplyBoltDamage(float Damage, AActor* /*Instigator*/)
{
	if (!HasAuthority() || !bActive)
	{
		return;
	}
	Health = FMath::Max(0.f, Health - FMath::Max(0.f, Damage));
	if (Health <= 0.f)
	{
		RemoveBulwark(EVerseGadgetEventKind::Destroyed);
	}
}

void AVerseBulwark::ServerAdvance(double Now)
{
	if (!HasAuthority() || !bActive)
	{
		return;
	}
	if (Now >= ExpireAt)
	{
		RemoveBulwark(EVerseGadgetEventKind::Expired);
		return;
	}
	if (Now >= NextHumAt)
	{
		NextHumAt = Now + HumIntervalS;
		VerseCombatEvents::RaiseNoise(this, VerseTags::Noise_Gadget_BulwarkHum, OwnerId, GetActorLocation());
	}
}

void AVerseBulwark::RemoveBulwark(EVerseGadgetEventKind Kind)
{
	if (!bActive)
	{
		return;
	}
	bActive = false;
	// Gone on this tick: no bolt or pawn meets it again.
	SetActorEnableCollision(false);
	Raise(Kind);
	if (OnRemoved)
	{
		OnRemoved(this);
	}
	Destroy();
}

void AVerseBulwark::OnOwnerDeath(const FVerseDeathEvent& Death)
{
	if (Death.VictimId == OwnerId)
	{
		RemoveBulwark(EVerseGadgetEventKind::Destroyed);
	}
}

void AVerseBulwark::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (HasAuthority())
	{
		ServerAdvance(VerseCombatEvents::ServerTime(this));
	}
}

void AVerseBulwark::EndPlay(const EEndPlayReason::Type Reason)
{
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnDeath.Remove(DeathHandle);
	}
	Super::EndPlay(Reason);
}

TArray<AVerseBulwark*> AVerseBulwark::FindWithin(const UWorld* World, const FVector& Location, double RadiusCm)
{
	TArray<AVerseBulwark*> Out;
	if (!World)
	{
		return Out;
	}
	for (TActorIterator<AVerseBulwark> It(World); It; ++It)
	{
		if (It->IsActive() && FVector::Dist(It->GetActorLocation(), Location) <= RadiusCm)
		{
			Out.Add(*It);
		}
	}
	return Out;
}
