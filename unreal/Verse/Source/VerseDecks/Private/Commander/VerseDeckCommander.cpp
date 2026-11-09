#include "Commander/VerseDeckCommander.h"

#include "Commander/VerseDeckWalk.h"
#include "Components/CapsuleComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "UObject/ConstructorHelpers.h"

namespace VerseDeckCommanderPrivate
{
	constexpr float CapsuleRadius = 30.f;
	constexpr float CapsuleHalfHeight = 90.f;
	/** Engine basic shapes are 100 cm across. */
	constexpr float ShapeCm = 100.f;
	/** Material parameters a body material may tint: the engine shape material's and the WP13 rig's. */
	const FName ColourParams[] = { TEXT("Color"), TEXT("BaseColor"), TEXT("UniformColour") };
	/** Faces stay a dark skin tone whatever the uniform. */
	const FLinearColor HeadColour(0.16f, 0.11f, 0.08f, 1.f);
	/** Rank plates are gold (README accents: amber, red, gold). */
	const FLinearColor PlateColour(0.55f, 0.38f, 0.10f, 1.f);
}

AVerseDeckCommander::AVerseDeckCommander()
{
	using namespace VerseDeckCommanderPrivate;
	PrimaryActorTick.bCanEverTick = true;
	AutoPossessAI = EAutoPossessAI::Disabled;
	AIControllerClass = nullptr;
	bUseControllerRotationYaw = false;
	bUseControllerRotationPitch = false;
	bUseControllerRotationRoll = false;
	Tags.Add(TEXT("verse.commander"));

	GetCapsuleComponent()->InitCapsuleSize(CapsuleRadius, CapsuleHalfHeight);
	UCharacterMovementComponent* Move = GetCharacterMovement();
	// Driven by the deck control without a controller.
	Move->bRunPhysicsWithNoController = true;
	Move->bOrientRotationToMovement = false;
	Move->MaxWalkSpeed = static_cast<float>(Verse::DeckWalk::PaceCmPerS);
	Move->MaxAcceleration = 1200.f;
	Move->BrakingDecelerationWalking = 1400.f;
	Move->MaxStepHeight = 35.f;
	// The commander never steps off a walkway or a platform edge; the nav grid routes them round.
	Move->bCanWalkOffLedges = false;
	Move->bCanWalkOffLedgesWhenCrouching = false;
	Move->SetWalkableFloorAngle(46.f);
	Move->NavAgentProps.AgentRadius = CapsuleRadius;
	Move->NavAgentProps.AgentHeight = CapsuleHalfHeight * 2.f;

	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cylinder(TEXT("/Engine/BasicShapes/Cylinder.Cylinder"));
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Sphere(TEXT("/Engine/BasicShapes/Sphere.Sphere"));
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cube(TEXT("/Engine/BasicShapes/Cube.Cube"));
	static ConstructorHelpers::FObjectFinder<UMaterialInterface> ShapeMaterial(TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));

	auto MakePart = [this](const TCHAR* Name, UStaticMesh* Shape, USceneComponent* Parent, const FVector& Location, const FVector& SizeCm)
	{
		UStaticMeshComponent* Part = CreateDefaultSubobject<UStaticMeshComponent>(Name);
		Part->SetupAttachment(Parent);
		Part->SetStaticMesh(Shape);
		Part->SetRelativeLocation(Location);
		Part->SetRelativeScale3D(SizeCm / ShapeCm);
		Part->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Part->SetCanEverAffectNavigation(false);
		Part->CastShadow = true;
		if (ShapeMaterial.Succeeded())
		{
			Part->SetMaterial(0, ShapeMaterial.Object);
		}
		return Part;
	};
	USceneComponent* Root = GetCapsuleComponent();
	// Placeholder body, 1.8 m tall, feet at the capsule bottom (-90): legs and torso as one column,
	// the head above, arms at the sides. The WP13 rig replaces it (stream S7).
	Torso = MakePart(TEXT("Torso"), Cylinder.Object, Root, FVector(0.0, 0.0, -14.0), FVector(42.0, 30.0, 152.0));
	Head = MakePart(TEXT("Head"), Sphere.Object, Root, FVector(3.0, 0.0, 74.0), FVector(23.0, 21.0, 26.0));
	LeftArm = MakePart(TEXT("LeftArm"), Cylinder.Object, Root, FVector(0.0, -26.0, 17.0), FVector(11.0, 11.0, 66.0));
	// The rank plate on the chest shows which way the commander faces.
	RankPlate = MakePart(TEXT("RankPlate"), Cube.Object, Root, FVector(21.5, -8.0, 38.0), FVector(3.0, 12.0, 6.0));
	RightShoulder = CreateDefaultSubobject<USceneComponent>(TEXT("RightShoulder"));
	RightShoulder->SetupAttachment(Root);
	RightShoulder->SetRelativeLocation(FVector(0.0, 26.0, 50.0));
	RightArm = MakePart(TEXT("RightArm"), Cylinder.Object, RightShoulder, FVector(0.0, 0.0, -33.0), FVector(11.0, 11.0, 66.0));
}

