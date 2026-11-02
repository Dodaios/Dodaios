#include "Weapons/VerseDefinitionJson.h"

#include "Combat/VerseGadgetDefinition.h"
#include "Combat/VerseWeaponDefinition.h"
#include "Curves/CurveFloat.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "GameplayTagContainer.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Policies/PrettyJsonPrintPolicy.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/EnumProperty.h"
#include "UObject/TextProperty.h"
#include "UObject/UnrealType.h"

const TCHAR* FVerseDefinitionJson::WeaponSchema = TEXT("verse.weapon/1");
const TCHAR* FVerseDefinitionJson::GadgetsSchema = TEXT("verse.gadgets/1");
const TCHAR* FVerseDefinitionJson::AssetFolder = TEXT("/Game/Verse/Combat/Abilities/Data");

namespace
{
	const FName NameVector2f(TEXT("Vector2f"));
	const FName NameVector3f(TEXT("Vector3f"));
	const FName NameCurve(TEXT("RuntimeFloatCurve"));
	const FName NameTag(TEXT("GameplayTag"));
	const FString SchemaKey(TEXT("$schema"));

	/** The definition fields a JSON file carries: every edit property declared on the class itself. */
	TArray<FProperty*> FieldsOf(const UClass* Class)
	{
		TArray<FProperty*> Out;
		for (TFieldIterator<FProperty> It(Class, EFieldIteratorFlags::ExcludeSuper); It; ++It)
		{
			if (It->HasAnyPropertyFlags(CPF_Edit))
			{
				Out.Add(*It);
			}
		}
		return Out;
	}

	UEnum* EnumOf(const FProperty* P)
	{
		if (const FEnumProperty* E = CastField<FEnumProperty>(P))
		{
			return E->GetEnum();
		}
		if (const FByteProperty* B = CastField<FByteProperty>(P))
		{
			return B->Enum;
		}
		return nullptr;
	}

	int64 GetEnumValue(const FProperty* P, const void* Ptr)
	{
		if (const FEnumProperty* E = CastField<FEnumProperty>(P))
		{
			return E->GetUnderlyingProperty()->GetSignedIntPropertyValue(Ptr);
		}
		return int64(*static_cast<const uint8*>(Ptr));
	}

	void SetEnumValue(const FProperty* P, void* Ptr, int64 Value)
	{
		if (const FEnumProperty* E = CastField<FEnumProperty>(P))
		{
			E->GetUnderlyingProperty()->SetIntPropertyValue(Ptr, Value);
			return;
		}
		*static_cast<uint8*>(Ptr) = uint8(Value);
	}

	TSharedPtr<FJsonValue> ExportValue(const FProperty* P, const void* Ptr);

	TSharedPtr<FJsonValue> Number(double V)
	{
		return MakeShared<FJsonValueNumber>(V);
	}

