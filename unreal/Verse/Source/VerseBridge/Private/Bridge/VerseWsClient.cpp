#include "Bridge/VerseWsClient.h"

#include "HAL/PlatformProcess.h"
#include "HAL/RunnableThread.h"
#include "IPAddress.h"
#include "Math/UnrealMathUtility.h"
#include "Misc/Base64.h"
#include "Misc/SecureHash.h"
#include "SocketSubsystem.h"
#include "Sockets.h"
#include "VerseLog.h"

namespace
{
	constexpr int32 MaxMessageBytes = 1 << 20;
	constexpr double ConnectTimeoutS = 2.0;
}

FVerseWsClient::FVerseWsClient() = default;

FVerseWsClient::~FVerseWsClient()
{
	Close(1001);
}

bool FVerseWsClient::ParseUrl(const FString& Url, FString& OutHost, int32& OutPort, FString& OutPath)
{
	FString Rest;
	if (!Url.StartsWith(TEXT("ws://")))
	{
		return false;
	}
	Rest = Url.Mid(5);
	int32 Slash = INDEX_NONE;
	FString HostPort = Rest;
	OutPath = TEXT("/");
	if (Rest.FindChar('/', Slash))
	{
		HostPort = Rest.Left(Slash);
		OutPath = Rest.Mid(Slash);
	}
	int32 Colon = INDEX_NONE;
	if (!HostPort.FindLastChar(':', Colon))
	{
		return false;
	}
	OutHost = HostPort.Left(Colon).Replace(TEXT("["), TEXT("")).Replace(TEXT("]"), TEXT(""));
	OutPort = FCString::Atoi(*HostPort.Mid(Colon + 1));
	const bool bLoopback = OutHost == TEXT("127.0.0.1") || OutHost == TEXT("localhost") || OutHost == TEXT("::1");
	if (OutHost == TEXT("localhost"))
	{
		OutHost = TEXT("127.0.0.1");
	}
	return bLoopback && OutPort > 0 && OutPort < 65536;
}

FString FVerseWsClient::AcceptFor(const FString& Key)
{
	const FString Joined = Key + TEXT("258EAFA5-E914-47DA-95CA-C5AB0DC85B11");
	const FTCHARToUTF8 Utf8(*Joined);
	uint8 Digest[20];
	FSHA1::HashBuffer(Utf8.Get(), Utf8.Length(), Digest);
	return FBase64::Encode(Digest, 20);
}

void FVerseWsClient::EncodeFrame(uint8 Opcode, const uint8* Payload, int64 Len, const uint8 Mask[4], TArray<uint8>& Out)
{
	Out.Reset();
	Out.Add(0x80 | (Opcode & 0x0F));
	if (Len < 126)
	{
		Out.Add(0x80 | uint8(Len));
	}
	else if (Len <= 0xFFFF)
	{
		Out.Add(0x80 | 126);
		Out.Add(uint8(Len >> 8));
		Out.Add(uint8(Len & 0xFF));
	}
	else
	{
		Out.Add(0x80 | 127);
		for (int32 I = 7; I >= 0; --I)
		{
			Out.Add(uint8((uint64(Len) >> (8 * I)) & 0xFF));
		}
	}
	Out.Append(Mask, 4);
	const int32 Start = Out.Num();
	Out.AddUninitialized(int32(Len));
	for (int64 I = 0; I < Len; ++I)
	{
		Out[Start + int32(I)] = Payload[I] ^ Mask[I & 3];
	}
}

bool FVerseWsClient::Connect(const FString& Url)
{
	Close(1000);
	if (!ParseUrl(Url, Host, Port, Path))
	{
		UE_LOG(LogVerseBridge, Warning, TEXT("bridge URL is not a loopback ws:// URL"));
		return false;
	}
	bStopping = false;
	bOpen = false;
	bFinished = false;
	CloseRequested = 0;
	Buffer.Reset();
	Thread = FRunnableThread::Create(this, TEXT("VerseBridgeSocket"), 0, TPri_Normal);
	return Thread != nullptr;
}

void FVerseWsClient::Close(int32 Code)
{
	if (!Thread)
	{
		return;
	}
	CloseRequested = Code;
	bStopping = true;
	Thread->WaitForCompletion();
	delete Thread;
	Thread = nullptr;
}

void FVerseWsClient::SendText(const FString& Text)
{
	const FTCHARToUTF8 Utf8(*Text);
	FOutgoing O;
	O.Opcode = 1;
	O.Payload.Append(reinterpret_cast<const uint8*>(Utf8.Get()), Utf8.Length());
	Outgoing.Enqueue(MoveTemp(O));
}

