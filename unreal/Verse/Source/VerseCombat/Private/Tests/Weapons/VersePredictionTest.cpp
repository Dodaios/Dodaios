#include "Misc/AutomationTest.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"
#include "VerseRng.h"
#include "Weapons/VerseFirePrediction.h"
#include "Weapons/VerseRecoil.h"
#include "Weapons/VerseSpread.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Combat.Prediction.FireReconcile (A2.6), in-process: the owner predicts with the same
// cadence, recoil, spread, magazine and predictor code the weapon component runs, talks to a server
// through a 60 ms one-way delay line, and the server validates with FVerseSpread::ValidateFire. The
// two-process replication run with PktLag belongs to the WP10 netcode runner (open in the PR).

namespace VersePredictionTest
{
	struct FFireMsg
	{
		double Arrive = 0.0;
		uint16 Counter = 0;
		uint32 Seed = 0;
		FVector Origin;
		FVector Dir;
		float ClientTime = 0.f;
	};

	struct FConfirmMsg
	{
		double Arrive = 0.0;
		uint16 Counter = 0;
		EVerseShotResult Result = EVerseShotResult::Miss;
	};

	FVector Quantize10(const FVector& V)
	{
		return FVector(FMath::RoundToDouble(V.X * 10.0) / 10.0, FMath::RoundToDouble(V.Y * 10.0) / 10.0, FMath::RoundToDouble(V.Z * 10.0) / 10.0);
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePredictionFireReconcile, "Verse.Combat.Prediction.FireReconcile", VERSE_WP02_TEST_FLAGS)
bool FVersePredictionFireReconcile::RunTest(const FString&)
{
	using namespace VersePredictionTest;
	const UVerseWeaponDefinition* W = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!W)
	{
		return false;
	}
	const double OneWay = 0.06;
	const double Rtt = 2.0 * OneWay;
	const uint32 ShooterId = 7;
	const uint32 MatchSeed = 4242;

	// Client side.
	FVerseFireCadence Cadence;
	FVerseRecoilState Recoil;
	FVerseSpread Spread;
	FVerseFirePredictor Predictor;
	FVerseWeaponSlotState ClientSlot;
	FVerseMagazine::InitFull(ClientSlot, *W);
	// Server side.
	FVerseWeaponSlotState ServerSlot = ClientSlot;
	float ServerLastClientTime = -1000.f;

	TArray<FFireMsg> ToServer;
	TArray<FConfirmMsg> ToClient;
	TMap<uint16, double> SentAt;
	TMap<uint16, FVector> ClientOrigin;
	double MaxOriginErr = 0.0;
	double MaxRejectLatency = 0.0;
	int32 Rejected = 0;
	int32 Accepted = 0;
	uint16 Counter = 0;
	FVerseRng Jitter(5);

