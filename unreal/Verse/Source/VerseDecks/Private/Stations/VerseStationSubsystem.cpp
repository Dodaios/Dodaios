#include "Stations/VerseStationSubsystem.h"

#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Stations/VerseStation.h"

UVerseStationSubsystem* UVerseStationSubsystem::Get(const UObject* WorldContext)
{
	if (!WorldContext || !GEngine)
	{
		return nullptr;
	}
	const UWorld* World = GEngine->GetWorldFromContextObject(WorldContext, EGetWorldErrorMode::ReturnNull);
	return World ? World->GetSubsystem<UVerseStationSubsystem>() : nullptr;
}

int32 UVerseStationSubsystem::AddUseTarget(FVerseUseTarget Target)
{
	const int32 Handle = NextHandle++;
	Targets.Add(Handle, MoveTemp(Target));
	return Handle;
}

void UVerseStationSubsystem::RemoveUseTarget(int32 Handle)
{
	if (Targets.Remove(Handle) > 0 && CurrentPrompt.Handle == Handle)
	{
		CurrentPrompt = FVerseStationPrompt();
		OnPromptChanged.Broadcast(CurrentPrompt);
	}
}

void UVerseStationSubsystem::RegisterStation(AVerseStation* Station)
{
	Stations.AddUnique(Station);
}

void UVerseStationSubsystem::UnregisterStation(AVerseStation* Station)
{
	Stations.Remove(Station);
}

AVerseStation* UVerseStationSubsystem::FindStation(FName StationId) const
{
	for (const TWeakObjectPtr<AVerseStation>& Station : Stations)
	{
		if (Station.IsValid() && Station->StationId == StationId)
		{
			return Station.Get();
		}
	}
	return nullptr;
}

int32 UVerseStationSubsystem::PickWithin(TConstArrayView<FVector> Locations, const FVector& At, float Reach, const FVector* Facing)
{
	int32 Best = INDEX_NONE;
	double BestScore = TNumericLimits<double>::Max();
	FVector2D Face(0.0, 0.0);
	if (Facing)
	{
		Face = FVector2D(Facing->X, Facing->Y).GetSafeNormal();
	}
	for (int32 I = 0; I < Locations.Num(); ++I)
	{
		const double Dx = Locations[I].X - At.X;
		const double Dy = Locations[I].Y - At.Y;
		const double D = FMath::Sqrt(Dx * Dx + Dy * Dy);
		if (D > Reach)
		{
			continue;
		}
		// One under the commander's feet counts as in front (30 cm, as 0.3 m in control.ts).
		const double Cos = (Facing && !Face.IsNearlyZero() && D > 30.0) ? (Dx * Face.X + Dy * Face.Y) / D : 1.0;
		const double Score = D * (1.5 - 0.5 * Cos);
		if (Score < BestScore)
		{
			BestScore = Score;
			Best = I;
		}
	}
	return Best;
}

int32 UVerseStationSubsystem::PickTarget(const FVector& At, const FVector* Facing, const AActor* CrosshairActor) const
{
	TArray<FVector> Locations;
	TArray<int32> Handles;
	for (const TPair<int32, FVerseUseTarget>& Pair : Targets)
	{
		const FVerseUseTarget& T = Pair.Value;
		if (T.CanUse && !T.CanUse())
		{
			continue;
		}
		const FVector Location = T.Location ? T.Location() : FVector::ZeroVector;
		// The crosshair wins only within the same reach as everything else (parity, control.ts):
		// the view trace is longer than the reach, so it alone would make far stations usable.
		if (CrosshairActor && T.Owner.Get() == CrosshairActor
			&& FVector::DistSquared2D(Location, At) <= FMath::Square(double(VerseStations::ReachCm)))
		{
			return Pair.Key;
		}
		Locations.Add(Location);
		Handles.Add(Pair.Key);
	}
	const int32 Index = PickWithin(Locations, At, VerseStations::ReachCm, Facing);
	return Index == INDEX_NONE ? INDEX_NONE : Handles[Index];
}

void UVerseStationSubsystem::SetViewerOverride(const FVector& Location, const FVector& Facing, AActor* CrosshairActor)
{
	bViewerOverride = true;
	OverrideLocation = Location;
	OverrideFacing = Facing;
	OverrideCrosshair = CrosshairActor;
}

