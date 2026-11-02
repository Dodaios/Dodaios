#include "Stream/VerseStreamKey.h"

namespace
{
	constexpr uint32 K[64] = {
		0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
		0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
		0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
		0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
		0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
		0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
		0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
		0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
	};

	FORCEINLINE uint32 Rotr(uint32 X, uint32 N) { return (X >> N) | (X << (32 - N)); }

	void Compress(uint32 State[8], const uint8* Block)
	{
		uint32 W[64];
		for (int32 I = 0; I < 16; ++I)
		{
			W[I] = (uint32(Block[I * 4]) << 24) | (uint32(Block[I * 4 + 1]) << 16) | (uint32(Block[I * 4 + 2]) << 8)
				| uint32(Block[I * 4 + 3]);
		}
		for (int32 I = 16; I < 64; ++I)
		{
			const uint32 S0 = Rotr(W[I - 15], 7) ^ Rotr(W[I - 15], 18) ^ (W[I - 15] >> 3);
			const uint32 S1 = Rotr(W[I - 2], 17) ^ Rotr(W[I - 2], 19) ^ (W[I - 2] >> 10);
			W[I] = W[I - 16] + S0 + W[I - 7] + S1;
		}
		uint32 A = State[0], B = State[1], C = State[2], D = State[3];
		uint32 E = State[4], F = State[5], G = State[6], H = State[7];
		for (int32 I = 0; I < 64; ++I)
		{
			const uint32 S1 = Rotr(E, 6) ^ Rotr(E, 11) ^ Rotr(E, 25);
			const uint32 Ch = (E & F) ^ (~E & G);
			const uint32 T1 = H + S1 + Ch + K[I] + W[I];
			const uint32 S0 = Rotr(A, 2) ^ Rotr(A, 13) ^ Rotr(A, 22);
			const uint32 Maj = (A & B) ^ (A & C) ^ (B & C);
			const uint32 T2 = S0 + Maj;
			H = G;
			G = F;
			F = E;
			E = D + T1;
			D = C;
			C = B;
			B = A;
			A = T1 + T2;
		}
		State[0] += A;
		State[1] += B;
		State[2] += C;
		State[3] += D;
		State[4] += E;
		State[5] += F;
		State[6] += G;
		State[7] += H;
	}

	TArray<uint8> Utf8(const FString& Text)
	{
		const FTCHARToUTF8 Converted(*Text);
		return TArray<uint8>(reinterpret_cast<const uint8*>(Converted.Get()), Converted.Length());
	}

	/** 127.0.0.0/8 as a dotted quad, [::1], or localhost. */
	bool IsLoopbackHost(const FString& Host)
	{
		if (Host == TEXT("[::1]") || Host == TEXT("localhost"))
		{
			return true;
		}
		TArray<FString> Octets;
		Host.ParseIntoArray(Octets, TEXT("."), false);
		if (Octets.Num() != 4 || Octets[0] != TEXT("127"))
		{
			return false;
		}
		for (const FString& Octet : Octets)
		{
			if (Octet.IsEmpty() || Octet.Len() > 3 || !Octet.IsNumeric() || Octet.Contains(TEXT("-")) || Octet.Contains(TEXT("."))
				|| FCString::Atoi(*Octet) > 255)
			{
				return false;
			}
		}
		return true;
	}
}

