#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Engine/World.h"
#include "EngineUtils.h"
#include "Fixture/VerseMovementCourse.h"
#include "GameFramework/PlayerStart.h"
#include "GameFramework/WorldSettings.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Tests/Movement/VerseMovementTestWorld.h"
#include "VerseCharacter.h"
#include "VerseCharacterMovement.h"
#include "VerseMovementNetworking.h"
#include "VerseMovementScripts.h"
#include "VerseMovementTuning.h"
#include "VerseRng.h"

namespace
{
	constexpr EAutomationTestFlags BasicsTestFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	/** Steady horizontal speed after accelerating for Settle seconds, averaged over Measure seconds. */
	float SteadySpeed(FVerseMovementTestWorld& W, AVerseCharacter& Pawn, uint32 Buttons, const FVector2f& Move, float Settle = 2.5f, float Measure = 1.f)
	{
		uint32 Prev = 0;
		const int32 SettleTicks = FMath::RoundToInt(Settle / FVerseMovementTestWorld::Dt);
		const int32 MeasureTicks = FMath::RoundToInt(Measure / FVerseMovementTestWorld::Dt);
		FVector Start = FVector::ZeroVector;
		for (int32 Tick = 0; Tick < SettleTicks + MeasureTicks; ++Tick)
		{
			if (Tick == SettleTicks)
			{
				Start = Pawn.GetActorLocation();
			}
			W.Drive(Pawn, VerseTestFrame(Move, Buttons, Prev));
			Prev = Buttons;
			W.Tick();
		}
		return FVector::Dist2D(Pawn.GetActorLocation(), Start) / Measure / 100.f;
	}
}

// WP01.1: DA_MovementTuning loads from Data/movement/movement_tuning.json; the file holds the start values.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementTuningTest, "Verse.Movement.Tuning", BasicsTestFlags)
bool FVerseMovementTuningTest::RunTest(const FString& Parameters)
{
	const FString Path = UVerseMovementTuning::DefaultJsonPath();
	TestTrue(TEXT("movement_tuning.json exists"), FPaths::FileExists(Path));
	UVerseMovementTuning* Tuning = NewObject<UVerseMovementTuning>();
	FString Error;
	TestTrue(FString::Printf(TEXT("json loads (%s)"), *Error), Tuning->LoadFromJsonFile(Path, Error));
	const FVerseMovementTuningValues Defaults;
	for (TFieldIterator<FFloatProperty> It(FVerseMovementTuningValues::StaticStruct()); It; ++It)
	{
		TestEqual(FString::Printf(TEXT("json %s equals the start value"), *It->GetName()),
			It->GetPropertyValue_InContainer(&Tuning->Values), It->GetPropertyValue_InContainer(&Defaults), 1e-5f);
	}
	FVerseMovementTuningValues RoundTrip;
	TestTrue(TEXT("ToJson parses back"), UVerseMovementTuning::ParseJson(UVerseMovementTuning::ToJson(Defaults), RoundTrip, Error));
	TestEqual(TEXT("round trip keeps the walk speed"), RoundTrip.WalkSpeed, Defaults.WalkSpeed);
	TestFalse(TEXT("unknown field fails"), UVerseMovementTuning::ParseJson(TEXT("{\"WalkSped\": 4.5}"), RoundTrip, Error));
	TestFalse(TEXT("wrong case fails"), UVerseMovementTuning::ParseJson(TEXT("{\"walkspeed\": 4.5}"), RoundTrip, Error));
	TestFalse(TEXT("inverted speeds fail"), UVerseMovementTuning::ParseJson(TEXT("{\"WalkSpeed\": 7.0}"), RoundTrip, Error));
	TestFalse(TEXT("non-number fails"), UVerseMovementTuning::ParseJson(TEXT("{\"WalkSpeed\": \"fast\"}"), RoundTrip, Error));
	TestEqual(TEXT("start values: walk 4.5"), Defaults.WalkSpeed, 4.5f);
	TestEqual(TEXT("start values: sprint 6.5"), Defaults.SprintSpeed, 6.5f);
	TestEqual(TEXT("start values: crouch 2.2"), Defaults.CrouchSpeed, 2.2f);
	TestEqual(TEXT("start values: prone 0.9"), Defaults.ProneSpeed, 0.9f);
	TestEqual(TEXT("start values: slide cooldown 1.0"), Defaults.SlideCooldown, 1.0f);
	if (const UVerseMovementTuning* Asset = LoadObject<UVerseMovementTuning>(nullptr, TEXT("/Game/Verse/Movement/DA_MovementTuning.DA_MovementTuning"), nullptr, LOAD_NoWarn | LOAD_Quiet))
	{
		for (TFieldIterator<FFloatProperty> It(FVerseMovementTuningValues::StaticStruct()); It; ++It)
		{
			TestEqual(FString::Printf(TEXT("DA_MovementTuning %s matches the json"), *It->GetName()),
				It->GetPropertyValue_InContainer(&Asset->Values), It->GetPropertyValue_InContainer(&Tuning->Values), 1e-5f);
		}
	}
	else
	{
		AddError(TEXT("DA_MovementTuning asset is missing (/Game/Verse/Movement/DA_MovementTuning)"));
	}
	return true;
}

