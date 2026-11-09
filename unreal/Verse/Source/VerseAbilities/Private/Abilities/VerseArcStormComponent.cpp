#include "Abilities/VerseArcStormComponent.h"

#include "Abilities/VerseAbilitiesLog.h"
#include "Abilities/VerseArcSound.h"
#include "AudioDevice.h"
#include "Components/AudioComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Controller.h"
#include "GameFramework/Pawn.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/CoreDelegates.h"

const TCHAR* UVerseArcStormComponent::BoltMaterialPath = TEXT("/Game/Verse/Characters/Sovereign/M_Sov_ArcBolt.M_Sov_ArcBolt");

namespace
{
	const TCHAR* CylinderPath = TEXT("/Engine/BasicShapes/Cylinder.Cylinder");
	/** Bolt widths, cm: the core flickers between the two, the glow stays wide. */
	constexpr float CoreMinCm = 0.5f;
	constexpr float CoreMaxCm = 1.1f;
	constexpr float GlowCm = 6.f;
	/** Light at the hands and where the bolts land, candela. */
	constexpr float HandLightCd = 60.f;
	constexpr float ImpactLightCd = 30.f;
	constexpr int32 SoundLogCap = 512;

	/** The world transform that stretches the 100 cm basic cylinder over `A`..`B` at `WidthCm`. */
	FTransform SegmentTransform(const FVector& A, const FVector& B, float WidthCm)
	{
		const FVector Dir = B - A;
		const double Len = Dir.Size();
		const FQuat Rot = Len > 1e-3 ? FRotationMatrix::MakeFromZ(Dir / Len).ToQuat() : FQuat::Identity;
		return FTransform(Rot, (A + B) * 0.5, FVector(WidthCm / 100.0, WidthCm / 100.0, Len / 100.0));
	}

	UInstancedStaticMeshComponent* MakeLayer(UVerseArcStormComponent* Owner, FName Name)
	{
		UInstancedStaticMeshComponent* Layer = NewObject<UInstancedStaticMeshComponent>(Owner->GetOwner(), Name, RF_Transient);
		Layer->SetupAttachment(Owner);
		Layer->SetUsingAbsoluteLocation(true);
		Layer->SetUsingAbsoluteRotation(true);
		Layer->SetUsingAbsoluteScale(true);
		Layer->SetWorldTransform(FTransform::Identity);
		Layer->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, CylinderPath));
		Layer->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Layer->SetCastShadow(false);
		Layer->SetCanEverAffectNavigation(false);
		Layer->bDisableCollision = true;
		Layer->SetVisibility(false);
		Layer->RegisterComponent();
		return Layer;
	}

	UPointLightComponent* MakeLight(UVerseArcStormComponent* Owner, FName Name, float Radius)
	{
		UPointLightComponent* Light = NewObject<UPointLightComponent>(Owner->GetOwner(), Name, RF_Transient);
		Light->SetupAttachment(Owner);
		Light->SetUsingAbsoluteLocation(true);
		Light->SetMobility(EComponentMobility::Movable);
		Light->SetIntensityUnits(ELightUnits::Candelas);
		Light->SetIntensity(0.f);
		Light->SetAttenuationRadius(Radius);
		Light->SetLightColor(VerseArc::GlowColor());
		Light->SetCastShadows(false);
		Light->RegisterComponent();
		return Light;
	}
}

UVerseArcStormComponent::UVerseArcStormComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	// After animation: the hand sockets are this frame's.
	PrimaryComponentTick.TickGroup = TG_PostUpdateWork;
	Flicker.Initialize(0x5eed);
}

void UVerseArcStormComponent::OnRegister()
{
	Super::OnRegister();
	if (CoreLayer || !GetOwner())
	{
		return;
	}
	CoreLayer = MakeLayer(this, TEXT("ArcCore"));
	GlowLayer = MakeLayer(this, TEXT("ArcGlow"));
	if (UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, BoltMaterialPath))
	{
		CoreMaterial = UMaterialInstanceDynamic::Create(Material, this);
		CoreMaterial->SetVectorParameterValue(TEXT("Color"), VerseArc::CoreColor());
		CoreMaterial->SetScalarParameterValue(TEXT("Intensity"), 30.f);
		GlowMaterial = UMaterialInstanceDynamic::Create(Material, this);
		GlowMaterial->SetVectorParameterValue(TEXT("Color"), VerseArc::GlowColor());
		GlowMaterial->SetScalarParameterValue(TEXT("Intensity"), 4.f);
		CoreLayer->SetMaterial(0, CoreMaterial);
		GlowLayer->SetMaterial(0, GlowMaterial);
	}
	else
	{
		UE_LOG(LogVerseAbilities, Log, TEXT("Arc Storm: %s is missing; bolts draw with the default material"), BoltMaterialPath);
	}
	HandLight = MakeLight(this, TEXT("ArcHandLight"), 700.f);
	ImpactLight = MakeLight(this, TEXT("ArcImpactLight"), 400.f);
}