	TSharedPtr<FJsonValue> ExportValue(const FProperty* P, const void* Ptr)
	{
		if (const UEnum* Enum = EnumOf(P))
		{
			return MakeShared<FJsonValueString>(Enum->GetNameStringByValue(GetEnumValue(P, Ptr)));
		}
		if (const FBoolProperty* B = CastField<FBoolProperty>(P))
		{
			return MakeShared<FJsonValueBoolean>(B->GetPropertyValue(Ptr));
		}
		if (const FNumericProperty* N = CastField<FNumericProperty>(P))
		{
			return Number(N->IsFloatingPoint() ? N->GetFloatingPointPropertyValue(Ptr) : double(N->GetSignedIntPropertyValue(Ptr)));
		}
		if (CastField<FNameProperty>(P))
		{
			return MakeShared<FJsonValueString>(static_cast<const FName*>(Ptr)->ToString());
		}
		if (CastField<FTextProperty>(P))
		{
			return MakeShared<FJsonValueString>(static_cast<const FText*>(Ptr)->ToString());
		}
		if (const FStructProperty* S = CastField<FStructProperty>(P))
		{
			const FName Name = S->Struct->GetFName();
			if (Name == NameVector2f)
			{
				const FVector2f& V = *static_cast<const FVector2f*>(Ptr);
				return MakeShared<FJsonValueArray>(TArray<TSharedPtr<FJsonValue>>{Number(V.X), Number(V.Y)});
			}
			if (Name == NameVector3f)
			{
				const FVector3f& V = *static_cast<const FVector3f*>(Ptr);
				return MakeShared<FJsonValueArray>(TArray<TSharedPtr<FJsonValue>>{Number(V.X), Number(V.Y), Number(V.Z)});
			}
			if (Name == NameCurve)
			{
				const FRuntimeFloatCurve& C = *static_cast<const FRuntimeFloatCurve*>(Ptr);
				TArray<TSharedPtr<FJsonValue>> Keys;
				if (const FRichCurve* Rich = C.GetRichCurveConst())
				{
					for (const FRichCurveKey& K : Rich->GetConstRefOfKeys())
					{
						Keys.Add(MakeShared<FJsonValueArray>(TArray<TSharedPtr<FJsonValue>>{Number(K.Time), Number(K.Value)}));
					}
				}
				return MakeShared<FJsonValueArray>(Keys);
			}
			if (Name == NameTag)
			{
				const FGameplayTag& T = *static_cast<const FGameplayTag*>(Ptr);
				return MakeShared<FJsonValueString>(T.IsValid() ? T.ToString() : FString());
			}
		}
		if (const FMapProperty* M = CastField<FMapProperty>(P))
		{
			const UEnum* KeyEnum = EnumOf(M->KeyProp);
			FScriptMapHelper Helper(M, Ptr);
			// Deterministic order: by enum value.
			TArray<TPair<int64, int32>> Order;
			for (int32 I = 0; I < Helper.GetMaxIndex(); ++I)
			{
				if (Helper.IsValidIndex(I))
				{
					Order.Add({KeyEnum ? GetEnumValue(M->KeyProp, Helper.GetKeyPtr(I)) : int64(I), I});
				}
			}
			Order.Sort([](const TPair<int64, int32>& A, const TPair<int64, int32>& B) { return A.Key < B.Key; });
			TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
			for (const TPair<int64, int32>& O : Order)
			{
				const FString Key = KeyEnum ? KeyEnum->GetNameStringByValue(O.Key) : FString::FromInt(O.Value);
				Obj->SetField(Key, ExportValue(M->ValueProp, Helper.GetValuePtr(O.Value)));
			}
			return MakeShared<FJsonValueObject>(Obj);
		}
		return MakeShared<FJsonValueNull>();
	}

	bool ReadNumbers(const TSharedPtr<FJsonValue>& J, int32 Count, double* Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
		if (!J.IsValid() || !J->TryGetArray(Arr) || Arr->Num() != Count)
		{
			return false;
		}
		for (int32 I = 0; I < Count; ++I)
		{
			if (!(*Arr)[I].IsValid() || !(*Arr)[I]->TryGetNumber(Out[I]))
			{
				return false;
			}
		}
		return true;
	}

