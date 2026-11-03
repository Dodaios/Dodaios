#include "Misc/AutomationTest.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"
#include "Weapons/VerseRecoil.h"
#include "Weapons/VerseSpread.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Combat.Spread.*: first-shot accuracy (R6), bloom, seeded directions and the server's fire
// validation (combat-state.md 4.4). Verse.Combat.FireRate: the cadence (A2.3).

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseSpreadFirstShot, "Verse.Combat.Spread.FirstShot", VERSE_WP02_TEST_FLAGS)
bool FVerseSpreadFirstShot::RunTest(const FString&)
{
	for (const UVerseWeaponDefinition* W : VerseWp02Test::AllWeapons(*this))
	{
		const FString Id = W->WeaponId.ToString();
		TestTrue(FString::Printf(TEXT("%s: pattern resets no later than first-shot rest"), *Id), W->PatternResetTime <= W->FirstShotRestTime);
		for (const float Ads : {0.f, 1.f})
		{
			FVerseSpread S;
			FVerseRecoilState R;
			FVerseSpreadInput In;
			In.AdsBlend = Ads;
			// A spray, then a rest of exactly FirstShotRestTime.
			float Now = 1.f;
			for (int32 I = 0; I < 6; ++I)
			{
				R.BeginShot(*W, Now);
				R.OnShot(FVector2f(0.5f, 0.f), Now);
				S.OnShot(*W, Now);
				Now += W->FireInterval();
			}
			Now = S.LastShotTime + W->FirstShotRestTime + 1e-4f; // just past the rest (float-safe)
			S.DecayTo(*W, Now, W->FirstShotRestTime);
			R.BeginShot(*W, Now);
			TestEqual(FString::Printf(TEXT("%s ads %.0f: first shot n = 0"), *Id, Ads), R.ShotIndex, 0);
			const float Want = FMath::Lerp(W->FirstShotSpread.X, W->FirstShotSpread.Y, Ads);
			TestEqual(FString::Printf(TEXT("%s ads %.0f: first shot sigma"), *Id, Ads), S.SigmaFor(*W, In, Now), Want, 1e-6f);
			S.OnShot(*W, Now);
			TestEqual(TEXT("first shot resets bloom, then one bloom step"), S.Bloom, FMath::Min(W->BloomMax, W->BloomPerShot), 1e-6f);

			// The next shot inside the spray uses base spread plus bloom.
			const float Next = Now + W->FireInterval();
			const FVector2f* Base = W->SpreadBase.Find(EVerseStance::Stand);
			const float WantNext = (Base ? FMath::Lerp(Base->X, Base->Y, Ads) : 0.f) + S.Bloom;
			TestEqual(TEXT("follow-up sigma = base + bloom"), S.SigmaFor(*W, In, Next), WantNext, 1e-5f);
		}
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseSpreadBloomAndInputs, "Verse.Combat.Spread.BloomAndInputs", VERSE_WP02_TEST_FLAGS)
bool FVerseSpreadBloomAndInputs::RunTest(const FString&)
{
	const UVerseWeaponDefinition* W = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!W)
	{
		return false;
	}
	FVerseSpread S;
	for (int32 I = 0; I < 100; ++I)
	{
		S.OnShot(*W, 1.f + I * W->FireInterval());
	}
	TestEqual(TEXT("bloom capped at BloomMax"), S.Bloom, W->BloomMax, 1e-6f);
	const float Last = S.LastShotTime;
	S.DecayTo(*W, Last + W->BloomRecoveryDelay * 0.5f, 0.1f);
	TestEqual(TEXT("no decay before the delay"), S.Bloom, W->BloomMax, 1e-6f);
	S.DecayTo(*W, Last + W->BloomRecoveryDelay, 0.1f);
	TestEqual(TEXT("decay at the rate"), S.Bloom, FMath::Max(0.f, W->BloomMax - W->BloomRecoveryRate * 0.1f), 1e-5f);

	FVerseSpreadInput In;
	In.HorizontalSpeedMps = 4.f;
	In.bAirborne = true;
	const FVector2f* Base = W->SpreadBase.Find(EVerseStance::Stand);
	TestEqual(TEXT("movement and airborne add"), FVerseSpread::RestingSigma(*W, In, 0.f),
		Base->X + 4.f * W->SpreadMovePerMps + W->SpreadAirborne, 1e-5f);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseSpreadSeedAndValidation, "Verse.Combat.Spread.SeedAndValidation", VERSE_WP02_TEST_FLAGS)
