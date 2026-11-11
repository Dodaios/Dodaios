#include "Life/VerseDeckDrone.h"

#include "Animation/AnimSequence.h"
#include "Commander/VerseDeckCommander.h"
#include "Commander/VerseDeckNavGrid.h"
#include "Commander/VerseDeckWalk.h"
#include "Components/SkeletalMeshComponent.h"
#include "Decks/VerseDeckManifest.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Input/VerseDeckControlComponent.h"
#include "VerseLog.h"

const TCHAR* AVerseDeckDrone::CompanionMeshPath = TEXT("/Game/Verse/Characters/Drones/SK_Drone_Companion.SK_Drone_Companion");
const TCHAR* AVerseDeckDrone::UtilityMeshPath = TEXT("/Game/Verse/Characters/Drones/SK_Drone_Utility.SK_Drone_Utility");

namespace
{
	const FName Hover(TEXT("hover"));
	const FName Walk(TEXT("walk"));

	/** `actors/clips.ts` resolved for each kind: (motion, clip asset). */
	struct FClipEntry
	{
		FName Motion;
		const TCHAR* Path;
	};
	const FClipEntry CompanionClips[] = {
		{ Hover, TEXT("/Game/Verse/Animations/Drones/A_Drone_Companion_Hover.A_Drone_Companion_Hover") },
		// A drone without a drive clip walks with A_Follow (`actor.ts` play).
		{ Walk, TEXT("/Game/Verse/Animations/Drones/A_Drone_Companion_Follow.A_Drone_Companion_Follow") },
	};
	const FClipEntry UtilityClips[] = {
		// No A_Hover: hover falls back to the idle clip.
		{ Hover, TEXT("/Game/Verse/Animations/Drones/A_Drone_Utility_Idle.A_Drone_Utility_Idle") },
		{ Walk, TEXT("/Game/Verse/Animations/Drones/A_Drone_Utility_Drive.A_Drone_Utility_Drive") },
	};

	double YawToDeg(const FVector& From, const FVector& To)
	{
		return FMath::RadiansToDegrees(FMath::Atan2(To.Y - From.Y, To.X - From.X));
	}

	uint32 Hash(const FString& Text)
	{
		return GetTypeHash(Text);
	}
}

namespace VerseDeckDrones
{
	TPair<FString, int32> SocketGroup(const FString& Id)
	{
		const int32 Cut = Id.Find(TEXT("__"), ESearchCase::CaseSensitive, ESearchDir::FromEnd);
		if (Cut > 0)
		{
			const FString Tail = Id.Mid(Cut + 2);
			return { Id.Left(Cut), Tail.IsNumeric() && !Tail.Contains(TEXT(".")) && !Tail.Contains(TEXT("-")) ? FCString::Atoi(*Tail) : 0 };
		}
		// /^(.*?)_?(\d+)$/
		int32 Digits = 0;
		while (Digits < Id.Len() && FChar::IsDigit(Id[Id.Len() - 1 - Digits]))
		{
			++Digits;
		}
		if (Digits == 0)
		{
			return { Id, 0 };
		}
		FString Head = Id.Left(Id.Len() - Digits);
		if (Head.EndsWith(TEXT("_")))
		{
			Head.LeftChopInline(1);
		}
		return { Head, FCString::Atoi(*Id.Right(Digits)) };
	}

