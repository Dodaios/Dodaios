#pragma once

#include "CoreMinimal.h"

/**
 * The loading screen's state (parity A-07): key art, a tip and a progress bar from the moment
 * the app opens until the first deck frame is on screen, then a fade-out under 600 ms. A deck
 * that loads in a blink would only flash the screen, so it stays a minimum time.
 */
class VERSEUI_API FVerseLoadingModel
{
public:
	enum class EPhase : uint8
	{
		Hidden,
		Showing,
		Leaving,
		Gone,
	};

	static constexpr double FadeSeconds = 0.52;
	static constexpr double MinShowSeconds = 1.2;
	static constexpr int32 NumTips = 3;

	/** Starts showing at Now; the tip is picked from Seed. */
	void Begin(double Now, int32 Seed);
	/** The first frame of the deck is on screen: the bar fills and the screen fades out. */
	void NotifyFirstDeckFrame(double Now);
	void Tick(double Now);

	EPhase GetPhase() const { return Phase; }
	bool IsVisible() const { return Phase == EPhase::Showing || Phase == EPhase::Leaving; }
	/** 1 while showing, falling to 0 over FadeSeconds while leaving. */
	float Opacity(double Now) const;
	/** 0..1; eases toward 0.92 while the deck loads, 1 once it is ready. */
	float Progress(double Now) const;
	/** 1..NumTips (the key verse.loading.tip_N). */
	int32 GetTip() const { return Tip; }
	/** When the first deck frame arrived, or -1. */
	double GetFirstFrameAt() const { return FirstFrameAt; }
	/** When the fade started and ended, or -1. */
	double GetFadeStartedAt() const { return FadeStartedAt; }
	double GetGoneAt() const { return GoneAt; }
	double GetStartedAt() const { return StartedAt; }

	/** Progress while the deck loads. */
	static float GuessProgress(double ElapsedSeconds);

private:
	EPhase Phase = EPhase::Hidden;
	double StartedAt = -1.0;
	double FirstFrameAt = -1.0;
	double FadeStartedAt = -1.0;
	double GoneAt = -1.0;
	int32 Tip = 1;
};
