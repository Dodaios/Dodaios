#include "Balance/VerseModelController.h"

#include "Balance/VerseHarnessPerceptFeed.h"
#include "Bot/VerseBotTier.h"
#include "Controller/VerseBotPilot.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/Pawn.h"
#include "VerseCombatDriverComponent.h"

AVerseModelController::AVerseModelController()
{
	PrimaryActorTick.bCanEverTick = false;
	Brain = [](const FVersePerceptFrame&) { return FVerseInputFrame(); };
}

void AVerseModelController::PostInitializeComponents()
{
	Super::PostInitializeComponents();
	// A harness slot is a player: it needs a player state for its id and the scoreboard.
	if (HasAuthority())
	{
		InitPlayerState();
	}
}

void AVerseModelController::Destroyed()
{
	DetachPerception();
	Super::Destroyed();
}

void AVerseModelController::AttachPerception(UVerseHarnessPerceptFeed* Feed, const FVersePerceptionProfile& Profile)
{
	DetachPerception();
	if (!Feed)
	{
		return;
	}
	PerceptSource = Feed;
	PerceptHandle = Feed->OnPerceptFrame.AddUObject(this, &AVerseModelController::HandlePerceptFrame);
	Feed->RegisterObserver(this, Profile);
}

void AVerseModelController::DetachPerception()
{
	if (UVerseHarnessPerceptFeed* Feed = PerceptSource.Get())
	{
		Feed->OnPerceptFrame.Remove(PerceptHandle);
		Feed->UnregisterObserver(this);
	}
	PerceptSource.Reset();
	PerceptHandle.Reset();
}

void AVerseModelController::HandlePerceptFrame(AController* Observer, const FVersePerceptFrame& Percepts)
{
	if (Observer != this)
	{
		return;
	}
	const double NowS = double(Percepts.ServerTimeMs) / 1000.0;
	const float DeltaS = LastFrameS >= 0.0 ? float(FMath::Max(0.0, NowS - LastFrameS)) : 0.f;
	LastFrameS = NowS;
	const FVerseInputFrame Input = Think(Percepts, NowS, DeltaS);
	++FramesThought;
	if (APawn* Own = GetPawn())
	{
		ApplyInputToPawn(*this, *Own, Input);
		// Buttons become shots, reloads, knife and gadgets through the primary module's combat driver.
		if (UVerseCombatDriverComponent* Driver = UVerseCombatDriverComponent::FindOn(Own))
		{
			Driver->SetExternalFrame(Input);
		}
	}
}

void AVerseModelController::ApplyInputToPawn(AController& Controller, APawn& Pawn, const FVerseInputFrame& Input)
{
	FRotator Control = Controller.GetControlRotation();
	Control.Pitch = FMath::ClampAngle(FRotator::NormalizeAxis(Control.Pitch + Input.LookDeltaDeg.X), -89.f, 89.f);
	Control.Yaw = FRotator::NormalizeAxis(Control.Yaw + Input.LookDeltaDeg.Y);
	Control.Roll = 0.f;
	Controller.SetControlRotation(Control);

	const FRotator Yaw(0.f, Control.Yaw, 0.f);
	const FRotationMatrix Basis(Yaw);
	FVector2f Move = Input.Move;
	if (Move.SizeSquared() > 1.f)
	{
		Move.Normalize();
	}
	if (!Move.IsNearlyZero())
	{
		Pawn.AddMovementInput(Basis.GetUnitAxis(EAxis::X) * Move.X + Basis.GetUnitAxis(EAxis::Y) * Move.Y, 1.f);
	}

	ACharacter* Character = Cast<ACharacter>(&Pawn);
	if (!Character)
	{
		return;
	}
	if (Input.Pressed & uint32(EVerseInputButton::Jump))
	{
		Character->Jump();
	}
	else if (!(Input.Buttons & uint32(EVerseInputButton::Jump)))
	{
		Character->StopJumping();
	}
	const bool bLow = (Input.Buttons & (uint32(EVerseInputButton::Crouch) | uint32(EVerseInputButton::Prone))) != 0;
	const UCharacterMovementComponent* Movement = Character->GetCharacterMovement();
	const bool bWantsLow = Character->bIsCrouched || (Movement && Movement->bWantsToCrouch);
	if (bLow && !bWantsLow)
	{
		Character->Crouch();
	}
	else if (!bLow && bWantsLow)
	{
		Character->UnCrouch();
	}
}

