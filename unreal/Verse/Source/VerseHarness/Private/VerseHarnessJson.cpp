#include "VerseHarnessJson.h"

#include "Misc/Parse.h"

namespace VerseHarnessJsonPrivate
{
	constexpr int32 MaxDepth = 64;

	struct FReader
	{
		const TCHAR* At;
		const TCHAR* End;
		FString Error;

		void Skip()
		{
			while (At < End && (*At == ' ' || *At == '\t' || *At == '\n' || *At == '\r'))
			{
				++At;
			}
		}

		bool Fail(const TCHAR* Why)
		{
			if (Error.IsEmpty())
			{
				Error = Why;
			}
			return false;
		}

		bool Literal(const TCHAR* Word)
		{
			const int32 Len = FCString::Strlen(Word);
			if (End - At >= Len && FCString::Strncmp(At, Word, Len) == 0)
			{
				At += Len;
				return true;
			}
			return false;
		}

		bool ParseString(FString& Out)
		{
			if (At >= End || *At != '"')
			{
				return Fail(TEXT("expected a string"));
			}
			++At;
			while (At < End && *At != '"')
			{
				TCHAR C = *At++;
				if (C == '\\')
				{
					if (At >= End)
					{
						return Fail(TEXT("unterminated escape"));
					}
					const TCHAR E = *At++;
					switch (E)
					{
					case '"': Out.AppendChar('"'); break;
					case '\\': Out.AppendChar('\\'); break;
					case '/': Out.AppendChar('/'); break;
					case 'b': Out.AppendChar('\b'); break;
					case 'f': Out.AppendChar('\f'); break;
					case 'n': Out.AppendChar('\n'); break;
					case 'r': Out.AppendChar('\r'); break;
					case 't': Out.AppendChar('\t'); break;
					case 'u':
					{
						if (End - At < 4)
						{
							return Fail(TEXT("short unicode escape"));
						}
						const FString Hex(4, At);
						At += 4;
						Out.AppendChar(TCHAR(FParse::HexNumber(*Hex)));
						break;
					}
					default:
						return Fail(TEXT("unknown escape"));
					}
				}
				else
				{
					Out.AppendChar(C);
				}
			}
			if (At >= End)
			{
				return Fail(TEXT("unterminated string"));
			}
			++At;
			return true;
		}

		bool ParseValue(FVerseJson& Out, int32 Depth)
		{
			if (Depth > MaxDepth)
			{
				return Fail(TEXT("nested too deep"));
			}
			Skip();
			if (At >= End)
			{
				return Fail(TEXT("unexpected end"));
			}
			const TCHAR C = *At;
			if (C == '{')
			{
				Out.Type = FVerseJson::EType::Object;
				++At;
				Skip();
				if (At < End && *At == '}')
				{
					++At;
					return true;
				}
				while (true)
				{
					Skip();
					FString Key;
					if (!ParseString(Key))
					{
						return false;
					}
					Skip();
					if (At >= End || *At != ':')
					{
						return Fail(TEXT("expected ':'"));
					}
					++At;
					TSharedPtr<FVerseJson> Child = MakeShared<FVerseJson>();
					if (!ParseValue(*Child, Depth + 1))
					{
						return false;
					}
					Out.Object.Emplace(MoveTemp(Key), Child);
					Skip();
					if (At < End && *At == ',')
					{
						++At;
						continue;
					}
					if (At < End && *At == '}')
					{
						++At;
						return true;
					}
					return Fail(TEXT("expected ',' or '}'"));
				}
			}
			if (C == '[')
			{
				Out.Type = FVerseJson::EType::Array;
				++At;
				Skip();
				if (At < End && *At == ']')
				{
					++At;
					return true;
				}
				while (true)
				{
					TSharedPtr<FVerseJson> Child = MakeShared<FVerseJson>();
					if (!ParseValue(*Child, Depth + 1))
					{
						return false;
					}
					Out.Array.Add(Child);
					Skip();
					if (At < End && *At == ',')
					{
						++At;
						continue;
					}
					if (At < End && *At == ']')
					{
						++At;
						return true;
					}
					return Fail(TEXT("expected ',' or ']'"));
				}
			}
			if (C == '"')
			{
				Out.Type = FVerseJson::EType::String;
				return ParseString(Out.String);
			}
			if (Literal(TEXT("true")))
			{
				Out.Type = FVerseJson::EType::Bool;
				Out.bBool = true;
				return true;
			}
			if (Literal(TEXT("false")))
			{
				Out.Type = FVerseJson::EType::Bool;
				return true;
			}
			if (Literal(TEXT("null")))
			{
				Out.Type = FVerseJson::EType::Null;
				return true;
			}
			const TCHAR* Start = At;
			while (At < End && (FChar::IsDigit(*At) || *At == '-' || *At == '+' || *At == '.' || *At == 'e' || *At == 'E'))
			{
				++At;
			}
			if (At == Start)
			{
				return Fail(TEXT("unexpected character"));
			}
			Out.Type = FVerseJson::EType::Number;
			Out.Number = FCString::Atod(*FString(int32(At - Start), Start));
			return true;
		}
	};
}

