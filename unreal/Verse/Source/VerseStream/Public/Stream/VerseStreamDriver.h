#pragma once

#include "CoreMinimal.h"
#include "Stream/VerseStreamTypes.h"

/**
 * Runs the Pixel Streaming 2 session (WP20.2). The default driver
 * (FVerseConsoleStreamDriver) drives the plugin through its console variables and the
 * `PixelStreaming.StartStreaming` / `PixelStreaming.StopStreaming` commands, so VerseStream
 * needs no module edge beyond architecture.md 2. Tests use FFakeStreamDriver.
 */
class VERSESTREAM_API IVerseStreamDriver
{
public:
	/** Result of Start: true when the session started; on false, an error code for `panel.stream_state`. */
	using FOnStarted = TFunction<void(bool bStarted, const FString& Error)>;

	virtual ~IVerseStreamDriver() = default;

	/** True when a Pixel Streaming 2 streamer exists in this process. */
	virtual bool IsAvailable() const = 0;

	/** Start streaming with Config. Calls OnStarted exactly once, possibly before returning. */
	virtual void Start(const FVerseStreamConfig& Config, FOnStarted OnStarted) = 0;

	/** Stop streaming now. Safe to call when not streaming. */
	virtual void Stop() = 0;

	/** Change the offscreen render size of a running session. */
	virtual void Resize(FIntPoint RenderSize) = 0;

	virtual bool IsStreaming() const = 0;
};

/**
 * Outbound link to the verse host. The bridge client (WP17, VerseBridge) implements it by
 * sending `panel.stream_state` (bridge-protocol.md 12); tests use FFakeStreamLink.
 */
class VERSESTREAM_API IVerseStreamLink
{
public:
	virtual ~IVerseStreamLink() = default;

	/** Send `panel.stream_state {state, error?}`. Error is empty when there is none. */
	virtual void SendStreamState(EVersePanelStreamState State, const FString& Error) = 0;
};
