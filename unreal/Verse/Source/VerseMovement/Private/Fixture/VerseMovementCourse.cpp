#include "Fixture/VerseMovementCourse.h"

#include "Components/BoxComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerStart.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/FileHelper.h"
#include "UObject/ConstructorHelpers.h"
#include "VerseCharacter.h"
#include "VerseCharacterMovement.h"
#include "VerseCollision.h"
#include "VerseInputFrameController.h"
#include "VerseLog.h"

namespace VerseMovementCourse
{
	namespace
	{
		TArray<FBlock> MakeBlocks()
		{
			TArray<FBlock> Out;
			Out.Add({TEXT("Floor"), FVector(0.f, 1000.f, -25.f), FVector(3000.f, 9000.f, 25.f)});
			for (int32 Index = 0; Index < LedgeCount; ++Index)
			{
				const float H = LedgeHeights[Index];
				Out.Add({TEXT("Ledge"), FVector(LedgeFaceX + 200.f, LedgeLaneY(Index), H * 0.5f), FVector(200.f, LedgeHalfWidth, H * 0.5f)});
			}
			for (const float Y : {CrawlTunnelY, CrouchTunnelY})
			{
				const float H = Y == CrawlTunnelY ? CrawlTunnelHeight : CrouchTunnelHeight;
				const float CenterX = TunnelEntryX + TunnelLength * 0.5f;
				Out.Add({TEXT("TunnelWall"), FVector(CenterX, Y - 125.f, H * 0.5f), FVector(TunnelLength * 0.5f, 25.f, H * 0.5f)});
				Out.Add({TEXT("TunnelWall"), FVector(CenterX, Y + 125.f, H * 0.5f), FVector(TunnelLength * 0.5f, 25.f, H * 0.5f)});
				Out.Add({TEXT("TunnelRoof"), FVector(CenterX, Y, H + 25.f), FVector(TunnelLength * 0.5f, 150.f, 25.f)});
			}
			{
				const float X = BreachWallX + 12.5f;
				Out.Add({TEXT("BreachSill"), FVector(X, BreachY, BreachSill * 0.5f), FVector(12.5f, 150.f, BreachSill * 0.5f)});
				Out.Add({TEXT("BreachLintel"), FVector(X, BreachY, BreachTop + 25.f), FVector(12.5f, 150.f, 25.f)});
				Out.Add({TEXT("BreachPost"), FVector(X, BreachY - 250.f, 125.f), FVector(12.5f, 100.f, 125.f)});
				Out.Add({TEXT("BreachPost"), FVector(X, BreachY + 250.f, 125.f), FVector(12.5f, 100.f, 125.f)});
			}
			Out.Add({TEXT("CornerWallRight"), FVector(CornerEndX - 400.f, CornerWallY + 100.f, 150.f), FVector(400.f, 15.f, 150.f)});
			Out.Add({TEXT("CornerWallLeft"), FVector(CornerEndX - 400.f, CornerWallY - 100.f, 150.f), FVector(400.f, 15.f, 150.f)});
			for (const float Pitch : {30.f, 46.f})
			{
				const float Rad = FMath::DegreesToRadians(Pitch);
				const float Z = 400.f * FMath::Sin(Rad) - 20.f * FMath::Cos(Rad);
				Out.Add({Pitch < 40.f ? TEXT("Slope30") : TEXT("Slope46"), FVector(800.f, Pitch < 40.f ? Slope30Y : Slope46Y, Z),
					FVector(400.f, 300.f, 20.f), Pitch});
			}
			for (int32 Step = 0; Step < 10; ++Step)
			{
				const float Top = (Step + 1) * 20.f;
				Out.Add({TEXT("Stair"), FVector(615.f + 30.f * Step, StairsY, Top * 0.5f), FVector(15.f, 150.f, Top * 0.5f)});
			}
			Out.Add({TEXT("StairLanding"), FVector(1050.f, StairsY, 100.f), FVector(150.f, 150.f, 100.f)});
			Out.Add({TEXT("DropPlatform"), FVector(1000.f, DropY, DropHeight * 0.5f), FVector(400.f, 300.f, DropHeight * 0.5f)});
			return Out;
		}
	}

	TConstArrayView<FBlock> Blocks()
	{
		static const TArray<FBlock> Table = MakeBlocks();
		return Table;
	}
}

