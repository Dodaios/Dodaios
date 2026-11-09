#include "VerseIntegrationSubsystem.h"

#include "Core/VerseUiSubsystem.h"
#include "Debris/VerseDebrisSubsystem.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Character.h"
#include "Gadgets/VerseGadgetComponent.h"
#include "LagComp/VerseLagCompensation.h"
#include "Penetration/VersePenetrationSubsystem.h"
#include "Perception/VersePerceptionService.h"
#include "Pieces/VerseDestructionManager.h"
#include "Projectiles/VerseProjectileManager.h"
#include "TimerManager.h"

bool UVerseIntegrationSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	const UWorld* World = Cast<UWorld>(Outer);
	return World && World->IsGameWorld() && Super::ShouldCreateSubsystem(Outer);
}

void UVerseIntegrationSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	BindKillCamFracture(InWorld);
	if (InWorld.GetNetMode() != NM_Client)
	{
		BindCombatSeams(InWorld);
		TWeakObjectPtr<UWorld> WeakWorld(&InWorld);
		InWorld.GetTimerManager().SetTimer(RebindTimer, FTimerDelegate::CreateWeakLambda(this, [WeakWorld]()
			{
				if (UWorld* World = WeakWorld.Get())
				{
					BindCombatSeams(*World);
				}
			}), 1.f, true);
	}
}

bool UVerseIntegrationSubsystem::BindCombatSeams(UWorld& World)
{
	UVersePenetrationSubsystem* Penetration = World.GetSubsystem<UVersePenetrationSubsystem>();
	AVerseDestructionManager* Pieces = AVerseDestructionManager::Get(&World);
	IVersePieceDamage* PieceDamage = Pieces ? &Pieces->GetPieceDamage() : nullptr;
	if (UVerseProjectileManager* Bolts = UVerseProjectileManager::Get(&World))
	{
		Bolts->SetPenetrationQuery(Penetration);
		Bolts->SetPieceDamage(PieceDamage);
	}
	UVersePerceptionService* Perception = UVersePerceptionService::Get(&World);
	if (Perception && Penetration)
	{
		Perception->SetSightQuery(TScriptInterface<IVersePenetrationQuery>(Penetration));
	}
	for (TActorIterator<APawn> It(&World); It; ++It)
	{
		if (UVerseGadgetComponent* Gadgets = UVerseGadgetComponent::FindOn(*It))
		{
			Gadgets->SetPenetrationQuery(Penetration);
			Gadgets->SetPieceDamage(PieceDamage);
		}
	}
	return Penetration && Pieces;
}

void UVerseIntegrationSubsystem::BindPawn(APawn& Pawn)
{
	UWorld* World = Pawn.GetWorld();
	if (!World || !World->IsGameWorld() || !Pawn.HasAuthority())
	{
		return;
	}
	if (ACharacter* Character = Cast<ACharacter>(&Pawn))
	{
		if (USkeletalMeshComponent* Mesh = Character->GetMesh())
		{
			// The server tests bolts against the posed hit bodies even when nothing renders them.
			Mesh->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
			if (UVerseLagCompSubsystem* Lag = UVerseLagCompSubsystem::Get(World))
			{
				Lag->RegisterSkeletalTarget(&Pawn, Mesh);
			}
		}
	}
	if (UVerseGadgetComponent* Gadgets = UVerseGadgetComponent::FindOn(&Pawn))
	{
		UVersePenetrationSubsystem* Penetration = World->GetSubsystem<UVersePenetrationSubsystem>();
		AVerseDestructionManager* Pieces = AVerseDestructionManager::Get(World);
		Gadgets->SetPenetrationQuery(Penetration);
		Gadgets->SetPieceDamage(Pieces ? &Pieces->GetPieceDamage() : nullptr);
	}
}

void UVerseIntegrationSubsystem::UnbindPawn(APawn& Pawn)
{
	if (UVerseLagCompSubsystem* Lag = UVerseLagCompSubsystem::Get(&Pawn))
	{
		Lag->UnregisterTarget(&Pawn);
	}
}

bool UVerseIntegrationSubsystem::BindKillCamFracture(UWorld& World)
{
	UVerseUiSubsystem* Ui = World.GetSubsystem<UVerseUiSubsystem>();
	UVerseDebrisSubsystem* Debris = World.GetSubsystem<UVerseDebrisSubsystem>();
	if (!Ui || !Debris)
	{
		return false;
	}
	TWeakObjectPtr<UVerseDebrisSubsystem> WeakDebris(Debris);
	Ui->OnKillCamFracture = [WeakDebris](const FVerseFractureEvent& Event)
	{
		if (UVerseDebrisSubsystem* Target = WeakDebris.Get())
		{
			Target->ReplayFracture(Event);
		}
	};
	return true;
}
