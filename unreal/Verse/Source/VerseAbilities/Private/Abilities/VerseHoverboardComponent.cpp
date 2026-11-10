#include "Abilities/VerseHoverboardComponent.h"

#include "Abilities/VerseArcStormComponent.h"
#include "Abilities/VerseHoverboard.h"
#include "Components/CapsuleComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Materials/MaterialInstanceDynamic.h"

const TCHAR* UVerseHoverboardComponent::BoardMaterialPath = TEXT("/Game/Verse/Characters/Sovereign/M_Sov_Board.M_Sov_Board");

namespace
{
	const TCHAR* CubePath = TEXT("/Engine/BasicShapes/Cube.Cube");
	const TCHAR* CylinderPath = TEXT("/Engine/BasicShapes/Cylinder.Cylinder");
	/** The thruster amber; the underglow throws it on the floor. */
	const FLinearColor Amber(1.f, 0.55f, 0.12f);
	constexpr float UnderglowCd = 14.f;

	struct FLook
	{
		FLinearColor Color;
		float Metallic;
		float Roughness;
		float Emissive;
	};
	// Charcoal deck, gold rim and spine, near-black grip (the reference's colours, linear).
	const FLook Deck{FLinearColor::FromSRGBColor(FColor(0x17, 0x19, 0x1e)), 0.75f, 0.32f, 0.f};
	const FLook Gold{FLinearColor::FromSRGBColor(FColor(0xc9, 0xa2, 0x4a)), 0.9f, 0.28f, 0.08f};
	const FLook Grip{FLinearColor::FromSRGBColor(FColor(0x0c, 0x0d, 0x10)), 0.2f, 0.85f, 0.f};
}

UVerseHoverboardComponent::UVerseHoverboardComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.TickGroup = TG_PrePhysics;
}

