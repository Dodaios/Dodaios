#include "Balance/VerseBalanceGauntletController.h"
#include "Balance/VerseHarnessPerceptFeed.h"
#include "Balance/VerseHarnessScenario.h"
#include "Balance/VerseModelController.h"
#include "Bot/VerseBotTier.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerStart.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

#if WITH_DEV_AUTOMATION_TESTS

namespace VerseHarnessWorldTestPrivate
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	/** A bare game world with no game mode: the fixture the harness falls back to plain characters in. */
	struct FFixtureWorld
	{
		UWorld* World = nullptr;

		FFixtureWorld()
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("VerseHarnessFixture"));
			FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
			Context.SetCurrentWorld(World);
			World->InitializeActorsForPlay(FURL());
			World->BeginPlay();
		}

		~FFixtureWorld()
		{
			GEngine->DestroyWorldContext(World);
			World->DestroyWorld(false);
		}

		APlayerStart* Start(const FVector& At, FName Tag) const
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			APlayerStart* S = World->SpawnActor<APlayerStart>(APlayerStart::StaticClass(), FTransform(At), Params);
			S->PlayerStartTag = Tag;
			return S;
		}
	};

	FVerseHarnessScenario RusherVsSilent(const FString& OutDir)
	{
		FVerseHarnessScenario S;
		S.Run = TEXT("world-test");
		S.OutputDir = OutDir;
		FVerseHarnessUnit Unit;
		Unit.Pairing = TEXT("skilled+rusher_vs_average+silent");
		Unit.Set = TEXT("humans");
		Unit.Seed = 7;
		Unit.Bouts = 3;
		Unit.A.Kind = EVerseHarnessSlotKind::Model;
		Unit.A.Model = TEXT("skilled");
		Unit.A.Trick = TEXT("rusher");
		Unit.B.Kind = EVerseHarnessSlotKind::Model;
		Unit.B.Model = TEXT("average");
		Unit.B.Trick = TEXT("silent");
		S.Units.Add(Unit);
		return S;
	}

	double DistTo(const AController* C, const FVector& At)
	{
		const APawn* P = C ? C->GetPawn() : nullptr;
		return P ? FVector::Dist(P->GetActorLocation(), At) : TNumericLimits<double>::Max();
	}
} // namespace VerseHarnessWorldTestPrivate

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHarnessModelsActTest, "Verse.Harness.World.ModelsActWithNullBrain",
								 VerseHarnessWorldTestPrivate::Flags)
