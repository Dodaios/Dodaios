#include "Melee/VerseMeleeComponent.h"

#include "Camera/CameraActor.h"
#include "Camera/PlayerCameraManager.h"
#include "Combat/VerseMeleeDefinition.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/GameStateBase.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Melee/VerseMeleeWorld.h"
#include "VerseGameplayTags.h"
#include "VerseLog.h"

namespace
{
	/** Rewind cap (combat-state.md 1, architecture 3.2). */
	constexpr double MaxRewindS = 0.25;

	FTransform ActorFromBase(const FTransform& Base, const APawn* Pawn)
	{
		FTransform Out = Base;
		Out.AddToTranslation(FVector(0.0, 0.0, VerseMelee::HalfHeightOf(Pawn)));
		return Out;
	}

	FTransform BaseFromActor(const APawn* Pawn)
	{
		FVector Location = Pawn->GetActorLocation();
		Location.Z -= VerseMelee::HalfHeightOf(Pawn);
		return FTransform(FRotator(0.0, Pawn->GetActorRotation().Yaw, 0.0), Location);
	}
}

UVerseMeleeComponent::UVerseMeleeComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.bStartWithTickEnabled = false;
	PrimaryComponentTick.TickGroup = TG_PrePhysics;
	SetIsReplicatedByDefault(true);
}

EVerseMeleeOutcome UVerseMeleeComponent::Classify(const FTransform& Attacker, const FTransform& Victim,
	const UVerseMeleeDefinition& Def, bool bVictimEligible, bool bSweepClear)
{
	return VerseMelee::ClassifyMeasured(FVerseMeleeGeometry::Measure(Attacker, Victim), Def, bVictimEligible, bSweepClear);
}

void UVerseMeleeComponent::BeginPlay()
{
	Super::BeginPlay();
	EnsureDefinition();
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		DeathHandle = Hub->OnDeath.AddUObject(this, &UVerseMeleeComponent::OnHubDeath);
	}
}

void UVerseMeleeComponent::EndPlay(const EEndPlayReason::Type Reason)
{
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnDeath.Remove(DeathHandle);
	}
	EndPresentation();
	Super::EndPlay(Reason);
}

void UVerseMeleeComponent::EnsureDefinition()
{
	if (Definition)
	{
		return;
	}
	Definition = NewObject<UVerseMeleeDefinition>(this, TEXT("Melee_Hookbill"), RF_Transient);
	FString Error;
	if (!FVerseMeleeImport::FromFile(FVerseMeleeImport::DefaultPath(), *Definition, Tuning, Error))
	{
		UE_LOG(LogVerseCombat, Warning, TEXT("melee: %s; using the contract start values"), *Error);
	}
	Knife.EquipS = Tuning.EquipS;
	Knife.HitDelayS = Definition->StrikeHitDelay;
	Knife.RecoverS = Tuning.SwingRecoverS;
}

const UVerseMeleeDefinition& UVerseMeleeComponent::GetDefinition() const
{
	return Definition ? *Definition : *GetDefault<UVerseMeleeDefinition>();
}

IVerseMeleeWorld* UVerseMeleeComponent::MeleeWorld() const
{
	return UVerseMeleeWorldSubsystem::Get(this);
}

APawn* UVerseMeleeComponent::OwnerPawn() const
{
	return Cast<APawn>(GetOwner());
}

double UVerseMeleeComponent::ServerNow() const
{
	const UWorld* World = GetWorld();
	if (!World)
	{
		return 0.0;
	}
	if (const AGameStateBase* GameState = World->GetGameState())
	{
		return GameState->GetServerWorldTimeSeconds();
	}
	return World->GetTimeSeconds();
}

EVerseKnifeAnim UVerseMeleeComponent::GetKnifeAnim() const
{
	return Knife.Evaluate(ServerNow());
}

void UVerseMeleeComponent::PressMelee(bool bKnifeSlotActive)
{
	EnsureDefinition();
	const double Now = ServerNow();
	if (IsInFinisher() || !Clock.CanPress(Now))
	{
		return;
	}
	// Predicted presentation only; the client's clock copy never decides anything.
	Knife.Press(Now, bKnifeSlotActive);
	if (!GetOwner()->HasAuthority())
	{
		// A remote client keeps its own copy of the cooldown so it does not spam the server.
		Clock.TryPress(Now, GetDefinition().StrikeCooldown);
	}
	ServerMelee(float(Now));
}

