#include "Misc/AutomationTest.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"
#include "VerseRng.h"
#include "Weapons/VerseRecoil.h"
#include "Weapons/VerseSpread.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Combat.Recoil.*: the recoil invariants R1-R6 of combat-state.md 4.3 for every weapon asset
// (A2.1), plus the compensation and recovery rules of 4.2. R5 here is the in-process half; the
// lagged two-process run belongs to the WP10 netcode runner.

namespace VerseRecoilTest
{
	const EVerseStance Stances[] = {EVerseStance::Stand, EVerseStance::Crouch, EVerseStance::Prone, EVerseStance::Slide};

	/** Rounds a full magazine holds when fired from spawn (magazine plus the chambered round). */
	int32 SprayLength(const UVerseWeaponDefinition& W)
	{
		return FMath::Max(1, W.MagazineSize);
	}

	struct FSpray
	{
		TArray<FVector2f> Kicks;
		TArray<float> AccPitch;
		TArray<float> AccYaw;
		float SumKickPitch = 0.f;
	};

	/** Full-magazine spray at max RPM, 60 Hz ticks, no look input; the same path the weapon component runs. */
	FSpray Spray(const UVerseWeaponDefinition& W, uint32 BaseSeed, EVerseStance Stance, float Ads)
	{
		FSpray Out;
		FVerseRecoilState R;
		FVerseFireCadence Cadence;
		const float Mul = FVerseRecoilState::Multiplier(W, Stance, Ads);
		const int32 Shots = SprayLength(W);
		float Now = 10.f;
		int32 Fired = 0;
		for (int32 Tick = 0; Fired < Shots && Tick < 100000; ++Tick)
		{
			const float Start = Now;
			Now += VerseWp02Test::Tick;
			TArray<float> Times;
			// Max RPM: semi weapons get a fresh press on every tick, so each shot goes the moment
			// the cadence allows it.
			Cadence.bTriggerWasDown = false;
			Cadence.Collect(W, true, Start, Now, Shots - Fired, Times);
			for (const float T : Times)
			{
				R.TickKick(W, T);
				R.BeginShot(W, T);
				const uint32 Seed = FVerseSpread::ShotSeed(BaseSeed, uint16(Fired + 1), 7u);
				const FVector2f K = R.KickFor(W, Mul, Seed);
				R.OnShot(K, T);
				Out.Kicks.Add(K);
				Out.SumKickPitch += K.X;
				Out.AccPitch.Add(R.Accumulated.X);
				Out.AccYaw.Add(R.Accumulated.Y);
				++Fired;
			}
			R.TickKick(W, Now);
			R.TickRecovery(W, Now, VerseWp02Test::Tick);
			if (Out.AccPitch.Num() > 0)
			{
				Out.AccPitch.Last() = R.Accumulated.X; // A after this tick's recovery
				Out.AccYaw.Last() = R.Accumulated.Y;
			}
		}
		return Out;
	}