	bool ImportValue(const FProperty* P, void* Ptr, const TSharedPtr<FJsonValue>& J, const FString& Path, TArray<FString>& Errors)
	{
		auto Fail = [&Errors, &Path](const TCHAR* Why)
		{
			Errors.Add(FString::Printf(TEXT("%s: %s"), *Path, Why));
			return false;
		};
		if (!J.IsValid())
		{
			return Fail(TEXT("missing"));
		}
		if (const UEnum* Enum = EnumOf(P))
		{
			FString S;
			if (!J->TryGetString(S))
			{
				return Fail(TEXT("expected an enum name"));
			}
			const int64 V = Enum->GetValueByNameString(S);
			if (V == INDEX_NONE)
			{
				return Fail(TEXT("unknown enum entry"));
			}
			SetEnumValue(P, Ptr, V);
			return true;
		}
		if (const FBoolProperty* B = CastField<FBoolProperty>(P))
		{
			bool V = false;
			if (!J->TryGetBool(V))
			{
				return Fail(TEXT("expected a boolean"));
			}
			B->SetPropertyValue(Ptr, V);
			return true;
		}
		if (const FNumericProperty* N = CastField<FNumericProperty>(P))
		{
			double V = 0.0;
			if (!J->TryGetNumber(V))
			{
				return Fail(TEXT("expected a number"));
			}
			if (N->IsFloatingPoint())
			{
				N->SetFloatingPointPropertyValue(Ptr, V);
			}
			else
			{
				if (V != FMath::RoundToDouble(V))
				{
					return Fail(TEXT("expected an integer"));
				}
				if (CastField<FByteProperty>(N) && (V < 0.0 || V > 255.0))
				{
					return Fail(TEXT("out of range for uint8"));
				}
				N->SetIntPropertyValue(Ptr, int64(V));
			}
			return true;
		}
		if (CastField<FNameProperty>(P))
		{
			FString S;
			if (!J->TryGetString(S))
			{
				return Fail(TEXT("expected a string"));
			}
			*static_cast<FName*>(Ptr) = FName(*S);
			return true;
		}
		if (CastField<FTextProperty>(P))
		{
			FString S;
			if (!J->TryGetString(S))
			{
				return Fail(TEXT("expected a string"));
			}
			*static_cast<FText*>(Ptr) = FText::FromString(S);
			return true;
		}
		if (const FStructProperty* S = CastField<FStructProperty>(P))
		{
			const FName Name = S->Struct->GetFName();
			if (Name == NameVector2f)
			{
				double V[2];
				if (!ReadNumbers(J, 2, V))
				{
					return Fail(TEXT("expected [x, y]"));
				}
				*static_cast<FVector2f*>(Ptr) = FVector2f(float(V[0]), float(V[1]));
				return true;
			}
			if (Name == NameVector3f)
			{
				double V[3];
				if (!ReadNumbers(J, 3, V))
				{
					return Fail(TEXT("expected [x, y, z]"));
				}
				*static_cast<FVector3f*>(Ptr) = FVector3f(float(V[0]), float(V[1]), float(V[2]));
				return true;
			}
			if (Name == NameCurve)
			{
				const TArray<TSharedPtr<FJsonValue>>* Keys = nullptr;
				if (!J->TryGetArray(Keys) || Keys->Num() == 0)
				{
					return Fail(TEXT("expected [[x, y], ...] with at least one key"));
				}
				FRuntimeFloatCurve& C = *static_cast<FRuntimeFloatCurve*>(Ptr);
				FRichCurve* Rich = C.GetRichCurve();
				Rich->Reset();
				for (const TSharedPtr<FJsonValue>& K : *Keys)
				{
					double V[2];
					if (!ReadNumbers(K, 2, V))
					{
						return Fail(TEXT("a curve key must be [x, y]"));
					}
					const FKeyHandle H = Rich->AddKey(float(V[0]), float(V[1]));
					Rich->SetKeyInterpMode(H, RCIM_Linear);
				}
				return true;
			}
			if (Name == NameTag)
			{
				FString Str;
				if (!J->TryGetString(Str))
				{
					return Fail(TEXT("expected a tag name"));
				}
				FGameplayTag& T = *static_cast<FGameplayTag*>(Ptr);
				T = Str.IsEmpty() ? FGameplayTag() : FGameplayTag::RequestGameplayTag(FName(*Str), false);
				if (!Str.IsEmpty() && !T.IsValid())
				{
					return Fail(TEXT("unknown gameplay tag"));
				}
				return true;
			}
			return Fail(TEXT("unsupported struct"));
		}
		if (const FMapProperty* M = CastField<FMapProperty>(P))
		{
			const TSharedPtr<FJsonObject>* Obj = nullptr;
			if (!J->TryGetObject(Obj))
			{
				return Fail(TEXT("expected an object"));
			}
			const UEnum* KeyEnum = EnumOf(M->KeyProp);
			if (!KeyEnum)
			{
				return Fail(TEXT("unsupported map key"));
			}
			FScriptMapHelper Helper(M, Ptr);
			Helper.EmptyValues();
			bool bOk = true;
			for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*Obj)->Values)
			{
				const int64 KeyValue = KeyEnum->GetValueByNameString(Pair.Key);
				if (KeyValue == INDEX_NONE)
				{
					Errors.Add(FString::Printf(TEXT("%s.%s: unknown key"), *Path, *Pair.Key));
					bOk = false;
					continue;
				}
				const int32 Index = Helper.AddDefaultValue_Invalid_NeedsRehash();
				SetEnumValue(M->KeyProp, Helper.GetKeyPtr(Index), KeyValue);
				bOk &= ImportValue(M->ValueProp, Helper.GetValuePtr(Index), Pair.Value, Path + TEXT(".") + Pair.Key, Errors);
			}
			Helper.Rehash();
			return bOk;
		}
		return Fail(TEXT("unsupported property type"));
	}

	bool ApplyObject(const FJsonObject& Json, UObject& Out, const TCHAR* Schema, TArray<FString>& Errors)
	{
		const int32 ErrorsBefore = Errors.Num();
		FString SchemaValue;
		if (Schema && (!Json.TryGetStringField(SchemaKey, SchemaValue) || SchemaValue != Schema))
		{
			Errors.Add(FString::Printf(TEXT("$schema must be \"%s\""), Schema));
		}
		const TArray<FProperty*> Fields = FieldsOf(Out.GetClass());
		TSet<FString> Known;
		Known.Add(SchemaKey);
		for (const FProperty* P : Fields)
		{
			const FString Key = P->GetName();
			Known.Add(Key);
			ImportValue(P, P->ContainerPtrToValuePtr<void>(&Out), Json.TryGetField(Key), Key, Errors);
		}
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Json.Values)
		{
			if (!Known.Contains(Pair.Key))
			{
				Errors.Add(FString::Printf(TEXT("%s: unknown field"), *Pair.Key));
			}
		}
		return Errors.Num() == ErrorsBefore;
	}

	TSharedRef<FJsonObject> ExportObject(const UObject& Obj, const TCHAR* Schema)
	{
		TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
		if (Schema)
		{
			Json->SetStringField(SchemaKey, Schema);
		}
		for (const FProperty* P : FieldsOf(Obj.GetClass()))
		{
			Json->SetField(P->GetName(), ExportValue(P, P->ContainerPtrToValuePtr<void>(&Obj)));
		}
		return Json;
	}

	FString ToText(const TSharedRef<FJsonObject>& Obj)
	{
		FString Out;
		const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer = TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Out);
		FJsonSerializer::Serialize(Obj, Writer);
		return Out;
	}

	TSharedPtr<FJsonObject> Parse(const FString& Text, TArray<FString>& Errors)
	{
		TSharedPtr<FJsonObject> Obj;
		const TSharedRef<TJsonReader<TCHAR>> Reader = TJsonReaderFactory<TCHAR>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Obj) || !Obj.IsValid())
		{
			Errors.Add(TEXT("not a JSON object"));
			return nullptr;
		}
		return Obj;
	}

	FString Pascal(const FName& Id)
	{
		TArray<FString> Parts;
		Id.ToString().ParseIntoArray(Parts, TEXT("_"));
		FString Out;
		for (FString& P : Parts)
		{
			if (!P.IsEmpty())
			{
				Out += P.Left(1).ToUpper() + P.Mid(1);
			}
		}
		return Out;
	}
}