// WP01.1, WP01.3: IVerseMovementQuery on the movement component; sprint and mantle block firing.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementQueryTest, "Verse.Movement.Query", BasicsTestFlags)
bool FVerseMovementQueryTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	AVerseCharacter* Pawn = W.SpawnPawn(FVector(0.f, VerseMovementCourse::OpenFloorY, 0.f), 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	TestTrue(TEXT("movement implements IVerseMovementQuery"), M->GetClass()->ImplementsInterface(UVerseMovementQuery::StaticClass()));
	const IVerseMovementQuery* Query = Cast<IVerseMovementQuery>(M);
	TestNotNull(TEXT("query cast"), Query);
	TestEqual(TEXT("starts standing"), int32(Query->GetStance()), int32(EVerseStance::Stand));
	TestFalse(TEXT("idle does not block firing"), Query->BlocksFiring());
	const uint32 Sprint = uint32(EVerseInputButton::Sprint);
	SteadySpeed(W, *Pawn, Sprint, FVector2f(1.f, 0.f), 1.f, 0.2f);
	TestTrue(TEXT("sprinting"), Query->IsSprinting());
	TestTrue(TEXT("sprint blocks firing"), Query->BlocksFiring());
	SteadySpeed(W, *Pawn, Sprint, FVector2f(0.f, 1.f), 1.f, 0.2f);
	TestFalse(TEXT("sprint key while strafing is not a sprint"), Query->IsSprinting());
	SteadySpeed(W, *Pawn, uint32(EVerseInputButton::Crouch), FVector2f(1.f, 0.f), 0.5f, 0.2f);
	TestEqual(TEXT("crouch stance"), int32(Query->GetStance()), int32(EVerseStance::Crouch));
	TestFalse(TEXT("crouch does not block firing"), Query->BlocksFiring());
	// Jump: airborne flag.
	W.Place(*Pawn, FVector(0.f, VerseMovementCourse::OpenFloorY, 0.f), 0.f);
	W.TickSeconds(0.5f);
	W.Drive(*Pawn, VerseTestFrame(FVector2f::ZeroVector, uint32(EVerseInputButton::Jump), 0));
	W.Tick(6);
	TestTrue(TEXT("airborne after a jump"), Query->IsAirborne());
	W.Drive(*Pawn, VerseTestFrame(FVector2f::ZeroVector, 0, 0));
	W.TickSeconds(1.5f);
	// Mantle: blocks firing while it runs.
	W.Place(*Pawn, FVector(VerseMovementCourse::LedgeFaceX - 80.f, VerseMovementCourse::LedgeLaneY(1), 0.f), 0.f);
	W.TickSeconds(0.3f);
	bool bSawMantleBlock = false;
	uint32 Prev = 0;
	for (int32 Tick = 0; Tick < 60; ++Tick)
	{
		const uint32 Buttons = uint32(EVerseInputButton::Jump);
		W.Drive(*Pawn, VerseTestFrame(FVector2f(1.f, 0.f), Buttons, Prev));
		Prev = Buttons;
		W.Tick();
		bSawMantleBlock |= Query->IsMantling() && Query->BlocksFiring();
	}
	TestTrue(TEXT("mantle blocks firing"), bSawMantleBlock);
	TestEqual(TEXT("lean quantisation"), int32(IVerseMovementQuery::QuantizeLean(1.f)), 127);
	return true;
}

