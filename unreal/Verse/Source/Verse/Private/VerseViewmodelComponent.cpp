#include "VerseViewmodelComponent.h"

#include "Camera/CameraComponent.h"
#include "Combat/VerseWeaponDefinition.h"
#include "Components/PointLightComponent.h"
#include "Components/PoseableMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Damage/VerseDamageService.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "Finisher/VerseFinisherTimeline.h"
#include "GameFramework/Pawn.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Inventory/VerseWeaponSlot.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Melee/VerseMeleeComponent.h"
#include "Misc/App.h"
#include "Projectiles/VerseBoltPresentation.h"
#include "VerseCharacter.h"
#include "VerseCharacterMovement.h"
#include "Weapons/VerseCombatEvents.h"
#include "Weapons/VerseWeaponComponent.h"

namespace VerseViewmodelPrivate
{
	const TCHAR* FlashMeshPath = TEXT("/Game/Verse/VFX/Weapons/SM_Vfx_MuzzleFlash.SM_Vfx_MuzzleFlash");
	const TCHAR* FlashMaterialPath = TEXT("/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_MuzzleOwn.MI_Weapon_Vfx_MuzzleOwn");
	const FName MuzzleSocket(TEXT("SOCKET_Muzzle"));
	const FName SightSocket(TEXT("SOCKET_Sight"));
	const FName KnifeId(TEXT("hookbill"));
	/** Amber of the own muzzle (art-pipeline 8.1 amber #F2A33A). */
	const FLinearColor FlashColor(1.f, 0.55f, 0.18f);

	float Smooth01(float Edge0, float Edge1, float X)
	{
		const float T = FMath::Clamp((X - Edge0) / FMath::Max(Edge1 - Edge0, KINDA_SMALL_NUMBER), 0.f, 1.f);
		return T * T * (3.f - 2.f * T);
	}

	/** Exponential approach factor for a rate per second. */
	float Approach(float Rate, float Dt)
	{
		return 1.f - FMath::Exp(-Rate * Dt);
	}
}

UVerseViewmodelComponent::UVerseViewmodelComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	// After the pawn moved and the camera took its rotation this frame.
	PrimaryComponentTick.TickGroup = TG_PostPhysics;
	SetIsReplicatedByDefault(false);
}

UVerseViewmodelComponent* UVerseViewmodelComponent::FindOn(const AActor* Actor)
{
	return Actor ? Actor->FindComponentByClass<UVerseViewmodelComponent>() : nullptr;
}

FVerseViewmodelPose UVerseViewmodelComponent::PoseFor(FName WeaponId)
{
	FVerseViewmodelPose P;
	const FString Id = WeaponId.ToString().ToLower();
	if (Id == TEXT("tallow"))
	{
		// Pistol: held further out, one hand.
		P.HipOffset = FVector(28.0, 9.0, -12.0);
		P.HipRotation = FRotator(2.0, -5.0, 0.0);
		P.SightDistance = 30.0;
		P.KickBackCm = 2.0;
		P.KickPitchDeg = 6.0;
	}
	else if (Id == TEXT("skitter"))
	{
		P.HipOffset = FVector(24.0, 10.0, -14.0);
		P.HipRotation = FRotator(1.5, -4.5, 0.0);
		P.SightDistance = 20.0;
		P.KickBackCm = 1.6;
		P.KickPitchDeg = 1.6;
	}
	else if (Id == TEXT("longsight"))
	{
		P.HipOffset = FVector(24.0, 11.0, -16.0);
		P.HipRotation = FRotator(1.5, -3.5, 0.0);
		P.SightDistance = 12.0;
		P.KickBackCm = 3.6;
		P.KickPitchDeg = 4.5;
	}
	else if (Id == TEXT("hookbill"))
	{
		// Knife: blade forward, edge down, held low on the right.
		P.HipOffset = FVector(24.0, 12.0, -14.0);
		P.HipRotation = FRotator(18.0, -14.0, -20.0);
		P.SightDistance = 26.0;
		P.KickBackCm = 0.0;
		P.KickPitchDeg = 0.0;
	}
	else
	{
		// Graveline and any rifle without its own row: the sight sits right of and below the
		// crosshair and the barrel points at it, so the weapon fills the lower right quarter.
		// Aiming, the slim reflex frame sits 24 cm out: its 4 cm frame spans about a tenth of
		// the view and the tall riser keeps rail and receiver low in the frame.
		P.HipOffset = FVector(26.0, 11.0, -17.0);
		P.HipRotation = FRotator(2.0, -4.0, 0.0);
		P.SightDistance = GravelineSightDistanceCm;
		P.KickBackCm = 2.4;
		P.KickPitchDeg = 2.6;
	}
	return P;
}