void UVerseMeleeComponent::ServerMelee_Implementation(float ClientServerTime)
{
	EVerseMeleeOutcome Outcome = EVerseMeleeOutcome::Whiff;
	HandleMeleePress(double(ClientServerTime), Outcome);
}

void UVerseMeleeComponent::ClientConfirmMelee_Implementation(EVerseMeleeOutcome Outcome)
{
	Knife.Confirm(Outcome);
}

bool UVerseMeleeComponent::HandleMeleePress(double ViewServerTime, EVerseMeleeOutcome& OutOutcome)
{
	OutOutcome = EVerseMeleeOutcome::Whiff;
	APawn* Me = OwnerPawn();
	IVerseMeleeWorld* World = MeleeWorld();
	if (!Me || !World || !Me->HasAuthority())
	{
		return false;
	}
	EnsureDefinition();
	const UVerseMeleeDefinition& Def = GetDefinition();
	const double Now = World->ServerNow();
	const FVerseMeleeParticipant MeState = World->Describe(Me);
	if (!VerseMelee::CanStartMelee(MeState) || Session.bActive || !Clock.TryPress(Now, Def.StrikeCooldown))
	{
		return false;
	}
	// A melee press is an offensive action (combat-state.md 9.3).
	VerseMelee::EndSpawnProtection(Me);

	const double ViewTime = FMath::Clamp(ViewServerTime, Now - MaxRewindS, Now);
	const FTransform MeBase = World->GetBaseTransformAt(Me, ViewTime);
	TArray<APawn*> Candidates;
	World->GetCandidates(Me, Candidates);

	APawn* FinisherTarget = nullptr;
	APawn* StrikeTarget = nullptr;
	double FinisherDist = TNumericLimits<double>::Max();
	double StrikeDist = TNumericLimits<double>::Max();
	for (APawn* Candidate : Candidates)
	{
		const FVerseMeleeParticipant Target = World->Describe(Candidate);
		if (Target.Phase == EVerseCombatPhase::Dead)
		{
			continue;
		}
		const FTransform TargetBase = World->GetBaseTransformAt(Candidate, ViewTime);
		const FVerseMeleeGeometry Geometry = FVerseMeleeGeometry::Measure(MeBase, TargetBase);
		const bool bEligible = VerseMelee::IsFinisherEligible(MeState, Target);
		EVerseMeleeOutcome Result = VerseMelee::ClassifyMeasured(Geometry, Def, bEligible, true);
		if (Result == EVerseMeleeOutcome::Finisher && !World->IsSweepClear(Me, Candidate))
		{
			Result = VerseMelee::ClassifyMeasured(Geometry, Def, bEligible, false);
		}
		if (Result == EVerseMeleeOutcome::Finisher && Geometry.HorizontalCm < FinisherDist)
		{
			FinisherTarget = Candidate;
			FinisherDist = Geometry.HorizontalCm;
		}
		else if (Result == EVerseMeleeOutcome::Strike && VerseMelee::CanBeStruck(Target) && Geometry.ReachCm() < StrikeDist)
		{
			StrikeTarget = Candidate;
			StrikeDist = Geometry.ReachCm();
		}
	}

	if (FinisherTarget)
	{
		OutOutcome = EVerseMeleeOutcome::Finisher;
		StartFinisher(FinisherTarget, Now);
	}
	else if (StrikeTarget)
	{
		OutOutcome = EVerseMeleeOutcome::Strike;
		RaiseNoise(VerseTags::Noise_Melee);
		const TWeakObjectPtr<APawn> Weak(StrikeTarget);
		if (Def.StrikeHitDelay <= 0.f)
		{
			ApplyStrike(Weak);
		}
		else
		{
			// Applied by the server tick on the first tick at or after the hit delay (7.3).
			PendingStrikes.Add({Weak, Now + Def.StrikeHitDelay});
			SetComponentTickEnabled(true);
		}
	}
	else
	{
		RaiseNoise(VerseTags::Noise_Melee);
	}
	ClientConfirmMelee(OutOutcome);
	return true;
}