void UVerseHoverboardComponent::OnRegister()
{
	Super::OnRegister();
	AActor* Owner = GetOwner();
	if (Board || !Owner)
	{
		return;
	}
	Board = NewObject<USceneComponent>(Owner, TEXT("BoardRoot"), RF_Transient);
	Board->SetupAttachment(this);
	Board->SetUsingAbsoluteLocation(true);
	Board->SetUsingAbsoluteRotation(true);
	Board->SetUsingAbsoluteScale(true);
	Board->RegisterComponent();

	UMaterialInterface* Lit = LoadObject<UMaterialInterface>(nullptr, BoardMaterialPath);
	auto Paint = [this, Lit](const FLook& Look) -> UMaterialInstanceDynamic*
	{
		if (!Lit)
		{
			return nullptr;
		}
		UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Lit, this);
		Mid->SetVectorParameterValue(TEXT("Color"), Look.Color);
		Mid->SetScalarParameterValue(TEXT("Metallic"), Look.Metallic);
		Mid->SetScalarParameterValue(TEXT("Roughness"), Look.Roughness);
		Mid->SetScalarParameterValue(TEXT("Emissive"), Look.Emissive);
		return Mid;
	};
	UMaterialInstanceDynamic* DeckMat = Paint(Deck);
	UMaterialInstanceDynamic* GoldMat = Paint(Gold);
	UMaterialInstanceDynamic* GripMat = Paint(Grip);
	if (UMaterialInterface* Glow = LoadObject<UMaterialInterface>(nullptr, UVerseArcStormComponent::BoltMaterialPath))
	{
		Thrust = UMaterialInstanceDynamic::Create(Glow, this);
		Thrust->SetVectorParameterValue(TEXT("Color"), Amber);
		Thrust->SetScalarParameterValue(TEXT("Intensity"), 0.f);
	}
	auto Part = [this, Owner](const TCHAR* Mesh, const FVector& At, const FVector& SizeCm, UMaterialInterface* Material)
	{
		UStaticMeshComponent* P = NewObject<UStaticMeshComponent>(Owner, NAME_None, RF_Transient);
		P->SetupAttachment(Board);
		P->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, Mesh));
		P->SetRelativeLocation(At);
		P->SetRelativeScale3D(SizeCm / 100.0);
		P->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		P->SetCanEverAffectNavigation(false);
		P->SetCastShadow(true);
		if (Material)
		{
			P->SetMaterial(0, Material);
		}
		P->SetVisibility(false);
		P->RegisterComponent();
		Parts.Add(P);
	};
	// A stadium deck 96 x 34 x 5 cm (a box between two discs), the gold rim the same shape a little
	// larger and thinner just under it, the grip pad and a gold spine on top.
	for (const auto& [Material, Grow, Thick, Z] : {TTuple<UMaterialInterface*, double, double, double>(GoldMat, 1.06, 2.0, -1.8),
		TTuple<UMaterialInterface*, double, double, double>(DeckMat, 1.0, 5.0, 0.0)})
	{
		Part(CubePath, FVector(0.0, 0.0, Z), FVector(62.0, 34.0 * Grow, Thick), Material);
		Part(CylinderPath, FVector(31.0, 0.0, Z), FVector(34.0 * Grow, 34.0 * Grow, Thick), Material);
		Part(CylinderPath, FVector(-31.0, 0.0, Z), FVector(34.0 * Grow, 34.0 * Grow, Thick), Material);
	}
	Part(CubePath, FVector(0.0, 0.0, 2.8), FVector(68.0, 24.0, 0.6), GripMat);
	Part(CubePath, FVector(0.0, 0.0, 3.1), FVector(60.0, 1.8, 0.8), GoldMat);
	// Two thruster pods under nose and tail, glowing nozzles pointing down.
	for (const double X : {-33.0, 33.0})
	{
		Part(CylinderPath, FVector(X, 0.0, -4.5), FVector(15.5, 15.5, 5.0), DeckMat);
		Part(CylinderPath, FVector(X, 0.0, -7.4), FVector(11.6, 11.6, 1.2), Thrust);
	}
	Underglow = NewObject<UPointLightComponent>(Owner, TEXT("BoardUnderglow"), RF_Transient);
	Underglow->SetupAttachment(Board);
	Underglow->SetRelativeLocation(FVector(0.0, 0.0, -4.0));
	// A wide source: a soft pool of light under the deck, not a hot spot.
	Underglow->SetSourceRadius(22.f);
	Underglow->SetSoftSourceRadius(30.f);
	Underglow->SetMobility(EComponentMobility::Movable);
	Underglow->SetIntensityUnits(ELightUnits::Candelas);
	Underglow->SetIntensity(0.f);
	Underglow->SetAttenuationRadius(160.f);
	Underglow->SetLightColor(Amber);
	Underglow->SetCastShadows(false);
	Underglow->RegisterComponent();
}

void UVerseHoverboardComponent::BeginPlay()
{
	Super::BeginPlay();
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		ArenaHandle = Hub->OnArenaSwitch.AddUObject(this, &UVerseHoverboardComponent::OnArenaSwitch);
	}
	if (const AActor* Owner = GetOwner())
	{
		LastYaw = float(Owner->GetActorRotation().Yaw);
	}
}

void UVerseHoverboardComponent::EndPlay(const EEndPlayReason::Type Reason)
{
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnArenaSwitch.Remove(ArenaHandle);
	}
	Super::EndPlay(Reason);
}

bool UVerseHoverboardComponent::Toggle()
{
	if (bArenaOn)
	{
		return false;
	}
	SetOn(!bOn);
	return true;
}

void UVerseHoverboardComponent::SetOn(bool bInOn)
{
	const bool bWant = bInOn && !bArenaOn;
	if (bWant == bOn)
	{
		return;
	}
	bOn = bWant;
	Park(bOn);
	OnToggled.Broadcast(bOn);
}

void UVerseHoverboardComponent::SetMoveInput(const FVector2D& Direction, bool bInBoost)
{
	Input = Direction;
	bBoost = bInBoost;
	bHasInput = true;
}