TSharedPtr<FVerseJson> FVerseJson::Parse(const FString& Text, FString& OutError)
{
	VerseHarnessJsonPrivate::FReader Reader{*Text, *Text + Text.Len(), FString()};
	TSharedPtr<FVerseJson> Root = MakeShared<FVerseJson>();
	if (!Reader.ParseValue(*Root, 0))
	{
		OutError = Reader.Error;
		return nullptr;
	}
	Reader.Skip();
	if (Reader.At != Reader.End)
	{
		OutError = TEXT("trailing characters after the document");
		return nullptr;
	}
	return Root;
}

const FVerseJson* FVerseJson::Find(const TCHAR* Key) const
{
	for (const TPair<FString, TSharedPtr<FVerseJson>>& Member : Object)
	{
		if (Member.Key == Key)
		{
			return Member.Value.Get();
		}
	}
	return nullptr;
}

bool FVerseJson::TryString(const TCHAR* Key, FString& Out) const
{
	const FVerseJson* V = Find(Key);
	if (V && V->Type == EType::String)
	{
		Out = V->String;
		return true;
	}
	return false;
}

bool FVerseJson::TryNumber(const TCHAR* Key, double& Out) const
{
	const FVerseJson* V = Find(Key);
	if (V && V->Type == EType::Number)
	{
		Out = V->Number;
		return true;
	}
	return false;
}

bool FVerseJson::TryInt(const TCHAR* Key, int32& Out) const
{
	double Value = 0.0;
	if (TryNumber(Key, Value))
	{
		Out = int32(Value);
		return true;
	}
	return false;
}

bool FVerseJson::TryFloat(const TCHAR* Key, float& Out) const
{
	double Value = 0.0;
	if (TryNumber(Key, Value))
	{
		Out = float(Value);
		return true;
	}
	return false;
}

bool FVerseJson::TryBool(const TCHAR* Key, bool& Out) const
{
	const FVerseJson* V = Find(Key);
	if (V && V->Type == EType::Bool)
	{
		Out = V->bBool;
		return true;
	}
	return false;
}

const FVerseJson* FVerseJson::ObjectField(const TCHAR* Key) const
{
	const FVerseJson* V = Find(Key);
	return V && V->Type == EType::Object ? V : nullptr;
}

const TArray<TSharedPtr<FVerseJson>>* FVerseJson::ArrayField(const TCHAR* Key) const
{
	const FVerseJson* V = Find(Key);
	return V && V->Type == EType::Array ? &V->Array : nullptr;
}

FString FVerseJson::StringOr(const TCHAR* Key, const FString& Default) const
{
	FString Out;
	return TryString(Key, Out) ? Out : Default;
}