FString UVerseViewmodelComponent::MeshPathFor(FName WeaponId)
{
	static const TSet<FString> WithArt = {TEXT("graveline"), TEXT("tallow"), TEXT("hookbill"), TEXT("skitter"), TEXT("longsight")};
	FString Id = WeaponId.ToString().ToLower();
	if (!WithArt.Contains(Id))
	{
		return FString();
	}
	Id[0] = FChar::ToUpper(Id[0]);
	return FString::Printf(TEXT("/Game/Verse/Weapons/%s/SK_Weapon_%s.SK_Weapon_%s"), *Id, *Id, *Id);
}

UCameraComponent* UVerseViewmodelComponent::GetCamera() const
{
	const AVerseCharacter* Character = Cast<AVerseCharacter>(GetOwner());
	return Character ? Character->GetFirstPersonCamera() : nullptr;
}

float UVerseViewmodelComponent::Now() const
{
	return VerseCombatEvents::ServerTime(this);
}

bool UVerseViewmodelComponent::ShouldBuild() const
{
	const APawn* Pawn = Cast<APawn>(GetOwner());
	const UWorld* World = GetWorld();
	return Pawn && World && World->IsGameWorld() && FApp::CanEverRender() && Pawn->IsLocallyControlled() && Pawn->IsPlayerControlled()
		&& GetCamera() != nullptr;
}

void UVerseViewmodelComponent::BeginPlay()
{
	Super::BeginPlay();
	if (UVerseEventHub* Hub = UVerseEventHub::Get(GetWorld()))
	{
		FireHandle = Hub->OnFire.AddUObject(this, &UVerseViewmodelComponent::HandleFire);
	}
}

void UVerseViewmodelComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (UVerseEventHub* Hub = UVerseEventHub::Get(GetWorld()))
	{
		Hub->OnFire.Remove(FireHandle);
	}
	TearDown();
	Super::EndPlay(EndPlayReason);
}