	float MinKickBound(const UVerseWeaponDefinition& W)
	{
		const float MMin = FVerseRecoilState::MinMultiplier(W);
		float Min = TNumericLimits<float>::Max();
		for (int32 N = 0; N <= SprayLength(W); ++N)
		{
			Min = FMath::Min(Min, MMin * W.PatternAt(N).Size() * (1.f - W.RecoilRandomFraction));
		}
		return Min;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseRecoilRecoveryBelowKick, "Verse.Combat.Recoil.RecoveryBelowKick", VERSE_WP02_TEST_FLAGS)
bool FVerseRecoilRecoveryBelowKick::RunTest(const FString&)
{
	const TArray<const UVerseWeaponDefinition*> Weapons = VerseWp02Test::AllWeapons(*this);
	TestTrue(TEXT("at least the four weapons load"), Weapons.Num() >= 4);

	TSharedRef<FJsonObject> Proof = MakeShared<FJsonObject>();
	for (const UVerseWeaponDefinition* W : Weapons)
	{
		const FString Id = W->WeaponId.ToString();
		TestTrue(FString::Printf(TEXT("%s: R1 inequality"), *Id),
			W->SatisfiesRecoveryBelowKick(FVerseRecoilState::MinMultiplier(*W), VerseRecoilTest::SprayLength(*W)));

		for (const EVerseStance Stance : VerseRecoilTest::Stances)
		{
			for (const float Ads : {0.f, 1.f})
			{
				const VerseRecoilTest::FSpray S = VerseRecoilTest::Spray(*W, 1234u, Stance, Ads);
				TestEqual(FString::Printf(TEXT("%s: full magazine fired"), *Id), S.Kicks.Num(), VerseRecoilTest::SprayLength(*W));
				for (int32 I = 1; I < S.AccPitch.Num(); ++I)
				{
					if (S.AccPitch[I] <= S.AccPitch[I - 1])
					{
						AddError(FString::Printf(TEXT("%s stance %d ads %.0f: A_p did not rise at shot %d (%.4f -> %.4f)"), *Id, int32(Stance),
							Ads, I, S.AccPitch[I - 1], S.AccPitch[I]));
						break;
					}
				}
				if (S.AccPitch.Num() > 0 && S.AccPitch.Last() < 0.5f * S.SumKickPitch)
				{
					AddError(FString::Printf(TEXT("%s: A_p %.3f below half the summed kick %.3f"), *Id, S.AccPitch.Last(), S.SumKickPitch));
				}
			}
		}

		// Evidence: pitch and yaw per shot, ten seeds, standing hip fire (section 0.4).
		TArray<TSharedPtr<FJsonValue>> Seeds;
		for (uint32 Seed = 1; Seed <= 10; ++Seed)
		{
			const VerseRecoilTest::FSpray S = VerseRecoilTest::Spray(*W, Seed, EVerseStance::Stand, 0.f);
			TArray<TSharedPtr<FJsonValue>> Pitch, Yaw, KickPitch, KickYaw;
			for (int32 I = 0; I < S.Kicks.Num(); ++I)
			{
				Pitch.Add(MakeShared<FJsonValueNumber>(S.AccPitch[I]));
				Yaw.Add(MakeShared<FJsonValueNumber>(S.AccYaw[I]));
				KickPitch.Add(MakeShared<FJsonValueNumber>(S.Kicks[I].X));
				KickYaw.Add(MakeShared<FJsonValueNumber>(S.Kicks[I].Y));
			}
			TSharedRef<FJsonObject> One = MakeShared<FJsonObject>();
			One->SetNumberField(TEXT("seed"), Seed);
			One->SetArrayField(TEXT("acc_pitch_deg"), Pitch);
			One->SetArrayField(TEXT("acc_yaw_deg"), Yaw);
			One->SetArrayField(TEXT("kick_pitch_deg"), KickPitch);
			One->SetArrayField(TEXT("kick_yaw_deg"), KickYaw);
			Seeds.Add(MakeShared<FJsonValueObject>(One));
		}
		Proof->SetArrayField(Id, Seeds);
	}
	VerseWp02Test::WriteProof(TEXT("2.4"), TEXT("recoil_spray.json"), Proof);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseRecoilKickRate, "Verse.Combat.Recoil.KickRate", VERSE_WP02_TEST_FLAGS)
bool FVerseRecoilKickRate::RunTest(const FString&)
{
	for (const UVerseWeaponDefinition* W : VerseWp02Test::AllWeapons(*this))
	{
		const float Rate = VerseRecoilTest::MinKickBound(*W) / FMath::Max(W->RecoilKickTime, UE_SMALL_NUMBER);
		TestTrue(FString::Printf(TEXT("%s: R2 min|k|/t_k %.2f >= 10 rho %.2f"), *W->WeaponId.ToString(), Rate, 10.f * W->RecoilRecoveryRate),
			Rate >= 10.f * W->RecoilRecoveryRate);

		// The eased kick is fully applied after t_k and never overshoots.
		FVerseRecoilState R;
		R.OnShot(FVector2f(1.f, 0.5f), 0.f);
		FVector2f Applied = FVector2f::ZeroVector;
		for (float T = 0.f; T <= W->RecoilKickTime + 0.05f; T += 0.002f)
		{
			Applied += R.TickKick(*W, T);
		}
		TestTrue(TEXT("kick applied in full"), Applied.Equals(FVector2f(1.f, 0.5f), 1e-4f));
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseRecoilRandomBound, "Verse.Combat.Recoil.RandomBound", VERSE_WP02_TEST_FLAGS)
bool FVerseRecoilRandomBound::RunTest(const FString&)
{
	for (const UVerseWeaponDefinition* W : VerseWp02Test::AllWeapons(*this))
	{
		int32 Violations = 0;
		for (uint32 Spray = 0; Spray < 10000; ++Spray)
		{
			for (int32 N = 0; N < VerseRecoilTest::SprayLength(*W); ++N)
			{
				const EVerseStance Stance = VerseRecoilTest::Stances[(Spray + N) % 4];
				const float Ads = float((Spray >> 2) & 1);
				const float M = FVerseRecoilState::Multiplier(*W, Stance, Ads);
				const uint32 Seed = FVerseSpread::ShotSeed(Spray, uint16(N + 1), 99u);
				const FVector2f K = FVerseRecoilState::KickAt(*W, N, M, Seed);
				const FVector2f P = W->PatternAt(N);
				if ((K - M * P).Size() > W->RecoilRandomFraction * M * P.Size() + 1e-4f)
				{
					++Violations;
				}
			}
		}
		TestEqual(FString::Printf(TEXT("%s: R3 violations over 10,000 sprays"), *W->WeaponId.ToString()), Violations, 0);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseRecoilPatternMean, "Verse.Combat.Recoil.PatternMean", VERSE_WP02_TEST_FLAGS)
bool FVerseRecoilPatternMean::RunTest(const FString&)
{
	for (const UVerseWeaponDefinition* W : VerseWp02Test::AllWeapons(*this))
	{
		const float M = FVerseRecoilState::Multiplier(*W, EVerseStance::Stand, 0.f);
		for (int32 N = 0; N < VerseRecoilTest::SprayLength(*W); ++N)
		{
			FVector2D Sum = FVector2D::ZeroVector;
			for (uint32 S = 0; S < 10000; ++S)
			{
				const FVector2f K = FVerseRecoilState::KickAt(*W, N, M, FVerseSpread::ShotSeed(S, uint16(N + 1), 3u));
				Sum += FVector2D(K.X, K.Y);
			}
			const FVector2D Mean = Sum / 10000.0;
			const FVector2f Want = M * W->PatternAt(N);
			const double Err = (Mean - FVector2D(Want.X, Want.Y)).Size();
			if (Err > 0.01 * Want.Size())
			{
				AddError(FString::Printf(TEXT("%s shot %d: mean off by %.5f deg (%.2f %%)"), *W->WeaponId.ToString(), N, Err, 100.0 * Err / Want.Size()));
			}
		}
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseRecoilDeterminism, "Verse.Combat.Recoil.Determinism", VERSE_WP02_TEST_FLAGS)
bool FVerseRecoilDeterminism::RunTest(const FString&)
{
	// Two independent states fed the same seed, stance, ADS and look input end identical (the
	// server path itself is R5, Verse.Combat.Recoil.ClientServerMatch in VerseServerFireTest.cpp).
	for (const UVerseWeaponDefinition* W : VerseWp02Test::AllWeapons(*this))
	{
		FVerseRecoilState Server, Client;
		FVerseRng Look(77);
		float Now = 5.f;
		for (int32 Shot = 0; Shot < 200; ++Shot)
		{
			Now += W->FireInterval() * (1.f + float(Look.Range(0.0, 3.0)));
			const EVerseStance Stance = VerseRecoilTest::Stances[Shot % 4];
			const float Ads = float(Look.Range(0.0, 1.0));
			const float M = FVerseRecoilState::Multiplier(*W, Stance, Ads);
			const uint32 Seed = FVerseSpread::ShotSeed(42u, uint16(Shot), 11u);
			Server.BeginShot(*W, Now);
			Client.BeginShot(*W, Now);
			const FVector2f Ks = Server.KickFor(*W, M, Seed);
			const FVector2f Kc = Client.KickFor(*W, M, Seed);
			if (!Ks.Equals(Kc, 1e-4f))
			{
				AddError(FString::Printf(TEXT("%s shot %d: k differs"), *W->WeaponId.ToString(), Shot));
				break;
			}
			Server.OnShot(Ks, Now);
			Client.OnShot(Kc, Now);
			FVector2f In(float(Look.Range(-0.3, 0.1)), float(Look.Range(-0.1, 0.1)));
			FVector2f In2 = In;
			Server.OnLookInput(In);
			Client.OnLookInput(In2);
			Server.TickRecovery(*W, Now + 0.2f, 0.016f);
			Client.TickRecovery(*W, Now + 0.2f, 0.016f);
		}
		TestTrue(TEXT("accumulators match"), Server.Accumulated.Equals(Client.Accumulated, 1e-4f));
		TestEqual(TEXT("shot index matches"), Server.ShotIndex, Client.ShotIndex);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseRecoilCompensation, "Verse.Combat.Recoil.Compensation", VERSE_WP02_TEST_FLAGS)
bool FVerseRecoilCompensation::RunTest(const FString&)
{
	const UVerseWeaponDefinition* W = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!W)
	{
		return false;
	}
	FVerseRecoilState R;
	R.OnShot(FVector2f(2.f, 0.5f), 0.f);
	FVector2f Down(-0.5f, 0.f);
	R.OnLookInput(Down);
	TestEqual(TEXT("pull-down compensates pitch"), R.Accumulated.X, 1.5f, 1e-5f);
	TestEqual(TEXT("look input passes through"), Down.X, -0.5f);
	FVector2f Big(-10.f, -2.f);
	R.OnLookInput(Big);
	TestEqual(TEXT("never below zero"), R.Accumulated.X, 0.f);
	TestEqual(TEXT("yaw against its sign compensates to zero"), R.Accumulated.Y, 0.f);
	FVector2f Up(1.f, 1.f);
	R.OnLookInput(Up);
	TestEqual(TEXT("upward input adds nothing"), R.Accumulated.X, 0.f);

	// Recovery waits d_r, runs at rho and only returns what the weapon added.
	FVerseRecoilState Q;
	Q.OnShot(FVector2f(1.f, 0.f), 0.f);
	TestTrue(TEXT("no recovery before d_r"), Q.TickRecovery(*W, W->RecoilRecoveryDelay * 0.5f, 0.1f).IsNearlyZero());
	const FVector2f Step = Q.TickRecovery(*W, W->RecoilRecoveryDelay + 0.01f, 0.1f);
	TestEqual(TEXT("recovery step = rho dt"), Step.X, FMath::Min(1.f, W->RecoilRecoveryRate * 0.1f), 1e-5f);
	float Total = Step.X;
	for (int32 I = 0; I < 10000 && !Q.Accumulated.IsNearlyZero(); ++I)
	{
		Total += Q.TickRecovery(*W, 10.f, 0.1f).X;
	}
	TestEqual(TEXT("recovery returns exactly the kick"), Total, 1.f, 1e-4f);

	// Pattern resets after PatternResetTime.
	FVerseRecoilState P;
	P.OnShot(FVector2f(1.f, 0.f), 0.f);
	P.OnShot(FVector2f(1.f, 0.f), 0.05f);
	TestEqual(TEXT("index climbs inside a spray"), P.ShotIndexAt(*W, 0.06f), 2);
	TestEqual(TEXT("index resets after the pause"), P.ShotIndexAt(*W, 0.05f + W->PatternResetTime), 0);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
