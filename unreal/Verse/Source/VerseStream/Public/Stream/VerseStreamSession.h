#pragma once

#include "CoreMinimal.h"
#include "Stream/VerseStreamArbiter.h"
#include "Stream/VerseStreamDriver.h"

/**
 * The panel stream's state machine (WP20.2, WP20.5): bridge panel events in, driver calls and
 * `panel.stream_state` reports out. Pure C++ over two interfaces, so it is tested with fakes.
 *
 * - `panel.visibility {visible: true}` while the full view is hidden: report `starting`,
 *   start the driver at the panel's render size; report `streaming` or `failed`.
 * - `panel.visibility {visible: false}`: stop the driver at once (A20.1: within 1 s), report
 *   `stopped`.
 * - `panel.resize`: resize a running session.
 * - Full view shows while the panel streams: stop, report `stopped` with `full_view_open`;
 *   full view hides again: start again.
 */
class VERSESTREAM_API FVerseStreamSession
{
public:
	using FSignalUrlProvider = TFunction<FString()>;
	using FClock = TFunction<double()>;

	FVerseStreamSession(TSharedRef<IVerseStreamDriver> InDriver, TSharedRef<IVerseStreamLink> InLink,
		FSignalUrlProvider InSignalUrl, FClock InClock = FClock());

	void OnPanelVisibility(bool bVisible, const FVersePanelGeometry& Geometry);
	void OnPanelResize(const FVersePanelGeometry& Geometry);
	void OnFullViewVisible(bool bVisible);

	EVersePanelStreamState GetState() const { return State; }
	const FString& GetLastError() const { return LastError; }
	const FVerseStreamArbiter& GetArbiter() const { return Arbiter; }

	/** Called with true when the lifecycle should enter Panel, false when it should leave it. */
	TFunction<void(bool bEnterPanel)> OnPanelStateChanged;

	/** Seconds from the last hide (panel hidden or full view shown) to the driver being stopped. */
	double GetLastStopLatencySeconds() const { return LastStopLatency; }
	int32 GetStartCount() const { return StartCount; }
	int32 GetStopCount() const { return StopCount; }

private:
	void Reconcile();
	void StartStream();
	void StopStream(const FString& Reason);
	void Report(EVersePanelStreamState NewState, const FString& Error);
	double Now() const;

	TSharedRef<IVerseStreamDriver> Driver;
	TSharedRef<IVerseStreamLink> Link;
	FSignalUrlProvider SignalUrl;
	FClock Clock;
	FVerseStreamArbiter Arbiter;
	EVersePanelStreamState State = EVersePanelStreamState::Stopped;
	FString LastError;
	bool bReported = false;
	bool bInPanelState = false;
	uint32 Generation = 0;
	double LastStopLatency = 0.0;
	int32 StartCount = 0;
	int32 StopCount = 0;
};

namespace VerseStream
{
	/** The `data` object of `panel.stream_state` as compact JSON (bridge-protocol.md 12). */
	VERSESTREAM_API FString StreamStateJson(EVersePanelStreamState State, const FString& Error);

	/** An error code reduced to the characters `panel.stream_state.error` uses (a-z, 0-9, _), at most 64. */
	VERSESTREAM_API FString SanitizeErrorCode(const FString& Error);
}