void UVerseViewmodelComponent::Build()
{
	using namespace VerseViewmodelPrivate;
	UCameraComponent* Camera = GetCamera();
	AActor* Owner = GetOwner();
	if (!Camera || !Owner || Root)
	{
		return;
	}
	// The camera renders tagged primitives with their own field of view and pulled towards the eye.
	Camera->SetEnableFirstPersonFieldOfView(true);
	Camera->SetFirstPersonFieldOfView(ViewmodelFov);
	Camera->SetEnableFirstPersonScale(true);
	Camera->SetFirstPersonScale(ViewmodelScale);

	Root = NewObject<USceneComponent>(Owner, TEXT("ViewmodelRoot"));
	Root->SetupAttachment(Camera);
	Root->RegisterComponent();

	Mesh = NewObject<UPoseableMeshComponent>(Owner, TEXT("ViewmodelWeapon"));
	Mesh->SetupAttachment(Root);
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetCastShadow(false);
	Mesh->bOnlyOwnerSee = true;
	Mesh->SetFirstPersonPrimitiveType(EFirstPersonPrimitiveType::FirstPerson);
	// Channel 0 for the hangar lights, channel 1 for the own fill light below.
	Mesh->LightingChannels.bChannel0 = true;
	Mesh->LightingChannels.bChannel1 = true;
	Mesh->RegisterComponent();

	Flash = NewObject<UStaticMeshComponent>(Owner, TEXT("ViewmodelFlash"));
	Flash->SetupAttachment(Mesh);
	Flash->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Flash->SetCastShadow(false);
	Flash->bOnlyOwnerSee = true;
	Flash->SetFirstPersonPrimitiveType(EFirstPersonPrimitiveType::FirstPerson);
	if (UStaticMesh* FlashMesh = LoadObject<UStaticMesh>(nullptr, FlashMeshPath, nullptr, LOAD_NoWarn | LOAD_Quiet))
	{
		Flash->SetStaticMesh(FlashMesh);
	}
	if (UMaterialInterface* FlashBase = LoadObject<UMaterialInterface>(nullptr, FlashMaterialPath, nullptr, LOAD_NoWarn | LOAD_Quiet))
	{
		FlashMaterial = UMaterialInstanceDynamic::Create(FlashBase, Flash);
		FlashMaterial->SetScalarParameterValue(TEXT("EmissiveNits"), 90.f);
		Flash->SetMaterial(0, FlashMaterial);
	}
	Flash->SetVisibility(false);
	Flash->RegisterComponent();

	// A short warm light at the muzzle lights the hands' surroundings for a frame or two.
	FlashLight = NewObject<UPointLightComponent>(Owner, TEXT("ViewmodelFlashLight"));
	FlashLight->SetupAttachment(Root);
	FlashLight->SetIntensityUnits(ELightUnits::Lumens);
	FlashLight->SetIntensity(0.f);
	FlashLight->SetLightColor(FlashColor);
	FlashLight->SetAttenuationRadius(650.f);
	FlashLight->SetCastShadows(false);
	FlashLight->SetVisibility(false);
	FlashLight->RegisterComponent();

	// The hangar lights hit the weapon from far above, so at the hip it read as a black shape.
	// A soft light near the eye on channel 1 shows its form; the drawn weapon sits 5 to 30 cm
	// from the eye (first-person scale), so the light sits about 35 cm away from it.
	FillLight = NewObject<UPointLightComponent>(Owner, TEXT("ViewmodelFillLight"));
	FillLight->SetupAttachment(Camera);
	FillLight->SetRelativeLocation(FVector(-12.0, 22.0, 28.0));
	FillLight->SetIntensityUnits(ELightUnits::Lumens);
	FillLight->SetIntensity(FillLumens);
	FillLight->SetLightColor(FLinearColor(1.f, 0.93f, 0.84f));
	FillLight->SetAttenuationRadius(120.f);
	FillLight->SetSourceRadius(8.f);
	FillLight->SetCastShadows(false);
	FillLight->SetAffectTranslucentLighting(false);
	FillLight->LightingChannels.bChannel0 = false;
	FillLight->LightingChannels.bChannel1 = true;
	FillLight->RegisterComponent();

	ShownWeaponId = NAME_None;
	bHaveViewRotation = false;

	// Own bolts leave from the muzzle the person sees, not from the eye.
	if (UVerseBoltPresentation* Bolts = UVerseBoltPresentation::Get(this))
	{
		TWeakObjectPtr<UVerseViewmodelComponent> Weak(this);
		Bolts->VisualMuzzle = [Weak](int32 ShooterId, FVector& OutMuzzle)
		{
			const UVerseViewmodelComponent* Self = Weak.Get();
			return Self && Self->OwnId == ShooterId && Self->GetMuzzleWorld(OutMuzzle);
		};
	}
}

void UVerseViewmodelComponent::TearDown()
{
	if (Root)
	{
		if (UVerseBoltPresentation* Bolts = UVerseBoltPresentation::Get(this))
		{
			Bolts->VisualMuzzle = nullptr;
		}
	}
	for (USceneComponent* C : {static_cast<USceneComponent*>(FillLight.Get()), static_cast<USceneComponent*>(FlashLight.Get()), static_cast<USceneComponent*>(Flash.Get()),
			 static_cast<USceneComponent*>(Mesh.Get()), Root.Get()})
	{
		if (C)
		{
			C->DestroyComponent();
		}
	}
	FillLight = nullptr;
	FlashLight = nullptr;
	Flash = nullptr;
	FlashMaterial = nullptr;
	Mesh = nullptr;
	Root = nullptr;
	ShownWeaponId = NAME_None;
}