void UVerseHoverboardComponent::SetArenaOn(bool bInArena)
{
	if (bInArena)
	{
		SetOn(false);
		Share = 0.f;
		Place(0.f);
	}
	bArenaOn = bInArena;
}

void UVerseHoverboardComponent::OnArenaSwitch(const FVerseArenaSwitchEvent& Event)
{
	SetArenaOn(Event.bArenaOn);
}

bool UVerseHoverboardComponent::IsBoardVisible() const
{
	return Parts.Num() > 0 && Parts[0]->IsVisible();
}

float UVerseHoverboardComponent::FeetOffset() const
{
	const ACharacter* Character = Cast<ACharacter>(GetOwner());
	return Character && Character->GetCapsuleComponent() ? Character->GetCapsuleComponent()->GetScaledCapsuleHalfHeight() : 0.f;
}

bool UVerseHoverboardComponent::FloorUnder(const FVector& At, float& OutZ) const
{
	FHitResult Hit;
	FCollisionQueryParams Params(TEXT("BoardFloor"), false, GetOwner());
	const UWorld* World = GetWorld();
	if (World && World->LineTraceSingleByChannel(Hit, At + FVector(0.0, 0.0, 50.0), At - FVector(0.0, 0.0, 300.0), ECC_Visibility, Params))
	{
		OutZ = float(Hit.ImpactPoint.Z);
		return true;
	}
	return false;
}

void UVerseHoverboardComponent::Park(bool bRiding)
{
	ACharacter* Character = Cast<ACharacter>(GetOwner());
	UCharacterMovementComponent* Move = Character ? Character->GetCharacterMovement() : nullptr;
	if (!Move)
	{
		if (!bRiding)
		{
			Velocity = FVector2D::ZeroVector;
		}
		return;
	}
	if (bRiding && !bParked)
	{
		// The board carries on with the walk's speed; the character's own movement waits.
		Velocity = FVector2D(Move->Velocity.X, Move->Velocity.Y);
		SavedMode = uint8(Move->MovementMode.GetValue());
		Move->StopMovementImmediately();
		Move->SetMovementMode(MOVE_None);
		bParked = true;
	}
	else if (!bRiding && bParked)
	{
		Move->SetMovementMode(SavedMode == uint8(MOVE_None) ? MOVE_Falling : EMovementMode(SavedMode));
		Move->Velocity = FVector(Velocity, 0.0);
		Velocity = FVector2D::ZeroVector;
		bParked = false;
	}
}

void UVerseHoverboardComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	Step(DeltaTime);
}

void UVerseHoverboardComponent::Step(float DeltaTime)
{
	const float Dt = FMath::Clamp(DeltaTime, 0.f, 0.1f);
	Time += Dt;
	Share = VerseBoard::DeployStep(Share, bOn, Dt, bReducedMotion);
	if (bOn)
	{
		Ride(Dt);
	}
	bHasInput = false;
	Place(Dt);
}

