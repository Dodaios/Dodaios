#include "Events/VerseEventHub.h"
#include "KillCam/VerseKillCam.h"
#include "Misc/AutomationTest.h"
#include "Tests/UI/Fakes/VerseUiFakes.h"

#if WITH_DEV_AUTOMATION_TESTS

namespace VerseUiKillCamTest
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	/** The server's log of the killer: a sprint on a curve, 60 Hz (architecture 3.2). */
	FVector ServerPath(double T)
	{
		const double Radius = 600.0;   // cm
		const double Speed = 650.0;    // cm/s, sprint
		const double A = Speed * T / Radius;
		return FVector(Radius * FMath::Cos(A), Radius * FMath::Sin(A), 90.0 + 15.0 * FMath::Sin(T * 3.0));
	}

	FRotator ServerAim(double T)
	{
		return FRotator(-5.0 + 3.0 * FMath::Sin(T), FMath::RadiansToDegrees(650.0 * T / 600.0) + 90.0, 0.0);
	}
}

using namespace VerseUiKillCamTest;

// A18.2: starts within 150 ms of FVerseDeathEvent, ends at least 200 ms before respawn; the
// replayed killer path is within 10 cm of the server log.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiKillCamTimingTest, "Verse.UI.KillCam.Timing", Flags)
bool FVerseUiKillCamTimingTest::RunTest(const FString&)
{
	FVerseUiTestWorld W;
	if (!TestNotNull(TEXT("UI subsystem in a game world"), W.Ui))
	{
		return false;
	}
	UVerseEventHub* Hub = UVerseEventHub::Get(W.World);
	if (!TestNotNull(TEXT("event hub"), Hub))
	{
		return false;
	}
	const int32 Person = 1;
	const int32 Killer = 2;
	W.Source->LocalId = Person;

	// Client frames at an uneven ~45 fps; each frame sees the replicated server pose of its time.
	FRandomStream Rng(7);
	double Server = 50.0;
	const double DeathAt = 56.0;
	while (Server < DeathAt)
	{
		W.Source->ServerTime = Server;
		W.Source->Poses = {{Killer, ServerPath(Server), ServerAim(Server)}, {Person, FVector(0, 0, 90), FRotator::ZeroRotator}};
		W.Ui->Tick(0.02f);
		const double Step = Rng.FRandRange(0.012, 0.034);
		Server += Step;
		W.Now += Step;
	}
	W.Source->ServerTime = DeathAt;
	W.Source->Poses = {{Killer, ServerPath(DeathAt), ServerAim(DeathAt)}};

	FVerseDeathEvent Death;
	Death.KillerId = Killer;
	Death.VictimId = Person;
	Death.WeaponId = TEXT("graveline");
	Death.ServerTime = DeathAt;
	Death.RespawnAt = DeathAt + 3.0;
	const double EventArrived = W.Now;
	Hub->OnDeath.Broadcast(Death);

	const FVerseKillCamPlayer& Cam = W.Ui->GetKillCam();
	TestTrue(TEXT("kill cam playing"), Cam.IsPlaying());
	TestTrue(TEXT("starts within 150 ms of the death event"), Cam.GetPlayStart() - EventArrived <= 0.150);
	const double RespawnLocal = EventArrived + (Death.RespawnAt - DeathAt);
	TestTrue(TEXT("planned end at least 200 ms before respawn"), RespawnLocal - Cam.GetPlannedEnd() >= 0.200);

	double WorstCm = 0.0;
	int32 Samples = 0;
	while (Cam.IsPlaying() && W.Now < RespawnLocal + 1.0)
	{
		const double Step = Rng.FRandRange(0.012, 0.034);
		W.Now += Step;
		W.Source->ServerTime += Step;
		W.Ui->Tick(float(Step));
		FVector Pose;
		FRotator Aim;
		if (Cam.GetKillerPose(Pose, Aim))
		{
			WorstCm = FMath::Max(WorstCm, FVector::Distance(Pose, ServerPath(Cam.GetReplayTime())));
			++Samples;
		}
	}
	AddInfo(FString::Printf(TEXT("replay %.3f s, %d frames, worst path error %.3f cm, ended %.3f s before respawn"),
		Cam.GetClipEnd() - Cam.GetClipStart(), Samples, WorstCm, RespawnLocal - Cam.GetEndedAt()));
	TestTrue(TEXT("replay ran for most of the 3 s respawn"), Cam.GetClipEnd() - Cam.GetClipStart() >= 2.5);
	TestEqual(TEXT("kill cam finished on its own"), Cam.GetState(), EVerseKillCamState::Finished);
	TestTrue(TEXT("ended at least 200 ms before respawn"), RespawnLocal - Cam.GetEndedAt() >= 0.200);
	TestTrue(TEXT("killer path within 10 cm of the server log"), WorstCm <= 10.0);
	TestTrue(TEXT("frames sampled"), Samples > 50);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiKillCamEventsTest, "Verse.UI.KillCam.Events", Flags)