void UVerseMeleeComponent::ApplyStrike(TWeakObjectPtr<APawn> Victim)
{
	APawn* Me = OwnerPawn();
	IVerseMeleeWorld* World = MeleeWorld();
	if (!Me || !World || !Victim.IsValid())
	{
		return;
	}
	if (World->Describe(Me).Phase == EVerseCombatPhase::Dead)
	{
		return;
	}
	FVerseHitEvent Hit;
	Hit.InstigatorId = VerseMelee::PlayerIdOf(Me);
	Hit.VictimId = VerseMelee::PlayerIdOf(Victim.Get());
	Hit.WeaponId = Tuning.WeaponId;
	Hit.Source = EVerseDamageSource::Melee;
	// StrikeZone: multiplier 1.0 regardless of bone (7.3); reported as the torso.
	Hit.Zone = EVerseHitZone::UpperTorso;
	const FVector From = Me->GetActorLocation();
	const FVector To = Victim->GetActorLocation();
	Hit.ImpactWorld = FVector_NetQuantize10(To);
	Hit.Direction = FVector_NetQuantizeNormal((To - From).GetSafeNormal());
	Hit.DistanceM = float(FVector::Dist(From, To) / 100.0);
	Hit.Damage = GetDefinition().StrikeDamage;
	World->ApplyMeleeHit(Me, Victim.Get(), Hit);
}

void UVerseMeleeComponent::RaiseNoise(const FGameplayTag& Tag) const
{
	const APawn* Me = OwnerPawn();
	UVerseEventHub* Hub = UVerseEventHub::Get(this);
	if (!Me || !Hub)
	{
		return;
	}
	FVerseNoiseEvent Noise;
	Noise.Noise = Tag;
	Noise.SourceId = VerseMelee::PlayerIdOf(Me);
	Noise.Location = Me->GetActorLocation();
	Noise.ServerTime = float(ServerNow());
	Hub->OnNoise.Broadcast(Noise);
}

void UVerseMeleeComponent::StartFinisher(APawn* Victim, double Now)
{
	APawn* Me = OwnerPawn();
	Session.Start(Now);
	SessionVictim = Victim;
	AttackerDeathTime = FVerseFinisherSession::NoDeath;
	Clock.BlockUntil(Now + VerseFinisher::EndAt);

	FTransform VictimPaired;
	FTransform WarpBase;
	FVerseFinisherPose::ComputePaired(BaseFromActor(Me), BaseFromActor(Victim), Tuning.PairedOffsetCm, VictimPaired, WarpBase);
	SessionWarpTarget = ActorFromBase(WarpBase, Me);
	SessionWarpStart = Me->GetActorTransform();

	VerseMelee::SetPhase(Me, EVerseCombatPhase::FinisherAttacker);
	VerseMelee::SetPhase(Victim, EVerseCombatPhase::FinisherVictim);
	// The server snaps the victim to the paired pose at once; clients smooth to it (4.6).
	Victim->SetActorLocationAndRotation(ActorFromBase(VictimPaired, Victim).GetLocation(), VictimPaired.GetRotation());

	SetComponentTickEnabled(true);
	SendPhase(EVerseFinisherPhase::Locked);
}

void UVerseMeleeComponent::SendPhase(EVerseFinisherPhase Phase)
{
	FVerseFinisherEvent E;
	E.AttackerId = VerseMelee::PlayerIdOf(OwnerPawn());
	E.VictimId = VerseMelee::PlayerIdOf(SessionVictim.Get());
	E.Phase = Phase;
	E.SequenceStartServerTime = float(Session.StartTime);
	E.WarpTarget = SessionWarpTarget;
	MulticastFinisher(E);
}

void UVerseMeleeComponent::OnHubDeath(const FVerseDeathEvent& E)
{
	if (Session.bActive && E.VictimId == VerseMelee::PlayerIdOf(OwnerPawn()))
	{
		AttackerDeathTime = FMath::Min(AttackerDeathTime, double(E.ServerTime));
	}
}