bool UVerseViewmodelComponent::IsShowing() const
{
	return Mesh && Mesh->IsVisible() && Mesh->GetSkinnedAsset() != nullptr;
}

void UVerseViewmodelComponent::ShowWeapon(FName WeaponId)
{
	if (!Mesh || WeaponId == ShownWeaponId)
	{
		return;
	}
	ShownWeaponId = WeaponId;
	const FString Path = MeshPathFor(WeaponId);
	USkeletalMesh* Asset = Path.IsEmpty() ? nullptr : LoadObject<USkeletalMesh>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
	Mesh->SetSkinnedAssetAndUpdate(Asset);
	Pose = PoseFor(WeaponId);
	if (Asset)
	{
		// Seen from a hand's width, the polished weapon steel mirrored the bright hangar ceiling
		// and the sight's inner walls burned white. A satin, less metallic finish (M_Verse_Weapon parameters) keeps it readable.
		// Reticle and lens keep their own look.
		const TArray<FName> Slots = Mesh->GetMaterialSlotNames();
		for (int32 Index = 0; Index < Slots.Num(); ++Index)
		{
			const FString Slot = Slots[Index].ToString();
			if (Slot.Contains(TEXT("Reticle")) || Slot.Contains(TEXT("Optic")))
			{
				continue;
			}
			if (UMaterialInstanceDynamic* Satin = Mesh->CreateDynamicMaterialInstance(Index))
			{
				Satin->SetScalarParameterValue(TEXT("RoughnessMin"), ViewmodelRoughnessMin);
				Satin->SetScalarParameterValue(TEXT("RoughnessMax"), 0.7f);
				Satin->SetScalarParameterValue(TEXT("Metallic"), 0.75f);
				Satin->SetScalarParameterValue(TEXT("OilAmount"), 0.08f);
			}
		}
	}
	MagBone = NAME_None;
	BoltBone = NAME_None;
	if (Asset)
	{
		for (const FName Bone : {FName(TEXT("Magazine"))})
		{
			if (Mesh->GetBoneIndex(Bone) != INDEX_NONE)
			{
				MagBone = Bone;
				MagRest = Mesh->GetBoneLocationByName(Bone, EBoneSpaces::ComponentSpace);
			}
		}
		for (const FName Bone : {FName(TEXT("Bolt")), FName(TEXT("Slide"))})
		{
			if (Mesh->GetBoneIndex(Bone) != INDEX_NONE)
			{
				BoltBone = Bone;
				BoltRest = Mesh->GetBoneLocationByName(Bone, EBoneSpaces::ComponentSpace);
				break;
			}
		}
	}
	if (Flash)
	{
		const bool bMuzzle = Asset && Mesh->DoesSocketExist(VerseViewmodelPrivate::MuzzleSocket);
		Flash->AttachToComponent(Mesh, FAttachmentTransformRules::SnapToTargetNotIncludingScale, bMuzzle ? VerseViewmodelPrivate::MuzzleSocket : NAME_None);
	}
}

void UVerseViewmodelComponent::HandleFire(const FVerseFireEvent& Event)
{
	if (!Root || Event.ShooterId != OwnId || OwnId == MIN_int32)
	{
		return;
	}
	// The own prediction and the server's echo carry the same counter: kick once.
	if (bHaveShot && Event.ShotCounter == LastShotCounter)
	{
		return;
	}
	bHaveShot = true;
	LastShotCounter = Event.ShotCounter;
	const float AdsScale = FMath::Lerp(1.f, 0.45f, AdsSmoothed);
	const float Jitter = FMath::FRandRange(-1.f, 1.f);
	KickPos += FVector(-Pose.KickBackCm, 0.15 * Jitter, 0.25 * Pose.KickBackCm) * AdsScale;
	KickRot += FRotator(Pose.KickPitchDeg * FMath::FRandRange(0.85f, 1.15f), 0.6f * Jitter, 1.2f * Jitter) * AdsScale;
	BoltCycle = 1.f;
	FlashUntil = Now() + MuzzleFlashSeconds;
	if (Flash)
	{
		Flash->SetRelativeRotation(FRotator(0.f, 0.f, FMath::FRandRange(0.f, 360.f)));
		Flash->SetRelativeScale3D(FVector(FMath::FRandRange(0.9f, 1.4f)));
	}
}

