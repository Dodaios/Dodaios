#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "GameFramework/GameModeBase.h"

#include "VerseMovementCourse.generated.h"

class UBoxComponent;
class UStaticMeshComponent;

/**
 * The geometry of LV_Test_Movement (work-packages.md WP01.9), in one table shared by the map
 * and the automation tests: ledges 0.5/1.0/1.5/2.0/2.1 m, a 0.75 m crawl tunnel, a 1.2 m crouch
 * tunnel, 30 and 46 deg slopes, stairs, a 4 m drop, lean corners and a low breach. Actor-local
 * centimetres; the floor top is z = 0 and every lane runs along +X.
 */
namespace VerseMovementCourse
{
	struct FBlock
	{
		const TCHAR* Name;
		FVector Center;
		FVector Extent;
		float PitchDeg = 0.f;
	};

	/** Every collision block of the course. */
	VERSEMOVEMENT_API TConstArrayView<FBlock> Blocks();

	inline constexpr float LedgeHeights[] = {50.f, 100.f, 150.f, 200.f, 210.f};
	inline constexpr int32 LedgeCount = 5;
	/** The ledge faces sit at this X; lanes start at X = 0. */
	inline constexpr float LedgeFaceX = 600.f;
	inline constexpr float LedgeHalfWidth = 300.f;
	inline float LedgeLaneY(int32 Index) { return 800.f * Index; }

	inline constexpr float CrawlTunnelY = 4400.f;
	inline constexpr float CrawlTunnelHeight = 75.f;
	inline constexpr float CrouchTunnelY = 5200.f;
	inline constexpr float CrouchTunnelHeight = 120.f;
	inline constexpr float TunnelEntryX = 600.f;
	inline constexpr float TunnelLength = 400.f;

	inline constexpr float BreachY = 6000.f;
	inline constexpr float BreachWallX = 600.f;
	inline constexpr float BreachSill = 80.f;
	inline constexpr float BreachTop = 200.f;

	/** Lean corners: a wall along +X at y = CornerWallY, its end at x = CornerEndX. */
	inline constexpr float CornerLaneY = 6800.f;
	inline constexpr float CornerWallY = 6800.f;
	inline constexpr float CornerEndX = 1000.f;

	inline constexpr float Slope30Y = -800.f;
	inline constexpr float Slope46Y = -1600.f;
	inline constexpr float StairsY = -2400.f;
	inline constexpr float DropY = -3200.f;
	inline constexpr float DropHeight = 400.f;
	/** Flat open floor for speed tests. */
	inline constexpr float OpenFloorY = -4800.f;
}

/** Spawns the course blocks: collision boxes plus a visible cube each. */
UCLASS()
class VERSEMOVEMENT_API AVerseMovementCourse : public AActor
{
	GENERATED_BODY()

public:
	AVerseMovementCourse();

private:
	UPROPERTY(VisibleAnywhere, Category = "Course")
	TArray<TObjectPtr<UBoxComponent>> Boxes;

	UPROPERTY(VisibleAnywhere, Category = "Course")
	TArray<TObjectPtr<UStaticMeshComponent>> Visuals;
};

/** Game mode of LV_Test_Movement and the netcode soak: AVerseCharacter pawns, soak reports. */
UCLASS()
class VERSEMOVEMENT_API AVerseMovementTestGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AVerseMovementTestGameMode();

	virtual void InitGame(const FString& MapName, const FString& Options, FString& ErrorMessage) override;
	virtual AActor* ChoosePlayerStart_Implementation(AController* Player) override;
	virtual void Tick(float DeltaSeconds) override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

	/** Server: movement net stats of every pawn as JSON. */
	FString BuildServerReport() const;

private:
	FString ReportPath;
	float ReportTimer = 0.f;
	/** ?VerseQuitAfter=<seconds>: the soak server writes its report and exits by itself. */
	float QuitAfter = 0.f;
	float Elapsed = 0.f;
	int32 StartIndex = 0;
};