void AVerseModelController::Configure(const FVersePersonModel& InModel, const FVerseTrickConfig& InTrick, uint32 InSeed)
{
	Model = InModel;
	TrickConfig = InTrick;
	Seed = InSeed;
	ResetMatchMemory();
}

void AVerseModelController::SetBrain(FBrain InBrain)
{
	Brain = InBrain ? MoveTemp(InBrain) : FBrain([](const FVersePerceptFrame&) { return FVerseInputFrame(); });
}

void AVerseModelController::UseBotBrain(UVerseBotTier* BrainTier, uint64 BrainSeed, bool bLearning)
{
	if (!BrainTier)
	{
		Pilot.Reset();
		PilotTier = nullptr;
		SetBrain(nullptr);
		return;
	}
	PilotTier = BrainTier;
	PilotSeed = BrainSeed;
	bPilotLearning = bLearning;
	Pilot = MakeShared<FVerseBotPilot>(*this);
	Pilot->Reset(*PilotTier, PilotSeed, bPilotLearning);
	TWeakPtr<FVerseBotPilot> Weak = Pilot;
	SetBrain([Weak](const FVersePerceptFrame& Frame)
	{
		const TSharedPtr<FVerseBotPilot> Strong = Weak.Pin();
		return Strong.IsValid() ? Strong->Think(Frame) : FVerseInputFrame();
	});
}

void AVerseModelController::ResetMatchMemory()
{
	if (Pilot.IsValid() && PilotTier)
	{
		Pilot->Reset(*PilotTier, PilotSeed, bPilotLearning);
	}
	TrickState = FVerseTrickState();
	Rng = FVerseRng(Seed, 0, EVerseRngSalt::Harness);
	LastInput = FVerseInputFrame();
	bSawLastTick = false;
	ReactUntilS = 0.0;
	LastFrameS = -1.0;
	FramesThought = 0;
}

FVerseInputFrame AVerseModelController::ApplyPersonLimits(const FVersePersonModel& InModel,
	const FVerseInputFrame& InBrain, bool bReacting, float DeltaS)
{
	FVerseInputFrame Out = InBrain;
	if (bReacting)
	{
		// Before the reaction time has passed the person has not processed the sighting yet.
		Out.Buttons &= ~(uint32(EVerseInputButton::Fire) | uint32(EVerseInputButton::Ads));
		Out.LookDeltaDeg = FVector2f::ZeroVector;
	}
	const float MaxTurn = InModel.TurnRateDegS * FMath::Max(DeltaS, 0.f);
	Out.LookDeltaDeg.X = FMath::Clamp(Out.LookDeltaDeg.X, -MaxTurn, MaxTurn);
	Out.LookDeltaDeg.Y = FMath::Clamp(Out.LookDeltaDeg.Y, -MaxTurn, MaxTurn);
	return Out;
}

FVerseInputFrame AVerseModelController::Think(const FVersePerceptFrame& Percepts, double NowS, float DeltaS)
{
	const bool bSees = FVerseTrickOverrides::AnySighting(Percepts);
	if (bSees && !bSawLastTick)
	{
		const double ReactionMs = FMath::Max(80.0, Rng.Gaussian(Model.ReactionMeanMs, Model.ReactionSdMs));
		ReactUntilS = NowS + ReactionMs / 1000.0;
	}
	bSawLastTick = bSees;

	const FVerseInputFrame FromBrain = Brain(Percepts);
	// The bot brain waits its tier's reaction (the person's) itself; a second wait would double it.
	const bool bReacting = !Pilot.IsValid() && IsReacting(NowS);
	const FVerseInputFrame Limited = ApplyPersonLimits(Model, FromBrain, bReacting, DeltaS);
	LastInput = FVerseTrickOverrides::Apply(TrickConfig, Percepts, Limited, TrickState, Rng, NowS);
	LastInput.ServerTimeMs = Percepts.ServerTimeMs;
	return LastInput;
}
