#include "Tiers/VerseBotJsonLite.h"

namespace VerseBotJsonLite
{
	namespace
	{
		struct FParser
		{
			const FString& Text;
			int32 Pos = 0;
			FString Error;

			explicit FParser(const FString& InText) : Text(InText) {}

			bool Fail(const TCHAR* What)
			{
				if (Error.IsEmpty())
				{
					Error = FString::Printf(TEXT("%s at offset %d"), What, Pos);
				}
				return false;
			}

			void SkipWhitespace()
			{
				while (Pos < Text.Len() && (Text[Pos] == ' ' || Text[Pos] == '\t' || Text[Pos] == '\n' || Text[Pos] == '\r'))
				{
					++Pos;
				}
			}

			bool Literal(const TCHAR* Word)
			{
				const int32 Len = FCString::Strlen(Word);
				if (Text.Mid(Pos, Len) == Word)
				{
					Pos += Len;
					return true;
				}
				return Fail(TEXT("unexpected token"));
			}

			bool ParseString(FString& Out)
			{
				if (Pos >= Text.Len() || Text[Pos] != '"')
				{
					return Fail(TEXT("expected a string"));
				}
				++Pos;
				while (Pos < Text.Len())
				{
					const TCHAR C = Text[Pos++];
					if (C == '"')
					{
						return true;
					}
					if (C == '\\')
					{
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
							if (Pos + 4 > Text.Len())
							{
								return Fail(TEXT("short unicode escape"));
							}
							const FString Hex = Text.Mid(Pos, 4);
							for (const TCHAR H : Hex)
							{
								if (!FChar::IsHexDigit(H))
								{
									return Fail(TEXT("bad unicode escape"));
								}
							}
							Out.AppendChar(TCHAR(FParse::HexNumber(*Hex)));
							Pos += 4;
							break;
						}
						default: return Fail(TEXT("bad escape"));
						}
						continue;
					}
					if (C < 0x20)
					{
						return Fail(TEXT("control character in a string"));
					}
					Out.AppendChar(C);
				}
				return Fail(TEXT("unterminated string"));
			}

			bool ParseNumber(double& Out)
			{
				const int32 Start = Pos;
				if (Pos < Text.Len() && Text[Pos] == '-') ++Pos;
				if (Pos >= Text.Len() || !FChar::IsDigit(Text[Pos])) return Fail(TEXT("bad number"));
				if (Text[Pos] == '0') ++Pos;
				else while (Pos < Text.Len() && FChar::IsDigit(Text[Pos])) ++Pos;
				if (Pos < Text.Len() && Text[Pos] == '.')
				{
					++Pos;
					if (Pos >= Text.Len() || !FChar::IsDigit(Text[Pos])) return Fail(TEXT("bad fraction"));
					while (Pos < Text.Len() && FChar::IsDigit(Text[Pos])) ++Pos;
				}
				if (Pos < Text.Len() && (Text[Pos] == 'e' || Text[Pos] == 'E'))
				{
					++Pos;
					if (Pos < Text.Len() && (Text[Pos] == '+' || Text[Pos] == '-')) ++Pos;
					if (Pos >= Text.Len() || !FChar::IsDigit(Text[Pos])) return Fail(TEXT("bad exponent"));
					while (Pos < Text.Len() && FChar::IsDigit(Text[Pos])) ++Pos;
				}
				Out = FCString::Atod(*Text.Mid(Start, Pos - Start));
				return true;
			}

			bool ParseValue(FValue& Out, int32 Depth)
			{
				if (Depth > 32)
				{
					return Fail(TEXT("nesting too deep"));
				}
				SkipWhitespace();
				if (Pos >= Text.Len())
				{
					return Fail(TEXT("unexpected end"));
				}
				const TCHAR C = Text[Pos];
				if (C == '{')
				{
					Out.Type = EType::Object;
					++Pos;
					SkipWhitespace();
					if (Pos < Text.Len() && Text[Pos] == '}')
					{
						++Pos;
						return true;
					}
					for (;;)
					{
						SkipWhitespace();
						FString Key;
						if (!ParseString(Key)) return false;
						if (Out.Find(Key)) return Fail(TEXT("duplicate key"));
						SkipWhitespace();
						if (Pos >= Text.Len() || Text[Pos] != ':') return Fail(TEXT("expected ':'"));
						++Pos;
						TSharedRef<FValue> Child = MakeShared<FValue>();
						if (!ParseValue(Child.Get(), Depth + 1)) return false;
						Out.Object.Emplace(MoveTemp(Key), Child);
						SkipWhitespace();
						if (Pos < Text.Len() && Text[Pos] == ',') { ++Pos; continue; }
						if (Pos < Text.Len() && Text[Pos] == '}') { ++Pos; return true; }
						return Fail(TEXT("expected ',' or '}'"));
					}
				}
				if (C == '[')
				{
					Out.Type = EType::Array;
					++Pos;
					SkipWhitespace();
					if (Pos < Text.Len() && Text[Pos] == ']')
					{
						++Pos;
						return true;
					}
					for (;;)
					{
						TSharedRef<FValue> Child = MakeShared<FValue>();
						if (!ParseValue(Child.Get(), Depth + 1)) return false;
						Out.Array.Add(Child);
						SkipWhitespace();
						if (Pos < Text.Len() && Text[Pos] == ',') { ++Pos; continue; }
						if (Pos < Text.Len() && Text[Pos] == ']') { ++Pos; return true; }
						return Fail(TEXT("expected ',' or ']'"));
					}
				}
				if (C == '"')
				{
					Out.Type = EType::String;
					return ParseString(Out.String);
				}
				if (C == 't')
				{
					Out.Type = EType::Bool;
					Out.bBool = true;
					return Literal(TEXT("true"));
				}
				if (C == 'f')
				{
					Out.Type = EType::Bool;
					return Literal(TEXT("false"));
				}
				if (C == 'n')
				{
					Out.Type = EType::Null;
					return Literal(TEXT("null"));
				}
				Out.Type = EType::Number;
				return ParseNumber(Out.Number);
			}
		};
	}

	TSharedPtr<FValue> Parse(const FString& Text, FString& Error)
	{
		FParser Parser(Text);
		TSharedRef<FValue> Root = MakeShared<FValue>();
		if (!Parser.ParseValue(Root.Get(), 0))
		{
			Error = Parser.Error;
			return nullptr;
		}
		Parser.SkipWhitespace();
		if (Parser.Pos != Text.Len())
		{
			Parser.Fail(TEXT("trailing characters"));
			Error = Parser.Error;
			return nullptr;
		}
		return Root;
	}
}