void AVerseDeckCommander::BeginPlay()
{
	Super::BeginPlay();
	ApplyUniform();
}

AVerseDeckCommander* AVerseDeckCommander::Find(const UWorld* World)
{
	if (World == nullptr)
	{
		return nullptr;
	}
	for (TActorIterator<AVerseDeckCommander> It(World); It; ++It)
	{
		if (IsValid(*It))
		{
			return *It;
		}
	}
	return nullptr;
}

FVector AVerseDeckCommander::GetFeet() const
{
	return GetActorLocation() - FVector(0.0, 0.0, GetCapsuleComponent()->GetScaledCapsuleHalfHeight());
}

void AVerseDeckCommander::PlaceAt(const FVector& FeetCm, double YawDeg)
{
	StopWalk();
	DriveAxes = FVector2D::ZeroVector;
	const FVector Centre = FeetCm + FVector(0.0, 0.0, GetCapsuleComponent()->GetScaledCapsuleHalfHeight() + 1.0);
	SetActorLocationAndRotation(Centre, FRotator(0.0, YawDeg, 0.0), false, nullptr, ETeleportType::TeleportPhysics);
	GetCharacterMovement()->StopMovementImmediately();
}

void AVerseDeckCommander::Drive(const FVector2D& Axes, bool bHurry, double ViewYawDeg, bool bShooterView)
{
	DriveAxes = Axes;
	bDriveHurry = bHurry;
	DriveViewYaw = ViewYawDeg;
	bDriveShooter = bShooterView;
	if (!Axes.IsNearlyZero())
	{
		// The keys take over from any walk in progress.
		StopWalk();
	}
}

void AVerseDeckCommander::WalkPath(const TArray<FVector>& Points, bool bHurry)
{
	Path = Points;
	bPathHurry = bHurry;
	// The first point is where the body stands.
	if (Path.Num() > 1)
	{
		Path.RemoveAt(0);
	}
}

void AVerseDeckCommander::StopWalk()
{
	Path.Reset();
}

TOptional<FVector> AVerseDeckCommander::GetWalkGoal() const
{
	if (Path.Num() == 0)
	{
		return {};
	}
	return Path.Last();
}

void AVerseDeckCommander::Salute()
{
	StopWalk();
	SaluteLeft = SaluteS;
}

void AVerseDeckCommander::SetUniform(FName InUniform, const FLinearColor& Colour)
{
	Uniform = InUniform;
	UniformColour = Colour;
	ApplyUniform();
}

void AVerseDeckCommander::ApplyUniform()
{
	using namespace VerseDeckCommanderPrivate;
	TInlineComponentArray<UMeshComponent*> Meshes(this);
	for (UMeshComponent* Part : Meshes)
	{
		const bool bHead = Part == Head;
		const bool bPlate = Part == RankPlate;
		for (int32 Slot = 0; Slot < Part->GetNumMaterials(); ++Slot)
		{
			UMaterialInterface* Current = Part->GetMaterial(Slot);
			if (Current == nullptr)
			{
				continue;
			}
			UMaterialInstanceDynamic* Dynamic = Cast<UMaterialInstanceDynamic>(Current);
			if (Dynamic == nullptr)
			{
				Dynamic = Part->CreateDynamicMaterialInstance(Slot, Current);
				BodyMaterials.Add(Dynamic);
			}
			if (Dynamic == nullptr)
			{
				continue;
			}
			for (const FName& Param : ColourParams)
			{
				Dynamic->SetVectorParameterValue(Param, bHead ? HeadColour : bPlate ? PlateColour : UniformColour);
			}
		}
	}
}

void AVerseDeckCommander::SetBodyVisible(bool bVisible)
{
	if (bVisible == bBodyVisible)
	{
		return;
	}
	bBodyVisible = bVisible;
	TInlineComponentArray<UMeshComponent*> Meshes(this);
	for (UMeshComponent* Part : Meshes)
	{
		Part->SetVisibility(bVisible);
	}
}

double AVerseDeckCommander::GetFloorSpeed() const
{
	return GetVelocity().Size2D();
}