void UVerseHoverboardComponent::Ride(float Dt)
{
	AActor* Owner = GetOwner();
	if (!Owner || Dt <= 0.f)
	{
		return;
	}
	FVector2D Held = Input;
	bool bShift = bBoost;
	if (!bHasInput)
	{
		const APawn* Pawn = Cast<APawn>(Owner);
		const FVector Last = Pawn ? Pawn->GetLastMovementInputVector() : FVector::ZeroVector;
		Held = FVector2D(Last.X, Last.Y);
		bShift = false;
	}
	const bool bHeld = Held.Size() > 0.1;
	const FVector2D Dir = bHeld ? Held.GetSafeNormal() : FVector2D::ZeroVector;
	Velocity = VerseBoard::Glide(Velocity, bHeld ? &Dir : nullptr, bShift, Dt);

	// Glide, swept: a wall stops the part of the step that runs into it, the rest slides along.
	const FVector Wanted(Velocity * Dt, 0.0);
	const FVector From = Owner->GetActorLocation();
	FHitResult Hit;
	ACharacter* Character = Cast<ACharacter>(Owner);
	UCharacterMovementComponent* Move = Character ? Character->GetCharacterMovement() : nullptr;
	if (Move)
	{
		Move->SafeMoveUpdatedComponent(Wanted, Owner->GetActorQuat(), true, Hit);
		if (Hit.IsValidBlockingHit())
		{
			const FVector Rest = FVector::VectorPlaneProject(Wanted * (1.f - Hit.Time), Hit.Normal);
			Move->SafeMoveUpdatedComponent(FVector(Rest.X, Rest.Y, 0.0), Owner->GetActorQuat(), true, Hit);
		}
	}
	else
	{
		Owner->AddActorWorldOffset(Wanted, true, &Hit);
		if (Hit.IsValidBlockingHit())
		{
			const FVector Rest = FVector::VectorPlaneProject(Wanted * (1.f - Hit.Time), Hit.Normal);
			Owner->AddActorWorldOffset(FVector(Rest.X, Rest.Y, 0.0), true);
		}
	}
	const FVector Moved = Owner->GetActorLocation() - From;
	Velocity = VerseBoard::Absorb(Velocity, FVector2D(Wanted), FVector2D(Moved.X, Moved.Y), Dt);

	// The body turns toward the glide; the turn rate drives the lean.
	float Yaw = float(Owner->GetActorRotation().Yaw);
	if (Velocity.Size() > 30.0)
	{
		const float Want = float(FMath::RadiansToDegrees(FMath::Atan2(Velocity.Y, Velocity.X)));
		Yaw = FMath::FixedTurn(Yaw, Want, 540.f * Dt);
		Owner->SetActorRotation(FRotator(0.0, Yaw, 0.0));
	}
	const float Rate = FMath::DegreesToRadians(FMath::FindDeltaAngleDegrees(LastYaw, Yaw)) / Dt;
	TurnRate += (Rate - TurnRate) * FMath::Min(1.f, Dt * 10.f);
	LastYaw = Yaw;
}

void UVerseHoverboardComponent::Place(float Dt)
{
	AActor* Owner = GetOwner();
	if (!Owner || !Board)
	{
		return;
	}
	const bool bShown = Share > 0.001f;
	for (UStaticMeshComponent* P : Parts)
	{
		P->SetVisibility(bShown);
	}
	Underglow->SetVisibility(bShown);
	if (!bShown)
	{
		Lift = 0.f;
		LeanNow = FVector2D::ZeroVector;
		return;
	}
	const float Speed = GetSpeed();
	Lift = VerseBoard::HoverHeight(Share, Time, Speed, bReducedMotion);
	LeanNow = VerseBoard::Lean(Speed, TurnRate, bReducedMotion);
	FVector Feet = Owner->GetActorLocation() - FVector(0.0, 0.0, FeetOffset());
	float FloorZ = float(Feet.Z) - Lift;
	if (bOn && FloorUnder(Feet, FloorZ))
	{
		// Riding: the feet float `Lift` above the floor.
		Feet.Z = FloorZ + Lift;
		Owner->SetActorLocation(Feet + FVector(0.0, 0.0, FeetOffset()));
	}
	const float Scale = VerseBoard::DeployScale(Share);
	Board->SetWorldLocationAndRotation(Feet - FVector(0.0, 0.0, 3.4 * Scale),
		FRotator(-FMath::RadiansToDegrees(LeanNow.X), Owner->GetActorRotation().Yaw, FMath::RadiansToDegrees(LeanNow.Y)));
	Board->SetWorldScale3D(FVector(Scale));
	const float Flicker = 0.85f + FMath::Sin(Time * 31.f) * 0.08f + FMath::Sin(Time * 17.3f) * 0.07f;
	const float Push = FMath::Min(1.f, 0.55f + Speed / VerseBoard::BoostCm);
	if (Thrust)
	{
		Thrust->SetScalarParameterValue(TEXT("Intensity"), 6.f * FMath::Min(1.f, Share) * Flicker * Push);
	}
	Underglow->SetIntensity(UnderglowCd * FMath::Min(1.f, Share) * (0.6f + 0.4f * Push) * Flicker);
}