void UVerseArcStormComponent::BeginPlay()
{
	Super::BeginPlay();
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		ArenaHandle = Hub->OnArenaSwitch.AddUObject(this, &UVerseArcStormComponent::OnArenaSwitch);
	}
	FocusHandle = FCoreDelegates::ApplicationWillDeactivateDelegate.AddUObject(this, &UVerseArcStormComponent::OnAppDeactivate);
	// Silent without audio: no device, no sound component (the log still runs).
	if (UWorld* World = GetWorld(); World && World->GetAudioDevice())
	{
		Wave = NewObject<UVerseArcSoundWave>(this, TEXT("ArcSound"), RF_Transient);
		Sound = NewObject<UAudioComponent>(GetOwner(), TEXT("ArcAudio"), RF_Transient);
		Sound->SetupAttachment(this);
		Sound->bAutoActivate = false;
		Sound->bAllowSpatialization = true;
		Sound->SetSound(Wave);
		Sound->RegisterComponent();
	}
}

void UVerseArcStormComponent::EndPlay(const EEndPlayReason::Type Reason)
{
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnArenaSwitch.Remove(ArenaHandle);
	}
	FCoreDelegates::ApplicationWillDeactivateDelegate.Remove(FocusHandle);
	if (Sound)
	{
		Sound->Stop();
	}
	Super::EndPlay(Reason);
}

void UVerseArcStormComponent::SetHeld(bool bInHeld)
{
	bHeld = bInHeld && !bArenaOn;
}

void UVerseArcStormComponent::SetBody(USkeletalMeshComponent* InBody)
{
	Body = InBody;
}

void UVerseArcStormComponent::SetArenaOn(bool bOn)
{
	bArenaOn = bOn;
	if (bOn)
	{
		bHeld = false;
		Level = 0.f;
		Hide();
		UpdateSound(0.f);
	}
}

void UVerseArcStormComponent::ReleaseOnFocusLoss()
{
	bHeld = false;
}

void UVerseArcStormComponent::OnArenaSwitch(const FVerseArenaSwitchEvent& Event)
{
	SetArenaOn(Event.bArenaOn);
}

void UVerseArcStormComponent::OnAppDeactivate()
{
	ReleaseOnFocusLoss();
}

TArray<FVector> UVerseArcStormComponent::GetHands() const
{
	if (HandsOverride.Num() > 0)
	{
		return HandsOverride;
	}
	TArray<FVector> Hands;
	if (const USkeletalMeshComponent* Mesh = Body.Get())
	{
		for (const TCHAR* Side : {TEXT("L"), TEXT("R")})
		{
			for (const FString& Name : {FString::Printf(TEXT("Middle_03_%s"), Side), FString::Printf(TEXT("Hand_%s"), Side)})
			{
				if (Mesh->DoesSocketExist(*Name))
				{
					Hands.Add(Mesh->GetSocketLocation(*Name));
					break;
				}
			}
		}
		return Hands;
	}
	// No body (first person without arms): the bottom corners of the view, where the hands are.
	if (const APawn* Pawn = Cast<APawn>(GetOwner()))
	{
		const FVector Eye = Pawn->GetPawnViewLocation();
		const FRotationMatrix View(Pawn->GetViewRotation());
		const FVector F = View.GetUnitAxis(EAxis::X);
		const FVector R = View.GetUnitAxis(EAxis::Y);
		const FVector U = View.GetUnitAxis(EAxis::Z);
		Hands.Add(Eye + F * 45.0 - R * 22.0 - U * 28.0);
		Hands.Add(Eye + F * 45.0 + R * 22.0 - U * 28.0);
	}
	return Hands;
}

FVector UVerseArcStormComponent::GetAim() const
{
	const AActor* Owner = GetOwner();
	if (!Owner)
	{
		return GetForwardVector();
	}
	if (AimMode == EVerseArcAim::View)
	{
		if (const APawn* Pawn = Cast<APawn>(Owner); Pawn && Pawn->GetController())
		{
			return Pawn->GetController()->GetControlRotation().Vector();
		}
	}
	// The body's facing, level.
	return FVector(Owner->GetActorForwardVector().X, Owner->GetActorForwardVector().Y, 0.0).GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);
}

float UVerseArcStormComponent::GetHandLightIntensity() const
{
	return HandLight ? HandLight->Intensity : 0.f;
}

int32 UVerseArcStormComponent::GetDrawnSegments() const
{
	return CoreLayer && CoreLayer->IsVisible() ? CoreLayer->GetInstanceCount() : 0;
}

float UVerseArcStormComponent::FloorBelow(const FVector& From) const
{
	FHitResult Hit;
	FCollisionQueryParams Params(TEXT("ArcFloor"), false, GetOwner());
	const UWorld* World = GetWorld();
	if (World && World->LineTraceSingleByChannel(Hit, From, From - FVector(0.0, 0.0, 400.0), ECC_Visibility, Params))
	{
		return float(Hit.ImpactPoint.Z);
	}
	return float(From.Z) - 1000.f;
}

void UVerseArcStormComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	Step(DeltaTime);
}

