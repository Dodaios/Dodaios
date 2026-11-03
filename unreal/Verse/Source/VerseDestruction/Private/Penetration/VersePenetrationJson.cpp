#include "Penetration/VersePenetrationJson.h"

#include "Misc/Parse.h"

namespace
{
	class FReader
	{
	public:
		explicit FReader(const FString& InText) : Text(InText) {}

		bool ReadDocument(FVerseJson& Out, FString& OutError)
		{
			SkipSpace();
			if (!ReadValue(Out, 0))
			{
				OutError = FString::Printf(TEXT("%s at offset %d"), *Error, Pos);
				return false;
			}
			SkipSpace();
			if (Pos != Text.Len())
			{
				OutError = FString::Printf(TEXT("trailing text at offset %d"), Pos);
				return false;
			}
			return true;
		}

	private:
		const FString& Text;
		int32 Pos = 0;
		FString Error;

		static constexpr int32 MaxDepth = 64;

		TCHAR Peek() const { return Pos < Text.Len() ? Text[Pos] : TCHAR(0); }

		void SkipSpace()
		{
			while (Pos < Text.Len() && (Text[Pos] == ' ' || Text[Pos] == '\t' || Text[Pos] == '\r' || Text[Pos] == '\n'))
			{
				++Pos;
			}
		}

		bool Fail(const TCHAR* What)
		{
			Error = What;
			return false;
		}

		bool Literal(const TCHAR* Word)
		{
			const int32 Len = FCString::Strlen(Word);
			if (Text.Len() - Pos >= Len && FCString::Strncmp(*Text + Pos, Word, Len) == 0)
			{
				Pos += Len;
				return true;
			}
			return false;
		}

		bool ReadValue(FVerseJson& Out, int32 Depth)
		{
			if (Depth > MaxDepth)
			{
				return Fail(TEXT("nesting too deep"));
			}
			SkipSpace();
			const TCHAR C = Peek();
			if (C == '{')
			{
				return ReadObject(Out, Depth);
			}
			if (C == '[')
			{
				return ReadArray(Out, Depth);
			}
			if (C == '"')
			{
				Out.Type = FVerseJson::EType::String;
				return ReadString(Out.String);
			}
			if (Literal(TEXT("true")))
			{
				Out.Type = FVerseJson::EType::Bool;
				Out.Bool = true;
				return true;
			}
			if (Literal(TEXT("false")))
			{
				Out.Type = FVerseJson::EType::Bool;
				Out.Bool = false;
				return true;
			}
			if (Literal(TEXT("null")))
			{
				Out.Type = FVerseJson::EType::Null;
				return true;
			}
			if (C == '-' || FChar::IsDigit(C))
			{
				return ReadNumber(Out);
			}
			return Fail(TEXT("unexpected character"));
		}

		bool ReadNumber(FVerseJson& Out)
		{
			const int32 Start = Pos;
			if (Peek() == '-')
			{
				++Pos;
			}
			if (!FChar::IsDigit(Peek()))
			{
				return Fail(TEXT("bad number"));
			}
			while (FChar::IsDigit(Peek()))
			{
				++Pos;
			}
			if (Peek() == '.')
			{
				++Pos;
				if (!FChar::IsDigit(Peek()))
				{
					return Fail(TEXT("bad number"));
				}
				while (FChar::IsDigit(Peek()))
				{
					++Pos;
				}
			}
			if (Peek() == 'e' || Peek() == 'E')
			{
				++Pos;
				if (Peek() == '+' || Peek() == '-')
				{
					++Pos;
				}
				if (!FChar::IsDigit(Peek()))
				{
					return Fail(TEXT("bad number"));
				}
				while (FChar::IsDigit(Peek()))
				{
					++Pos;
				}
			}
			Out.Type = FVerseJson::EType::Number;
			Out.Number = FCString::Atod(*Text.Mid(Start, Pos - Start));
			return true;
		}

