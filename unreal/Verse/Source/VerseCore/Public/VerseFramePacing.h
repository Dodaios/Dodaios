#pragma once

#include "CoreMinimal.h"

/**
 * The one owner of t.MaxFPS. The Verse runs beside the app and other work, so an uncapped frame
 * rate burns CPU cores for frames nobody needs. Several parts want a cap: the person's frame limit
 * (game settings, display.frame_limit), the bridge lifecycle (panel 30, dormant 2) and the panel
 * stream. Each part sets its own input here; a ticker applies the lowest cap.
 *
 * Pacing rules:
 * - while the Verse window is the foreground window (duel, deck view, menus) the person's limit
 *   applies; its default follows the refresh rate of the display the window is on;
 * - while the Verse window is not the foreground window at most BackgroundFps.
 *
 * A t.MaxFPS set from the console or the command line (-ExecCmds, perf runs) wins: the pacer
 * never overrides a value set with a higher priority than code.
 */
struct VERSECORE_API FVerseFramePacing
{
	static constexpr float BackgroundFps = 30.f;
	/** The display limit when the refresh rate cannot be read. */
	static constexpr float FallbackDisplayFps = 240.f;

	/** The person's frame limit. */
	struct FUserLimit
	{
		/** Follow the refresh rate of the display the Verse window is on. */
		bool bMatchDisplay = true;
		/** Fixed limit when bMatchDisplay is off; 0 = unlimited. */
		float Fps = 0.f;
	};

	struct FInputs
	{
		FUserLimit User;
		/** Refresh rate of the display the window is on; 0 = unknown. */
		float DisplayHz = 0.f;
		/** Bridge lifecycle cap; 0 = none. */
		float LifecycleCap = 0.f;
		/** Panel stream cap; 0 = none. */
		float StreamCap = 0.f;
		bool bForeground = true;
	};

	/** The cap for these inputs, the lowest of every active one; 0 = uncapped. */
	static float Resolve(const FInputs& In);

	/** The person's limit (VerseUI applies display.frame_limit). */
	static void SetUserLimit(const FUserLimit& Limit);
	static FUserLimit GetUserLimit();
	static void SetLifecycleCap(float Fps);
	static void SetStreamCap(float Fps);

	/**
	 * Low-latency frame pacing (display.low_latency): turns the engine's max-tick-rate handler and
	 * latency markers on or off. On NVIDIA GPUs that is Reflex (the Reflex plugin, Win64); where no
	 * handler exists it does nothing and the engine's own limiter applies.
	 */
	static void SetLowLatency(bool bEnabled);

	/** Refresh rate of the display the foreground window is on (Windows), else the platform's; 0 = unknown. */
	static float ReadDisplayHz();

	/** Reads the window focus and the display, then writes t.MaxFPS when it differs. Game thread. */
	static void Apply();

	/** Starts the ticker (VerseCore startup); does nothing in the editor, commandlets and servers. */
	static void Start();
	static void Stop();
};