void AVerseDeckCommander::Step(const FVector2D& Dir, double FaceYawDeg, double Speed, float DeltaSeconds)
{
	using namespace Verse::DeckWalk;
	const double Yaw = TurnToward(GetActorRotation().Yaw, FaceYawDeg, TurnRateDegPerS, DeltaSeconds);
	SetActorRotation(FRotator(0.0, Yaw, 0.0));
	const double Heading = FMath::RadiansToDegrees(FMath::Atan2(Dir.Y, Dir.X));
	// Facing the view while strafing or backing up is no turn to wait for: pace by the facing goal.
	const double Pace = TurnPace(Yaw, bReverse || bDriveShooter ? FaceYawDeg : Heading);
	GetCharacterMovement()->MaxWalkSpeed = static_cast<float>(Speed * Pace);
	AddMovementInput(FVector(Dir.X, Dir.Y, 0.0), 1.f);
}

void AVerseDeckCommander::FollowPath(float DeltaSeconds)
{
	using namespace Verse::DeckWalk;
	const FVector Feet = GetFeet();
	while (Path.Num() > 0)
	{
		const FVector2D Delta(Path[0].X - Feet.X, Path[0].Y - Feet.Y);
		// Corners are passed once close; the goal needs the feet on it.
		const double Reach = Path.Num() > 1 ? 35.0 : ArriveCm;
		if (Delta.Size() > Reach)
		{
			break;
		}
		const FVector Reached = Path[0];
		Path.RemoveAt(0);
		if (Path.Num() == 0)
		{
			GetCharacterMovement()->StopMovementImmediately();
			OnArrived.Broadcast(Reached);
			return;
		}
	}
	if (Path.Num() == 0)
	{
		return;
	}
	const FVector2D Dir = FVector2D(Path[0].X - Feet.X, Path[0].Y - Feet.Y).GetSafeNormal();
	bReverse = false;
	bDriveShooter = false;
	Step(Dir, FMath::RadiansToDegrees(FMath::Atan2(Dir.Y, Dir.X)), Speed(bPathHurry), DeltaSeconds);
}

void AVerseDeckCommander::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	using namespace Verse::DeckWalk;

	if (SaluteLeft > 0.0)
	{
		SaluteLeft = FMath::Max(0.0, SaluteLeft - DeltaSeconds);
		// Up in a quarter second, held, down in the last quarter second.
		const double T = SaluteS - SaluteLeft;
		const double Raise = FMath::Clamp(FMath::Min(T, SaluteLeft) / 0.25, 0.0, 1.0);
		const double Eased = FMath::InterpEaseInOut(0.0, 1.0, Raise, 2.0);
		// The arm folds and swings up and in until the hand meets the right brow.
		const FVector Shoulder = RightShoulder->GetRelativeLocation();
		const FVector Brow(12.0, 9.0, 80.0);
		const FVector ToBrow = Brow - Shoulder;
		const FQuat Up = FQuat::FindBetweenNormals(FVector(0.0, 0.0, -1.0), ToBrow.GetSafeNormal());
		RightShoulder->SetRelativeRotation(FQuat::Slerp(FQuat::Identity, Up, Eased));
		const double Length = FMath::Lerp(66.0, ToBrow.Size(), Eased);
		RightArm->SetRelativeLocation(FVector(0.0, 0.0, -Length * 0.5));
		RightArm->SetRelativeScale3D(FVector(0.11, 0.11, Length / 100.0));
		return;
	}
	RightShoulder->SetRelativeRotation(FRotator::ZeroRotator);
	RightArm->SetRelativeLocation(FVector(0.0, 0.0, -33.0));
	RightArm->SetRelativeScale3D(FVector(0.11, 0.11, 0.66));

	if (TOptional<FVector2D> Dir = WalkDirection(DriveViewYaw, DriveAxes))
	{
		if (CanStand)
		{
			// Stay on the deck's floor: a blocked step slides along the edge on the free axis.
			const FVector Feet = GetFeet();
			const FVector2D At(Feet.X, Feet.Y);
			constexpr double Probe = 35.0;
			if (!CanStand(At + Dir.GetValue() * Probe))
			{
				const FVector2D AlongX(Dir->X, 0.0);
				const FVector2D AlongY(0.0, Dir->Y);
				if (FMath::Abs(Dir->X) > 0.2 && CanStand(At + AlongX.GetSafeNormal() * Probe))
				{
					Dir = AlongX.GetSafeNormal();
				}
				else if (FMath::Abs(Dir->Y) > 0.2 && CanStand(At + AlongY.GetSafeNormal() * Probe))
				{
					Dir = AlongY.GetSafeNormal();
				}
				else
				{
					bReverse = false;
					return;
				}
			}
		}
		FFacing Facing;
		if (bDriveShooter)
		{
			Facing = BodyFacing(DriveViewYaw, Dir.GetValue());
		}
		else
		{
			Facing.YawDeg = FMath::RadiansToDegrees(FMath::Atan2(Dir->Y, Dir->X));
		}
		bReverse = Facing.bReverse;
		Step(Dir.GetValue(), Facing.YawDeg, Speed(bDriveHurry), DeltaSeconds);
		return;
	}
	bReverse = false;
	FollowPath(DeltaSeconds);
}