void FVerseWsClient::SendBinary(const TArray<uint8>& Bytes)
{
	FOutgoing O;
	O.Opcode = 2;
	O.Payload = Bytes;
	Outgoing.Enqueue(MoveTemp(O));
}

bool FVerseWsClient::SendRaw(const uint8* Data, int32 Len)
{
	int32 Sent = 0;
	while (Sent < Len)
	{
		int32 N = 0;
		if (!Socket->Send(Data + Sent, Len - Sent, N) || N <= 0)
		{
			if (N == 0 && Socket->GetConnectionState() == SCS_Connected)
			{
				FPlatformProcess::Sleep(0.001f);
				continue;
			}
			return false;
		}
		Sent += N;
	}
	return true;
}

bool FVerseWsClient::SendFrame(uint8 Opcode, const TArray<uint8>& Payload)
{
	uint8 Mask[4];
	const uint32 R = uint32(FMath::Rand()) ^ (uint32(FMath::Rand()) << 15) ^ uint32(FPlatformTime::Cycles());
	FMemory::Memcpy(Mask, &R, 4);
	TArray<uint8> Wire;
	EncodeFrame(Opcode, Payload.GetData(), Payload.Num(), Mask, Wire);
	return SendRaw(Wire.GetData(), Wire.Num());
}

bool FVerseWsClient::Handshake()
{
	uint8 Nonce[16];
	for (uint8& B : Nonce)
	{
		B = uint8(FMath::RandRange(0, 255));
	}
	const FString Key = FBase64::Encode(Nonce, 16);
	const FString Request = FString::Printf(
		TEXT("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n")
		TEXT("Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"),
		*Path, *Host, Port, *Key);
	const FTCHARToUTF8 Utf8(*Request);
	if (!SendRaw(reinterpret_cast<const uint8*>(Utf8.Get()), Utf8.Length()))
	{
		return false;
	}
	const double Deadline = FPlatformTime::Seconds() + ConnectTimeoutS;
	while (FPlatformTime::Seconds() < Deadline && !bStopping)
	{
		if (!ReadAvailable())
		{
			return false;
		}
		for (int32 I = 3; I < Buffer.Num(); ++I)
		{
			if (Buffer[I - 3] == '\r' && Buffer[I - 2] == '\n' && Buffer[I - 1] == '\r' && Buffer[I] == '\n')
			{
				const FString Head = FString(FUTF8ToTCHAR(reinterpret_cast<const ANSICHAR*>(Buffer.GetData()), I + 1).Length(),
					FUTF8ToTCHAR(reinterpret_cast<const ANSICHAR*>(Buffer.GetData()), I + 1).Get());
				Buffer.RemoveAt(0, I + 1);
				if (!Head.StartsWith(TEXT("HTTP/1.1 101")))
				{
					return false;
				}
				return Head.Contains(AcceptFor(Key), ESearchCase::CaseSensitive);
			}
		}
		FPlatformProcess::Sleep(0.002f);
	}
	return false;
}

bool FVerseWsClient::ReadAvailable()
{
	uint32 Pending = 0;
	while (Socket->HasPendingData(Pending) && Pending > 0)
	{
		const int32 Start = Buffer.Num();
		Buffer.AddUninitialized(int32(Pending));
		int32 Read = 0;
		if (!Socket->Recv(Buffer.GetData() + Start, int32(Pending), Read))
		{
			Buffer.SetNum(Start);
			return false;
		}
		Buffer.SetNum(Start + Read);
		if (Read == 0)
		{
			break;
		}
	}
	return Socket->GetConnectionState() != SCS_ConnectionError;
}

