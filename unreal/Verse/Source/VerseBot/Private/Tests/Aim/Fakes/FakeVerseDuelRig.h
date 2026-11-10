#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "Aim/VerseBotAimSystem.h"
#include "Bot/VersePerceptTypes.h"
#include "Combat/VerseCombatTypes.h"
#include "Combat/VerseWeaponDefinition.h"
#include "CoreMinimal.h"
#include "UObject/StrongObjectPtr.h"
#include "VerseRng.h"

/**
 * Fakes for WP09's own tests (work-packages 0.3): WP02's weapon asset and recoil (combat-state.md
 * 4.1, 4.2), WP07's sight percepts (scripted) and WP01's pawn (a point that applies the look delta).
 * Compiled only WITH_DEV_AUTOMATION_TESTS.
 */
namespace VerseBotFakes
{
	/** The assault rifle start values of combat-state.md 3.1 as an in-memory weapon definition. */
	inline UVerseWeaponDefinition* MakeRifle()
	{
		UVerseWeaponDefinition* W = NewObject<UVerseWeaponDefinition>(GetTransientPackage(), NAME_None, RF_Transient);
		W->FireMode = EVerseFireMode::Auto;
		W->RPM = 690.f;
		W->MagazineSize = 30;
		W->ProjectileSpeed = 880.f;
		W->RecoilRandomFraction = 0.15f;
		W->RecoilKickTime = 0.035f;
		W->RecoilRecoveryRate = 5.f;
		W->RecoilRecoveryDelay = 0.12f;
		W->PatternResetTime = 0.35f;
		W->RecoilAdsMultiplier = 0.8f;
		W->FirstShotRestTime = 0.3f;
		FRichCurve& Pitch = *W->RecoilPitchCurve.GetRichCurve();
		FRichCurve& Yaw = *W->RecoilYawCurve.GetRichCurve();
		// Pitch 0.45 deg rising to 0.62 by shot 8, then hold; yaw drifting right to shot 10, then left.
		Pitch.AddKey(0.f, 0.45f);
		Pitch.AddKey(8.f, 0.62f);
		Yaw.AddKey(0.f, 0.10f);
		Yaw.AddKey(10.f, 0.10f);
		Yaw.AddKey(11.f, -0.15f);
		for (FRichCurveKey& Key : Pitch.Keys) Key.InterpMode = RCIM_Linear;
		for (FRichCurveKey& Key : Yaw.Keys) Key.InterpMode = RCIM_Linear;
		W->RecoilStanceMultiplier.Add(EVerseStance::Stand, 1.f);
		W->RecoilStanceMultiplier.Add(EVerseStance::Crouch, 0.8f);
		W->RecoilStanceMultiplier.Add(EVerseStance::Prone, 0.6f);
		W->RecoilStanceMultiplier.Add(EVerseStance::Slide, 1.2f);
		return W;
	}

	/** The kick k_n of combat-state.md 4.1 (pitch, yaw), as WP02 computes it. */
	inline FVector2D Kick(const UVerseWeaponDefinition& W, uint64 Seed, int32 N, double M)
	{
		const FVector2f P = W.PatternAt(N);
		const FVector2D Pd(P.X, P.Y);
		FVerseRng Rng(Seed, uint64(N), EVerseRngSalt::Recoil);
		const FVector2D U = Rng.UnitDisk();
		return M * (Pd + W.RecoilRandomFraction * Pd.Size() * U);
	}

	/**
	 * A one-on-one rig: the bot's pawn at the origin with a first-person view, a target that moves
	 * on a script, and the fake weapon that fires while the bot holds Fire. Each Step builds the
	 * bot's percept frame (own HUD + one sighting when bTargetVisible), runs the aim system and
	 * applies the look delta and the recoil to the view.
	 */
	struct FFakeDuelRig
	{
		static constexpr double Dt = 1.0 / 60.0;

		TStrongObjectPtr<UVerseWeaponDefinition> Weapon;
		FVerseBotAimSystem Aim;
		uint64 RecoilSeed = 7;

		double TimeS = 0.0;
		uint32 Tick = 0;
		FVector Eye = FVector(0, 0, 160);
		/** View (pitch, yaw) degrees. */
		FVector2D View = FVector2D::ZeroVector;
		/** Recoil applied and not yet recovered (combat-state.md 4.2). */
		FVector2D Accumulator = FVector2D::ZeroVector;
		bool bRecovery = true;
		/** Fire regardless of the bot (recoil tests hold the trigger for it). */
		bool bForceFire = false;
		/** Kicks being applied: remaining amount and time left. */
		TArray<TPair<FVector2D, double>> Kicking;

		/** Rounds on the own HUD; a large count stands in for infinite ammo (never refilled mid-spray). */
		int32 Magazine = 1000000;
		int32 ShotIndex = 0;
		double LastShotS = -1.0e9;
		int32 ShotsFired = 0;