	TArray<FVerseDroneRoute> UtilityRoutes(const FVerseDeckManifest& Manifest, int32 MaxDrones)
	{
		struct FPoint
		{
			int32 Order;
			FVector Feet;
		};
		TArray<FString> Order;
		TMap<FString, TArray<FPoint>> Groups;
		for (const FVerseDeckSocket* Socket : Manifest.SocketsOfKind(TEXT("waypoint")))
		{
			const TPair<FString, int32> G = SocketGroup(Socket->ManifestId.ToString());
			if (!Groups.Contains(G.Key))
			{
				Order.Add(G.Key);
			}
			Groups.FindOrAdd(G.Key).Add({ G.Value, Socket->Transform.GetLocation() });
		}
		TArray<FVerseDroneRoute> Out;
		for (const FString& Group : Order)
		{
			TArray<FPoint>& Points = Groups[Group];
			const bool bDroneRoute = Group.StartsWith(TEXT("service")) || Group.StartsWith(TEXT("cargo")) || Group.StartsWith(TEXT("pad")) || Group.StartsWith(TEXT("corridor"));
			if (Points.Num() < 2 || !bDroneRoute || Out.Num() >= MaxDrones)
			{
				continue;
			}
			Points.StableSort([](const FPoint& A, const FPoint& B) { return A.Order < B.Order; });
			FVerseDroneRoute& Route = Out.AddDefaulted_GetRef();
			Route.Group = FName(*Group);
			for (const FPoint& P : Points)
			{
				Route.Points.Add(P.Feet);
			}
		}
		return Out;
	}

	FVector HeelPoint(const FVector& LeaderFeet, double LeaderYawDeg)
	{
		const FVector Forward = FRotator(0.0, LeaderYawDeg, 0.0).Vector();
		const FVector Right = FRotator(0.0, LeaderYawDeg + 90.0, 0.0).Vector();
		return LeaderFeet - Forward * HeelCm - Right * HeelSideCm;
	}
}

AVerseDeckDrone::AVerseDeckDrone()
{
	PrimaryActorTick.bCanEverTick = true;
	RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	Body = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Body"));
	Body->SetupAttachment(RootComponent);
	Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Body->SetCanEverAffectNavigation(false);
	// The mesh faces +Y in its own space (coordinates.md 3.3); the actor's forward is +X.
	Body->SetRelativeRotation(FRotator(0.0, -90.0, 0.0));
	Body->SetAnimationMode(EAnimationMode::AnimationSingleNode);
}

bool AVerseDeckDrone::Init(EVerseDroneKind InKind, const FVector& FeetCm, double YawDeg)
{
	Kind = InKind;
	USkeletalMesh* Mesh = LoadObject<USkeletalMesh>(nullptr, Kind == EVerseDroneKind::Companion ? CompanionMeshPath : UtilityMeshPath, nullptr, LOAD_NoWarn | LOAD_Quiet);
	if (Mesh == nullptr)
	{
		UE_LOG(LogVerseDecks, Warning, TEXT("drone: no mesh %s"), Kind == EVerseDroneKind::Companion ? CompanionMeshPath : UtilityMeshPath);
		return false;
	}
	Body->SetSkeletalMeshAsset(Mesh);
	Clips.Reset();
	const TArrayView<const FClipEntry> Entries = Kind == EVerseDroneKind::Companion ? TArrayView<const FClipEntry>(CompanionClips) : TArrayView<const FClipEntry>(UtilityClips);
	for (const FClipEntry& Entry : Entries)
	{
		if (UAnimSequence* Seq = LoadObject<UAnimSequence>(nullptr, Entry.Path, nullptr, LOAD_NoWarn | LOAD_Quiet))
		{
			Clips.Add(Entry.Motion, Seq);
		}
		else
		{
			UE_LOG(LogVerseDecks, Warning, TEXT("drone: no clip %s"), Entry.Path);
		}
	}
	Yaw = YawDeg;
	SetActorLocationAndRotation(FeetCm, FRotator(0.0, Yaw, 0.0));
	Play(Hover);
	return true;
}

void AVerseDeckDrone::SetRoute(const FVerseDroneRoute& InRoute)
{
	Route = InRoute;
	RouteIndex = 0;
}

const FVerseDeckNavGrid* AVerseDeckDrone::Nav() const
{
	if (NavOverride)
	{
		return NavOverride;
	}
	const UVerseDeckControlComponent* Control = UVerseDeckControlComponent::Get(GetWorld());
	return Control && Control->GetNav().IsComplete() ? &Control->GetNav() : nullptr;
}

