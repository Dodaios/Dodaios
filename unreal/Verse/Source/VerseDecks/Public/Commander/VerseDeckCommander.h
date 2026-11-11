#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"

#include "VerseDeckCommander.generated.h"

class UMaterialInstanceDynamic;
class UStaticMeshComponent;
class FVerseDeckNavGrid;

DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseCommanderArrived, const FVector& /*FeetCm*/);

/**
 * The commander on the decks (stream S5): the person's body while they walk the ship.
 *
 * Nobody possesses it. The deck control (`UVerseDeckControlComponent` on the player controller)
 * drives it each frame with the held keys relative to the view, or sends it along a path on the
 * deck's nav grid after a click; the player controller keeps its duel pawn parked for the arena.
 * The body is the Sovereign skin once the game dresses it (`UVerseSovereignBody`, stream S7,
 * on the character mesh); until then, and without the skin in the build, a placeholder of
 * engine shapes that wears the uniform colour and can salute.
 */
UCLASS()
class VERSEDECKS_API AVerseDeckCommander : public ACharacter
{
	GENERATED_BODY()

public:
	AVerseDeckCommander();

	virtual void Tick(float DeltaSeconds) override;

	/** The commander of this world, or nullptr. */
	static AVerseDeckCommander* Find(const UWorld* World);

	/** Feet on the floor, cm. */
	FVector GetFeet() const;
	/** Stand at `FeetCm` facing `YawDeg` (arrival, the end of a duel). */
	void PlaceAt(const FVector& FeetCm, double YawDeg);

	/**
	 * Held movement keys this frame: `Axes` X right, Y forward; `ViewYawDeg` the camera's yaw.
	 * `bShooterView` (third or first person) makes the body face the view as it walks (parity V-12);
	 * in the overview it faces where it walks. Keys take over from any walk in progress.
	 */
	void Drive(const FVector2D& Axes, bool bHurry, double ViewYawDeg, bool bShooterView);

	/** Walk along a path (from `FVerseDeckNavGrid::FindPath`); the last point is the goal. */
	void WalkPath(const TArray<FVector>& Points, bool bHurry = false);
	/** Stop any walk. */
	void StopWalk();
	bool IsWalking() const { return Path.Num() > 0; }
	/** The points still ahead on the current walk (tests, QA). */
	const TArray<FVector>& GetPath() const { return Path; }
	/** The goal of the current walk; unset when standing or driven. */
	TOptional<FVector> GetWalkGoal() const;

	/** The salute: the right hand to the brow for `SaluteS` seconds; the body stops walking. */
	void Salute();
	bool IsSaluting() const { return SaluteLeft > 0.0; }

	/**
	 * Wear a uniform (the service record's quartermaster, parity F-18): every body material
	 * gets its colour. `Uniform` is the record's id (work, standard, dress, ...), kept for QA.
	 */
	void SetUniform(FName Uniform, const FLinearColor& Colour);
	FName GetUniform() const { return Uniform; }
	FLinearColor GetUniformColour() const { return UniformColour; }

	/** Shows or hides the body (not the actor): hidden in first person and when the camera is pressed into it. */
	void SetBodyVisible(bool bVisible);
	bool IsBodyVisible() const { return bBodyVisible; }

	/** True when the character mesh carries a skin (the Sovereign): the shapes stay hidden. */
	bool HasSkin() const;
	/** Shows the skin or the shapes after the skin was put on (or taken off). */
	void RefreshBody();

	/** Walking backwards in a shooter view: the walk plays in reverse. */
	bool IsBackpedalling() const { return bReverse; }
	/** Current walking speed on the floor, cm/s. */
	double GetFloorSpeed() const;

	/**
	 * Where a body may stand on the floor plan (the deck's nav grid). Key walking never leaves it:
	 * a blocked step slides along the edge on whichever axis is still free (`driveStep`). Unset: anywhere.
	 */
	TFunction<bool(const FVector2D& PlanCm)> CanStand;

	FOnVerseCommanderArrived OnArrived;

	static constexpr double SaluteS = 1.6;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Decks|Commander")
	TObjectPtr<UStaticMeshComponent> Torso;
	UPROPERTY(VisibleAnywhere, Category = "Verse|Decks|Commander")
	TObjectPtr<UStaticMeshComponent> Head;
	UPROPERTY(VisibleAnywhere, Category = "Verse|Decks|Commander")
	TObjectPtr<UStaticMeshComponent> RankPlate;
	/** Pivot at the right shoulder; the salute raises it. */
	UPROPERTY(VisibleAnywhere, Category = "Verse|Decks|Commander")
	TObjectPtr<USceneComponent> RightShoulder;
	UPROPERTY(VisibleAnywhere, Category = "Verse|Decks|Commander")
	TObjectPtr<UStaticMeshComponent> RightArm;
	UPROPERTY(VisibleAnywhere, Category = "Verse|Decks|Commander")
	TObjectPtr<UStaticMeshComponent> LeftArm;

protected:
	virtual void BeginPlay() override;

private:
	void ApplyUniform();
	/** The placeholder shapes (every mesh component but the character mesh). */
	void ForEachShape(TFunctionRef<void(UMeshComponent*)> Fn) const;
	void FollowPath(float DeltaSeconds);
	void Step(const FVector2D& Dir, double FaceYawDeg, double Speed, float DeltaSeconds);

	UPROPERTY(Transient)
	TArray<TObjectPtr<UMaterialInstanceDynamic>> BodyMaterials;

	TArray<FVector> Path;
	bool bPathHurry = false;
	FVector2D DriveAxes = FVector2D::ZeroVector;
	bool bDriveHurry = false;
	double DriveViewYaw = 0.0;
	bool bDriveShooter = true;
	bool bReverse = false;
	double SaluteLeft = 0.0;
	bool bBodyVisible = true;
	FName Uniform = TEXT("work");
	FLinearColor UniformColour = FLinearColor(0.045f, 0.047f, 0.040f, 1.f);
};
