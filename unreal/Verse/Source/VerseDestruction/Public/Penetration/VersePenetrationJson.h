#pragma once

#include "CoreMinimal.h"

// A minimal JSON reader for the penetration table and its golden fixture. VerseDestruction
// links only Core, CoreUObject, Engine and VerseCore (architecture.md 2), and the engine's Json
// module is not among them, so this reads the subset those files use: objects, arrays,
// strings (with the usual escapes), numbers, true, false and null.

struct VERSEDESTRUCTION_API FVerseJson
{
	enum class EType : uint8
	{
		Null,
		Bool,
		Number,
		String,
		Array,
		Object
	};

	EType Type = EType::Null;
	bool Bool = false;
	double Number = 0.0;
	FString String;
	TArray<FVerseJson> Array;
	/** Keys in file order. */
	TArray<TPair<FString, FVerseJson>> Object;

	/** Parses Text; false and an error with the character offset on malformed input or trailing text. */
	static bool Parse(const FString& Text, FVerseJson& Out, FString& OutError);

	bool IsObject() const { return Type == EType::Object; }
	bool IsArray() const { return Type == EType::Array; }

	/** Member of an object, nullptr when absent or not an object. */
	const FVerseJson* Find(const TCHAR* Key) const;

	bool TryNumber(const TCHAR* Key, double& Out) const;
	bool TryString(const TCHAR* Key, FString& Out) const;
	bool TryBool(const TCHAR* Key, bool& Out) const;
	/** The member as an array, nullptr when absent or not an array. */
	const TArray<FVerseJson>* FindArray(const TCHAR* Key) const;

	double NumberOr(const TCHAR* Key, double Default) const;
	FString StringOr(const TCHAR* Key, const FString& Default = FString()) const;
	bool BoolOr(const TCHAR* Key, bool Default) const;
};