AVerseMovementCourse::AVerseMovementCourse()
{
	PrimaryActorTick.bCanEverTick = false;
	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	Root->SetMobility(EComponentMobility::Static);
	SetRootComponent(Root);
	static ConstructorHelpers::FObjectFinderOptional<UStaticMesh> Cube(TEXT("/Engine/BasicShapes/Cube.Cube"));
	int32 Index = 0;
	for (const VerseMovementCourse::FBlock& Block : VerseMovementCourse::Blocks())
	{
		const FString Name = FString::Printf(TEXT("%s_%02d"), Block.Name, Index++);
		UBoxComponent* Box = CreateDefaultSubobject<UBoxComponent>(*(Name + TEXT("_Collision")));
		Box->SetupAttachment(Root);
		Box->SetMobility(EComponentMobility::Static);
		Box->SetRelativeLocationAndRotation(Block.Center, FRotator(Block.PitchDeg, 0.f, 0.f));
		Box->InitBoxExtent(Block.Extent);
		Box->SetCollisionProfileName(VerseCollision::Profile::Architecture);
		Box->SetHiddenInGame(true);
		Boxes.Add(Box);
		if (Cube.Succeeded())
		{
			UStaticMeshComponent* Visual = CreateDefaultSubobject<UStaticMeshComponent>(*(Name + TEXT("_Visual")));
			Visual->SetupAttachment(Box);
			Visual->SetMobility(EComponentMobility::Static);
			Visual->SetStaticMesh(Cube.Get());
			Visual->SetRelativeScale3D(Block.Extent / 50.f);
			Visual->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Visual->SetCanEverAffectNavigation(false);
			Visuals.Add(Visual);
		}
	}
}

AVerseMovementTestGameMode::AVerseMovementTestGameMode()
{
	DefaultPawnClass = AVerseCharacter::StaticClass();
	PrimaryActorTick.bCanEverTick = true;
}

void AVerseMovementTestGameMode::InitGame(const FString& MapName, const FString& Options, FString& ErrorMessage)
{
	Super::InitGame(MapName, Options, ErrorMessage);
	ReportPath = UGameplayStatics::ParseOption(Options, TEXT("VerseNetReport"));
	QuitAfter = FCString::Atof(*UGameplayStatics::ParseOption(Options, TEXT("VerseQuitAfter")));
}

AActor* AVerseMovementTestGameMode::ChoosePlayerStart_Implementation(AController* Player)
{
	TArray<APlayerStart*> Starts;
	for (TActorIterator<APlayerStart> It(GetWorld()); It; ++It)
	{
		Starts.Add(*It);
	}
	Starts.Sort([](const APlayerStart& A, const APlayerStart& B) { return A.GetName() < B.GetName(); });
	if (Starts.IsEmpty())
	{
		return Super::ChoosePlayerStart_Implementation(Player);
	}
	return Starts[StartIndex++ % Starts.Num()];
}

FString AVerseMovementTestGameMode::BuildServerReport() const
{
	FString Pawns;
	for (TActorIterator<AVerseCharacter> It(GetWorld()); It; ++It)
	{
		const UVerseCharacterMovement* Movement = It->GetVerseMovement();
		if (!Movement)
		{
			continue;
		}
		Pawns += FString::Printf(TEXT("%s{\"pawn\": \"%s\", \"mantles\": %d, \"stats\": %s}"), Pawns.IsEmpty() ? TEXT("") : TEXT(", "),
			*It->GetName(), Movement->GetMantleCount(), *Movement->GetNetStats().ToJson());
	}
	return FString::Printf(TEXT("{\"role\": \"server\", \"time\": %.2f, \"pawns\": [%s]}"), GetWorld()->GetTimeSeconds(), *Pawns);
}

void AVerseMovementTestGameMode::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	Elapsed += DeltaSeconds;
	if (QuitAfter > 0.f && Elapsed >= QuitAfter)
	{
		QuitAfter = 0.f;
		if (!ReportPath.IsEmpty() && TActorIterator<AVerseCharacter>(GetWorld()))
		{
			FFileHelper::SaveStringToFile(BuildServerReport(), *ReportPath);
		}
		UE_LOG(LogVerseMovement, Display, TEXT("movement test server: quitting after %.0f s"), Elapsed);
		FPlatformMisc::RequestExit(false);
		return;
	}
	if (ReportPath.IsEmpty())
	{
		return;
	}
	ReportTimer += DeltaSeconds;
	// Keep the last report that still had pawns: the soak clients leave before the server quits.
	if (ReportTimer >= 5.f && TActorIterator<AVerseCharacter>(GetWorld()))
	{
		ReportTimer = 0.f;
		FFileHelper::SaveStringToFile(BuildServerReport(), *ReportPath);
	}
}

void AVerseMovementTestGameMode::EndPlay(const EEndPlayReason::Type Reason)
{
	if (!ReportPath.IsEmpty() && TActorIterator<AVerseCharacter>(GetWorld()))
	{
		FFileHelper::SaveStringToFile(BuildServerReport(), *ReportPath);
	}
	Super::EndPlay(Reason);
}
