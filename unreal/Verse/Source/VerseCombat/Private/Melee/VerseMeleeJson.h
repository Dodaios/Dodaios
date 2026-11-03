#pragma once

#include "CoreMinimal.h"

/**
 * A small strict JSON reader for the melee text surface. VerseCombat does not link the
 * engine's Json module (its Build.cs belongs to the integration owner), and the importer only
 * needs objects, strings and numbers. Arrays, booleans and null parse but are not used.
 */
struct FVerseMeleeJson
{
	enum class EType : uint8 { Null, Bool, Number, String, Array, Object };

	EType Type = EType::Null;
	bool Bool = false;
	double Number = 0.0;
	FString String;
	TArray<TSharedPtr<FVerseMeleeJson>> Array;
	TMap<FString, TSharedPtr<FVerseMeleeJson>> Object;

	/** Parses a whole document; nullptr with OutError on any syntax error or trailing text. */
	static TSharedPtr<FVerseMeleeJson> Parse(const FString& Text, FString& OutError)
	{
		FParser P{*Text, 0, Text.Len(), OutError};
		TSharedPtr<FVerseMeleeJson> Root = P.Value(0);
		P.Space();
		if (Root.IsValid() && P.Pos != P.Len)
		{
			OutError = FString::Printf(TEXT("trailing text at %d"), P.Pos);
			return nullptr;
		}
		return Root;
	}

	const FVerseMeleeJson* Field(const TCHAR* Name, EType Want) const
	{
		const TSharedPtr<FVerseMeleeJson>* Found = Type == EType::Object ? Object.Find(Name) : nullptr;
		return (Found && Found->IsValid() && (*Found)->Type == Want) ? Found->Get() : nullptr;
	}

private:
	struct FParser
	{
		const TCHAR* S;
		int32 Pos;
		int32 Len;
		FString& Error;

		void Space()
		{
			while (Pos < Len && FChar::IsWhitespace(S[Pos]))
			{
				++Pos;
			}
		}

		TSharedPtr<FVerseMeleeJson> Fail(const TCHAR* What)
		{
			if (Error.IsEmpty())
			{
				Error = FString::Printf(TEXT("%s at %d"), What, Pos);
			}
			return nullptr;
		}

		bool Literal(const TCHAR* Word)
		{
			const int32 N = FCString::Strlen(Word);
			if (Pos + N <= Len && FCString::Strncmp(S + Pos, Word, N) == 0)
			{
				Pos += N;
				return true;
			}
			return false;
		}

		bool StringBody(FString& Out)
		{
			++Pos; // opening quote
			while (Pos < Len)
			{
				const TCHAR C = S[Pos++];
				if (C == TEXT('"'))
				{
					return true;
				}
				if (C == TEXT('\\'))
				{
					if (Pos >= Len)
					{
						return false;
					}
					const TCHAR E = S[Pos++];
					switch (E)
					{
					case TEXT('"'): Out.AppendChar(TEXT('"')); break;
					case TEXT('\\'): Out.AppendChar(TEXT('\\')); break;
					case TEXT('/'): Out.AppendChar(TEXT('/')); break;
					case TEXT('n'): Out.AppendChar(TEXT('\n')); break;
					case TEXT('t'): Out.AppendChar(TEXT('\t')); break;
					case TEXT('r'): Out.AppendChar(TEXT('\r')); break;
					case TEXT('b'): Out.AppendChar(TEXT('\b')); break;
					case TEXT('f'): Out.AppendChar(TEXT('\f')); break;
					case TEXT('u'):
					{
						if (Pos + 4 > Len)
						{
							return false;
						}
						Out.AppendChar(TCHAR(FParse::HexNumber(*FString::ConstructFromPtrSize(S + Pos, 4))));
						Pos += 4;
						break;
					}
					default:
						return false;
					}
				}
				else
				{
					Out.AppendChar(C);
				}
			}
			return false;
		}

		TSharedPtr<FVerseMeleeJson> Value(int32 Depth)
		{
			if (Depth > 32)
			{
				return Fail(TEXT("nesting too deep"));
			}
			Space();
			if (Pos >= Len)
			{
				return Fail(TEXT("unexpected end"));
			}
			TSharedPtr<FVerseMeleeJson> V = MakeShared<FVerseMeleeJson>();
			const TCHAR C = S[Pos];
			if (C == TEXT('{'))
			{
				V->Type = EType::Object;
				++Pos;
				Space();
				if (Pos < Len && S[Pos] == TEXT('}'))
				{
					++Pos;
					return V;
				}
				while (true)
				{
					Space();
					if (Pos >= Len || S[Pos] != TEXT('"'))
					{
						return Fail(TEXT("expected a key"));
					}
					FString Key;
					if (!StringBody(Key))
					{
						return Fail(TEXT("bad key"));
					}
					Space();
					if (Pos >= Len || S[Pos] != TEXT(':'))
					{
						return Fail(TEXT("expected ':'"));
					}
					++Pos;
					TSharedPtr<FVerseMeleeJson> Child = Value(Depth + 1);
					if (!Child.IsValid())
					{
						return nullptr;
					}
					V->Object.Add(Key, Child);
					Space();
					if (Pos < Len && S[Pos] == TEXT(','))
					{
						++Pos;
						continue;
					}
					if (Pos < Len && S[Pos] == TEXT('}'))
					{
						++Pos;
						return V;
					}
					return Fail(TEXT("expected ',' or '}'"));
				}
			}
			if (C == TEXT('['))
			{
				V->Type = EType::Array;
				++Pos;
				Space();
				if (Pos < Len && S[Pos] == TEXT(']'))
				{
					++Pos;
					return V;
				}
				while (true)
				{
					TSharedPtr<FVerseMeleeJson> Child = Value(Depth + 1);
					if (!Child.IsValid())
					{
						return nullptr;
					}
					V->Array.Add(Child);
					Space();
					if (Pos < Len && S[Pos] == TEXT(','))
					{
						++Pos;
						continue;
					}
					if (Pos < Len && S[Pos] == TEXT(']'))
					{
						++Pos;
						return V;
					}
					return Fail(TEXT("expected ',' or ']'"));
				}
			}
			if (C == TEXT('"'))
			{
				V->Type = EType::String;
				return StringBody(V->String) ? V : Fail(TEXT("bad string"));
			}
			if (Literal(TEXT("true")))
			{
				V->Type = EType::Bool;
				V->Bool = true;
				return V;
			}
			if (Literal(TEXT("false")))
			{
				V->Type = EType::Bool;
				return V;
			}
			if (Literal(TEXT("null")))
			{
				return V;
			}
			const int32 Begin = Pos;
			while (Pos < Len && (FChar::IsDigit(S[Pos]) || S[Pos] == TEXT('-') || S[Pos] == TEXT('+')
				|| S[Pos] == TEXT('.') || S[Pos] == TEXT('e') || S[Pos] == TEXT('E')))
			{
				++Pos;
			}
			if (Pos == Begin)
			{
				return Fail(TEXT("unexpected character"));
			}
			const FString Token = FString::ConstructFromPtrSize(S + Begin, Pos - Begin);
			if (!(FChar::IsDigit(Token[0]) || Token[0] == TEXT('-')) || !FChar::IsDigit(Token[Token.Len() - 1]))
			{
				return Fail(TEXT("bad number"));
			}
			V->Type = EType::Number;
			V->Number = FCString::Atod(*Token);
			return V;
		}
	};
};