bool FVerseSpreadSeedAndValidation::RunTest(const FString&)
{
	// Same inputs, same direction (client and server derive it independently).
	const uint32 Seed = FVerseSpread::ShotSeed(17u, 300u, 9001u);
	TestEqual(TEXT("seed is a pure function"), Seed, FVerseSpread::ShotSeed(17u, 300u, 9001u));
	TestNotEqual(TEXT("seed depends on the counter"), Seed, FVerseSpread::ShotSeed(17u, 301u, 9001u));
	const FVector Fwd(1, 0, 0);
	TestTrue(TEXT("direction is a pure function"),
		FVerseSpread::ShotDirection(Fwd, 2.f, Seed, 3).Equals(FVerseSpread::ShotDirection(Fwd, 2.f, Seed, 3), 1e-12));

	int32 Outside = 0;
	for (uint32 I = 0; I < 10000; ++I)
	{
		const FVector D = FVerseSpread::ShotDirection(Fwd, 1.5f, FVerseSpread::ShotSeed(I, 1, 2), int32(I % 30));
		const double Angle = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(FVector::DotProduct(D, Fwd), -1.0, 1.0)));
		Outside += Angle > 1.5 + 1e-6 ? 1 : 0;
	}
	TestEqual(TEXT("every direction inside the cone"), Outside, 0);
	TestTrue(TEXT("sigma 0 shoots straight"), FVerseSpread::ShotDirection(Fwd, 0.f, Seed, 0).Equals(Fwd, 1e-9));

	const FVector Eye(0, 0, 160);
	TestTrue(TEXT("origin 29 cm off passes"), FVerseSpread::ValidateFire(Eye + FVector(29, 0, 0), Fwd, Eye, Fwd, 1.f));
	TestFalse(TEXT("origin 31 cm off is rejected"), FVerseSpread::ValidateFire(Eye + FVector(31, 0, 0), Fwd, Eye, Fwd, 1.f));
	const FVector Off2 = FRotator(0, 2.4, 0).Vector();
	const FVector Off3 = FRotator(0, 2.6, 0).Vector();
	TestTrue(TEXT("sigma + 1.5 - 0.1 deg passes"), FVerseSpread::ValidateFire(Eye, Off2, Eye, Fwd, 1.f));
	TestFalse(TEXT("sigma + 1.5 + 0.1 deg is rejected"), FVerseSpread::ValidateFire(Eye, Off3, Eye, Fwd, 1.f));
	TestFalse(TEXT("zero direction is rejected"), FVerseSpread::ValidateFire(Eye, FVector::ZeroVector, Eye, Fwd, 1.f));
	return true;
}

namespace VerseFireRateTest
{
	/** Shot times of a full magazine at 60 Hz with the trigger pattern of the fire mode. */
	TArray<float> FireMagazine(const UVerseWeaponDefinition& W, bool bTapEveryTick)
	{
		FVerseFireCadence Cadence;
		TArray<float> Times;
		float Now = 3.f;
		bool bDown = true;
		for (int32 Tick = 0; Times.Num() < W.MagazineSize && Tick < 100000; ++Tick)
		{
			const float Start = Now;
			Now += VerseWp02Test::Tick;
			const bool bTrigger = bTapEveryTick ? bDown : true;
			bDown = !bDown;
			Cadence.Collect(W, bTrigger, Start, Now, W.MagazineSize - Times.Num(), Times);
		}
		return Times;
	}

	double MeasuredRpm(const TArray<float>& Times)
	{
		return Times.Num() > 1 ? 60.0 * double(Times.Num() - 1) / double(Times.Last() - Times[0]) : 0.0;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseFireRate, "Verse.Combat.FireRate", VERSE_WP02_TEST_FLAGS)
bool FVerseFireRate::RunTest(const FString&)
{
	const UVerseWeaponDefinition* Graveline = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	const UVerseWeaponDefinition* Tallow = VerseWp02Test::Weapon(*this, TEXT("tallow"));
	if (!Graveline || !Tallow)
	{
		return false;
	}
	const TArray<float> G = VerseFireRateTest::FireMagazine(*Graveline, false);
	TestEqual(TEXT("Graveline fires the full magazine"), G.Num(), Graveline->MagazineSize);
	const double GRpm = VerseFireRateTest::MeasuredRpm(G);
	TestTrue(FString::Printf(TEXT("Graveline %.2f RPM within 1 %% of 690"), GRpm), FMath::Abs(GRpm - 690.0) <= 6.9);

	// Spam the pistol trigger as fast as ticks allow: never above its cap.
	const TArray<float> T = VerseFireRateTest::FireMagazine(*Tallow, true);
	const double TRpm = VerseFireRateTest::MeasuredRpm(T);
	TestTrue(FString::Printf(TEXT("Tallow %.2f RPM never above 380"), TRpm), TRpm <= 380.0 + 1e-3);
	for (int32 I = 1; I < T.Num(); ++I)
	{
		if (T[I] - T[I - 1] < Tallow->FireInterval() - 1e-5f)
		{
			AddError(FString::Printf(TEXT("Tallow shots %d and %d closer than the interval"), I - 1, I));
		}
	}

	// Semi needs a fresh press; holding fires once.
	FVerseFireCadence Hold;
	TArray<float> Held;
	float Now = 0.f;
	for (int32 I = 0; I < 120; ++I)
	{
		Hold.Collect(*Tallow, true, Now, Now + VerseWp02Test::Tick, 15, Held);
		Now += VerseWp02Test::Tick;
	}
	TestEqual(TEXT("held semi trigger fires once"), Held.Num(), 1);

	// Every weapon: auto and semi never beat their RPM.
	for (const UVerseWeaponDefinition* W : VerseWp02Test::AllWeapons(*this))
	{
		const TArray<float> S = VerseFireRateTest::FireMagazine(*W, W->FireMode != EVerseFireMode::Auto);
		TestTrue(FString::Printf(TEXT("%s at or under its RPM"), *W->WeaponId.ToString()), VerseFireRateTest::MeasuredRpm(S) <= W->RPM * 1.0001);
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
