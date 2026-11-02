#include "Melee/VerseMeleeComponent.h"

#include "Camera/CameraActor.h"
#include "Camera/PlayerCameraManager.h"
#include "Combat/VerseMeleeDefinition.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
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

	bool IsDead(const APawn* Pawn)
	{
		const UVerseCombatStateComponent* State = Pawn ? Pawn->FindComponentByClass<UVerseCombatStateComponent>() : nullptr;
		return State && State->Phase == EVerseCombatPhase::Dead;
	}

	/** The local player controller of Viewer: its own, or the one a lock remembered (a dead victim may be unpossessed). */
	APlayerController* LocalPlayerController(APawn* Viewer, AController* Remembered)
	{
		AController* Controller = Viewer ? Viewer->GetController() : nullptr;
		if (!Controller)
		{
			Controller = Remembered;
		}
		APlayerController* PC = Cast<APlayerController>(Controller);
		return PC && PC->IsLocalController() ? PC : nullptr;
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
	VerseMelee::EndSpawnProtection(Me, Now);

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
	// 7.4 "no input": both pawns are held from Locked to release (owning clients lock on the event).
	LockPawn(Me, SessionWarpTarget.Rotator().Yaw);
	LockPawn(Victim, VictimPaired.Rotator().Yaw);
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
		ReleaseLocks();
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
		LockPawn(Victim, VictimTo.Rotator().Yaw);
	}
	LockPawn(Me, WarpTarget.Rotator().Yaw);
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

bool UVerseMeleeComponent::IsPawnLocked(const APawn* Pawn) const
{
	return Pawn && Locks.ContainsByPredicate([Pawn](const FPawnLock& L) { return L.Pawn.Get() == Pawn; });
}

void UVerseMeleeComponent::LockPawn(APawn* Pawn, double PairedYaw)
{
	if (!Pawn)
	{
		return;
	}
	if (FPawnLock* Existing = Locks.FindByPredicate([Pawn](const FPawnLock& L) { return L.Pawn.Get() == Pawn; }))
	{
		Existing->Yaw = PairedYaw;
		return;
	}
	// The server holds every pawn; a client holds only the pawn it controls (the rest follow replication).
	const bool bAuthority = Pawn->HasAuthority();
	const bool bLocal = Pawn->IsLocallyControlled();
	if (!bAuthority && !bLocal)
	{
		return;
	}
	FPawnLock Lock;
	Lock.Pawn = Pawn;
	Lock.Yaw = PairedYaw;
	if (AController* Controller = Pawn->GetController())
	{
		Controller->SetIgnoreMoveInput(true);
		Controller->SetIgnoreLookInput(true);
		Lock.Controller = Controller;
		Lock.bInputIgnored = true;
		// bUseControllerRotationYaw puts the actor back to the control rotation every frame, so the
		// control rotation carries the paired yaw.
		const FRotator Paired(0.0, PairedYaw, 0.0);
		Controller->SetControlRotation(Paired);
		APlayerController* PC = Cast<APlayerController>(Controller);
		if (PC && bAuthority && !bLocal)
		{
			PC->ClientSetRotation(Paired, false);
		}
	}
	if (ACharacter* Character = Cast<ACharacter>(Pawn))
	{
		if (UCharacterMovementComponent* Movement = Character->GetCharacterMovement())
		{
			Lock.PrevMovementMode = uint8(Movement->MovementMode.GetValue());
			Lock.PrevCustomMode = Movement->CustomMovementMode;
			Movement->StopMovementImmediately();
			Movement->DisableMovement();
			Lock.bMovementStopped = true;
		}
	}
	Locks.Add(Lock);
}

void UVerseMeleeComponent::HoldLocks()
{
	for (const FPawnLock& Lock : Locks)
	{
		// A bot's focus or a stray rotation update must not turn a locked pawn.
		AController* Controller = Lock.Controller.Get();
		if (Controller && Lock.bInputIgnored
			&& FMath::Abs(FRotator::NormalizeAxis(Controller->GetControlRotation().Yaw - Lock.Yaw)) > 0.01)
		{
			Controller->SetControlRotation(FRotator(0.0, Lock.Yaw, 0.0));
		}
	}
}