void AVerseDeckDrone::Play(FName Motion)
{
	TObjectPtr<UAnimSequence>* Seq = Clips.Find(Motion);
	if (Seq == nullptr || *Seq == nullptr || (Clip == Motion && Body->IsPlaying()))
	{
		Clip = Motion;
		return;
	}
	Clip = Motion;
	Body->PlayAnimation(*Seq, true);
	if (Motion != Walk)
	{
		// Drones idling side by side must not bob in step (`actor.ts` play).
		const double Length = (*Seq)->GetPlayLength();
		Body->SetPosition(float(double(Hash(GetName()) % 1000) / 1000.0 * Length), false);
	}
	Body->SetPlayRate(1.f);
}

bool AVerseDeckDrone::PlanTo(const FVector& Goal)
{
	const FVerseDeckNavGrid* Grid = Nav();
	TArray<FVector> Points;
	if (Grid == nullptr || !Grid->FindPath(GetActorLocation(), Goal, Points) || Points.Num() < 2)
	{
		return false;
	}
	Points.RemoveAt(0);
	Path = MoveTemp(Points);
	return true;
}

bool AVerseDeckDrone::WalkStep(float DeltaSeconds, double PaceCmPerS)
{
	if (Path.Num() == 0)
	{
		return true;
	}
	FVector Feet = GetActorLocation();
	const double Heading = YawToDeg(Feet, Path[0]);
	Yaw = Verse::DeckWalk::TurnToward(Yaw, Heading, VerseDeckDrones::TurnRateDegPerS, DeltaSeconds);
	// Slow into tight turns (`actor.ts` walk).
	const double Speed = PaceCmPerS * Verse::DeckWalk::TurnPace(Yaw, Heading);
	double Left = Speed * DeltaSeconds;
	while (Left > 0.0 && Path.Num() > 0)
	{
		const FVector2D To(Path[0].X - Feet.X, Path[0].Y - Feet.Y);
		const double D = To.Size();
		if (D <= Left)
		{
			Feet.X = Path[0].X;
			Feet.Y = Path[0].Y;
			Left -= D;
			Path.RemoveAt(0);
			continue;
		}
		Feet.X += To.X / D * Left;
		Feet.Y += To.Y / D * Left;
		Left = 0.0;
	}
	// The floor under the drone, eased like `actor.ts` (y += (ground - y) * min(1, dt * 12)).
	const FVerseDeckNavGrid* Grid = Nav();
	const TOptional<double> Ground = Grid ? Grid->FloorHeight(FVector2D(Feet.X, Feet.Y)) : TOptional<double>();
	if (Ground.IsSet())
	{
		Feet.Z += (Ground.GetValue() - Feet.Z) * FMath::Min(1.0, DeltaSeconds * 12.0);
	}
	SetActorLocationAndRotation(Feet, FRotator(0.0, Yaw, 0.0));
	const double WalkSpeed = Kind == EVerseDroneKind::Utility ? VerseDeckDrones::UtilityPaceCmPerS : 130.0;
	Play(Walk);
	Body->SetPlayRate(float(Speed / WalkSpeed));
	return Path.Num() == 0;
}

