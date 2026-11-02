#pragma once

#include "CoreMinimal.h"

// The streamer's signalling credential (WP20.1). The Pixel Streaming 2 plugin cannot send a
// first frame of its own, so it authenticates with a key in its connection URL. The key is
// HMAC-SHA256(launch token, "verse.signal/1 streamer") in lower-case hex, the same value
// dodaios/verse_host/signal.py derive_streamer_key computes; the launch token itself never
// appears in a URL the plugin could log.

namespace VerseStreamKey
{
	/** SHA-256 of Data. */
	VERSESTREAM_API TArray<uint8> Sha256(TConstArrayView<uint8> Data);

	/** HMAC-SHA256 (RFC 2104) of Message under Key. */
	VERSESTREAM_API TArray<uint8> HmacSha256(TConstArrayView<uint8> Key, TConstArrayView<uint8> Message);

	/** Lower-case hex of Bytes. */
	VERSESTREAM_API FString ToHex(TConstArrayView<uint8> Bytes);

	/** The streamer key for a launch token (UTF-8). */
	VERSESTREAM_API FString DeriveStreamerKey(const FString& LaunchToken);

	/**
	 * The streamer's signalling URL from the bridge URL of DODAIOS_VERSE_BRIDGE
	 * (`ws://127.0.0.1:<port>/api/verse/bridge`) and the launch token. Empty when either is
	 * missing, the bridge URL is not a loopback ws:// URL, or its path is not the bridge path.
	 */
	VERSESTREAM_API FString BuildSignalUrl(const FString& BridgeUrl, const FString& LaunchToken);
}