void UVerseArcStormComponent::Step(float DeltaTime)
{
	if (!CoreLayer)
	{
		return;
	}
	const float Dt = FMath::Clamp(DeltaTime, 0.f, 0.1f);
	const bool bWasSilent = Level <= 0.f;
	Level = VerseArc::Rise(Level, Dt, bHeld);
	if (bWasSilent && Level > 0.f)
	{
		Log(FVerseArcSoundEvent::EKind::HumOn, Level);
	}
	const bool bOn = bHeld && Level > VerseArc::OnLevel && GetHands().Num() > 0;
	if (!bOn)
	{
		Hide();
		// The lights die away over a few frames.
		const float Decay = FMath::Pow(0.6f, Dt * 60.f);
		HandLight->SetIntensity(HandLight->Intensity * Decay);
		ImpactLight->SetIntensity(ImpactLight->Intensity * Decay);
		UpdateSound(0.f);
		return;
	}
	UntilStrike -= Dt;
	if (UntilStrike > 0.f)
	{
		// Between strikes the light still flickers.
		HandLight->SetIntensity(HandLightCd * (0.3f + 0.5f * Flicker.FRand()));
		UpdateSound(-1.f);
		return;
	}
	UntilStrike = VerseArc::RestrikeS * (0.6f + 0.8f * Flicker.FRand());
	Strike();
}

void UVerseArcStormComponent::Strike()
{
	const TArray<FVector> Hands = GetHands();
	FVector Mid = FVector::ZeroVector;
	for (const FVector& Hand : Hands)
	{
		Mid += Hand / Hands.Num();
	}
	LastStrike = VerseArc::PlanStrike(Hands, GetAim(), FloorBelow(Mid), uint32(Seed + StrikeCount));
	++StrikeCount;
	bStriking = true;
	Draw(LastStrike);
	HandLight->SetWorldLocation(LastStrike.HandsMid + GetAim() * 40.0);
	HandLight->SetIntensity(HandLightCd * (0.6f + 0.8f * Flicker.FRand()));
	ImpactLight->SetWorldLocation(LastStrike.Impact + FVector(0.0, 0.0, 10.0));
	ImpactLight->SetIntensity(ImpactLightCd * (0.5f + 0.8f * Flicker.FRand()));
	// Jumps of loudness are the strikes.
	const float Crackle = Level * (0.25f + 0.9f * Flicker.FRand());
	Log(FVerseArcSoundEvent::EKind::Crackle, Crackle);
	UpdateSound(Crackle);
}

void UVerseArcStormComponent::Draw(const VerseArc::FStrike& InStrike)
{
	TArray<FTransform> Core;
	TArray<FTransform> Glow;
	const float CoreCm = FMath::Lerp(CoreMinCm, CoreMaxCm, Flicker.FRand());
	for (const VerseArc::FBolt& Bolt : InStrike.Bolts)
	{
		const float Scale = Bolt.Kind == VerseArc::FBolt::EKind::Main ? 1.f : 0.6f;
		for (int32 I = 0; I + 1 < Bolt.Points.Num(); ++I)
		{
			Core.Add(SegmentTransform(Bolt.Points[I], Bolt.Points[I + 1], CoreCm * Scale));
			Glow.Add(SegmentTransform(Bolt.Points[I], Bolt.Points[I + 1], GlowCm * Scale));
		}
	}
	auto Fill = [](UInstancedStaticMeshComponent* Layer, const TArray<FTransform>& Transforms)
	{
		if (Layer->GetInstanceCount() == Transforms.Num())
		{
			Layer->BatchUpdateInstancesTransforms(0, Transforms, true, true, true);
		}
		else
		{
			Layer->ClearInstances();
			Layer->AddInstances(Transforms, false, true, false);
		}
		Layer->SetVisibility(true);
	};
	Fill(CoreLayer, Core);
	Fill(GlowLayer, Glow);
	if (GlowMaterial)
	{
		GlowMaterial->SetScalarParameterValue(TEXT("Intensity"), 3.f + 2.5f * Flicker.FRand());
	}
}

void UVerseArcStormComponent::Hide()
{
	bStriking = false;
	UntilStrike = 0.f;
	if (CoreLayer)
	{
		CoreLayer->SetVisibility(false);
		GlowLayer->SetVisibility(false);
	}
}

void UVerseArcStormComponent::UpdateSound(float Crackle)
{
	if (bSounding && Level <= 0.f)
	{
		bSounding = false;
		Log(FVerseArcSoundEvent::EKind::Stop, 0.f);
		if (Sound)
		{
			Sound->Stop();
		}
	}
	else if (!bSounding && Level > 0.f)
	{
		bSounding = true;
		if (Sound)
		{
			Sound->Play();
		}
	}
	if (Wave)
	{
		// Between strikes (`Crackle` < 0) the crackle falls silent within ~10 ms: each strike is a burst.
		Wave->SetTargets(Level, Crackle < 0.f ? 0.f : Crackle, Volume);
	}
}

void UVerseArcStormComponent::Log(FVerseArcSoundEvent::EKind Kind, float Value)
{
	if (SoundLog.Num() >= SoundLogCap)
	{
		SoundLog.RemoveAt(0, SoundLogCap / 2);
	}
	SoundLog.Add({Kind, Value, StrikeCount});
}