// A1.1: each stance's steady speed within 2 % of the DataAsset value on flat floor.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementSpeedsTest, "Verse.Movement.Speeds", BasicsTestFlags)
bool FVerseMovementSpeedsTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	struct FCase { const TCHAR* Name; uint32 Buttons; float Settle; };
	const FCase Cases[] = {
		{TEXT("walk"), 0u, 2.f},
		{TEXT("sprint"), uint32(EVerseInputButton::Sprint), 2.f},
		{TEXT("crouch"), uint32(EVerseInputButton::Crouch), 2.f},
		{TEXT("prone"), uint32(EVerseInputButton::Prone), 3.f},
	};
	const FVector Start(-2500.f, VerseMovementCourse::OpenFloorY, 0.f);
	AVerseCharacter* Pawn = W.SpawnPawn(Start, 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	const FVerseMovementTuningValues& T = Pawn->GetVerseMovement()->Tuning();
	const float Expected[] = {T.WalkSpeed, T.SprintSpeed, T.CrouchSpeed, T.ProneSpeed};
	for (int32 Index = 0; Index < UE_ARRAY_COUNT(Cases); ++Index)
	{
		W.Place(*Pawn, Start, 0.f);
		W.Drive(*Pawn, VerseTestFrame(FVector2f::ZeroVector, 0, 0));
		W.TickSeconds(1.f); // stand up again
		const float Speed = SteadySpeed(W, *Pawn, Cases[Index].Buttons, FVector2f(1.f, 0.f), Cases[Index].Settle, 1.f);
		const float Error = FMath::Abs(Speed - Expected[Index]) / Expected[Index];
		AddInfo(FString::Printf(TEXT("%s: %.3f m/s, DataAsset %.3f m/s, error %.2f %%"), Cases[Index].Name, Speed, Expected[Index], Error * 100.f));
		TestTrue(FString::Printf(TEXT("%s speed within 2 %%"), Cases[Index].Name), Error <= 0.02f);
	}
	return true;
}

// WP01.3: jump apex at the DataAsset height.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementJumpTest, "Verse.Movement.Jump", BasicsTestFlags)
bool FVerseMovementJumpTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	AVerseCharacter* Pawn = W.SpawnPawn(FVector(0.f, VerseMovementCourse::OpenFloorY, 0.f), 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	W.TickSeconds(0.5f);
	const float Floor = FVerseMovementTestWorld::Feet(*Pawn).Z;
	float Apex = Floor;
	W.Drive(*Pawn, VerseTestFrame(FVector2f::ZeroVector, uint32(EVerseInputButton::Jump), 0));
	W.Tick();
	W.Drive(*Pawn, VerseTestFrame(FVector2f::ZeroVector, 0, uint32(EVerseInputButton::Jump)));
	for (int32 Tick = 0; Tick < 90; ++Tick)
	{
		W.Tick();
		Apex = FMath::Max(Apex, FVerseMovementTestWorld::Feet(*Pawn).Z);
	}
	const float Height = (Apex - Floor) / 100.f;
	AddInfo(FString::Printf(TEXT("jump apex %.3f m"), Height));
	TestEqual(TEXT("jump apex 0.55 m within 3 cm"), Height, Pawn->GetVerseMovement()->Tuning().JumpApexHeight, 0.03f);
	TestFalse(TEXT("landed again"), Pawn->GetVerseMovement()->IsAirborne());
	return true;
}

namespace
{
	/** A seeded 60 s stream of frames exercising every movement button. */
	TArray<FVerseInputFrame> MakeParityFrames(uint64 Seed, int32 Count)
	{
		FVerseRng Rng(Seed, 0, EVerseRngSalt::Harness);
		TArray<FVerseInputFrame> Frames;
		Frames.Reserve(Count);
		uint32 Buttons = 0;
		uint32 Prev = 0;
		FVector2f Move(1.f, 0.f);
		float TurnRate = 0.f;
		int32 Next = 0;
		const uint32 Pool[] = {
			0u, uint32(EVerseInputButton::Sprint), uint32(EVerseInputButton::Crouch), uint32(EVerseInputButton::Prone),
			uint32(EVerseInputButton::LeanLeft), uint32(EVerseInputButton::LeanRight), uint32(EVerseInputButton::Jump),
			uint32(EVerseInputButton::Sprint) | uint32(EVerseInputButton::Crouch)};
		for (int32 Index = 0; Index < Count; ++Index)
		{
			if (Index >= Next)
			{
				Buttons = Pool[Rng.RangeInt(0, UE_ARRAY_COUNT(Pool) - 1)];
				Move = FVector2f(float(Rng.Range(-0.2, 1.0)), float(Rng.Range(-1.0, 1.0)));
				TurnRate = float(Rng.Range(-90.0, 90.0));
				Next = Index + Rng.RangeInt(20, 150);
			}
			Frames.Add(VerseTestFrame(Move, Buttons, Prev, FVector2f(float(Rng.Range(-0.5, 0.5)), TurnRate / 60.f)));
			Prev = Buttons;
		}
		return Frames;
	}

