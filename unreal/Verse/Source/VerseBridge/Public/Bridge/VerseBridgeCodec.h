#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

/**
 * verse.bridge/1 envelope (docs/verse/unreal/contracts/bridge-protocol.md section 2).
 *
 * Every JSON frame is one object { type, seq?, base?, id?, re?, ts, data }. Unknown fields are
 * ignored; a frame without a string "type" or with a non-object "data" is malformed.
 */
namespace VerseBridge
{
	static constexpr const TCHAR* Protocol = TEXT("verse.bridge/1");

	/** Close codes of contract section 1. */
	enum class ECloseCode : int32
	{
		Normal = 1000,
		TooBig = 1009,
		TryLater = 1013,
		BadHello = 4400,
		Token = 4401,
		Peer = 4403,
		Replaced = 4409,
		Protocol = 4426,
	};
}

struct VERSEBRIDGE_API FVerseBridgeFrame
{
	FString Type;
	/** -1 when absent (Verse -> server frames carry none). */
	int64 Seq = -1;
	int64 Base = -1;
	FString Id;
	FString Re;
	double Ts = 0.0;
	TSharedPtr<FJsonObject> Data;

	bool HasBase() const { return Base >= 0; }
	bool IsReply() const { return Type == TEXT("reply"); }

	/** Parses one text frame; false on a malformed envelope. */
	static bool Parse(const FString& Text, FVerseBridgeFrame& Out, FString* OutError = nullptr);

	/** Compact JSON in the envelope order type, seq, base, re, id, ts, data. */
	FString Encode() const;

	/** A Verse -> server frame: { type, id?, ts, data }. */
	static FVerseBridgeFrame Make(const FString& Type, TSharedPtr<FJsonObject> Data, const FString& Id = FString());
};

namespace VerseBridgeJson
{
	/** Deep equality of two JSON values (object key order ignored, numbers by value). */
	VERSEBRIDGE_API bool Equal(const TSharedPtr<FJsonValue>& A, const TSharedPtr<FJsonValue>& B);
	VERSEBRIDGE_API bool Equal(const TSharedPtr<FJsonObject>& A, const TSharedPtr<FJsonObject>& B);
	VERSEBRIDGE_API FString Write(const TSharedPtr<FJsonObject>& Object);
	VERSEBRIDGE_API TSharedPtr<FJsonObject> Read(const FString& Text);

	VERSEBRIDGE_API FString Str(const TSharedPtr<FJsonObject>& O, const TCHAR* Field, const FString& Default = FString());
	VERSEBRIDGE_API int64 Int(const TSharedPtr<FJsonObject>& O, const TCHAR* Field, int64 Default = 0);
	VERSEBRIDGE_API double Num(const TSharedPtr<FJsonObject>& O, const TCHAR* Field, double Default = 0.0);
	VERSEBRIDGE_API bool Bool(const TSharedPtr<FJsonObject>& O, const TCHAR* Field, bool Default = false);
	VERSEBRIDGE_API TSharedPtr<FJsonObject> Obj(const TSharedPtr<FJsonObject>& O, const TCHAR* Field);
	VERSEBRIDGE_API const TArray<TSharedPtr<FJsonValue>>* Arr(const TSharedPtr<FJsonObject>& O, const TCHAR* Field);

	/** An enum value as sent, or the documented fallback for anything else (contract 2). */
	VERSEBRIDGE_API FString Enum(const TSharedPtr<FJsonObject>& O, const TCHAR* Field, std::initializer_list<const TCHAR*> Allowed, const TCHAR* Fallback);
}
