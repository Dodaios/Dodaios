#pragma once

#include "CoreMinimal.h"
#include "VerseRng.h"

class UVerseBotTier;

/** The hand-on-the-mouse fields of a tier (bot.md 9.1 Aim group). */
struct VERSEBOT_API FVerseBotAimParams
{
	double AimNoiseDeg = 1.4;
	double AimNoiseRate = 1.6;
	double AcquireErrorDeg = 6.0;
	double AcquireMs = 650.0;
	double TurnRateDegS = 450.0;
	double AimStiffness = 8.0;

	static FVerseBotAimParams FromTier(const UVerseBotTier& Tier);
};

/**
 * The bot's hand on the mouse (bot.md 8.1, port of the concept in bot/aim.ts): it moves its aim
 * toward where it wants to shoot like a person does, speed-limited, settling with stiffness, with
 * an Ornstein-Uhlenbeck wander and a larger acquire error after a new target that fades.
 *
 * Angles are degrees as FVector2f(pitch, yaw), the layout of FVerseInputFrame::LookDeltaDeg. The
 * controller keeps its own hand angles: what it has moved the view to, without the weapon's
 * recoil. The caller re-syncs the hand to the perceived view whenever no spray is running
 * (FVerseBotAimSystem does), so recoil that is left over gets seen and corrected like a person does.
 *
 * Deterministic (B5): every draw comes from its own FVerseRng stream.
 */
class VERSEBOT_API FVerseBotAimController
{
public:
	/** OU pitch amplitude relative to yaw (bot.md 8.1). */
	static constexpr double PitchNoiseScale = 0.6;
	/** Acquire error pitch relative to yaw (bot.md 8.1). */
	static constexpr double AcquirePitchScale = 0.5;
	/** Per-tick minimum step so the aim arrives instead of creeping (bot.md 8.1). */
	static constexpr double StepFloorDeg = 0.02;
	static constexpr double PitchLimitDeg = 89.0;

	void Reset(const FVerseBotAimParams& InParams, uint64 Seed, const FVector2D& HandPitchYaw);

	/** New tier values (adaptive mode applies them at respawn); the hand and the noise state stay. */
	void SetParams(const FVerseBotAimParams& InParams) { Params = InParams; }
	const FVerseBotAimParams& GetParams() const { return Params; }

	/** Puts the hand where the bot perceives its view to be. */
	void SyncHand(const FVector2D& HandPitchYaw) { Hand = HandPitchYaw; }
	FVector2D GetHand() const { return Hand; }

	/** A new target: random direction, magnitude abs(N(1, 0.35)) x AcquireErrorDeg, pitch x 0.5. */
	void Acquire(double NowS);

	/** Current OU wander, degrees (pitch, yaw). */
	FVector2D GetNoise() const { return Noise; }

	/** Error added to the intended aim now: OU wander plus the fading acquire error. */
	FVector2D GetErrorDeg(double NowS) const;

	/** Advances the OU process by Dt seconds: x += -k x dt + sd sqrt(2 k dt) N(0, 1). */
	void StepNoise(double Dt);

	/**
	 * One tick toward WantPitchYaw (plus the error when bNoisy): step = (want - hand) x
	 * (1 - exp(-AimStiffness dt)), floored at 0.02 deg, capped at TurnRateDegS x dt in magnitude.
	 * Advances the noise, moves the hand and returns the look delta (pitch, yaw).
	 */
	FVector2D Step(double NowS, double Dt, const FVector2D& WantPitchYaw, bool bNoisy);

	/** Shortest signed yaw difference To - From in (-180, 180]. */
	static double YawDelta(double From, double To);

private:
	FVerseBotAimParams Params;
	FVerseRng Rng;
	FVector2D Hand = FVector2D::ZeroVector;
	FVector2D Noise = FVector2D::ZeroVector;
	FVector2D AcquireError = FVector2D::ZeroVector;
	double AcquireAtS = -1.0e9;
};