FString FVerseDefinitionJson::DataDir()
{
	return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data"), TEXT("weapons"));
}

bool FVerseDefinitionJson::ApplyWeapon(const FJsonObject& Json, UVerseWeaponDefinition& Out, TArray<FString>& Errors)
{
	const int32 Before = Errors.Num();
	ApplyObject(Json, Out, WeaponSchema, Errors);
	CheckNames(Out.WeaponId, Out.DisplayName, Errors);
	if (Out.MaxPenetrations > UVerseWeaponDefinition::MaxPenetrationsCap)
	{
		Errors.Add(TEXT("MaxPenetrations: above the contract cap of 3"));
	}
	if (Out.RPM <= 0.f)
	{
		Errors.Add(TEXT("RPM: must be positive"));
	}
	return Errors.Num() == Before;
}

bool FVerseDefinitionJson::ApplyWeaponText(const FString& Text, UVerseWeaponDefinition& Out, TArray<FString>& Errors)
{
	const TSharedPtr<FJsonObject> Obj = Parse(Text, Errors);
	return Obj.IsValid() && ApplyWeapon(*Obj, Out, Errors);
}

TSharedRef<FJsonObject> FVerseDefinitionJson::ExportWeapon(const UVerseWeaponDefinition& W)
{
	return ExportObject(W, WeaponSchema);
}