bool FVerseWsClient::ProcessBuffer()
{
	while (Buffer.Num() >= 2)
	{
		const uint8 B0 = Buffer[0];
		const uint8 B1 = Buffer[1];
		const bool bFin = (B0 & 0x80) != 0;
		const uint8 Opcode = B0 & 0x0F;
		uint64 Len = B1 & 0x7F;
		int32 Off = 2;
		if (Len == 126)
		{
			if (Buffer.Num() < 4)
			{
				return true;
			}
			Len = (uint64(Buffer[2]) << 8) | Buffer[3];
			Off = 4;
		}
		else if (Len == 127)
		{
			if (Buffer.Num() < 10)
			{
				return true;
			}
			Len = 0;
			for (int32 I = 0; I < 8; ++I)
			{
				Len = (Len << 8) | Buffer[2 + I];
			}
			Off = 10;
		}
		if ((B1 & 0x80) != 0 || Len > uint64(MaxMessageBytes))
		{
			Finish(1002);
			return false;
		}
		if (uint64(Buffer.Num()) < Off + Len)
		{
			return true;
		}
		TArray<uint8> Payload(Buffer.GetData() + Off, int32(Len));
		Buffer.RemoveAt(0, Off + int32(Len));
		if (Opcode == 8)
		{
			const int32 Code = Payload.Num() >= 2 ? (int32(Payload[0]) << 8) | Payload[1] : 1005;
			TArray<uint8> Echo;
			if (Payload.Num() >= 2)
			{
				Echo.Append(Payload.GetData(), 2);
			}
			SendFrame(8, Echo);
			Finish(Code);
			return false;
		}
		if (Opcode == 9)
		{
			SendFrame(10, Payload);
			continue;
		}
		if (Opcode == 10)
		{
			continue;
		}
		if (Opcode == 1 || Opcode == 2)
		{
			FragmentOpcode = Opcode;
			Fragment = MoveTemp(Payload);
		}
		else if (Opcode == 0)
		{
			Fragment.Append(Payload);
		}
		if (!bFin)
		{
			continue;
		}
		FEvent E;
		if (FragmentOpcode == 1)
		{
			E.Kind = FEvent::EKind::Text;
			const FUTF8ToTCHAR Conv(reinterpret_cast<const ANSICHAR*>(Fragment.GetData()), Fragment.Num());
			E.Text = FString(Conv.Length(), Conv.Get());
		}
		else
		{
			E.Kind = FEvent::EKind::Binary;
			E.Bytes = MoveTemp(Fragment);
		}
		Fragment.Reset();
		Events.Enqueue(MoveTemp(E));
	}
	return true;
}

void FVerseWsClient::Finish(int32 Code)
{
	if (bFinished)
	{
		return;
	}
	bFinished = true;
	bOpen = false;
	FEvent E;
	E.Kind = FEvent::EKind::Closed;
	E.CloseCode = Code;
	Events.Enqueue(MoveTemp(E));
}

uint32 FVerseWsClient::Run()
{
	ISocketSubsystem* Subsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);
	if (!Subsystem)
	{
		Finish(1006);
		return 1;
	}
	TSharedRef<FInternetAddr> Addr = Subsystem->CreateInternetAddr();
	bool bValid = false;
	Addr->SetIp(*Host, bValid);
	Addr->SetPort(Port);
	Socket = bValid ? Subsystem->CreateSocket(NAME_Stream, TEXT("VerseBridge"), Addr->GetProtocolType()) : nullptr;
	if (!Socket)
	{
		Finish(1006);
		return 1;
	}
	Socket->SetNoDelay(true);
	if (!Socket->Connect(*Addr) || !Handshake())
	{
		Finish(1006);
	}
	else
	{
		bOpen = true;
		FEvent E;
		E.Kind = FEvent::EKind::Connected;
		Events.Enqueue(MoveTemp(E));
		Socket->SetNonBlocking(true);
		ProcessBuffer();
		while (!bStopping && !bFinished)
		{
			FOutgoing O;
			bool bSendOk = true;
			while (bSendOk && Outgoing.Dequeue(O))
			{
				bSendOk = SendFrame(O.Opcode, O.Payload);
			}
			if (!bSendOk)
			{
				Finish(1006);
				break;
			}
			if (Socket->Wait(ESocketWaitConditions::WaitForRead, FTimespan::FromMilliseconds(5)))
			{
				if (!ReadAvailable())
				{
					Finish(1006);
					break;
				}
				uint32 Pending = 0;
				if (Buffer.Num() == 0 && !Socket->HasPendingData(Pending))
				{
					// Readable with nothing to read: the peer closed the connection.
					uint8 Probe = 0;
					int32 Read = 0;
					if (!Socket->Recv(&Probe, 1, Read, ESocketReceiveFlags::Peek) || Read == 0)
					{
						if (Socket->GetConnectionState() != SCS_Connected)
						{
							Finish(1006);
							break;
						}
					}
				}
				ProcessBuffer();
			}
		}
		if (!bFinished && CloseRequested != 0)
		{
			// Flush what the game queued before closing (lifecycle.bye, a last duel.result).
			FOutgoing Last;
			while (Outgoing.Dequeue(Last) && SendFrame(Last.Opcode, Last.Payload))
			{
			}
			const int32 Code = CloseRequested;
			TArray<uint8> Payload{uint8(Code >> 8), uint8(Code & 0xFF)};
			SendFrame(8, Payload);
			Finish(Code);
		}
	}
	Socket->Close();
	Subsystem->DestroySocket(Socket);
	Socket = nullptr;
	bOpen = false;
	return 0;
}
