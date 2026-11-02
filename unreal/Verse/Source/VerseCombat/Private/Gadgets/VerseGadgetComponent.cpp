#include "Gadgets/VerseGadgetComponent.h"

#include "Combat/VerseGadgetDefinition.h"
#include "Damage/VerseDamageService.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Destruction/VersePenetrationTable.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Pawn.h"
#include "Gadgets/VerseBreachCharge.h"
#include "Gadgets/VerseBulwark.h"
#include "Stubs/VerseNullStubs.h"
#include "VerseCollision.h"
#include "Weapons/VerseCombatEvents.h"

UVerseGadgetComponent::UVerseGadgetComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	SetIsReplicatedByDefault(false);
}

UVerseGadgetComponent* UVerseGadgetComponent::FindOn(const AActor* Actor)
{
	return Actor ? Actor->FindComponentByClass<UVerseGadgetComponent>() : nullptr;
}

void UVerseGadgetComponent::BeginPlay()
{
	Super::BeginPlay();
	ResetForLife();
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		HitHandle = Hub->OnHit.AddUObject(this, &UVerseGadgetComponent::OnHubHit);
	}
}

void UVerseGadgetComponent::EndPlay(const EEndPlayReason::Type Reason)
{
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnHit.Remove(HitHandle);
	}
	Super::EndPlay(Reason);
}

void UVerseGadgetComponent::ResetForLife()
{
	BulwarkCharges = Bulwark ? Bulwark->Charges : 0;
	BreachCharges = BreachCharge ? BreachCharge->Charges : 0;
	BulwarkCooldownEndsAt = 0.f;
	bUsing = false;
}

const UVerseGadgetDefinition* UVerseGadgetComponent::DefinitionFor(EVerseLoadoutSlot Slot) const
{
	return Slot == EVerseLoadoutSlot::GadgetA ? Bulwark.Get() : (Slot == EVerseLoadoutSlot::GadgetB ? BreachCharge.Get() : nullptr);
}

int32 UVerseGadgetComponent::GetChargesLeft(EVerseLoadoutSlot Slot) const
{
	return Slot == EVerseLoadoutSlot::GadgetA ? BulwarkCharges : (Slot == EVerseLoadoutSlot::GadgetB ? BreachCharges : 0);
}

int32 UVerseGadgetComponent::NumPlantedCharges() const
{
	int32 N = 0;
	for (const TWeakObjectPtr<AVerseBreachCharge>& C : Planted)
	{
		N += (C.IsValid() && C->IsArmed()) ? 1 : 0;
	}
	return N;
}

bool UVerseGadgetComponent::ServerBeginUse(EVerseLoadoutSlot Slot, float Now)
{
	AActor* Owner = GetOwner();
	const UVerseGadgetDefinition* Def = DefinitionFor(Slot);
	if (!Owner || !Owner->HasAuthority() || !Def || bUsing || GetChargesLeft(Slot) <= 0)
	{
		return false;
	}
	if (Slot == EVerseLoadoutSlot::GadgetA && Now < BulwarkCooldownEndsAt)
	{
		return false;
	}
	if (const UVerseCombatStateComponent* State = UVerseCombatStateComponent::FindOn(Owner))
	{
		if (State->Phase != EVerseCombatPhase::Alive)
		{
			return false;
		}
	}
	bUsing = true;
	UsingSlot = Slot;
	UseEndsAt = Now + Def->UseTime;

	// A gadget activation is an offensive action: it ends spawn protection (combat-state.md 9.3).
	if (UVerseCombatStateComponent* State = UVerseCombatStateComponent::FindOn(Owner))
	{
		State->NotifyOffensiveAction(Now);
	}
	if (UVerseDamageService* Damage = UVerseDamageService::Get(this))
	{
		if (Damage->Rules.OnOffensiveAction)
		{
			Damage->Rules.OnOffensiveAction(Owner, EVerseDamageSource::Gadget);
		}
	}
	return true;
}

void UVerseGadgetComponent::Interrupt()
{
	bUsing = false;
}

void UVerseGadgetComponent::OnHubHit(const FVerseHitEvent& Hit)
{
	if (bUsing && Hit.Damage > 0.f && Hit.VictimId == VerseCombatIds::IdOf(GetOwner()))
	{
		Interrupt();
	}
}