	TArray<FVector> RunParity(EVerseInputButton /*Unused*/, FVerseMovementTestWorld::EDriver Driver, const TArray<FVerseInputFrame>& Frames)
	{
		FVerseMovementTestWorld W;
		TArray<FVector> Path;
		if (!W.IsValid())
		{
			return Path;
		}
		AVerseCharacter* Pawn = W.SpawnPawn(FVector(-1500.f, 2400.f, 0.f), 0.f, Driver);
		if (!Pawn)
		{
			return Path;
		}
		Path.Reserve(Frames.Num());
		for (const FVerseInputFrame& Frame : Frames)
		{
			W.Drive(*Pawn, Frame);
			W.Tick();
			Path.Add(Pawn->GetActorLocation());
		}
		return Path;
	}
}

// A1.7: the same frame stream through the person path and the bot path gives the same capsule path.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementInputParityTest, "Verse.Movement.InputParity", BasicsTestFlags)
bool FVerseMovementInputParityTest::RunTest(const FString& Parameters)
{
	const TArray<FVerseInputFrame> Frames = MakeParityFrames(1701, 60 * 60);
	const TArray<FVector> Person = RunParity(EVerseInputButton::None, FVerseMovementTestWorld::EDriver::Person, Frames);
	const TArray<FVector> Bot = RunParity(EVerseInputButton::None, FVerseMovementTestWorld::EDriver::Bot, Frames);
	if (!TestEqual(TEXT("both paths ran 60 s"), Person.Num(), Frames.Num()) || !TestEqual(TEXT("bot path ran 60 s"), Bot.Num(), Frames.Num()))
	{
		return false;
	}
	double MaxError = 0.0;
	double Travel = 0.0;
	for (int32 Index = 0; Index < Person.Num(); ++Index)
	{
		MaxError = FMath::Max(MaxError, FVector::Dist(Person[Index], Bot[Index]));
		if (Index > 0)
		{
			Travel += FVector::Dist(Person[Index], Person[Index - 1]);
		}
	}
	AddInfo(FString::Printf(TEXT("max capsule distance %.4f cm over %.1f m travelled"), MaxError, Travel / 100.0));
	TestTrue(TEXT("the pawn really moved (over 50 m)"), Travel > 5000.0);
	TestTrue(TEXT("capsule paths within 0.1 cm"), MaxError <= 0.1);
	return true;
}

// A1.9: movement for 2 pawns costs at most 0.3 ms of game thread per tick.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementCostTest, "Verse.Movement.Cost", BasicsTestFlags)
bool FVerseMovementCostTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	AVerseCharacter* A = W.SpawnPawn(FVector(0.f, 1200.f, 0.f), 0.f);
	AVerseCharacter* B = W.SpawnPawn(FVector(0.f, 2000.f, 0.f), 0.f);
	if (!TestNotNull(TEXT("pawn a"), A) || !TestNotNull(TEXT("pawn b"), B)) return false;
	A->SetInputScript(VerseMovementScripts::MakeSoak(11, 30.f, A, FVector::ZeroVector));
	B->SetInputScript(VerseMovementScripts::MakeSoak(12, 30.f, B, FVector::ZeroVector));
	W.TickSeconds(2.f); // warm up
	const uint64 StartCycles = A->GetVerseMovement()->GetTickCycles() + B->GetVerseMovement()->GetTickCycles();
	const int32 StartTicks = A->GetVerseMovement()->GetTickCount();
	W.TickSeconds(20.f);
	const uint64 Cycles = A->GetVerseMovement()->GetTickCycles() + B->GetVerseMovement()->GetTickCycles() - StartCycles;
	const int32 Ticks = A->GetVerseMovement()->GetTickCount() - StartTicks;
	const double MsPerTick = FPlatformTime::ToMilliseconds64(Cycles) / FMath::Max(Ticks, 1);
	AddInfo(FString::Printf(TEXT("movement of 2 pawns: %.4f ms per tick over %d ticks; mantles %d + %d"), MsPerTick, Ticks,
		A->GetVerseMovement()->GetMantleCount(), B->GetVerseMovement()->GetMantleCount()));
	TestTrue(TEXT("at most 0.3 ms per tick"), MsPerTick <= 0.3);
	return true;
}

