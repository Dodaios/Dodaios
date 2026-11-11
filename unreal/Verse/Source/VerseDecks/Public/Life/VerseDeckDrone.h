#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "VerseDeckDrone.generated.h"

class AVerseDeckCommander;
class FVerseDeckNavGrid;
class UAnimSequence;
class USkeletalMeshComponent;
struct FVerseDeckManifest;

UENUM()
enum class EVerseDroneKind : uint8
{
	/** The commander's hovering companion (`SK_Drone_Companion`), at the commander's heel. */
	Companion,
	/** An ambient utility floor drone (`SK_Drone_Utility`) on its service round. */
	Utility,
};

/** A waypoint route of a deck: its group and its points in order (feet, cm). */
struct VERSEDECKS_API FVerseDroneRoute
{
	FName Group;
	TArray<FVector> Points;
};

namespace VerseDeckDrones
{
	/** `socketGroup` of `content/loadDeck.ts`: `brief__01` -> (brief, 1), `pit_p_3` -> (pit_p, 3), else (id, 0). */
	VERSEDECKS_API TPair<FString, int32> SocketGroup(const FString& Id);
	/**
	 * The routes a utility drone drives, as `life/cast.ts` picks them: waypoint groups of two or
	 * more points, in first-seen order, whose group starts with service, cargo, pad or corridor;
	 * at most `MaxDrones`.
	 */
	VERSEDECKS_API TArray<FVerseDroneRoute> UtilityRoutes(const FVerseDeckManifest& Manifest, int32 MaxDrones = 2);
	/** Where the companion waits: 1.1 m behind the leader, 0.45 m to its left (`actor.ts` follow). */
	VERSEDECKS_API FVector HeelPoint(const FVector& LeaderFeet, double LeaderYawDeg);

	/** `actor.ts`: HEEL_DISTANCE, REPLAN_FOLLOW_S, TURN_RATE (rad/s, here deg/s), the cast's paces. */
	inline constexpr double HeelCm = 110.0;
	inline constexpr double HeelSideCm = 45.0;
	inline constexpr double ReplanS = 0.4;
	inline constexpr double TurnRateDegPerS = 5.5 * 180.0 / UE_DOUBLE_PI;
	inline constexpr double CompanionPaceCmPerS = 170.0;
	inline constexpr double UtilityPaceCmPerS = 120.0;
}

/**
 * A drone on the deck (parity with three.js `actors/actor.ts` for bodies of kind drone and
 * companion): the drone's skinned mesh playing its clips, walking the deck's nav grid. The
 * companion follows the commander to a heel point and hovers there turned toward them; a utility
 * drone drives its waypoint route round and round. Spawned by `UVerseDeckSubsystem` on arrival.
 */
UCLASS()
class VERSEDECKS_API AVerseDeckDrone : public AActor
{
	GENERATED_BODY()

public:
	AVerseDeckDrone();

	virtual void Tick(float DeltaSeconds) override;

	static const TCHAR* CompanionMeshPath;
	static const TCHAR* UtilityMeshPath;
	/** The companion's clips: at heel, and on the move. */
	static const TCHAR* CompanionHoverClipPath;
	static const TCHAR* CompanionFollowClipPath;
	/** Height of the companion's body centre above its mesh root (`drones.py` COMP_HOVER). */
	static constexpr double CompanionBodyCm = 85.0;
	/**
	 * Tag of an actor that already is the commander's companion (the crew's, `VerseCrew`): while
	 * one is in the world, the deck spawns no companion of its own, so there is only ever one.
	 */
	static const FName CompanionTag;
	/** True when an actor tagged `CompanionTag` that is not a deck drone is in the world. */
	static bool HasOtherCompanion(const UWorld* World);

	/** Sets the body and its clips; false when the mesh is not in the build. */
	bool Init(EVerseDroneKind InKind, const FVector& FeetCm, double YawDeg);
	/** A utility drone's round. */
	void SetRoute(const FVerseDroneRoute& InRoute);

	/** Spawns the companion at the commander and the utility drones on their routes. */
	static int32 SpawnForDeck(UWorld* World, const FVerseDeckManifest& Manifest);

	EVerseDroneKind GetKind() const { return Kind; }
	bool IsMoving() const { return Path.Num() > 0; }
	/** The clip playing now (tests, QA). */
	FName GetClip() const { return Clip; }
	FVector GetFeet() const { return GetActorLocation(); }
	double GetYaw() const { return Yaw; }

	UPROPERTY(VisibleAnywhere, Category = "Verse|Decks|Drone")
	TObjectPtr<USkeletalMeshComponent> Body;

	/** Grid used for walking; tests set it, the game takes the deck control's. */
	const FVerseDeckNavGrid* NavOverride = nullptr;
	/** Leader of the companion; the commander of the world when unset. */
	TWeakObjectPtr<AActor> Leader;

private:
	const FVerseDeckNavGrid* Nav() const;
	void Play(FName Motion);
	void Follow(float DeltaSeconds);
	void Drive(float DeltaSeconds);
	/** Moves along `Path`; true when the end was reached this frame. */
	bool WalkStep(float DeltaSeconds, double PaceCmPerS);
	bool PlanTo(const FVector& Goal);

	EVerseDroneKind Kind = EVerseDroneKind::Companion;
	UPROPERTY(Transient)
	TMap<FName, TObjectPtr<UAnimSequence>> Clips;
	FName Clip;
	TArray<FVector> Path;
	FVerseDroneRoute Route;
	int32 RouteIndex = 0;
	double Yaw = 0.0;
	double Clock = 0.0;
	double LastPlan = -100.0;
	bool bWalking = false;
};