		bool ReadString(FString& Out)
		{
			++Pos; // opening quote
			Out.Reset();
			while (Pos < Text.Len())
			{
				const TCHAR C = Text[Pos++];
				if (C == '"')
				{
					return true;
				}
				if (C != '\\')
				{
					Out.AppendChar(C);
					continue;
				}
				if (Pos >= Text.Len())
				{
					break;
				}
				const TCHAR E = Text[Pos++];
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
					if (Text.Len() - Pos < 4)
					{
						return Fail(TEXT("bad unicode escape"));
					}
					uint32 Code = 0;
					for (int32 I = 0; I < 4; ++I)
					{
						const TCHAR H = Text[Pos++];
						if (!FChar::IsHexDigit(H))
						{
							return Fail(TEXT("bad unicode escape"));
						}
						Code = Code * 16 + FParse::HexDigit(H);
					}
					Out.AppendChar(TCHAR(Code));
					break;
				}
				default:
					return Fail(TEXT("bad escape"));
				}
			}
			return Fail(TEXT("unterminated string"));
		}

		bool ReadArray(FVerseJson& Out, int32 Depth)
		{
			++Pos;
			Out.Type = FVerseJson::EType::Array;
			SkipSpace();
			if (Peek() == ']')
			{
				++Pos;
				return true;
			}
			while (true)
			{
				if (!ReadValue(Out.Array.AddDefaulted_GetRef(), Depth + 1))
				{
					return false;
				}
				SkipSpace();
				if (Peek() == ',')
				{
					++Pos;
					continue;
				}
				if (Peek() == ']')
				{
					++Pos;
					return true;
				}
				return Fail(TEXT("expected , or ]"));
			}
		}

		bool ReadObject(FVerseJson& Out, int32 Depth)
		{
			++Pos;
			Out.Type = FVerseJson::EType::Object;
			SkipSpace();
			if (Peek() == '}')
			{
				++Pos;
				return true;
			}
			while (true)
			{
				SkipSpace();
				if (Peek() != '"')
				{
					return Fail(TEXT("expected a key"));
				}
				TPair<FString, FVerseJson>& Member = Out.Object.AddDefaulted_GetRef();
				if (!ReadString(Member.Key))
				{
					return false;
				}
				SkipSpace();
				if (Peek() != ':')
				{
					return Fail(TEXT("expected :"));
				}
				++Pos;
				if (!ReadValue(Member.Value, Depth + 1))
				{
					return false;
				}
				SkipSpace();
				if (Peek() == ',')
				{
					++Pos;
					continue;
				}
				if (Peek() == '}')
				{
					++Pos;
					return true;
				}
				return Fail(TEXT("expected , or }"));
			}
		}
	};
}

bool FVerseJson::Parse(const FString& Text, FVerseJson& Out, FString& OutError)
{
	Out = FVerseJson();
	FReader Reader(Text);
	return Reader.ReadDocument(Out, OutError);
}

const FVerseJson* FVerseJson::Find(const TCHAR* Key) const
{
	if (Type != EType::Object)
	{
		return nullptr;
	}
	for (const TPair<FString, FVerseJson>& Member : Object)
	{
		if (Member.Key == Key)
		{
			return &Member.Value;
		}
	}
	return nullptr;
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

bool FVerseJson::TryBool(const TCHAR* Key, bool& Out) const
{
	const FVerseJson* V = Find(Key);
	if (V && V->Type == EType::Bool)
	{
		Out = V->Bool;
		return true;
	}
	return false;
}

const TArray<FVerseJson>* FVerseJson::FindArray(const TCHAR* Key) const
{
	const FVerseJson* V = Find(Key);
	return V && V->Type == EType::Array ? &V->Array : nullptr;
}

double FVerseJson::NumberOr(const TCHAR* Key, double Default) const
{
	double Out = Default;
	TryNumber(Key, Out);
	return Out;
}

FString FVerseJson::StringOr(const TCHAR* Key, const FString& Default) const
{
	FString Out = Default;
	TryString(Key, Out);
	return Out;
}

bool FVerseJson::BoolOr(const TCHAR* Key, bool Default) const
{
	bool Out = Default;
	TryBool(Key, Out);
	return Out;
}