bool UVerseViewmodelComponent::GetMuzzleWorld(FVector& OutLocation) const
{
	const UCameraComponent* Camera = GetCamera();
	if (!Camera || !IsShowing() || !Mesh->DoesSocketExist(VerseViewmodelPrivate::MuzzleSocket))
	{
		return false;
	}
	// Where the person sees the muzzle: the first-person scale pulls it towards the eye and the
	// narrower first-person field of view spreads it out; the result lies on the same screen ray.
	const FTransform CameraXf = Camera->GetComponentTransform();
	const FVector Local = CameraXf.InverseTransformPosition(Mesh->GetSocketLocation(VerseViewmodelPrivate::MuzzleSocket));
	const double WorldHalf = FMath::DegreesToRadians(FMath::Clamp(Camera->FieldOfView, 10.0, 170.0) * 0.5);
	const double FirstHalf = FMath::DegreesToRadians(double(ViewmodelFov) * 0.5);
	const double Spread = FMath::Tan(WorldHalf) / FMath::Tan(FirstHalf);
	const FVector Seen(Local.X * ViewmodelScale, Local.Y * ViewmodelScale * Spread, Local.Z * ViewmodelScale * Spread);
	OutLocation = CameraXf.TransformPosition(Seen);
	return true;
}

void UVerseViewmodelComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	Step(DeltaTime);
}