	double Now = 50.0;
	const FVector Eye(0, 0, 160);
	// Replication of the owner-only slot state: snapshots taken after the server's tick, one way late.
	TArray<TPair<double, FVerseWeaponSlotState>> Snapshots;
	bool bReloadRequested = false;
	const int32 FiringTicks = 60 * 7;
	for (int32 Tick = 0; Tick < FiringTicks + 60 * 4; ++Tick)
	{
		const double Start = Now;
		Now += VerseWp02Test::Tick;

		// Client: replicated state lands; with nothing in flight the prediction takes it (the
		// weapon component's ResyncPredictedSlot).
		while (Snapshots.Num() > 0 && Snapshots[0].Key <= Now + 1e-9)
		{
			if (Predictor.NumPending() == 0)
			{
				ClientSlot = Snapshots[0].Value;
				bReloadRequested &= !FVerseMagazine::IsReloading(ClientSlot) && FVerseMagazine::RoundsReady(ClientSlot, *W) == 0;
			}
			Snapshots.RemoveAt(0);
		}

		// Client: fire while the trigger is held (1 s on, 0.5 s off); ask for a reload when dry.
		const bool bTrigger = Tick < FiringTicks && FMath::Fmod(Now, 1.5) < 1.0;
		if (Tick < FiringTicks && FVerseMagazine::RoundsReady(ClientSlot, *W) == 0 && !bReloadRequested)
		{
			bReloadRequested = true;
			FFireMsg Reload;
			Reload.Arrive = Now + OneWay;
			Reload.Counter = 0; // 0 = ServerReload
			ToServer.Add(Reload);
		}

		TArray<float> Times;
		const int32 Rounds = FVerseMagazine::IsReloading(ClientSlot) ? 0 : FVerseMagazine::RoundsReady(ClientSlot, *W);
		Cadence.Collect(*W, bTrigger, float(Start), float(Now), Rounds, Times);
		for (const float T : Times)
		{
			Recoil.BeginShot(*W, T);
			uint16 C = ++Counter;
			if (C == 0)
			{
				C = ++Counter; // 0 is the reload message here
			}
			const uint32 Seed = FVerseSpread::ShotSeed(ShooterId, C, MatchSeed);
			FVerseSpreadInput In;
			const float Sigma = Spread.SigmaFor(*W, In, T);
			const FVector Dir = FVerseSpread::ShotDirection(FVector(1, 0, 0), Sigma, Seed, Recoil.ShotIndex);
			const FVector Origin = Eye + FVector(0, float(Jitter.Range(-5.0, 5.0)), 0);
			// Every 7th shot is tampered with (origin 45 cm off): the server must reject it.
			const bool bTamper = (C % 7) == 0;
			const FVector Sent = bTamper ? Origin + FVector(45, 0, 0) : Origin;
			Recoil.OnShot(Recoil.KickFor(*W, 1.f, Seed), T);
			Spread.OnShot(*W, T);
			FVerseMagazine::ConsumeRound(ClientSlot, *W);
			FVersePredictedShot P;
			P.Counter = C;
			P.Time = T;
			P.Origin = Sent;
			P.Dir = Dir;
			Predictor.Add(P);
			ClientOrigin.Add(C, Sent);
			SentAt.Add(C, Now);
			FFireMsg M;
			M.Arrive = Now + OneWay;
			M.Counter = C;
			M.Seed = Seed;
			M.Origin = Quantize10(Sent);
			M.Dir = Dir;
			M.ClientTime = T;
			ToServer.Add(M);
		}

		// Server: arrivals in order, then its tick, then the replication snapshot.
		for (int32 I = 0; I < ToServer.Num();)
		{
			if (ToServer[I].Arrive > Now + 1e-9)
			{
				++I;
				continue;
			}
			const FFireMsg M = ToServer[I];
			ToServer.RemoveAt(I);
			if (M.Counter == 0)
			{
				FVerseMagazine::StartReload(ServerSlot, *W, float(Now));
				continue;
			}
			EVerseShotResult R = EVerseShotResult::Miss;
			const bool bCadence = M.ClientTime + 0.001f >= ServerLastClientTime + W->FireInterval();
			const bool bSeed = M.Seed == FVerseSpread::ShotSeed(ShooterId, M.Counter, MatchSeed);
			FVerseSpreadInput In;
			const float Sigma = FMath::Max(FVerseSpread::RestingSigma(*W, In, W->BloomMax), W->FirstShotSpread.X);
			const bool bValid = FVerseSpread::ValidateFire(M.Origin, M.Dir, Eye, FVector(1, 0, 0), Sigma);
			if (!bCadence || !bSeed || !bValid || !FVerseMagazine::ConsumeRound(ServerSlot, *W))
			{
				R = EVerseShotResult::Rejected;
				++Rejected;
			}
			else
			{
				ServerLastClientTime = M.ClientTime;
				++Accepted;
				MaxOriginErr = FMath::Max(MaxOriginErr, FVector::Dist(M.Origin, ClientOrigin[M.Counter]));
			}
			FConfirmMsg Back;
			Back.Arrive = Now + OneWay;
			Back.Counter = M.Counter;
			Back.Result = R;
			ToClient.Add(Back);
		}
		FVerseMagazine::Tick(ServerSlot, *W, float(Now));
		Snapshots.Add({Now + OneWay, ServerSlot});

		// Client: confirmations.
		for (int32 I = 0; I < ToClient.Num();)
		{
			if (ToClient[I].Arrive > Now + 1e-9)
			{
				++I;
				continue;
			}
			const FConfirmMsg M = ToClient[I];
			ToClient.RemoveAt(I);
			const FVerseShotReconcile Rec = Predictor.Confirm(M.Counter, M.Result);
			TestTrue(TEXT("confirmation matches a pending shot"), Rec.bKnown);
			if (Rec.bRemoveBolt)
			{
				MaxRejectLatency = FMath::Max(MaxRejectLatency, Now - SentAt[M.Counter]);
			}
			for (int32 R = 0; R < Rec.RefundRounds; ++R)
			{
				FVerseMagazine::RefundRound(ClientSlot, *W);
			}
		}

	}

	TestTrue(TEXT("some shots accepted"), Accepted > 100);
	TestTrue(TEXT("tampered shots rejected"), Rejected > 10);
	TestTrue(FString::Printf(TEXT("predicted origin within 1 cm of the server's (%.3f cm)"), MaxOriginErr), MaxOriginErr <= 1.0);
	TestTrue(FString::Printf(TEXT("rejected bolt gone within one round trip + 1 tick (%.4f s)"), MaxRejectLatency),
		MaxRejectLatency <= Rtt + VerseWp02Test::Tick + 1e-6);
	TestEqual(TEXT("everything answered"), Predictor.NumPending(), 0);
	TestEqual(TEXT("ammo never diverges after reconcile (end)"), FVerseMagazine::RoundsReady(ClientSlot, *W), FVerseMagazine::RoundsReady(ServerSlot, *W));

	TSharedRef<FJsonObject> Proof = MakeShared<FJsonObject>();
	Proof->SetNumberField(TEXT("one_way_ms"), OneWay * 1000.0);
	Proof->SetNumberField(TEXT("accepted"), Accepted);
	Proof->SetNumberField(TEXT("rejected"), Rejected);
	Proof->SetNumberField(TEXT("max_origin_error_cm"), MaxOriginErr);
	Proof->SetNumberField(TEXT("max_reject_removal_s"), MaxRejectLatency);
	Proof->SetNumberField(TEXT("rtt_plus_tick_s"), Rtt + VerseWp02Test::Tick);
	VerseWp02Test::WriteProof(TEXT("2.6"), TEXT("netcode_report.json"), Proof);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