		bool bTargetVisible = true;
		FVector TargetPelvis = FVector(1500, 0, 100);
		FVector TargetVelocity = FVector::ZeroVector;
		uint8 VisibleMask = 0xFF;
		bool bTargetSpawnProtected = false;

		FVerseBotAimIntent Intent;
		FVerseBotAimOutput Last;

		void Init(const UVerseBotTier& Tier, uint64 Seed)
		{
			Weapon.Reset(MakeRifle());
			Aim.Reset(Tier, Seed);
		}

		FVersePerceptFrame BuildFrame() const
		{
			FVersePerceptFrame F;
			F.ServerTimeMs = uint32(FMath::RoundToInt64(TimeS * 1000.0));
			F.Self.Health = 100.f;
			F.Self.MaxHealth = 100.f;
			F.Self.Magazine = Magazine;
			F.Self.bChambered = Magazine > 0;
			F.Self.EyeLocation = Eye;
			F.Self.Location = FVector(Eye.X, Eye.Y, 100);
			F.Self.ViewRotation = FRotator(View.X, View.Y, 0.0);
			F.Self.Phase = EVerseCombatPhase::Alive;
			if (bTargetVisible)
			{
				FVerseSightPercept S;
				S.PerceptId = Tick;
				S.PelvisLocation = TargetPelvis;
				S.Velocity = TargetVelocity;
				S.VisibleMask = VisibleMask;
				S.bSpawnProtected = bTargetSpawnProtected;
				S.FacingYawDeg = 180.f;
				F.Sightings.Add(S);
			}
			return F;
		}

		/** One 60 Hz tick: perceive, think, act, simulate the weapon. */
		void Step()
		{
			const FVersePerceptFrame Frame = BuildFrame();
			FVerseBotAimInput In;
			In.Frame = &Frame;
			In.DtS = Dt;
			In.Weapon = Weapon.Get();
			In.Intent = Intent;
			Last = Aim.Tick(In);

			// The pawn applies the look delta; pulling down compensates the accumulator (4.2).
			View.X += Last.LookDeltaDeg.X;
			View.Y += Last.LookDeltaDeg.Y;
			if (Last.LookDeltaDeg.X < 0.f)
			{
				Accumulator.X = FMath::Max(0.0, Accumulator.X + Last.LookDeltaDeg.X);
			}

			// The weapon: full auto at its RPM while Fire is held.
			const bool bFire = bForceFire || (Last.Buttons & uint32(EVerseInputButton::Fire)) != 0;
			if (TimeS - LastShotS >= Weapon->PatternResetTime)
			{
				ShotIndex = 0;
			}
			if (bFire && Magazine > 0 && TimeS - LastShotS >= Weapon->FireInterval() - 1.0e-6)
			{
				const FVector2D K = Kick(*Weapon, RecoilSeed + uint64(ShotsFired) * 7919ull, ShotIndex, 1.0);
				Kicking.Add({K, Weapon->RecoilKickTime});
				Accumulator += K;
				++ShotIndex;
				++ShotsFired;
				LastShotS = TimeS;
				// The HUD count drops on every shot, so the bot sees each one. Infinite ammo starts
				// from a count that never runs out instead of refilling: a refill would hide a shot.
				--Magazine;
			}
			// Apply kicks over the kick time (linear here; WP02 eases out).
			for (int32 I = Kicking.Num() - 1; I >= 0; --I)
			{
				TPair<FVector2D, double>& K = Kicking[I];
				const double Part = FMath::Min(1.0, Dt / FMath::Max(Dt, K.Value));
				const FVector2D KickStep = K.Key * Part;
				View += KickStep;
				K.Key -= KickStep;
				K.Value -= Dt;
				if (K.Value <= 1.0e-9)
				{
					View += K.Key;
					Kicking.RemoveAt(I);
				}
			}
			// Recovery after d_r (4.2).
			if (bRecovery && TimeS - LastShotS >= Weapon->RecoilRecoveryDelay && Accumulator.SizeSquared() > 0.0)
			{
				const double Size = Accumulator.Size();
				const double StepSize = FMath::Min(Size, Weapon->RecoilRecoveryRate * Dt);
				const FVector2D StepVec = Accumulator / Size * StepSize;
				Accumulator -= StepVec;
				View -= StepVec;
			}

			TargetPelvis += TargetVelocity * Dt;
			TimeS += Dt;
			++Tick;
		}

		/** Angle between the view and the target's true upper torso, degrees. */
		double TrueErrorDeg() const
		{
			const FVector Point = TargetPelvis + FVector(0, 0, 34);
			return FVerseBotAimSystem::AngleBetween(View, FVerseBotAimSystem::AnglesTo(Eye, Point));
		}
	};
}

#endif // WITH_DEV_AUTOMATION_TESTS
