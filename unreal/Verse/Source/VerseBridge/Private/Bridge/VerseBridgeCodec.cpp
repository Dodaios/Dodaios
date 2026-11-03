#include "Bridge/VerseBridgeCodec.h"

#include "Policies/CondensedJsonPrintPolicy.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
	bool ReadInt(const TSharedPtr<FJsonObject>& O, const TCHAR* Field, int64& Out)
	{
		const TSharedPtr<FJsonValue> V = O->TryGetField(Field);
		if (!V.IsValid() || V->Type != EJson::Number)
		{
			return false;
		}
		Out = static_cast<int64>(V->AsNumber());
		return true;
	}
}

bool FVerseBridgeFrame::Parse(const FString& Text, FVerseBridgeFrame& Out, FString* OutError)
{
	auto Fail = [OutError](const TCHAR* Why)
	{
		if (OutError)
		{
			*OutError = Why;
		}
		return false;
	};
	TSharedPtr<FJsonObject> Root = VerseBridgeJson::Read(Text);
	if (!Root.IsValid())
	{
		return Fail(TEXT("frame is not a JSON object"));
	}
	FString Type;
	if (!Root->TryGetStringField(TEXT("type"), Type) || Type.IsEmpty())
	{
		return Fail(TEXT("frame has no type"));
	}
	Out = FVerseBridgeFrame();
	Out.Type = Type;
	const TSharedPtr<FJsonValue> DataValue = Root->TryGetField(TEXT("data"));
	if (!DataValue.IsValid() || DataValue->Type == EJson::Null)
	{
		Out.Data = MakeShared<FJsonObject>();
	}
	else if (DataValue->Type == EJson::Object)
	{
		Out.Data = DataValue->AsObject();
	}
	else
	{
		return Fail(TEXT("data is not an object"));
	}
	ReadInt(Root, TEXT("seq"), Out.Seq);
	ReadInt(Root, TEXT("base"), Out.Base);
	Root->TryGetStringField(TEXT("id"), Out.Id);
	Root->TryGetStringField(TEXT("re"), Out.Re);
	Root->TryGetNumberField(TEXT("ts"), Out.Ts);
	return true;
}

FString FVerseBridgeFrame::Encode() const
{
	FString Out;
	TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> W = TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
	W->WriteObjectStart();
	W->WriteValue(TEXT("type"), Type);
	if (Seq >= 0)
	{
		W->WriteValue(TEXT("seq"), Seq);
	}
	if (Base >= 0)
	{
		W->WriteValue(TEXT("base"), Base);
	}
	if (!Re.IsEmpty())
	{
		W->WriteValue(TEXT("re"), Re);
	}
	if (!Id.IsEmpty())
	{
		W->WriteValue(TEXT("id"), Id);
	}
	W->WriteValue(TEXT("ts"), Ts);
	W->WriteIdentifierPrefix(TEXT("data"));
	FJsonSerializer::Serialize(Data.IsValid() ? Data.ToSharedRef() : MakeShared<FJsonObject>(), W, false);
	W->WriteObjectEnd();
	W->Close();
	return Out;
}

FVerseBridgeFrame FVerseBridgeFrame::Make(const FString& InType, TSharedPtr<FJsonObject> InData, const FString& InId)
{
	FVerseBridgeFrame F;
	F.Type = InType;
	F.Id = InId;
	F.Ts = FDateTime::UtcNow().ToUnixTimestampDecimal();
	F.Data = InData.IsValid() ? InData : MakeShared<FJsonObject>();
	return F;
}