FString FVerseDefinitionJson::ExportWeaponText(const UVerseWeaponDefinition& W)
{
	return ToText(ExportWeapon(W));
}

bool FVerseDefinitionJson::ApplyGadget(const FJsonObject& Json, UVerseGadgetDefinition& Out, TArray<FString>& Errors)
{
	const int32 Before = Errors.Num();
	ApplyObject(Json, Out, nullptr, Errors);
	CheckNames(Out.GadgetId, Out.DisplayName, Errors);
	return Errors.Num() == Before;
}

TSharedRef<FJsonObject> FVerseDefinitionJson::ExportGadget(const UVerseGadgetDefinition& G)
{
	return ExportObject(G, nullptr);
}

bool FVerseDefinitionJson::LoadGadgetsText(const FString& Text, UObject* Outer, TArray<UVerseGadgetDefinition*>& Out, TArray<FString>& Errors)
{
	const int32 Before = Errors.Num();
	const TSharedPtr<FJsonObject> Obj = Parse(Text, Errors);
	if (!Obj.IsValid())
	{
		return false;
	}
	FString SchemaValue;
	if (!Obj->TryGetStringField(SchemaKey, SchemaValue) || SchemaValue != GadgetsSchema)
	{
		Errors.Add(FString::Printf(TEXT("$schema must be \"%s\""), GadgetsSchema));
	}
	const TArray<TSharedPtr<FJsonValue>>* List = nullptr;
	if (!Obj->TryGetArrayField(TEXT("gadgets"), List))
	{
		Errors.Add(TEXT("gadgets: expected an array"));
		return false;
	}
	for (const TSharedPtr<FJsonValue>& V : *List)
	{
		const TSharedPtr<FJsonObject>* G = nullptr;
		if (!V.IsValid() || !V->TryGetObject(G))
		{
			Errors.Add(TEXT("gadgets[]: expected an object"));
			continue;
		}
		UVerseGadgetDefinition* Def = NewObject<UVerseGadgetDefinition>(Outer ? Outer : GetTransientPackage());
		if (ApplyGadget(**G, *Def, Errors))
		{
			Out.Add(Def);
		}
	}
	return Errors.Num() == Before;
}

bool FVerseDefinitionJson::CheckNames(const FName& Id, const FText& DisplayName, TArray<FString>& Errors)
{
	bool bOk = true;
	const FString IdStr = Id.ToString();
	if (Id.IsNone() || IdStr.IsEmpty())
	{
		Errors.Add(TEXT("id: empty"));
		bOk = false;
	}
	for (const TCHAR C : IdStr)
	{
		if (!((C >= 'a' && C <= 'z') || (C >= '0' && C <= '9') || C == '_'))
		{
			Errors.Add(FString::Printf(TEXT("id \"%s\": only lower_snake_case ASCII"), *IdStr));
			bOk = false;
			break;
		}
	}
	const FString Display = DisplayName.ToString();
	if (Display.IsEmpty())
	{
		Errors.Add(TEXT("DisplayName: empty"));
		bOk = false;
	}
	for (const TCHAR C : Display)
	{
		if (!(FChar::IsAlpha(C) || FChar::IsDigit(C) || C == ' ' || C == '-'))
		{
			Errors.Add(FString::Printf(TEXT("DisplayName \"%s\": letters, digits, spaces and hyphens only"), *Display));
			bOk = false;
			break;
		}
	}
	return bOk;
}