FString FVerseJson::ToString() const
{
	switch (Type)
	{
	case EType::Bool:
		return bBool ? TEXT("true") : TEXT("false");
	case EType::Number:
		return FVerseJsonWriter::Number(Number);
	case EType::String:
		return FVerseJsonWriter::Quote(String);
	case EType::Array:
	{
		TArray<FString> Parts;
		for (const TSharedPtr<FVerseJson>& V : Array)
		{
			Parts.Add(V.IsValid() ? V->ToString() : TEXT("null"));
		}
		return TEXT("[") + FString::Join(Parts, TEXT(",")) + TEXT("]");
	}
	case EType::Object:
	{
		TArray<FString> Parts;
		for (const TPair<FString, TSharedPtr<FVerseJson>>& M : Object)
		{
			Parts.Add(FVerseJsonWriter::Quote(M.Key) + TEXT(":") + (M.Value.IsValid() ? M.Value->ToString() : TEXT("null")));
		}
		return TEXT("{") + FString::Join(Parts, TEXT(",")) + TEXT("}");
	}
	default:
		return TEXT("null");
	}
}

FString FVerseJsonWriter::Quote(const FString& Text)
{
	FString Out(TEXT("\""));
	for (const TCHAR C : Text)
	{
		switch (C)
		{
		case '"': Out += TEXT("\\\""); break;
		case '\\': Out += TEXT("\\\\"); break;
		case '\n': Out += TEXT("\\n"); break;
		case '\r': Out += TEXT("\\r"); break;
		case '\t': Out += TEXT("\\t"); break;
		default:
			if (C < 0x20)
			{
				Out += FString::Printf(TEXT("\\u%04x"), uint32(C));
			}
			else
			{
				Out.AppendChar(C);
			}
		}
	}
	Out.AppendChar('"');
	return Out;
}

FString FVerseJsonWriter::Number(double Value)
{
	if (!FMath::IsFinite(Value))
	{
		return TEXT("null");
	}
	if (FMath::Abs(Value) < 9.0e15 && Value == FMath::RoundToDouble(Value))
	{
		return FString::Printf(TEXT("%lld"), int64(Value));
	}
	FString Text = FString::Printf(TEXT("%.6f"), Value);
	while (Text.EndsWith(TEXT("0")))
	{
		Text.LeftChopInline(1);
	}
	// A value that rounds to a whole number at six places ("5.000000") must not end in a bare point.
	if (Text.EndsWith(TEXT(".")))
	{
		Text.LeftChopInline(1);
	}
	if (Text == TEXT("-0"))
	{
		Text = TEXT("0");
	}
	return Text;
}

void FVerseJsonWriter::Key(const TCHAR* Name)
{
	if (!Body.IsEmpty())
	{
		Body.AppendChar(',');
	}
	Body += Quote(Name);
	Body.AppendChar(':');
}

FVerseJsonWriter& FVerseJsonWriter::Str(const TCHAR* K, const FString& Value)
{
	Key(K);
	Body += Quote(Value);
	return *this;
}

FVerseJsonWriter& FVerseJsonWriter::Num(const TCHAR* K, double Value)
{
	Key(K);
	Body += Number(Value);
	return *this;
}

FVerseJsonWriter& FVerseJsonWriter::Bool(const TCHAR* K, bool Value)
{
	Key(K);
	Body += Value ? TEXT("true") : TEXT("false");
	return *this;
}

FVerseJsonWriter& FVerseJsonWriter::Null(const TCHAR* K)
{
	Key(K);
	Body += TEXT("null");
	return *this;
}

FVerseJsonWriter& FVerseJsonWriter::Raw(const TCHAR* K, const FString& Json)
{
	Key(K);
	Body += Json;
	return *this;
}

FVerseJsonWriter& FVerseJsonWriter::Numbers(const TCHAR* K, const TArray<float>& Values)
{
	TArray<FString> Parts;
	for (float V : Values)
	{
		Parts.Add(Number(V));
	}
	return Raw(K, TEXT("[") + FString::Join(Parts, TEXT(",")) + TEXT("]"));
}
