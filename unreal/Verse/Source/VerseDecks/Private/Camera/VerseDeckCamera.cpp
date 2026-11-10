#include "Camera/VerseDeckCamera.h"

#include "Camera/CameraComponent.h"
#include "Commander/VerseDeckCommander.h"
#include "Dom/JsonObject.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

AVerseDeckCamera::AVerseDeckCamera()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PostPhysics;
	Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
	RootComponent = Camera;
	Camera->SetConstraintAspectRatio(false);
	Camera->SetFieldOfView(static_cast<float>(Rig.Tuning.HfovThirdDeg));
}

void AVerseDeckCamera::SetViewByName(const FString& Name)
{
	const TOptional<EVerseDeckView> Parsed = Verse::DeckView::FromName(Name);
	if (Parsed.IsSet())
	{
		SetView(Parsed.GetValue());
	}
}

void AVerseDeckCamera::SetView(EVerseDeckView NewView)
{
	View = Verse::DeckView::Resolve(NewView, bEyeCapable);
	if (View == EVerseDeckView::First)
	{
		Rig.SetPerson(EVerseDeckPerson::First);
	}
	else if (View == EVerseDeckView::Third)
	{
		Rig.SetPerson(EVerseDeckPerson::Third);
	}
	// Choosing third or first takes the mouse at once; overview gives it back (parity V-20).
	bMouseLocked = View != EVerseDeckView::Overview;
}

void AVerseDeckCamera::CycleView()
{
	SetView(Verse::DeckView::Cycle(View, bEyeCapable));
}

void AVerseDeckCamera::Look(float Dx, float Dy, bool bCaptured)
{
	if (View == EVerseDeckView::Overview)
	{
		Overview.Look(Dx * Rig.Tuning.DragDegPerPx);
		return;
	}
	Rig.Look(Dx, Dy, bCaptured);
}

void AVerseDeckCamera::Zoom(float Factor)
{
	if (View == EVerseDeckView::Overview)
	{
		Overview.Zoom(Factor);
		return;
	}
	const TOptional<EVerseDeckPerson> Changed = Rig.Zoom(Factor);
	if (Changed.IsSet())
	{
		View = Changed.GetValue() == EVerseDeckPerson::First ? EVerseDeckView::First : EVerseDeckView::Third;
	}
}

void AVerseDeckCamera::Pan(FVector2D Input, float DeltaSeconds)
{
	if (View == EVerseDeckView::Overview)
	{
		Overview.Pan(Input, DeltaSeconds);
	}
}

void AVerseDeckCamera::FocusCommander()
{
	FVerseRigBody Body;
	if (!CommanderPose(Body))
	{
		return;
	}
	if (View == EVerseDeckView::Overview)
	{
		Overview.Focus(Body.FeetCm);
	}
	else
	{
		Rig.SnapBehind(Body.HeadingDeg);
	}
}

bool AVerseDeckCamera::ReturnFocus()
{
	return View == EVerseDeckView::Overview && Overview.Return();
}

void AVerseDeckCamera::FrameArrival(const FTransform& Arrival)
{
	Overview.CentreCm = Arrival.GetLocation();
	Rig.SnapBehind(Arrival.Rotator().Yaw);
}

bool AVerseDeckCamera::CommanderPose(FVerseRigBody& Out) const
{
	const UWorld* World = GetWorld();
	const APlayerController* Controller = World ? World->GetFirstPlayerController() : nullptr;
	// The deck commander when one walks the deck (stream S5), else the controller's pawn.
	const AVerseDeckCommander* Commander = AVerseDeckCommander::Find(World);
	const APawn* Pawn = Commander && !Commander->IsHidden() ? static_cast<const APawn*>(Commander) : (Controller ? Controller->GetPawn() : nullptr);
	if (Pawn == nullptr)
	{
		return false;
	}
	float Radius = 0.f;
	float HalfHeight = 0.f;
	Pawn->GetSimpleCollisionCylinder(Radius, HalfHeight);
	Out.FeetCm = Pawn->GetActorLocation() - FVector(0.0, 0.0, HalfHeight);
	Out.HeadingDeg = Pawn->GetActorRotation().Yaw;
	return true;
}

TOptional<double> AVerseDeckCamera::Trace(const FVector& From, const FVector& To) const
{
	const UWorld* World = GetWorld();
	if (World == nullptr || From.Equals(To))
	{
		return {};
	}
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseDeckCamera), false, this);
	const APlayerController* Controller = World->GetFirstPlayerController();
	if (const APawn* Pawn = Controller ? Controller->GetPawn() : nullptr)
	{
		Params.AddIgnoredActor(Pawn);
	}
	if (const AVerseDeckCommander* Commander = AVerseDeckCommander::Find(World))
	{
		Params.AddIgnoredActor(Commander);
	}
	FHitResult Hit;
	if (World->LineTraceSingleByChannel(Hit, From, To, ECC_Camera, Params))
	{
		return static_cast<double>(Hit.Time);
	}
	return {};
}

void AVerseDeckCamera::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	FVerseRigBody Body;
	const bool bHasBody = CommanderPose(Body);
	if (View == EVerseDeckView::Overview || !bHasBody)
	{
		Overview.Update();
	}
	else
	{
		Rig.Update(DeltaSeconds, Body, [this](const FVector& From, const FVector& To) { return Trace(From, To); });
	}
	Apply();
}

void AVerseDeckCamera::Apply()
{
	if (View == EVerseDeckView::Overview)
	{
		SetActorLocationAndRotation(Overview.Location, Overview.Rotation);
		Camera->SetFieldOfView(static_cast<float>(Rig.Tuning.HfovThirdDeg));
		return;
	}
	SetActorLocationAndRotation(Rig.Location, Rig.Rotation);
	Camera->SetFieldOfView(static_cast<float>(Rig.Hfov()));
}

FString AVerseDeckCamera::StateJson() const
{
	const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("view"), Verse::DeckView::Name(View));
	Root->SetStringField(TEXT("person"), Rig.Person == EVerseDeckPerson::First ? TEXT("first") : TEXT("third"));
	Root->SetNumberField(TEXT("distance"), View == EVerseDeckView::Overview ? Overview.DistanceCm : Rig.DistanceCm);
	Root->SetNumberField(TEXT("hfov"), View == EVerseDeckView::Overview ? Rig.Tuning.HfovThirdDeg : Rig.Hfov());
	Root->SetNumberField(TEXT("yaw"), View == EVerseDeckView::Overview ? Overview.YawDeg : Rig.YawDeg);
	Root->SetNumberField(TEXT("pitch"), View == EVerseDeckView::Overview ? Overview.PitchDeg : Rig.PitchDeg);
	Root->SetBoolField(TEXT("commander_hidden"), View == EVerseDeckView::First && Rig.FirstShare > 0.5);
	Root->SetBoolField(TEXT("locked"), bMouseLocked);
	FString Out;
	const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
		TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
	FJsonSerializer::Serialize(Root, Writer);
	return Out;
}
