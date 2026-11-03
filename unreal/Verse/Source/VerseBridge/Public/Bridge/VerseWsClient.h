#pragma once

#include "CoreMinimal.h"
#include "Containers/Queue.h"
#include "HAL/Runnable.h"

class FSocket;
class FRunnableThread;

/**
 * A minimal RFC 6455 WebSocket client for the loopback bridge (ws:// only, no extensions).
 *
 * The bridge is always 127.0.0.1 (bridge-protocol.md 1), so this needs no TLS and keeps the
 * module inside the frozen dependency list (Core, CoreUObject, Engine; Sockets comes through
 * Engine). Socket work runs on its own thread; events are queued and drained on the caller's
 * thread with Poll(), so every callback runs on the game thread.
 */
class VERSEBRIDGE_API FVerseWsClient : public FRunnable
{
public:
	struct FEvent
	{
		enum class EKind : uint8
		{
			Connected,
			Text,
			Binary,
			Closed,
		};
		EKind Kind = EKind::Text;
		FString Text;
		TArray<uint8> Bytes;
		int32 CloseCode = 0;
	};

	FVerseWsClient();
	virtual ~FVerseWsClient() override;

	/** Starts connecting to ws://host:port/path. False when the URL is not a loopback ws:// URL. */
	bool Connect(const FString& Url);

	/** Closes the socket (sends a close frame with Code when connected) and joins the thread. */
	void Close(int32 Code = 1000);

	void SendText(const FString& Text);
	void SendBinary(const TArray<uint8>& Bytes);

	/** Drains queued events (game thread). */
	bool Poll(FEvent& Out) { return Events.Dequeue(Out); }

	bool IsOpen() const { return bOpen; }

	/** Parses ws://host:port/path; only loopback hosts are accepted. */
	static bool ParseUrl(const FString& Url, FString& OutHost, int32& OutPort, FString& OutPath);

	/** The Sec-WebSocket-Accept value for a key (RFC 6455 4.2.2). */
	static FString AcceptFor(const FString& Key);

	/** Encodes one masked client frame (exposed for tests). */
	static void EncodeFrame(uint8 Opcode, const uint8* Payload, int64 Len, const uint8 Mask[4], TArray<uint8>& Out);

	// FRunnable
	virtual uint32 Run() override;
	virtual void Stop() override { bStopping = true; }

private:
	struct FOutgoing
	{
		uint8 Opcode = 1;
		TArray<uint8> Payload;
	};

	bool Handshake();
	bool SendRaw(const uint8* Data, int32 Len);
	bool SendFrame(uint8 Opcode, const TArray<uint8>& Payload);
	bool ReadAvailable();
	bool ProcessBuffer();
	void Finish(int32 Code);

	FString Host;
	int32 Port = 0;
	FString Path;
	FSocket* Socket = nullptr;
	FRunnableThread* Thread = nullptr;
	TQueue<FOutgoing, EQueueMode::Mpsc> Outgoing;
	TQueue<FEvent, EQueueMode::Spsc> Events;
	TArray<uint8> Buffer;
	TArray<uint8> Fragment;
	uint8 FragmentOpcode = 0;
	TAtomic<bool> bStopping{false};
	TAtomic<bool> bOpen{false};
	TAtomic<int32> CloseRequested{0};
	bool bFinished = false;
};