void UVerseMeleeComponent::AdvanceFinisherServer(double Now)
{
	APawn* Me = OwnerPawn();
	IVerseMeleeWorld* World = MeleeWorld();
	if (!Me || !World)
	{
		return;
	}
	if (World->Describe(Me).Phase == EVerseCombatPhase::Dead)
	{
		AttackerDeathTime = FMath::Min(AttackerDeathTime, Now);
	}
	TArray<FVerseFinisherStep> Entered;
	const bool bReleased = Session.Advance(Now, AttackerDeathTime, Entered);
	for (const FVerseFinisherStep& Step : Entered)
	{
		switch (Step.Phase)
		{
		case EVerseFinisherPhase::Takedown:
			RaiseNoise(VerseTags::Noise_Finisher);
			break;
		case EVerseFinisherPhase::Recover:
			if (APawn* Victim = SessionVictim.Get())
			{
				FVerseHitEvent Hit;
				Hit.InstigatorId = VerseMelee::PlayerIdOf(Me);
				Hit.VictimId = VerseMelee::PlayerIdOf(Victim);
				Hit.WeaponId = Tuning.WeaponId;
				Hit.Source = EVerseDamageSource::Finisher;
				Hit.Zone = EVerseHitZone::Neck;
				Hit.Bone = FName(TEXT("Neck"));
				Hit.ImpactWorld = FVector_NetQuantize10(Victim->GetActorLocation());
				Hit.Direction = FVector_NetQuantizeNormal(Victim->GetActorForwardVector());
				World->ApplyMeleeHit(Me, Victim, Hit);
			}
			break;
		case EVerseFinisherPhase::Aborted:
			// Both released; the victim keeps its health (nothing was applied to it).
			if (APawn* Victim = SessionVictim.Get())
			{
				if (World->Describe(Victim).Phase == EVerseCombatPhase::FinisherVictim)
				{
					VerseMelee::SetPhase(Victim, EVerseCombatPhase::Alive);
				}
			}
			break;
		default:
			break;
		}
		SendPhase(Step.Phase);
	}
	if (bReleased)
	{
		if (World->Describe(Me).Phase == EVerseCombatPhase::FinisherAttacker)
		{
			VerseMelee::SetPhase(Me, EVerseCombatPhase::Alive);
		}
		SessionVictim.Reset();
	}
}

void UVerseMeleeComponent::MulticastFinisher_Implementation(const FVerseFinisherEvent& E)
{
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnFinisher.Broadcast(E);
	}
	if (E.Phase == EVerseFinisherPhase::Locked)
	{
		BeginPresentation(E);
	}
	else if (E.Phase == EVerseFinisherPhase::Aborted)
	{
		bPresentAborted = true;
		UpdateLocalViews(ServerNow() - PresentStart);
		EndPresentation();
	}
}

void UVerseMeleeComponent::BeginPresentation(const FVerseFinisherEvent& E)
{
	APawn* Me = OwnerPawn();
	if (!Me)
	{
		return;
	}
	const double Now = ServerNow();
	bPresenting = true;
	bPresentAborted = false;
	PresentStart = E.SequenceStartServerTime;
	WarpTarget = E.WarpTarget;
	WarpStartElapsed = Me->HasAuthority() ? 0.0 : FMath::Max(0.0, Now - PresentStart);
	WarpStartPose = Me->HasAuthority() ? SessionWarpStart : Me->GetActorTransform();
	PresentVictim = VerseMelee::FindPawnById(GetWorld(), E.VictimId);
	if (APawn* Victim = PresentVictim.Get())
	{
		VictimFrom = Victim->GetActorTransform();
		VictimTo = FVerseFinisherPose::VictimFromWarpTarget(WarpTarget, Tuning.PairedOffsetCm, VictimFrom.GetLocation().Z);
	}
	SnapStartTime = Now;
	LastViews.Reset();
	Knife.Confirm(EVerseMeleeOutcome::Finisher);
	SetComponentTickEnabled(true);
	TickPresentation(Now);
}

void UVerseMeleeComponent::TickPresentation(double Now)
{
	APawn* Me = OwnerPawn();
	if (!bPresenting || !Me)
	{
		return;
	}
	const double Elapsed = Now - PresentStart;
	// 4.4: the attacker reaches Warp_Finisher at Takedown on every machine.
	if (Elapsed <= VerseFinisher::TakedownAt + 0.1)
	{
		const FTransform Pose = FVerseFinisherPose::EvaluateWarp(WarpStartPose, WarpStartElapsed, WarpTarget, Elapsed);
		Me->SetActorLocationAndRotation(Pose.GetLocation(), Pose.GetRotation());
	}
	// 4.6: the victim's client smooths to the paired pose (the server snapped it already).
	if (APawn* Victim = PresentVictim.Get())
	{
		const double Since = Now - SnapStartTime;
		if (!Me->HasAuthority() && Since <= Tuning.VictimSnapS + 0.1)
		{
			const FTransform Pose = FVerseFinisherPose::EvaluateSnap(VictimFrom, VictimTo, Since, Tuning.VictimSnapS);
			Victim->SetActorLocationAndRotation(Pose.GetLocation(), Pose.GetRotation());
		}
	}
	UpdateLocalViews(Elapsed);
	if (VerseFinisher::IsOver(Elapsed))
	{
		EndPresentation();
	}
}

