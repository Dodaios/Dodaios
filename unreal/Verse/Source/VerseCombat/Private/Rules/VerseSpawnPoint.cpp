#include "Rules/VerseSpawnPoint.h"

#include "Components/CapsuleComponent.h"

AVerseSpawnPoint::AVerseSpawnPoint(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
}

FVector AVerseSpawnPoint::GetFloorLocation() const
{
	const UCapsuleComponent* Capsule = GetCapsuleComponent();
	const double Half = Capsule ? Capsule->GetScaledCapsuleHalfHeight() : 0.0;
	return GetActorLocation() - FVector(0.0, 0.0, Half);
}
