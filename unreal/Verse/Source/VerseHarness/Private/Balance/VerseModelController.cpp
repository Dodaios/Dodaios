#include "Balance/VerseModelController.h"

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

void AVerseModelController::ResetMatchMemory()
{
	TrickState = FVerseTrickState();
	Rng = FVerseRng(Seed, 0, EVerseRngSalt::Harness);
	LastInput = FVerseInputFrame();
	bSawLastTick = false;
	ReactUntilS = 0.0;
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
	const FVerseInputFrame Limited = ApplyPersonLimits(Model, FromBrain, IsReacting(NowS), DeltaS);
	LastInput = FVerseTrickOverrides::Apply(TrickConfig, Percepts, Limited, TrickState, Rng, NowS);
	LastInput.ServerTimeMs = Percepts.ServerTimeMs;
	return LastInput;
}
