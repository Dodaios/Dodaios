#pragma once

#include "Components/SceneComponent.h"
#include "CoreMinimal.h"

#include "VerseHoverboardComponent.generated.h"

class UMaterialInstanceDynamic;
class UPointLightComponent;
class UStaticMeshComponent;

DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseBoardToggled, bool /*bOn*/);

/**
 * The hoverboard on the commander (parity Z-09, Z-10). `Toggle` (key B, the
 * tool rail's board button) folds it out under the feet or away again and
 * raises `OnToggled` for the notice (`NoticeKey`). While it is out the
 * component moves the pawn itself: the glide of `VerseBoard`, swept against
 * walls (a wall eats the speed), the feet `HoverHeight` above the floor, the
 * body turned toward the glide. A `ACharacter`'s own movement is parked
 * (`MOVE_None`) while riding and given back when the board folds away.
 *
 * The board is own-work art built from engine shapes: a charcoal ellipse
 * deck with a gold rim and spine, two amber thrusters and an amber
 * underglow. Off in the arena: it folds away at once and B does nothing.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSEABILITIES_API UVerseHoverboardComponent : public USceneComponent
{
	GENERATED_BODY()

public:
	UVerseHoverboardComponent();

	/** Material of the board's lit parts; parameters `Color`, `Metallic`, `Roughness`, `Emissive`. */
	static const TCHAR* BoardMaterialPath;

	/** Localized notice of a toggle (strings `verse.board.on` / `verse.board.off`). */
	static const TCHAR* NoticeKey(bool bOn) { return bOn ? TEXT("verse.board.on") : TEXT("verse.board.off"); }

	/** Fold out or away; false (and nothing happens) in the arena. */
	UFUNCTION(BlueprintCallable, Category = "Verse|Abilities")
	bool Toggle();

	UFUNCTION(BlueprintCallable, Category = "Verse|Abilities")
	void SetOn(bool bInOn);

	UFUNCTION(BlueprintPure, Category = "Verse|Abilities")
	bool IsOn() const { return bOn; }

	/** The held direction this frame (world, horizontal; zero to coast) and Shift; else the pawn's movement input is used. */
	void SetMoveInput(const FVector2D& Direction, bool bInBoost);

	UFUNCTION(BlueprintCallable, Category = "Verse|Abilities")
	void SetArenaOn(bool bInArena);

	UFUNCTION(BlueprintPure, Category = "Verse|Abilities")
	bool IsAllowed() const { return !bArenaOn; }

	void SetReducedMotion(bool bReduced) { bReducedMotion = bReduced; }

	/** One frame (the tick calls it; tests call it with a fixed step). */
	void Step(float DeltaTime);

	float GetShare() const { return Share; }
	FVector2D GetVelocity() const { return Velocity; }
	float GetSpeed() const { return float(Velocity.Size()); }
	/** Lean of the rider: X pitch, Y roll, radians. */
	FVector2D GetLean() const { return LeanNow; }
	/** The rider's feet above the floor, cm. */
	float GetLift() const { return Lift; }
	bool IsBoardVisible() const;

	FOnVerseBoardToggled OnToggled;

protected:
	virtual void OnRegister() override;
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	void Ride(float Dt);
	void Park(bool bRiding);
	void Place(float Dt);
	bool FloorUnder(const FVector& At, float& OutZ) const;
	float FeetOffset() const;
	void OnArenaSwitch(const struct FVerseArenaSwitchEvent& Event);

	bool bOn = false;
	bool bArenaOn = false;
	bool bReducedMotion = false;
	bool bParked = false;
	bool bHasInput = false;
	bool bBoost = false;
	FVector2D Input = FVector2D::ZeroVector;
	FVector2D Velocity = FVector2D::ZeroVector;
	FVector2D LeanNow = FVector2D::ZeroVector;
	float Share = 0.f;
	float Lift = 0.f;
	float Time = 0.f;
	float LastYaw = 0.f;
	float TurnRate = 0.f;
	uint8 SavedMode = 0;
	FDelegateHandle ArenaHandle;

	UPROPERTY(Transient)
	TObjectPtr<USceneComponent> Board;

	UPROPERTY(Transient)
	TArray<TObjectPtr<UStaticMeshComponent>> Parts;

	UPROPERTY(Transient)
	TObjectPtr<UMaterialInstanceDynamic> Thrust;

	UPROPERTY(Transient)
	TObjectPtr<UPointLightComponent> Underglow;
};