FVerseGadgetPlacement UVerseGadgetComponent::FindPlacement(EVerseLoadoutSlot Slot) const
{
	if (PlacementOverride)
	{
		return PlacementOverride(Slot);
	}
	FVerseGadgetPlacement Out;
	const APawn* Pawn = Cast<APawn>(GetOwner());
	const UWorld* World = GetWorld();
	const UVerseGadgetDefinition* Def = DefinitionFor(Slot);
	if (!Pawn || !World || !Def)
	{
		return Out;
	}
	const FVector Eye = Pawn->GetPawnViewLocation();
	const FRotator View = Pawn->GetBaseAimRotation();
	const double RangeCm = double(Def->PlaceRange) * 100.0;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseGadgetPlace), false, Pawn);

	if (Slot == EVerseLoadoutSlot::GadgetA)
	{
		// Floor in front of the eye, facing the deployer, with free width for the field.
		const FVector Flat = FRotator(0.0, View.Yaw, 0.0).Vector();
		const FVector Above = Eye + Flat * RangeCm;
		FHitResult Floor;
		if (!World->LineTraceSingleByChannel(Floor, Above, Above - FVector(0, 0, 300.0), VerseCollision::Bolt, Params))
		{
			return Out;
		}
		const FVector Right = FRotator(0.0, View.Yaw + 90.0, 0.0).Vector();
		const FVector Probe = Floor.ImpactPoint + FVector(0, 0, 50.0);
		const double HalfWidth = double(Def->Size.X) * 50.0;
		FHitResult Side;
		if (World->LineTraceSingleByChannel(Side, Probe, Probe + Right * HalfWidth, VerseCollision::Bolt, Params)
			|| World->LineTraceSingleByChannel(Side, Probe, Probe - Right * HalfWidth, VerseCollision::Bolt, Params))
		{
			return Out;
		}
		Out.bValid = true;
		Out.Location = Floor.ImpactPoint;
		Out.Rotation = FRotator(0.0, View.Yaw, 0.0);
		return Out;
	}

	// Breach charge: the first piece along the view within range whose material breach can break.
	const IVersePenetrationQuery* Query = PenetrationQuery ? PenetrationQuery : GetDefault<UVerseNullPenetrationQuery>();
	const TArray<FVersePenetrationHit> Pieces = Query->TraceBolt(Eye, View.Vector(), float(RangeCm), 0.f, 0.f, 0, 1);
	const UVersePenetrationTable* Table = GetDefault<UVersePenetrationTable>();
	if (Pieces.Num() > 0)
	{
		const FVersePenetrationRow* Row = Table->FindRow(Pieces[0].MaterialWireId);
		if (Row && Row->bBreakableByBreach)
		{
			Out.bValid = true;
			Out.PieceIndex = Pieces[0].PieceIndex;
			Out.Location = Pieces[0].Entry;
			Out.Normal = -View.Vector();
			Out.Rotation = Out.Normal.Rotation();
		}
	}
	return Out;
}

void UVerseGadgetComponent::Complete(float Now)
{
	bUsing = false;
	AActor* Owner = GetOwner();
	UWorld* World = GetWorld();
	const UVerseGadgetDefinition* Def = DefinitionFor(UsingSlot);
	if (!Owner || !World || !Def)
	{
		return;
	}
	const FVerseGadgetPlacement Place = FindPlacement(UsingSlot);
	if (!Place.bValid)
	{
		return; // nowhere to put it: the charge is kept
	}
	FActorSpawnParameters Spawn;
	Spawn.Owner = Owner;
	Spawn.Instigator = Cast<APawn>(Owner);
	Spawn.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

	if (UsingSlot == EVerseLoadoutSlot::GadgetA)
	{
		// One active: a second deploy removes the first.
		if (AVerseBulwark* Old = ActiveBulwark.Get())
		{
			Old->RemoveBulwark(EVerseGadgetEventKind::Destroyed);
		}
		AVerseBulwark* B = World->SpawnActor<AVerseBulwark>(AVerseBulwark::StaticClass(), Place.Location, Place.Rotation, Spawn);
		if (!B)
		{
			return;
		}
		B->InitBulwark(*Def, Owner, Now);
		TWeakObjectPtr<UVerseGadgetComponent> WeakThis = this;
		B->OnRemoved = [WeakThis](AVerseBulwark*)
		{
			if (UVerseGadgetComponent* Self = WeakThis.Get())
			{
				const UVerseGadgetDefinition* D = Self->Bulwark.Get();
				Self->BulwarkCooldownEndsAt = VerseCombatEvents::ServerTime(Self) + (D ? D->Cooldown : 0.f);
			}
		};
		ActiveBulwark = B;
		--BulwarkCharges;
		return;
	}

	AVerseBreachCharge* C = World->SpawnActor<AVerseBreachCharge>(AVerseBreachCharge::StaticClass(), Place.Location, Place.Rotation, Spawn);
	if (!C)
	{
		return;
	}
	C->SetPieceDamage(PieceDamage);
	C->InitCharge(*Def, Owner, Place.PieceIndex, Place.Normal, Now);
	Planted.RemoveAll([](const TWeakObjectPtr<AVerseBreachCharge>& P) { return !P.IsValid(); });
	Planted.Add(C);
	--BreachCharges;
}

void UVerseGadgetComponent::ServerAdvance(float Now)
{
	const AActor* Owner = GetOwner();
	if (!Owner || !Owner->HasAuthority())
	{
		return;
	}
	if (bUsing && Now >= UseEndsAt)
	{
		Complete(Now);
	}
	// The Bulwark's charge returns after its cooldown (Cooldown counts from the actor being gone).
	const UVerseGadgetDefinition* B = Bulwark.Get();
	if (B && B->Cooldown > 0.f && !ActiveBulwark.IsValid() && BulwarkCharges < B->Charges && BulwarkCooldownEndsAt > 0.f
		&& Now >= BulwarkCooldownEndsAt)
	{
		++BulwarkCharges;
		BulwarkCooldownEndsAt = 0.f;
	}
}

void UVerseGadgetComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	ServerAdvance(VerseCombatEvents::ServerTime(this));
}