// WP01.10: flags and lean ride in the saved move, so a replay re-simulates the same inputs.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementSavedMoveTest, "Verse.Movement.SavedMove", BasicsTestFlags)
bool FVerseMovementSavedMoveTest::RunTest(const FString& Parameters)
{
	FVerseSavedMove Move;
	Move.bSavedWantsSprint = true;
	Move.bSavedWantsMantle = true;
	const uint8 Flags = Move.GetCompressedFlags();
	TestTrue(TEXT("sprint flag set"), (Flags & VerseMoveFlags::Sprint) != 0);
	TestFalse(TEXT("prone flag clear"), (Flags & VerseMoveFlags::Prone) != 0);
	TestTrue(TEXT("mantle flag set"), (Flags & VerseMoveFlags::Mantle) != 0);
	TestTrue(TEXT("flags avoid the stock bits"), (VerseMoveFlags::Sprint | VerseMoveFlags::Prone | VerseMoveFlags::Mantle)
		& (FSavedMove_Character::FLAG_JumpPressed | FSavedMove_Character::FLAG_WantsToCrouch) ? false : true);
	Move.Clear();
	TestEqual(TEXT("clear resets"), int32(Move.GetCompressedFlags() & VerseMoveFlags::Sprint), 0);

	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	AVerseCharacter* Pawn = W.SpawnPawn(FVector(0.f, VerseMovementCourse::OpenFloorY, 0.f), 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	M->UpdateFromCompressedFlags(VerseMoveFlags::Prone | FSavedMove_Character::FLAG_WantsToCrouch);
	TestTrue(TEXT("compressed crouch reaches the movement"), M->bWantsToCrouch);
	FVerseMovementNetStats Stats;
	Stats.Corrections[int32(EVerseMoveKind::Mantle)] = 2;
	Stats.Corrections[int32(EVerseMoveKind::Walk)] = 1;
	TestEqual(TEXT("stats total"), Stats.Total(), 3);
	TestTrue(TEXT("stats json names the kinds"), Stats.ToJson().Contains(TEXT("\"mantle\": 2")));
	return true;
}

// WP01.9: LV_Test_Movement exists with the course, player starts and the movement game mode.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementFixtureMapTest, "Verse.Movement.FixtureMap", BasicsTestFlags)
bool FVerseMovementFixtureMapTest::RunTest(const FString& Parameters)
{
	const TCHAR* MapPath = TEXT("/Game/Verse/Test/WP01/LV_Test_Movement");
	if (!TestTrue(TEXT("LV_Test_Movement package exists"), FPackageName::DoesPackageExist(MapPath)))
	{
		return false;
	}
	UWorld* Map = LoadObject<UWorld>(nullptr, TEXT("/Game/Verse/Test/WP01/LV_Test_Movement.LV_Test_Movement"));
	if (!TestNotNull(TEXT("map loads"), Map) || !Map->PersistentLevel)
	{
		return false;
	}
	int32 Courses = 0;
	int32 Starts = 0;
	for (AActor* Actor : Map->PersistentLevel->Actors)
	{
		Courses += Cast<AVerseMovementCourse>(Actor) ? 1 : 0;
		Starts += Cast<APlayerStart>(Actor) ? 1 : 0;
	}
	TestEqual(TEXT("one course actor"), Courses, 1);
	TestTrue(TEXT("at least two player starts"), Starts >= 2);
	const AWorldSettings* Settings = Map->PersistentLevel->GetWorldSettings();
	TestTrue(TEXT("movement game mode override"), Settings && Settings->DefaultGameMode == AVerseMovementTestGameMode::StaticClass());
	// The course table covers every fixture of WP01.9.
	TSet<FString> Names;
	for (const VerseMovementCourse::FBlock& Block : VerseMovementCourse::Blocks())
	{
		Names.Add(Block.Name);
	}
	for (const TCHAR* Needed : {TEXT("Ledge"), TEXT("TunnelRoof"), TEXT("Slope30"), TEXT("Slope46"), TEXT("Stair"), TEXT("DropPlatform"),
		TEXT("CornerWallLeft"), TEXT("CornerWallRight"), TEXT("BreachSill"), TEXT("BreachLintel")})
	{
		TestTrue(FString::Printf(TEXT("course has %s"), Needed), Names.Contains(Needed));
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