bool FVerseUiKillCamEventsTest::RunTest(const FString&)
{
	FVerseKillCamBuffer Buffer;
	for (int32 I = 0; I <= 300; ++I)
	{
		const double T = 10.0 + I / 60.0;
		Buffer.AddPose(2, T, ServerPath(T), ServerAim(T));
	}
	for (int32 I = 0; I < 5; ++I)
	{
		FVerseFireEvent Fire;
		Fire.ShooterId = 2;
		Fire.ShotCounter = uint16(I);
		Buffer.AddFire(Fire, 13.0 + I * 0.3);
	}
	FVerseFractureEvent Break;
	Break.PieceIndex = 17;
	Buffer.AddFracture(Break, 14.2);
	FVerseFractureEvent Old;
	Old.PieceIndex = 3;
	Buffer.AddFracture(Old, 9.0);
	Buffer.Trim(15.0);
	TestEqual(TEXT("trim drops what is older than 4 s"), Buffer.GetFractures().Num(), 1);

	FVerseDeathEvent Death;
	Death.KillerId = 2;
	Death.VictimId = 1;
	Death.ServerTime = 15.0;
	Death.RespawnAt = 18.0;

	FVerseKillCamPlayer Player;
	TArray<uint16> Shots;
	TArray<uint16> Pieces;
	Player.OnReplayFire = [&Shots](const FVerseFireEvent& E) { Shots.Add(E.ShotCounter); };
	Player.OnReplayFracture = [&Pieces](const FVerseFractureEvent& E) { Pieces.Add(E.PieceIndex); };
	TestTrue(TEXT("begins"), Player.Begin(Buffer, Death, 1, 0.0, 15.0, false));
	for (double T = 0.0; T <= 3.0; T += 1.0 / 60.0)
	{
		Player.Tick(T);
	}
	TestEqual(TEXT("every shot in the window replays once, in order"), Shots, TArray<uint16>({0, 1, 2, 3, 4}));
	TestEqual(TEXT("the break in the window replays"), Pieces, TArray<uint16>({17}));

	FVector Cam;
	FRotator CamRot;
	TestTrue(TEXT("begins again"), Player.Begin(Buffer, Death, 1, 0.0, 15.0, false));
	Player.Tick(0.5);
	TestTrue(TEXT("camera available"), Player.GetCamera(Cam, CamRot));
	FVector Killer;
	FRotator Aim;
	Player.GetKillerPose(Killer, Aim);
	TestTrue(TEXT("third-person camera stands behind the killer"), FVector::Dist(Cam, Killer) > 150.f && FVector::Dist(Cam, Killer) < 400.f);
	Player.Skip(0.6);
	TestEqual(TEXT("skip"), Player.GetState(), EVerseKillCamState::Skipped);

	TestTrue(TEXT("finisher with reduced gore"), Player.Begin(Buffer, [&] { FVerseDeathEvent F = Death; F.Cause = EVerseDamageSource::Finisher; return F; }(), 1, 0.0, 15.0, true));
	TestTrue(TEXT("reduced gore cuts the finisher out of the replay"), Player.GetClipEnd() <= Death.ServerTime - 2.5 + 1e-6);

	FVerseDeathEvent Suicide = Death;
	Suicide.KillerId = 1;
	TestFalse(TEXT("no kill cam for a suicide"), Player.Begin(Buffer, Suicide, 1, 0.0, 15.0, false));
	FVerseDeathEvent WorldKill = Death;
	WorldKill.KillerId = -1;
	TestFalse(TEXT("no kill cam for a world kill"), Player.Begin(Buffer, WorldKill, 1, 0.0, 15.0, false));
	FVerseDeathEvent Late = Death;
	Late.RespawnAt = 15.5;
	TestFalse(TEXT("no kill cam when respawn is too close"), Player.Begin(Buffer, Late, 1, 0.0, 15.0, false));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