bool FVerseHarnessModelsActTest::RunTest(const FString& Parameters)
{
	using namespace VerseHarnessWorldTestPrivate;
	FFixtureWorld Fixture;
	const FVector Side0(0.0, 0.0, 100.0);
	const FVector Side1(3000.0, 0.0, 100.0);
	Fixture.Start(Side1, TEXT("VerseSide1"));
	Fixture.Start(Side0, TEXT("VerseSide0"));
	const FString OutDir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness"), TEXT("test"), TEXT("world"));
	IFileManager::Get().DeleteDirectory(*OutDir, false, true);

	UVerseBalanceGauntletController* Run = NewObject<UVerseBalanceGauntletController>();
	FString Error;
	if (!TestTrue(TEXT("run starts"), Run->Start(Fixture.World, RusherVsSilent(OutDir), Error)))
	{
		AddError(Error);
		return false;
	}
	AController* A = Run->GetSlot(0);
	AController* B = Run->GetSlot(1);
	TestTrue(TEXT("both slots are model controllers"), Cast<AVerseModelController>(A) && Cast<AVerseModelController>(B));
	TestEqual(TEXT("both models observe the percept feed"), Run->GetPerceptFeed()->NumObservers(), 2);

	// Bout 0: slot A on side 0, B on side 1.
	TestEqual(TEXT("bout 0 spawn side of A"), Run->GetSpawnSideA(), 0);
	TestTrue(TEXT("A spawned at side 0"), DistTo(A, Side0) < 1.0);
	TestTrue(TEXT("B spawned at side 1"), DistTo(B, Side1) < 1.0);

	// One server tick: the feed delivers frames, the trick layers act without any brain.
	TestTrue(TEXT("tick runs"), Run->Tick());
	TestEqual(TEXT("A thought once"), Cast<AVerseModelController>(A)->GetFramesThought(), int64(1));
	const APawn* PawnA = A ? A->GetPawn() : nullptr;
	TestTrue(TEXT("the rusher pushes its pawn forward"), PawnA && PawnA->GetPendingMovementInputVector().X > 0.5);
	TestTrue(TEXT("the rusher holds sprint"), Cast<AVerseModelController>(A)->GetLastInput().IsHeld(EVerseInputButton::Sprint));
	const ACharacter* PawnB = B ? Cast<ACharacter>(B->GetPawn()) : nullptr;
	TestTrue(TEXT("the silent model crouches its pawn"), PawnB && PawnB->GetCharacterMovement()->bWantsToCrouch);

	// Bout 1: both pawns reset, sides swapped.
	Run->EndBoutForTest();
	TestEqual(TEXT("bout index"), Run->GetBoutIndex(), 1);
	TestEqual(TEXT("bout 1 spawn side of A"), Run->GetSpawnSideA(), 1);
	TestTrue(TEXT("A respawned at side 1"), DistTo(Run->GetSlot(0), Side1) < 1.0);
	TestTrue(TEXT("B respawned at side 0"), DistTo(Run->GetSlot(1), Side0) < 1.0);
	TestTrue(TEXT("A got a fresh pawn"), Run->GetSlot(0)->GetPawn() != PawnA);

	FString Lines;
	FFileHelper::LoadFileToString(Lines, *FPaths::Combine(OutDir, TEXT("bouts.jsonl")));
	TestTrue(TEXT("bout 0 records side 0"), Lines.Contains(TEXT("\"spawnSideA\":0")));
	TestTrue(TEXT("bout 0 records its server window"), Lines.Contains(TEXT("\"serverStartMs\":")) && Lines.Contains(TEXT("\"serverEndMs\":")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHarnessSpawnFallbackTest, "Verse.Harness.World.SpawnPairWithoutStarts",
								 VerseHarnessWorldTestPrivate::Flags)
bool FVerseHarnessSpawnFallbackTest::RunTest(const FString& Parameters)
{
	using namespace VerseHarnessWorldTestPrivate;
	FFixtureWorld Fixture;
	const FString OutDir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness"), TEXT("test"), TEXT("fallback"));
	UVerseBalanceGauntletController* Run = NewObject<UVerseBalanceGauntletController>();
	FString Error;
	if (!TestTrue(TEXT("run starts"), Run->Start(Fixture.World, RusherVsSilent(OutDir), Error)))
	{
		AddError(Error);
		return false;
	}
	const double Gap = FVector::Dist(Run->GetSpawnTransform(0).GetLocation(), Run->GetSpawnTransform(1).GetLocation());
	TestTrue(TEXT("the harness pair is 20 m apart"), FMath::IsNearlyEqual(Gap, 2000.0, 1.0));
	TestTrue(TEXT("A at side 0"), DistTo(Run->GetSlot(0), Run->GetSpawnTransform(0).GetLocation()) < 1.0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHarnessTierTest, "Verse.Harness.World.TierAndPatch", VerseHarnessWorldTestPrivate::Flags)
bool FVerseHarnessTierTest::RunTest(const FString& Parameters)
{
	FString Error;
	UVerseBotTier* Hard = UVerseBalanceGauntletController::MakeTier(nullptr, TEXT("hard"), true,
																	TEXT(R"({"hard": {"TurnRateDegS": 123, "ReactionMs": [111, 11]}, "elite": {"TurnRateDegS": 999}, "AimNoiseDeg": 0.5})"),
																	Error);
	if (!TestNotNull(TEXT("hard tier with a patch"), Hard))
	{
		AddError(Error);
		return false;
	}
	TestEqual(TEXT("per-tier patch"), Hard->TurnRateDegS, 123.f);
	TestEqual(TEXT("vector field patch"), Hard->ReactionMs, FVector2f(111.f, 11.f));
	TestEqual(TEXT("flat patch applies to every tier"), Hard->AimNoiseDeg, 0.5f);
	TestEqual(TEXT("tier id"), Hard->TierId, FName(TEXT("hard")));

	UVerseBotTier* NoLearn = UVerseBalanceGauntletController::MakeTier(nullptr, TEXT("hard"), false, FString(), Error);
	TestEqual(TEXT("learning off caps the learnt weight at 0"), NoLearn ? NoLearn->LearnWeightMax : -1.f, 0.f);

	UVerseBotTier* Adaptive = UVerseBalanceGauntletController::MakeTier(nullptr, TEXT("adaptive"), true, FString(), Error);
	TestEqual(TEXT("adaptive starts from normal"), Adaptive ? Adaptive->TierId : NAME_None, FName(TEXT("normal")));

	Error.Reset();
	TestNull(TEXT("an unknown field fails"),
			 UVerseBalanceGauntletController::MakeTier(nullptr, TEXT("hard"), true, TEXT(R"({"NoSuchField": 1})"), Error));
	TestTrue(TEXT("the reason names the field"), Error.Contains(TEXT("NoSuchField")));
	TestNull(TEXT("an unknown tier fails"), UVerseBalanceGauntletController::MakeTier(nullptr, TEXT("legend"), true, FString(), Error));

	UVerseBotTier* Start = NewObject<UVerseBotTier>();
	UVerseBotTier::ApplyStartValues(TEXT("hard"), *Start);
	const FVersePersonModel Person = UVerseBalanceGauntletController::PersonFromTier(*Start, TEXT("hard"));
	TestEqual(TEXT("person reaction mean from the tier"), Person.ReactionMeanMs, Start->ReactionMs.X);
	TestEqual(TEXT("person turn rate from the tier"), Person.TurnRateDegS, Start->TurnRateDegS);
	TestEqual(TEXT("person aim wander from the tier"), Person.AimWanderSdDeg, Start->AimNoiseDeg);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHarnessInputApplyTest, "Verse.Harness.World.InputReachesPawn", VerseHarnessWorldTestPrivate::Flags)
bool FVerseHarnessInputApplyTest::RunTest(const FString& Parameters)
{
	using namespace VerseHarnessWorldTestPrivate;
	FFixtureWorld Fixture;
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AVerseModelController* Model = Fixture.World->SpawnActor<AVerseModelController>(Params);
	ACharacter* Pawn = Fixture.World->SpawnActor<ACharacter>(ACharacter::StaticClass(), FTransform(FVector(0, 0, 100)), Params);
	Pawn->GetCharacterMovement()->GetNavAgentPropertiesRef().bCanCrouch = true;
	Model->Possess(Pawn);
	Model->SetControlRotation(FRotator::ZeroRotator);

	FVerseInputFrame Input;
	Input.LookDeltaDeg = FVector2f(0.f, 90.f);
	Input.Move = FVector2f(1.f, 0.f);
	AVerseModelController::ApplyInputToPawn(*Model, *Pawn, Input);
	TestTrue(TEXT("yaw added to the control rotation"), FMath::IsNearlyEqual(Model->GetControlRotation().Yaw, 90.f, 0.01f));
	TestTrue(TEXT("move is in pawn space after the turn (+Y)"), Pawn->GetPendingMovementInputVector().Y > 0.99);
	TestFalse(TEXT("no crouch without the button"), Pawn->GetCharacterMovement()->bWantsToCrouch);

	FVerseInputFrame Low;
	Low.Buttons = uint32(EVerseInputButton::Prone);
	AVerseModelController::ApplyInputToPawn(*Model, *Pawn, Low);
	TestTrue(TEXT("prone lowers the character"), Pawn->GetCharacterMovement()->bWantsToCrouch);
	AVerseModelController::ApplyInputToPawn(*Model, *Pawn, FVerseInputFrame());
	TestFalse(TEXT("releasing stands up"), Pawn->GetCharacterMovement()->bWantsToCrouch);

	// Frames of another observer are not this model's.
	UVerseHarnessPerceptFeed* Feed = NewObject<UVerseHarnessPerceptFeed>();
	Model->AttachPerception(Feed, FVersePerceptionProfile());
	Model->HandlePerceptFrame(nullptr, FVersePerceptFrame());
	TestEqual(TEXT("foreign frame ignored"), Model->GetFramesThought(), int64(0));
	Feed->Tick(Fixture.World);
	TestEqual(TEXT("own frame thought"), Model->GetFramesThought(), int64(1));
	const FVerseSelfPercept Self = UVerseHarnessPerceptFeed::SelfOf(*Model);
	TestEqual(TEXT("self percept is the own pawn"), Self.Location, Pawn->GetActorLocation());
	Model->DetachPerception();
	TestEqual(TEXT("detached"), Feed->NumObservers(), 0);
	return true;
}

#endif