TArray<UVerseWeaponDefinition*> FVerseDefinitionJson::LoadAllWeapons(UObject* Outer, TArray<FString>& Errors)
{
	TArray<UVerseWeaponDefinition*> Out;
	TArray<FString> Files;
	IFileManager::Get().FindFiles(Files, *FPaths::Combine(DataDir(), TEXT("*.json")), true, false);
	Files.Sort();
	for (const FString& File : Files)
	{
		if (File.Equals(TEXT("gadgets.json"), ESearchCase::IgnoreCase))
		{
			continue;
		}
		FString Text;
		if (!FFileHelper::LoadFileToString(Text, *FPaths::Combine(DataDir(), File)))
		{
			Errors.Add(FString::Printf(TEXT("%s: cannot read"), *File));
			continue;
		}
		UVerseWeaponDefinition* Def = NewObject<UVerseWeaponDefinition>(Outer ? Outer : GetTransientPackage());
		TArray<FString> FileErrors;
		if (ApplyWeaponText(Text, *Def, FileErrors))
		{
			Out.Add(Def);
		}
		for (const FString& E : FileErrors)
		{
			Errors.Add(FString::Printf(TEXT("%s: %s"), *File, *E));
		}
	}
	return Out;
}

bool FVerseDefinitionJson::JsonEqual(const TSharedPtr<FJsonValue>& A, const TSharedPtr<FJsonValue>& B, const FString& Path,
	TArray<FString>& Diffs, double Tolerance)
{
	if (!A.IsValid() || !B.IsValid())
	{
		if (A.IsValid() != B.IsValid())
		{
			Diffs.Add(Path + TEXT(": missing on one side"));
			return false;
		}
		return true;
	}
	if (A->Type != B->Type)
	{
		Diffs.Add(Path + TEXT(": type differs"));
		return false;
	}
	switch (A->Type)
	{
	case EJson::Number:
		if (FMath::Abs(A->AsNumber() - B->AsNumber()) > Tolerance)
		{
			Diffs.Add(FString::Printf(TEXT("%s: %g != %g"), *Path, A->AsNumber(), B->AsNumber()));
			return false;
		}
		return true;
	case EJson::String:
		if (A->AsString() != B->AsString())
		{
			Diffs.Add(FString::Printf(TEXT("%s: \"%s\" != \"%s\""), *Path, *A->AsString(), *B->AsString()));
			return false;
		}
		return true;
	case EJson::Boolean:
		if (A->AsBool() != B->AsBool())
		{
			Diffs.Add(Path + TEXT(": boolean differs"));
			return false;
		}
		return true;
	case EJson::Array:
	{
		const TArray<TSharedPtr<FJsonValue>>& X = A->AsArray();
		const TArray<TSharedPtr<FJsonValue>>& Y = B->AsArray();
		if (X.Num() != Y.Num())
		{
			Diffs.Add(FString::Printf(TEXT("%s: %d != %d entries"), *Path, X.Num(), Y.Num()));
			return false;
		}
		bool bOk = true;
		for (int32 I = 0; I < X.Num(); ++I)
		{
			bOk &= JsonEqual(X[I], Y[I], FString::Printf(TEXT("%s[%d]"), *Path, I), Diffs, Tolerance);
		}
		return bOk;
	}
	case EJson::Object:
	{
		const TSharedPtr<FJsonObject> X = A->AsObject();
		const TSharedPtr<FJsonObject> Y = B->AsObject();
		bool bOk = true;
		for (const TPair<FString, TSharedPtr<FJsonValue>>& P : X->Values)
		{
			bOk &= JsonEqual(P.Value, Y->TryGetField(P.Key), Path + TEXT(".") + P.Key, Diffs, Tolerance);
		}
		for (const TPair<FString, TSharedPtr<FJsonValue>>& P : Y->Values)
		{
			if (!X->HasField(P.Key))
			{
				Diffs.Add(Path + TEXT(".") + P.Key + TEXT(": missing on one side"));
				bOk = false;
			}
		}
		return bOk;
	}
	default:
		return true;
	}
}

FString FVerseDefinitionJson::WeaponAssetName(const FName& WeaponId)
{
	return TEXT("DA_Weapon_") + Pascal(WeaponId);
}

FString FVerseDefinitionJson::GadgetAssetName(const FName& GadgetId)
{
	return TEXT("DA_Gadget_") + Pascal(GadgetId);
}