namespace VerseBridgeJson
{
	bool Equal(const TSharedPtr<FJsonObject>& A, const TSharedPtr<FJsonObject>& B)
	{
		if (!A.IsValid() || !B.IsValid())
		{
			return A.IsValid() == B.IsValid();
		}
		if (A->Values.Num() != B->Values.Num())
		{
			return false;
		}
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : A->Values)
		{
			const TSharedPtr<FJsonValue>* Other = B->Values.Find(Pair.Key);
			if (!Other || !Equal(Pair.Value, *Other))
			{
				return false;
			}
		}
		return true;
	}

	bool Equal(const TSharedPtr<FJsonValue>& A, const TSharedPtr<FJsonValue>& B)
	{
		if (!A.IsValid() || !B.IsValid())
		{
			return A.IsValid() == B.IsValid();
		}
		if (A->Type != B->Type)
		{
			return false;
		}
		switch (A->Type)
		{
		case EJson::Null:
			return true;
		case EJson::String:
			return A->AsString() == B->AsString();
		case EJson::Number:
			return A->AsNumber() == B->AsNumber();
		case EJson::Boolean:
			return A->AsBool() == B->AsBool();
		case EJson::Array:
		{
			const TArray<TSharedPtr<FJsonValue>>& X = A->AsArray();
			const TArray<TSharedPtr<FJsonValue>>& Y = B->AsArray();
			if (X.Num() != Y.Num())
			{
				return false;
			}
			for (int32 I = 0; I < X.Num(); ++I)
			{
				if (!Equal(X[I], Y[I]))
				{
					return false;
				}
			}
			return true;
		}
		case EJson::Object:
			return Equal(A->AsObject(), B->AsObject());
		default:
			return false;
		}
	}

	FString Write(const TSharedPtr<FJsonObject>& Object)
	{
		FString Out;
		TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> W = TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
		FJsonSerializer::Serialize(Object.IsValid() ? Object.ToSharedRef() : MakeShared<FJsonObject>(), W);
		return Out;
	}

	TSharedPtr<FJsonObject> Read(const FString& Text)
	{
		TSharedPtr<FJsonObject> Root;
		TSharedRef<TJsonReader<TCHAR>> Reader = TJsonReaderFactory<TCHAR>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
		{
			return nullptr;
		}
		return Root;
	}

	FString Str(const TSharedPtr<FJsonObject>& O, const TCHAR* Field, const FString& Default)
	{
		FString V;
		return O.IsValid() && O->TryGetStringField(Field, V) ? V : Default;
	}

	int64 Int(const TSharedPtr<FJsonObject>& O, const TCHAR* Field, int64 Default)
	{
		double V = 0.0;
		return O.IsValid() && O->TryGetNumberField(Field, V) ? static_cast<int64>(V) : Default;
	}

	double Num(const TSharedPtr<FJsonObject>& O, const TCHAR* Field, double Default)
	{
		double V = 0.0;
		return O.IsValid() && O->TryGetNumberField(Field, V) ? V : Default;
	}

	bool Bool(const TSharedPtr<FJsonObject>& O, const TCHAR* Field, bool Default)
	{
		bool V = false;
		return O.IsValid() && O->TryGetBoolField(Field, V) ? V : Default;
	}

	TSharedPtr<FJsonObject> Obj(const TSharedPtr<FJsonObject>& O, const TCHAR* Field)
	{
		const TSharedPtr<FJsonObject>* V = nullptr;
		return O.IsValid() && O->TryGetObjectField(Field, V) && V ? *V : nullptr;
	}

	const TArray<TSharedPtr<FJsonValue>>* Arr(const TSharedPtr<FJsonObject>& O, const TCHAR* Field)
	{
		const TArray<TSharedPtr<FJsonValue>>* V = nullptr;
		return O.IsValid() && O->TryGetArrayField(Field, V) ? V : nullptr;
	}

	FString Enum(const TSharedPtr<FJsonObject>& O, const TCHAR* Field, std::initializer_list<const TCHAR*> Allowed, const TCHAR* Fallback)
	{
		const FString V = Str(O, Field);
		for (const TCHAR* A : Allowed)
		{
			if (V == A)
			{
				return V;
			}
		}
		return Fallback;
	}
}
