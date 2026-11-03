#include "Repair/VerseRepairDrone.h"

#include "Components/BoxComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Net/UnrealNetwork.h"
#include "Pieces/VerseDestructionManager.h"
#include "VerseCollision.h"

AVerseRepairDrone::AVerseRepairDrone()
{
	PrimaryActorTick.bCanEverTick = false;
	bReplicates = true;
	SetReplicatingMovement(true);
	bAlwaysRelevant = true;

	HitBox = CreateDefaultSubobject<UBoxComponent>(TEXT("HitBox"));
	HitBox->SetBoxExtent(FVector(30.f, 30.f, 15.f));
	// Its own hit box on the bolt channel: stops bolts, never blocks or harms pawns (destruction.md 7).
	HitBox->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
	HitBox->SetCollisionObjectType(ECC_WorldDynamic);
	HitBox->SetCollisionResponseToAllChannels(ECR_Ignore);
	HitBox->SetCollisionResponseToChannel(VerseCollision::Bolt, ECR_Block);
	HitBox->SetCanEverAffectNavigation(false);
	SetRootComponent(HitBox);

	Body = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Body"));
	Body->SetupAttachment(HitBox);
	Body->SetCollisionProfileName(VerseCollision::Profile::NoCollision);
	Body->SetCanEverAffectNavigation(false);
}

void AVerseRepairDrone::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	DOREPLIFETIME(AVerseRepairDrone, DroneIndex);
	DOREPLIFETIME(AVerseRepairDrone, Task);
	DOREPLIFETIME(AVerseRepairDrone, Generation);
	DOREPLIFETIME(AVerseRepairDrone, Hp);
}

float AVerseRepairDrone::TakeDamage(float DamageAmount, const FDamageEvent& DamageEvent, AController* EventInstigator, AActor* DamageCauser)
{
	if (!HasAuthority() || DamageAmount <= 0.f)
	{
		return 0.f;
	}
	if (AVerseDestructionManager* Manager = AVerseDestructionManager::Get(this))
	{
		Manager->ApplyDroneDamage(DroneIndex, DamageAmount);
	}
	return DamageAmount; // no score, no XP (destruction.md 7)
}

void AVerseRepairDrone::SyncFromSim(const FVector& Location, uint8 InTask, uint32 InGeneration, float InHp)
{
	SetActorLocation(Location);
	Hp = InHp;
	if (Generation != InGeneration)
	{
		Generation = InGeneration;
		OnRep_Generation();
	}
	if (Task != InTask)
	{
		Task = InTask;
		OnRep_Task();
	}
}

void AVerseRepairDrone::OnRep_Task()
{
	OnTaskChanged(Task);
}

void AVerseRepairDrone::OnRep_Generation()
{
	OnShotDown();
}
