#pragma once

#include "Bot/VersePerceptTypes.h"
#include "CoreMinimal.h"

class UVerseBotTier;

/** What the brain asks of the aim layer this tick. World cm. */
struct VERSEBOT_API FVerseBotAimRequest
{
	bool bHasTarget = false;
	FVector TargetPoint = FVector::ZeroVector;
	/** The target was just acquired (a sighting after none): reaction starts now. */
	bool bNewTarget = false;
	/**
	 * With bNewTarget: the reaction still left, s. The brain samples the stimulus reaction of 8.1
	 * once and holds the sighting back from the decision layer for it, so it hands the aim 0 (the
	 * reaction is already spent). Negative: the aim layer samples its own.
	 */
	float ReactionRemainingS = -1.f;
	/** Target angular half-width, deg (fire tolerance, bot.md 8.1). */
	float TargetHalfWidthDeg = 1.f;
};

struct VERSEBOT_API FVerseBotAimResult
{
	/** Pitch, yaw for FVerseInputFrame::LookDeltaDeg. */
	FVector2f LookDeltaDeg = FVector2f::ZeroVector;
	/** Angle between the view axis after this step and the target, deg. */
	float ErrorDeg = 180.f;
	/** Reaction elapsed and error within FireTolerance x half-width. */
	bool bOnTarget = false;
};

/**
 * The aim and reaction layer (bot.md 8.1). WP09 ships the human-limited model in the Aim folder;
 * the brain codes against this surface. Deterministic per seed (B5).
 */
class VERSEBOT_API IVerseBotAimDriver
{
public:
	virtual ~IVerseBotAimDriver() = default;
	virtual void Reset(uint64 Seed, const UVerseBotTier& Tier) = 0;
	virtual FVerseBotAimResult Step(const FVerseSelfPercept& Self, const FVerseBotAimRequest& Request, float DtS) = 0;
};

/**
 * Fixed reaction (the tier's mean ReactionMs), then a follow capped at TurnRateDegS with no noise.
 * The controller's default until WP09 lands, and the "perfect follow" fake of WP08's tests.
 */
class VERSEBOT_API FVerseBotFollowAim final : public IVerseBotAimDriver
{
public:
	virtual void Reset(uint64 Seed, const UVerseBotTier& Tier) override;
	virtual FVerseBotAimResult Step(const FVerseSelfPercept& Self, const FVerseBotAimRequest& Request, float DtS) override;

private:
	float ReactionS = 0.32f;
	float TurnRateDegS = 450.f;
	float FireTolerance = 2.f;
	float SinceAcquireS = 0.f;
};
