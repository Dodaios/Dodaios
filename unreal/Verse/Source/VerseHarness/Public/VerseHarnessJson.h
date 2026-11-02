#pragma once

#include "CoreMinimal.h"

/**
 * A small JSON reader and writer for the harness files (verse.scenario/1, verse.capture/1,
 * person_models.json, verse.bout/1, speed.json). VerseHarness links only Core, CoreUObject,
 * Engine and the Verse modules (VerseHarness.Build.cs belongs to the integration owner), so it
 * cannot link the engine's Json module; these documents are small and plain, so this is enough.
 */
struct VERSEHARNESS_API FVerseJson
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
	bool bBool = false;
	double Number = 0.0;
	FString String;
	TArray<TSharedPtr<FVerseJson>> Array;
	/** Members in document order. */
	TArray<TPair<FString, TSharedPtr<FVerseJson>>> Object;

	static TSharedPtr<FVerseJson> Parse(const FString& Text, FString& OutError);

	bool IsObject() const { return Type == EType::Object; }
	const FVerseJson* Find(const TCHAR* Key) const;

	bool TryString(const TCHAR* Key, FString& Out) const;
	bool TryNumber(const TCHAR* Key, double& Out) const;
	bool TryInt(const TCHAR* Key, int32& Out) const;
	bool TryFloat(const TCHAR* Key, float& Out) const;
	bool TryBool(const TCHAR* Key, bool& Out) const;
	const FVerseJson* ObjectField(const TCHAR* Key) const;
	const TArray<TSharedPtr<FVerseJson>>* ArrayField(const TCHAR* Key) const;
	FString StringOr(const TCHAR* Key, const FString& Default = FString()) const;

	/** Compact serialisation of this value. */
	FString ToString() const;
};

/** Builds one compact JSON object; values are appended in call order. */
class VERSEHARNESS_API FVerseJsonWriter
{
public:
	FVerseJsonWriter& Str(const TCHAR* Key, const FString& Value);
	FVerseJsonWriter& Num(const TCHAR* Key, double Value);
	FVerseJsonWriter& Bool(const TCHAR* Key, bool Value);
	FVerseJsonWriter& Null(const TCHAR* Key);
	/** Raw, already-serialised JSON (an object, array or number). */
	FVerseJsonWriter& Raw(const TCHAR* Key, const FString& Json);
	FVerseJsonWriter& Numbers(const TCHAR* Key, const TArray<float>& Values);

	FString Close() const { return TEXT("{") + Body + TEXT("}"); }

	static FString Quote(const FString& Text);
	static FString Number(double Value);

private:
	void Key(const TCHAR* Name);
	FString Body;
};
