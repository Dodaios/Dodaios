#pragma once

#include "CoreMinimal.h"
#include "Templates/SharedPointer.h"

/**
 * A small strict JSON reader for the bot data files (tiers.json, adaptive.json). VerseBot links no
 * JSON module, and these files only need objects, arrays, numbers, strings and literals.
 * Duplicate object keys are an error, so a field can never be set twice.
 */
namespace VerseBotJsonLite
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

	struct FValue
	{
		EType Type = EType::Null;
		bool bBool = false;
		double Number = 0.0;
		FString String;
		TArray<TSharedRef<FValue>> Array;
		/** Keys in file order. */
		TArray<TPair<FString, TSharedRef<FValue>>> Object;

		const FValue* Find(const FString& Key) const
		{
			for (const TPair<FString, TSharedRef<FValue>>& Pair : Object)
			{
				if (Pair.Key == Key)
				{
					return &Pair.Value.Get();
				}
			}
			return nullptr;
		}
	};

	/** Parses Text; on failure returns null and sets Error (with the character offset). */
	TSharedPtr<FValue> Parse(const FString& Text, FString& Error);
}
