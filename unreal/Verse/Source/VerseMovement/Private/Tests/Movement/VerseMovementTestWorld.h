#pragma once

#include "CoreMinimal.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Combat/VerseCombatTypes.h"
#include "Tests/AutomationCommon.h"

class AVerseCharacter;
class AController;
class UBoxComponent;
class UVerseCharacterMovement;
class UWorld;

/**
 * A manually ticked game world with the fixture course (LV_Test_Movement's geometry) for the
 * Verse.Movement.* tests. Ticks at the server rate, 60 Hz.
 */
class FVerseMovementTestWorld
{
public:
	static constexpr float Dt = 1.f / 60.f;

	explicit FVerseMovementTestWorld(bool bWithCourse = true);
	~FVerseMovementTestWorld();

	bool IsValid() const { return World != nullptr; }
	UWorld* GetWorld() const { return World; }

	enum class EDriver : uint8
	{
		/** A local APlayerController; frames go through the person's FVerseInputFrameBuilder. */
		Person,
		/** An AVerseInputFrameController; frames go through SubmitFrame (bot path). */
		Bot
	};

	/** A pawn standing with its feet at Feet, facing Yaw. */
	AVerseCharacter* SpawnPawn(const FVector& FeetAt, float Yaw, EDriver Driver = EDriver::Bot);

	/** Teleports a pawn: feet at Feet, facing Yaw, at rest, standing. */
	void Place(AVerseCharacter& Pawn, const FVector& FeetLocation, float Yaw) const;

	/** Feeds one frame to the pawn through its driver. */
	void Drive(AVerseCharacter& Pawn, const FVerseInputFrame& Frame) const;

	void Tick(int32 Count = 1);
	void TickSeconds(float Seconds) { Tick(FMath::Max(1, FMath::RoundToInt(Seconds / Dt))); }

	/** An extra blocking box (architecture profile) at a world center. */
	UBoxComponent* AddBox(const FVector& Center, const FVector& Extent);

	static FVector Feet(const AVerseCharacter& Pawn);

private:
	FTestWorldWrapper Wrapper;
	UWorld* World = nullptr;
};

/** A frame that holds Buttons, with Pressed derived from the previous frame's buttons. */
FVerseInputFrame VerseTestFrame(const FVector2f& Move, uint32 Buttons, uint32 PreviousButtons, const FVector2f& Look = FVector2f::ZeroVector);

#endif
