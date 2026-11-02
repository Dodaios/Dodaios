#include "Tests/Movement/VerseMovementTestWorld.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/BoxComponent.h"
#include "Components/CapsuleComponent.h"
#include "Engine/World.h"
#include "Fixture/VerseMovementCourse.h"
#include "GameFramework/PlayerController.h"
#include "VerseCharacter.h"
#include "VerseCharacterMovement.h"
#include "VerseCollision.h"
#include "VerseInputFrameController.h"

FVerseMovementTestWorld::FVerseMovementTestWorld(bool bWithCourse)
{
	if (!Wrapper.CreateTestWorld(EWorldType::Game) || !Wrapper.BeginPlayInTestWorld())
	{
		return;
	}
	World = Wrapper.GetTestWorld();
	if (bWithCourse)
	{
		World->SpawnActor<AVerseMovementCourse>(FVector::ZeroVector, FRotator::ZeroRotator);
	}
}

FVerseMovementTestWorld::~FVerseMovementTestWorld()
{
	if (World)
	{
		Wrapper.DestroyTestWorld(false);
	}
}

AVerseCharacter* FVerseMovementTestWorld::SpawnPawn(const FVector& FeetAt, float Yaw, EDriver Driver)
{
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AVerseCharacter* Pawn = World->SpawnActor<AVerseCharacter>(FeetAt + FVector(0.f, 0.f, 92.f), FRotator(0.f, Yaw, 0.f), Params);
	if (!Pawn)
	{
		return nullptr;
	}
	AController* Controller = Driver == EDriver::Person
		? static_cast<AController*>(World->SpawnActor<APlayerController>())
		: static_cast<AController*>(World->SpawnActor<AVerseInputFrameController>());
	Controller->Possess(Pawn);
	Place(*Pawn, FeetAt, Yaw);
	Tick(2);
	return Pawn;
}

void FVerseMovementTestWorld::Place(AVerseCharacter& Pawn, const FVector& FeetLocation, float Yaw) const
{
	UVerseCharacterMovement* Movement = Pawn.GetVerseMovement();
	Pawn.SetInputScript(nullptr);
	Movement->SetMovementMode(MOVE_Walking);
	const float Half = Pawn.GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
	Pawn.SetActorLocationAndRotation(FeetLocation + FVector(0.f, 0.f, Half + 1.f), FRotator(0.f, Yaw, 0.f), false, nullptr, ETeleportType::TeleportPhysics);
	if (AController* Controller = Pawn.GetController())
	{
		Controller->SetControlRotation(FRotator(0.f, Yaw, 0.f));
	}
	Movement->StopMovementImmediately();
	Movement->bForceNextFloorCheck = true;
}

void FVerseMovementTestWorld::Drive(AVerseCharacter& Pawn, const FVerseInputFrame& Frame) const
{
	if (AVerseInputFrameController* Bot = Cast<AVerseInputFrameController>(Pawn.GetController()))
	{
		Bot->SubmitFrame(Frame);
		return;
	}
	FVerseInputFrameBuilder& Person = Pawn.GetPersonInput();
	Person.SetMove(Frame.Move);
	Person.AddLook(Frame.LookDeltaDeg);
	for (uint32 Bit = 1; Bit != 0 && Bit <= uint32(EVerseInputButton::Interact); Bit <<= 1)
	{
		Person.SetButton(EVerseInputButton(Bit), (Frame.Buttons & Bit) != 0);
	}
}

void FVerseMovementTestWorld::Tick(int32 Count)
{
	for (int32 Index = 0; Index < Count; ++Index)
	{
		Wrapper.TickTestWorld(Dt);
	}
}

UBoxComponent* FVerseMovementTestWorld::AddBox(const FVector& Center, const FVector& Extent)
{
	AActor* Owner = World->SpawnActor<AActor>(Center, FRotator::ZeroRotator);
	UBoxComponent* Box = NewObject<UBoxComponent>(Owner);
	Box->SetBoxExtent(Extent, false);
	Box->SetCollisionProfileName(VerseCollision::Profile::Architecture);
	Owner->SetRootComponent(Box);
	Box->RegisterComponent();
	Box->SetWorldLocation(Center);
	return Box;
}

FVector FVerseMovementTestWorld::Feet(const AVerseCharacter& Pawn)
{
	return Pawn.GetActorLocation() - FVector(0.f, 0.f, Pawn.GetCapsuleComponent()->GetScaledCapsuleHalfHeight());
}

FVerseInputFrame VerseTestFrame(const FVector2f& Move, uint32 Buttons, uint32 PreviousButtons, const FVector2f& Look)
{
	FVerseInputFrame Frame;
	Frame.Move = Move;
	Frame.Buttons = Buttons;
	Frame.Pressed = Buttons & ~PreviousButtons;
	Frame.LookDeltaDeg = Look;
	return Frame;
}

#endif
