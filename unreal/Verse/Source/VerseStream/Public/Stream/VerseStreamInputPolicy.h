#pragma once

#include "CoreMinimal.h"

// What the side panel may send over the Pixel Streaming data channel (WP20.4). The panel is
// overview and walking only; the duel never runs in the panel (architecture.md 6). The web
// component (verseStream/panelInput.ts) applies the same table before anything is sent; this
// side is the second wall.

namespace VerseStreamInput
{
	/** Message ids of the plugin's default ToStreamer protocol (PixelStreaming2Input DefaultDataProtocol). */
	inline constexpr uint8 IFrameRequest = 0;
	inline constexpr uint8 RequestQualityControl = 1;
	inline constexpr uint8 FpsRequest = 2;
	inline constexpr uint8 AverageBitrateRequest = 3;
	inline constexpr uint8 StartStreaming = 4;
	inline constexpr uint8 StopStreaming = 5;
	inline constexpr uint8 LatencyTest = 6;
	inline constexpr uint8 RequestInitialSettings = 7;
	inline constexpr uint8 TestEcho = 8;
	inline constexpr uint8 UIInteraction = 50;
	inline constexpr uint8 Command = 51;
	inline constexpr uint8 TextboxEntry = 52;
	inline constexpr uint8 KeyDown = 60;
	inline constexpr uint8 KeyUp = 61;
	inline constexpr uint8 KeyPress = 62;
	inline constexpr uint8 MouseEnter = 70;
	inline constexpr uint8 MouseLeave = 71;
	inline constexpr uint8 MouseDown = 72;
	inline constexpr uint8 MouseUp = 73;
	inline constexpr uint8 MouseMove = 74;
	inline constexpr uint8 MouseWheel = 75;
	inline constexpr uint8 MouseDouble = 76;

	/** Payload size in bytes after the id byte, or -1 for a message the panel never sends. */
	VERSESTREAM_API int32 PayloadSize(uint8 MessageId);

	/** True for the browser key codes the panel forwards: W, A, S, D, the arrow keys, Q and E (turn), V (view). */
	VERSESTREAM_API bool IsAllowedKeyCode(uint8 KeyCode);

	/** True when the whole data channel message (id byte first) may reach the input handler. */
	VERSESTREAM_API bool IsAllowedMessage(TConstArrayView<uint8> Message);

	/** The browser key codes IsAllowedKeyCode accepts, for tests and the key filter. */
	VERSESTREAM_API TConstArrayView<uint8> AllowedKeyCodes();

	/**
	 * Comma-separated Unreal key names the plugin's `PixelStreaming2.KeyFilter` should drop:
	 * every keyboard key whose browser key code is not allowed.
	 */
	VERSESTREAM_API FString BuildKeyFilter();

	/** The panel never starts or joins a duel (armoury, quick start). */
	inline constexpr bool AllowsDuelEntryInPanel = false;
}