TArray<uint8> VerseStreamKey::Sha256(TConstArrayView<uint8> Data)
{
	uint32 State[8] = { 0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19 };
	const int64 Len = Data.Num();
	int64 Offset = 0;
	for (; Offset + 64 <= Len; Offset += 64)
	{
		Compress(State, Data.GetData() + Offset);
	}
	uint8 Tail[128] = {};
	const int64 Rest = Len - Offset;
	if (Rest > 0)
	{
		FMemory::Memcpy(Tail, Data.GetData() + Offset, Rest);
	}
	Tail[Rest] = 0x80;
	const int32 TailLen = Rest + 1 + 8 <= 64 ? 64 : 128;
	const uint64 Bits = uint64(Len) * 8;
	for (int32 I = 0; I < 8; ++I)
	{
		Tail[TailLen - 1 - I] = uint8(Bits >> (8 * I));
	}
	Compress(State, Tail);
	if (TailLen == 128)
	{
		Compress(State, Tail + 64);
	}
	TArray<uint8> Out;
	Out.SetNumUninitialized(32);
	for (int32 I = 0; I < 8; ++I)
	{
		Out[I * 4] = uint8(State[I] >> 24);
		Out[I * 4 + 1] = uint8(State[I] >> 16);
		Out[I * 4 + 2] = uint8(State[I] >> 8);
		Out[I * 4 + 3] = uint8(State[I]);
	}
	return Out;
}

TArray<uint8> VerseStreamKey::HmacSha256(TConstArrayView<uint8> Key, TConstArrayView<uint8> Message)
{
	TArray<uint8> Block;
	if (Key.Num() > 64)
	{
		Block = Sha256(Key);
	}
	else
	{
		Block = TArray<uint8>(Key.GetData(), Key.Num());
	}
	Block.SetNumZeroed(64);
	TArray<uint8> Inner;
	Inner.Reserve(64 + Message.Num());
	TArray<uint8> Outer;
	Outer.Reserve(64 + 32);
	for (int32 I = 0; I < 64; ++I)
	{
		Inner.Add(Block[I] ^ 0x36);
		Outer.Add(Block[I] ^ 0x5c);
	}
	Inner.Append(Message.GetData(), Message.Num());
	Outer.Append(Sha256(Inner));
	return Sha256(Outer);
}

FString VerseStreamKey::ToHex(TConstArrayView<uint8> Bytes)
{
	static const TCHAR* Digits = TEXT("0123456789abcdef");
	FString Out;
	Out.Reserve(Bytes.Num() * 2);
	for (const uint8 Byte : Bytes)
	{
		Out.AppendChar(Digits[Byte >> 4]);
		Out.AppendChar(Digits[Byte & 0x0f]);
	}
	return Out;
}

FString VerseStreamKey::DeriveStreamerKey(const FString& LaunchToken)
{
	static const char Info[] = "verse.signal/1 streamer";
	const TArray<uint8> Key = Utf8(LaunchToken);
	const TArray<uint8> Message(reinterpret_cast<const uint8*>(Info), sizeof(Info) - 1);
	return ToHex(HmacSha256(Key, Message));
}

FString VerseStreamKey::BuildSignalUrl(const FString& BridgeUrl, const FString& LaunchToken)
{
	static const FString Scheme = TEXT("ws://");
	static const FString BridgePath = TEXT("/api/verse/bridge");
	if (LaunchToken.IsEmpty() || !BridgeUrl.StartsWith(Scheme, ESearchCase::IgnoreCase))
	{
		return FString();
	}
	const FString Rest = BridgeUrl.Mid(Scheme.Len());
	int32 Slash = INDEX_NONE;
	if (!Rest.FindChar(TEXT('/'), Slash))
	{
		return FString();
	}
	const FString HostPort = Rest.Left(Slash);
	const FString Path = Rest.Mid(Slash);
	if (Path != BridgePath)
	{
		return FString();
	}
	FString Host = HostPort;
	if (HostPort.StartsWith(TEXT("[")))
	{
		int32 Close = INDEX_NONE;
		if (!HostPort.FindChar(TEXT(']'), Close))
		{
			return FString();
		}
		Host = HostPort.Left(Close + 1);
	}
	else
	{
		int32 Colon = INDEX_NONE;
		if (HostPort.FindLastChar(TEXT(':'), Colon))
		{
			Host = HostPort.Left(Colon);
		}
	}
	if (!IsLoopbackHost(Host))
	{
		return FString();
	}
	return Scheme + HostPort + TEXT("/api/verse/signal?role=streamer&key=") + DeriveStreamerKey(LaunchToken);
}