void UVerseStationSubsystem::ClearViewerOverride()
{
	bViewerOverride = false;
	OverrideCrosshair.Reset();
}

bool UVerseStationSubsystem::ReadViewer(FVector& OutLocation, FVector& OutFacing, const AActor*& OutCrosshair) const
{
	OutCrosshair = nullptr;
	if (bViewerOverride)
	{
		OutLocation = OverrideLocation;
		OutFacing = OverrideFacing;
		OutCrosshair = OverrideCrosshair.Get();
		return true;
	}
	const UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	const APawn* Pawn = PC ? PC->GetPawn() : nullptr;
	if (!Pawn)
	{
		return false;
	}
	OutLocation = Pawn->GetActorLocation();
	OutFacing = PC->GetControlRotation().Vector();
	FVector ViewLoc;
	FRotator ViewRot;
	PC->GetPlayerViewPoint(ViewLoc, ViewRot);
	FHitResult Hit;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseStationCrosshair), false, Pawn);
	if (World->LineTraceSingleByChannel(Hit, ViewLoc, ViewLoc + ViewRot.Vector() * 400.0, ECC_Visibility, Params))
	{
		OutCrosshair = Hit.GetActor();
	}
	return true;
}

void UVerseStationSubsystem::RefreshPrompt()
{
	FVector At;
	FVector Facing;
	const AActor* Crosshair = nullptr;
	FVerseStationPrompt Next;
	if (ReadViewer(At, Facing, Crosshair))
	{
		const int32 Handle = PickTarget(At, &Facing, Crosshair);
		if (const FVerseUseTarget* T = Targets.Find(Handle))
		{
			Next.Handle = Handle;
			Next.Label = T->Label ? T->Label() : FString();
			Next.Action = T->Action ? T->Action() : FString();
		}
	}
	if (!(Next == CurrentPrompt))
	{
		CurrentPrompt = Next;
		OnPromptChanged.Broadcast(CurrentPrompt);
	}
}

bool UVerseStationSubsystem::UseFocused(int32 UserId)
{
	RefreshPrompt();
	return UseTarget(CurrentPrompt.Handle, UserId);
}

bool UVerseStationSubsystem::UseTarget(int32 Handle, int32 UserId)
{
	const FVerseUseTarget* T = Targets.Find(Handle);
	if (!T || (T->CanUse && !T->CanUse()) || !T->Use)
	{
		return false;
	}
	// Copy: Use may add or remove targets.
	const TFunction<void(int32)> UseFn = T->Use;
	UseFn(UserId);
	return true;
}

void UVerseStationSubsystem::PostNotice(const FString& Text)
{
	if (!Text.IsEmpty())
	{
		OnNotice.Broadcast(Text);
	}
}

FString UVerseStationSubsystem::ErrorText(const FString& Code) const
{
	const TCHAR* Fallback = TEXT("That did not work.");
	if (Code == TEXT("rate_limited")) { Fallback = TEXT("Too many requests. Wait a moment, then try again."); }
	else if (Code == TEXT("busy")) { Fallback = TEXT("A batch is already starting."); }
	else if (Code == TEXT("not_found")) { Fallback = TEXT("That is no longer there."); }
	else if (Code == TEXT("unavailable")) { Fallback = TEXT("That is not available right now."); }
	else if (Code == TEXT("conflict")) { Fallback = TEXT("That was declined."); }
	const FString Key = FString::Printf(TEXT("verse.station.error.%s"), Code.IsEmpty() ? TEXT("internal") : *Code);
	return Localize(Key, Fallback);
}

void UVerseStationSubsystem::Tick(float DeltaTime)
{
	SincePrompt += DeltaTime;
	if (SincePrompt >= VerseStations::PromptIntervalS)
	{
		SincePrompt = 0.f;
		RefreshPrompt();
	}
}

TStatId UVerseStationSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseStationSubsystem, STATGROUP_Tickables);
}

void UVerseStationSubsystem::Deinitialize()
{
	Targets.Reset();
	Stations.Reset();
	OnPromptChanged.Clear();
	OnNotice.Clear();
	Link.Reset();
	Super::Deinitialize();
}