void AVerseDeckDrone::Follow(float DeltaSeconds)
{
	AActor* Lead = Leader.Get();
	if (Lead == nullptr)
	{
		Lead = AVerseDeckCommander::Find(GetWorld());
		Leader = Lead;
	}
	if (Lead == nullptr)
	{
		Play(Hover);
		return;
	}
	const AVerseDeckCommander* Commander = Cast<AVerseDeckCommander>(Lead);
	const FVector LeaderFeet = Commander ? Commander->GetFeet() : Lead->GetActorLocation();
	const double LeaderYaw = Lead->GetActorRotation().Yaw;
	const bool bLeaderMoving = Commander ? Commander->GetFloorSpeed() > 5.0 : Lead->GetVelocity().Size2D() > 5.0;
	const FVector Feet = GetActorLocation();
	const double D = FVector2D(LeaderFeet.X - Feet.X, LeaderFeet.Y - Feet.Y).Size();
	if (!bWalking && D > VerseDeckDrones::HeelCm * 1.5 && Clock - LastPlan > VerseDeckDrones::ReplanS)
	{
		LastPlan = Clock;
		if (PlanTo(VerseDeckDrones::HeelPoint(LeaderFeet, LeaderYaw)))
		{
			bWalking = true;
		}
	}
	if (bWalking)
	{
		const bool bDone = WalkStep(DeltaSeconds, VerseDeckDrones::CompanionPaceCmPerS);
		if (bDone || D < VerseDeckDrones::HeelCm)
		{
			Path.Reset();
			bWalking = false;
		}
		else
		{
			return;
		}
	}
	Play(Hover);
	Body->SetPlayRate(1.f);
	const double Target = bLeaderMoving ? LeaderYaw : YawToDeg(Feet, LeaderFeet);
	Yaw = Verse::DeckWalk::TurnToward(Yaw, Target, VerseDeckDrones::TurnRateDegPerS * 0.4, DeltaSeconds);
	SetActorRotation(FRotator(0.0, Yaw, 0.0));
}

void AVerseDeckDrone::Drive(float DeltaSeconds)
{
	if (Route.Points.Num() == 0)
	{
		Play(Hover);
		return;
	}
	if (!bWalking)
	{
		const FVector Next = Route.Points[RouteIndex % Route.Points.Num()];
		if (!PlanTo(Next))
		{
			// There already, or no way there: on to the next point (`actor.ts` arrive).
			++RouteIndex;
			Play(Hover);
			Body->SetPlayRate(1.f);
			return;
		}
		bWalking = true;
	}
	if (WalkStep(DeltaSeconds, VerseDeckDrones::UtilityPaceCmPerS))
	{
		bWalking = false;
		++RouteIndex;
	}
}

void AVerseDeckDrone::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	Clock += DeltaSeconds;
	if (Kind == EVerseDroneKind::Companion)
	{
		Follow(DeltaSeconds);
	}
	else
	{
		Drive(DeltaSeconds);
	}
}

int32 AVerseDeckDrone::SpawnForDeck(UWorld* World, const FVerseDeckManifest& Manifest)
{
	if (World == nullptr)
	{
		return 0;
	}
	for (TActorIterator<AVerseDeckDrone> It(World); It; ++It)
	{
		It->Destroy();
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	Params.ObjectFlags |= RF_Transient;
	int32 Spawned = 0;
	if (const AVerseDeckCommander* Commander = AVerseDeckCommander::Find(World))
	{
		const double Yaw = Commander->GetActorRotation().Yaw;
		if (AVerseDeckDrone* Drone = World->SpawnActor<AVerseDeckDrone>(Params))
		{
			if (Drone->Init(EVerseDroneKind::Companion, VerseDeckDrones::HeelPoint(Commander->GetFeet(), Yaw), Yaw))
			{
				++Spawned;
			}
			else
			{
				Drone->Destroy();
			}
		}
	}
	for (const FVerseDroneRoute& Route : VerseDeckDrones::UtilityRoutes(Manifest))
	{
		AVerseDeckDrone* Drone = World->SpawnActor<AVerseDeckDrone>(Params);
		if (Drone == nullptr)
		{
			continue;
		}
		const double Yaw = YawToDeg(Route.Points[0], Route.Points[1]);
		if (!Drone->Init(EVerseDroneKind::Utility, Route.Points[0], Yaw))
		{
			Drone->Destroy();
			continue;
		}
		Drone->SetRoute(Route);
		++Spawned;
	}
	UE_LOG(LogVerseDecks, Log, TEXT("deck %s: %d drones"), *Manifest.Deck.ToString(), Spawned);
	return Spawned;
}