void UVerseMeleeComponent::ReleaseLocks()
{
	for (const FPawnLock& Lock : Locks)
	{
		AController* Controller = Lock.Controller.Get();
		if (Controller && Lock.bInputIgnored)
		{
			Controller->SetIgnoreMoveInput(false);
			Controller->SetIgnoreLookInput(false);
		}
		// A dead pawn's movement belongs to the death path (ragdoll, respawn).
		ACharacter* Character = Cast<ACharacter>(Lock.Pawn.Get());
		if (Character && Lock.bMovementStopped && !IsDead(Character) && Character->GetCharacterMovement())
		{
			Character->GetCharacterMovement()->SetMovementMode(EMovementMode(Lock.PrevMovementMode), Lock.PrevCustomMode);
		}
	}
	Locks.Reset();
}

void UVerseMeleeComponent::UpdateLocalViews(double Elapsed)
{
	APawn* Me = OwnerPawn();
	APawn* Victim = PresentVictim.Get();
	if (!Me)
	{
		return;
	}
	// Per role (7.4): only the attacker returns to first person with its weapon; the victim is
	// released to the death view at Recover.
	const EVerseGoreLevel Gore = VerseMelee::GetLocalGoreLevel();
	const FTransform Camera = VerseFinisher::CameraTransform(Me->GetActorTransform(),
		Victim ? Victim->GetActorTransform() : Me->GetActorTransform(), Tuning.CameraDistanceCm, Tuning.CameraHeightCm);
	const TPair<APawn*, FVerseFinisherViewState> Viewers[] = {
		{Me, VerseFinisher::EvaluateView(Elapsed, bPresentAborted, Gore)},
		{Victim, VerseFinisher::EvaluateVictimView(Elapsed, bPresentAborted, Gore)}};
	for (const TPair<APawn*, FVerseFinisherViewState>& V : Viewers)
	{
		if (!V.Key)
		{
			continue;
		}
		const FVerseFinisherViewState* Last = LastViews.Find(V.Key);
		const bool bWasBlack = Last && Last->View == EVerseFinisherView::Black;
		if (!Last || !(*Last == V.Value))
		{
			LastViews.Add(V.Key, V.Value);
			OnFinisherView.Broadcast(V.Key, V.Value);
		}
		ApplyView(V.Key, V.Value, Camera, bWasBlack);
	}
}

void UVerseMeleeComponent::ApplyView(APawn* Viewer, const FVerseFinisherViewState& State, const FTransform& Camera, bool bWasBlack)
{
	const FPawnLock* Lock = Locks.FindByPredicate([Viewer](const FPawnLock& L) { return L.Pawn.Get() == Viewer; });
	APlayerController* Controller = LocalPlayerController(Viewer, Lock ? Lock->Controller.Get() : nullptr);
	if (!Controller)
	{
		return;
	}
	APlayerCameraManager* CameraManager = Controller->PlayerCameraManager;
	if (State.bReleasedToDeathView)
	{
		// The death view owns the view target and the fade now; only undo the cut this component made.
		if (bWasBlack && CameraManager)
		{
			CameraManager->StopCameraFade();
		}
		return;
	}
	if (State.View != EVerseFinisherView::FirstPerson)
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
	if (CameraManager)
	{
		if (State.View == EVerseFinisherView::Black)
		{
			CameraManager->SetManualCameraFade(1.f, FLinearColor::Black, false);
		}
		else if (bWasBlack)
		{
			// Only the cut this component started; a fade another system started stays.
			CameraManager->StopCameraFade();
		}
	}
}

void UVerseMeleeComponent::EndPresentation()
{
	if (bPresenting)
	{
		bPresenting = false;
		UpdateLocalViews(VerseFinisher::EndAt);
		// A dead victim still viewing the finisher camera means no death view took it: fall back
		// to its own pawn before the camera goes.
		APawn* Victim = PresentVictim.Get();
		if (Victim && FinisherCamera)
		{
			const FPawnLock* Lock = Locks.FindByPredicate([Victim](const FPawnLock& L) { return L.Pawn.Get() == Victim; });
			APlayerController* Controller = LocalPlayerController(Victim, Lock ? Lock->Controller.Get() : nullptr);
			if (Controller && Controller->GetViewTarget() == FinisherCamera)
			{
				Controller->SetViewTarget(Victim);
			}
		}
	}
	if (FinisherCamera)
	{
		FinisherCamera->Destroy();
		FinisherCamera = nullptr;
	}
	ReleaseLocks();
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
	HoldLocks();
	TickPresentation(Now);
	if (!Session.bActive && !bPresenting && PendingStrikes.Num() == 0)
	{
		SetComponentTickEnabled(false);
	}
}