void UVerseMeleeComponent::UpdateLocalViews(double Elapsed)
{
	APawn* Me = OwnerPawn();
	APawn* Victim = PresentVictim.Get();
	if (!Me)
	{
		return;
	}
	const FVerseFinisherViewState State = VerseFinisher::EvaluateView(Elapsed, bPresentAborted, GoreLevel);
	const FTransform Camera = VerseFinisher::CameraTransform(Me->GetActorTransform(),
		Victim ? Victim->GetActorTransform() : Me->GetActorTransform(), Tuning.CameraDistanceCm, Tuning.CameraHeightCm);
	for (APawn* Viewer : {Me, Victim})
	{
		if (!Viewer)
		{
			continue;
		}
		const FVerseFinisherViewState* Last = LastViews.Find(Viewer);
		if (!Last || !(*Last == State))
		{
			LastViews.Add(Viewer, State);
			OnFinisherView.Broadcast(Viewer, State);
		}
		ApplyView(Viewer, State, Camera);
	}
}

void UVerseMeleeComponent::ApplyView(APawn* Viewer, const FVerseFinisherViewState& State, const FTransform& Camera)
{
	if (!Viewer->IsLocallyControlled())
	{
		return;
	}
	APlayerController* Controller = Cast<APlayerController>(Viewer->GetController());
	if (!Controller)
	{
		return;
	}
	const bool bThird = State.View != EVerseFinisherView::FirstPerson;
	if (bThird)
	{
		if (!FinisherCamera)
		{
			FActorSpawnParameters Params;
			Params.ObjectFlags |= RF_Transient;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			FinisherCamera = GetWorld()->SpawnActor<ACameraActor>(Camera.GetLocation(), Camera.Rotator(), Params);
		}
		if (FinisherCamera)
		{
			FinisherCamera->SetActorTransform(Camera);
			if (Controller->GetViewTarget() != FinisherCamera)
			{
				Controller->SetViewTargetWithBlend(FinisherCamera, float(Tuning.CameraBlendS));
			}
		}
	}
	else if (Controller->GetViewTarget() != Viewer)
	{
		Controller->SetViewTargetWithBlend(Viewer, float(Tuning.CameraBlendS));
	}
	if (APlayerCameraManager* CameraManager = Controller->PlayerCameraManager)
	{
		if (State.View == EVerseFinisherView::Black)
		{
			CameraManager->SetManualCameraFade(1.f, FLinearColor::Black, false);
		}
		else
		{
			CameraManager->StopCameraFade();
		}
	}
}

void UVerseMeleeComponent::EndPresentation()
{
	if (bPresenting)
	{
		bPresenting = false;
		const FVerseFinisherViewState Done;
		for (APawn* Viewer : {OwnerPawn(), PresentVictim.Get()})
		{
			if (Viewer)
			{
				OnFinisherView.Broadcast(Viewer, Done);
				ApplyView(Viewer, Done, Viewer->GetActorTransform());
			}
		}
	}
	if (FinisherCamera)
	{
		FinisherCamera->Destroy();
		FinisherCamera = nullptr;
	}
	PresentVictim.Reset();
	LastViews.Reset();
}

void UVerseMeleeComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	const double Now = ServerNow();
	if (GetOwner() && GetOwner()->HasAuthority())
	{
		for (int32 Index = 0; Index < PendingStrikes.Num();)
		{
			if (Now + VerseMelee::TimeTolerance >= PendingStrikes[Index].ApplyAt)
			{
				const TWeakObjectPtr<APawn> Victim = PendingStrikes[Index].Victim;
				PendingStrikes.RemoveAt(Index);
				ApplyStrike(Victim);
			}
			else
			{
				++Index;
			}
		}
		if (Session.bActive)
		{
			AdvanceFinisherServer(Now);
		}
	}
	TickPresentation(Now);
	if (!Session.bActive && !bPresenting && PendingStrikes.Num() == 0)
	{
		SetComponentTickEnabled(false);
	}
}