void UVerseViewmodelComponent::Step(float Dt)
{
	using namespace VerseViewmodelPrivate;
	const bool bWant = ShouldBuild();
	if (!bWant)
	{
		if (Root)
		{
			TearDown();
		}
		return;
	}
	if (!Root)
	{
		Build();
		if (!Root)
		{
			return;
		}
	}
	APawn* Pawn = CastChecked<APawn>(GetOwner());
	OwnId = VerseCombatIds::IdOf(Pawn);
	const float T = Now();

	const UVerseInventoryComponent* Inventory = UVerseInventoryComponent::FindOn(Pawn);
	const UVerseWeaponComponent* Weapon = UVerseWeaponComponent::FindOn(Pawn);
	const UVerseMeleeComponent* Melee = Pawn->FindComponentByClass<UVerseMeleeComponent>();
	const UVerseCombatStateComponent* State = Pawn->FindComponentByClass<UVerseCombatStateComponent>();
	const bool bAlive = !State || State->IsAlive();
	const bool bFinisher = Melee && Melee->IsInFinisher();

	// What is in the hand: the knife while a swing runs, else the active slot's weapon.
	const FVerseKnifePresentation* Knife = Melee ? &Melee->GetKnife() : nullptr;
	const double KnifeT = Knife ? double(T) - Knife->PressTime : 1.0e9;
	const double KnifeLength = Knife ? Knife->HitDelayS + Knife->RecoverS : 0.0;
	const bool bSwinging = Knife && KnifeT >= 0.0 && KnifeT <= KnifeLength;
	const EVerseLoadoutSlot Slot = Inventory ? Inventory->ActiveSlot : EVerseLoadoutSlot::Primary;
	const UVerseWeaponDefinition* Def = Inventory ? Inventory->GetActiveWeapon() : nullptr;
	FName Want = NAME_None;
	if (bSwinging || Slot == EVerseLoadoutSlot::Melee)
	{
		Want = KnifeId;
	}
	else if (Def)
	{
		Want = Def->WeaponId;
	}
	if (Slot != LastSlot)
	{
		LastSlot = Slot;
		EquipStartedAt = T;
		EquipSeconds = Slot == EVerseLoadoutSlot::Melee ? (Knife ? float(Knife->EquipS) : 0.12f) : (Def ? FMath::Max(0.1f, Def->EquipTime) : 0.4f);
	}
	ShowWeapon(Want);
	const bool bVisible = bAlive && !bFinisher && Mesh->GetSkinnedAsset() != nullptr;
	Mesh->SetVisibility(bVisible, false);
	FillLight->SetVisibility(bVisible);
	if (!bVisible)
	{
		Flash->SetVisibility(false);
		FlashLight->SetVisibility(false);
		KickPos = FVector::ZeroVector;
		KickRot = FRotator::ZeroRotator;
		return;
	}

	// Aim down sights: the sight socket onto the view axis.
	const float AdsRaw = Weapon && Want != KnifeId ? Weapon->GetAdsBlend01() : 0.f;
	AdsSmoothed = FMath::Lerp(AdsSmoothed, AdsRaw, Approach(30.f, Dt));
	FVector AdsOffset = Pose.HipOffset;
	if (Mesh->DoesSocketExist(SightSocket))
	{
		const FVector Sight = Mesh->GetSocketTransform(SightSocket, RTS_Component).GetLocation();
		AdsOffset = FVector(Pose.SightDistance - Sight.X, -Sight.Y, -Sight.Z);
	}
	// While aiming the sight sits a hand's width from the eye: the fill light would burn its inner walls white.
	FillLight->SetIntensity(FillLumens * FMath::Lerp(1.f, 0.12f, AdsSmoothed));
	FVector Pos = FMath::Lerp(Pose.HipOffset, AdsOffset, double(AdsSmoothed));
	FRotator Rot = Pose.HipRotation * (1.f - AdsSmoothed);

	// Slot switch: the weapon rises from below.
	const float Equip = Smooth01(0.f, 1.f, (T - EquipStartedAt) / FMath::Max(EquipSeconds, 0.05f));
	Pos += FVector(-4.0, 2.0, -24.0) * (1.f - Equip);
	Rot += FRotator(-38.f, 6.f, 14.f) * (1.f - Equip);

	// Reload: tilt in, magazine out and back in, tilt out.
	float MagDrop = 0.f;
	const FVerseWeaponSlotState* SlotState = Inventory ? Inventory->GetActiveState() : nullptr;
	if (SlotState && SlotState->Definition && FVerseMagazine::IsReloading(*SlotState) && Want != KnifeId)
	{
		const float Span = FMath::Max(SlotState->ReloadEndsAt - SlotState->ReloadStartedAt, 0.1f);
		const float P = FMath::Clamp((T - SlotState->ReloadStartedAt) / Span, 0.f, 1.f);
		const float Tilt = Smooth01(0.f, 0.15f, P) * (1.f - Smooth01(0.82f, 1.f, P));
		Pos += FVector(-3.0, -2.0, -6.0) * Tilt;
		Rot += FRotator(12.f, 8.f, 32.f) * Tilt;
		MagDrop = Smooth01(0.12f, 0.32f, P) * (1.f - Smooth01(0.45f, 0.7f, P));
		// The hand seats the magazine: a short bump.
		const float Seat = Smooth01(0.66f, 0.72f, P) * (1.f - Smooth01(0.72f, 0.8f, P));
		Pos += FVector(0.0, 0.0, 1.2) * Seat;
		if (SlotState->Reload == EVerseReloadPhase::Empty && P > 0.8f && P < 0.95f)
		{
			BoltCycle = FMath::Max(BoltCycle, 1.f - FMath::Abs(P - 0.875f) / 0.075f);
		}
	}

	// Knife: wind-up, thrust at the contact frame, recover.
	if (Want == KnifeId && Knife && bSwinging)
	{
		const float Hit = float(Knife->HitDelayS);
		const float K = float(KnifeT);
		const float Wind = Smooth01(0.f, Hit * 0.45f, K) * (1.f - Smooth01(Hit * 0.45f, Hit, K));
		const float Thrust = Smooth01(Hit * 0.4f, Hit, K) * (1.f - Smooth01(Hit + 0.05f, Hit + float(Knife->RecoverS), K));
		Pos += FVector(-6.0, 5.0, 2.0) * Wind + FVector(22.0, -11.0, 7.0) * Thrust;
		Rot += FRotator(10.f, 18.f, -20.f) * Wind + FRotator(-14.f, -16.f, 30.f) * Thrust;
	}

	// Sprint: the weapon drops and turns in.
	const UVerseCharacterMovement* Move = Cast<UVerseCharacterMovement>(Cast<ACharacter>(Pawn) ? Cast<ACharacter>(Pawn)->GetCharacterMovement() : nullptr);
	const bool bSprint = Move && Move->IsSprinting() && !bSwinging;
	SprintBlend = FMath::Lerp(SprintBlend, bSprint ? 1.f : 0.f, Approach(10.f, Dt));
	Pos += FVector(-2.0, -3.0, -5.0) * SprintBlend;
	Rot += FRotator(-14.f, 22.f, -8.f) * SprintBlend;

	// Walk bob, quieter in ADS.
	const double Speed = Pawn->GetVelocity().Size2D();
	const bool bGround = Move && Move->IsMovingOnGround();
	BobAmount = FMath::Lerp(BobAmount, bGround ? float(FMath::Clamp(Speed / 450.0, 0.0, 1.3)) : 0.f, Approach(8.f, Dt));
	BobPhase += Dt * (Speed / 170.0) * PI;
	const float BobScale = BobAmount * FMath::Lerp(1.f, 0.15f, AdsSmoothed);
	Pos += FVector(0.0, FMath::Sin(BobPhase) * 0.7, -FMath::Abs(FMath::Cos(BobPhase)) * 0.6) * BobScale;
	Rot += FRotator(0.f, 0.f, FMath::Sin(BobPhase) * 1.2f) * BobScale;

	// Look sway: the weapon lags the turn and settles.
	const FRotator View = Pawn->GetViewRotation();
	if (bHaveViewRotation && Dt > 0.f)
	{
		const FRotator Delta = (View - LastViewRotation).GetNormalized();
		const FVector2D Push(FMath::Clamp(-Delta.Yaw, -6.f, 6.f), FMath::Clamp(-Delta.Pitch, -6.f, 6.f));
		Sway = FMath::Lerp(Sway + Push * 0.35f, FVector2D::ZeroVector, Approach(9.f, Dt));
	}
	LastViewRotation = View;
	bHaveViewRotation = true;
	const float SwayScale = FMath::Lerp(1.f, 0.25f, AdsSmoothed);
	Pos += FVector(0.0, Sway.X * 0.35, Sway.Y * 0.35) * SwayScale;
	Rot += FRotator(Sway.Y * 0.8f, Sway.X * 0.8f, Sway.X * 0.6f) * SwayScale;

	// Shot kick springs back.
	KickPos = FMath::Lerp(KickPos, FVector::ZeroVector, double(Approach(16.f, Dt)));
	KickRot = FMath::Lerp(KickRot, FRotator::ZeroRotator, Approach(13.f, Dt));
	Pos += KickPos;
	Rot += KickRot;

	LocalPose = FTransform(Rot, Pos);
	Root->SetRelativeTransform(LocalPose);

	// Parts: magazine out on reload, bolt or slide back on each shot.
	if (!MagBone.IsNone())
	{
		Mesh->SetBoneLocationByName(MagBone, MagRest + FVector(0.0, 0.0, -28.0 * MagDrop), EBoneSpaces::ComponentSpace);
	}
	BoltCycle = FMath::Max(0.f, BoltCycle - Dt / 0.06f);
	if (!BoltBone.IsNone())
	{
		Mesh->SetBoneLocationByName(BoltBone, BoltRest + FVector(-4.0 * BoltCycle, 0.0, 0.0), EBoneSpaces::ComponentSpace);
	}

	// Muzzle flash card and light.
	const bool bFlash = T < FlashUntil && Want != KnifeId;
	Flash->SetVisibility(bFlash);
	FlashLight->SetVisibility(bFlash);
	if (bFlash)
	{
		// The drawn muzzle sits a few cm from the eye: a light there burned the sight white.
		// The light sits where the shot leaves into the room instead, and is softer while aiming.
		if (const UCameraComponent* Camera = GetCamera())
		{
			FlashLight->SetWorldLocation(Camera->GetComponentLocation() + Camera->GetForwardVector() * FlashLightForwardCm);
		}
		FlashLight->SetIntensity(FlashLumens * FMath::Lerp(1.f, 0.12f, AdsSmoothed));
	}
}
