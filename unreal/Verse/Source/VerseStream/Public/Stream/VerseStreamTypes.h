#pragma once

#include "CoreMinimal.h"

// Shared values of the IDE side panel stream (WP20, architecture.md 6, bridge-protocol.md 12).

/** The `panel.stream_state` values of bridge-protocol.md 12. */
enum class EVersePanelStreamState : uint8
{
	Stopped,
	Starting,
	Streaming,
	Failed,
};

namespace VerseStream
{
	/** Wire name of a stream state, as `panel.stream_state.state` carries it. */
	VERSESTREAM_API const TCHAR* StateName(EVersePanelStreamState State);

	/** Frame rate of the panel stream (architecture.md 6). */
	inline constexpr int32 PanelFps = 30;
	/** Bitrate cap of the panel stream in bit/s (architecture.md 6). */
	inline constexpr int32 MaxBitrateBps = 8'000'000;
	/** Start bitrate, inside the cap. */
	inline constexpr int32 StartBitrateBps = 4'000'000;
	/** Largest offscreen render target the panel ever asks for (render pixels). */
	inline constexpr int32 MaxRenderW = 1920;
	inline constexpr int32 MaxRenderH = 1200;
	/** Smallest render target worth encoding. */
	inline constexpr int32 MinRenderW = 160;
	inline constexpr int32 MinRenderH = 100;
	/** Hidden panel to stopped stream (A20.1). */
	inline constexpr double StopDeadlineSeconds = 1.0;

	/** `panel.stream_state.error` when the full Verse window is showing (WP20.5 arbitration). */
	inline const TCHAR* const ErrorFullViewOpen = TEXT("full_view_open");
	/** `panel.stream_state.error` when no Pixel Streaming 2 streamer is present. */
	inline const TCHAR* const ErrorStreamerUnavailable = TEXT("streamer_unavailable");
	/** `panel.stream_state.error` when no signalling URL could be built (no launch environment). */
	inline const TCHAR* const ErrorNoSignal = TEXT("no_signal_url");
}

/** The side panel's size as `panel.visibility` and `panel.resize` carry it (CSS pixels, device pixel ratio). */
struct VERSESTREAM_API FVersePanelGeometry
{
	int32 W = 0;
	int32 H = 0;
	float Dpr = 1.0f;

	bool IsValid() const;

	/** Render size for the panel: CSS size times DPR, capped to the maximum with the aspect kept, even sides for H.264. */
	FIntPoint RenderSize() const;

	bool operator==(const FVersePanelGeometry& Other) const
	{
		return W == Other.W && H == Other.H && FMath::IsNearlyEqual(Dpr, Other.Dpr);
	}
	bool operator!=(const FVersePanelGeometry& Other) const { return !(*this == Other); }
};

/** Everything a driver needs to start the panel stream. */
struct VERSESTREAM_API FVerseStreamConfig
{
	/** `ws://127.0.0.1:<port>/api/verse/signal?role=streamer&key=<key>` (dodaios/verse_host/signal.py). */
	FString SignalUrl;
	FIntPoint RenderSize = FIntPoint::ZeroValue;
	int32 Fps = VerseStream::PanelFps;
	int32 MaxBitrateBps = VerseStream::MaxBitrateBps;
	int32 StartBitrateBps = VerseStream::StartBitrateBps;
	/** Preferred hardware encoder codec. */
	FString Codec = TEXT("H264");
};
