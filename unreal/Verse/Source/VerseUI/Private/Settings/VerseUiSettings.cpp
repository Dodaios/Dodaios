#include "Settings/VerseUiSettings.h"

#include "Misc/ConfigCacheIni.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

// ---------------------------------------------------------------------------------------------
// App settings

FString FVerseAppSettings::GoreToString(EVerseGoreLevel Level)
{
	return Level == EVerseGoreLevel::Reduced ? TEXT("reduced") : TEXT("full");
}

bool FVerseAppSettings::GoreFromString(const FString& Text, EVerseGoreLevel& Out)
{
	if (Text == TEXT("full"))
	{
		Out = EVerseGoreLevel::Full;
		return true;
	}
	if (Text == TEXT("reduced"))
	{
		Out = EVerseGoreLevel::Reduced;
		return true;
	}
	return false;
}

void FVerseAppSettings::ApplyJson(const TSharedPtr<FJsonObject>& Json)
{
	if (!Json.IsValid())
	{
		return;
	}
	FString Text;
	if (Json->TryGetStringField(TEXT("gore"), Text))
	{
		GoreFromString(Text, Gore);
	}
	Json->TryGetBoolField(TEXT("reduced_motion"), bReducedMotion);
	if (Json->TryGetStringField(TEXT("return_key"), Text))
	{
		const FKey Key(*Text);
		if (Key.IsValid())
		{
			ReturnKey = Key;
		}
	}
	Json->TryGetBoolField(TEXT("ui_sound"), bUiSound);
	Json->TryGetBoolField(TEXT("level_sound"), bLevelSound);
	Json->TryGetStringField(TEXT("uniform"), Uniform);
	const TSharedPtr<FJsonObject>* View = nullptr;
	if (Json->TryGetObjectField(TEXT("view"), View))
	{
		(*View)->TryGetStringField(TEXT("mode"), ViewMode);
		double Number = 0.0;
		if ((*View)->TryGetNumberField(TEXT("sensitivity"), Number))
		{
			Sensitivity = float(FMath::Clamp(Number, 0.1, 5.0));
		}
		(*View)->TryGetBoolField(TEXT("invert_y"), bInvertY);
		if ((*View)->TryGetNumberField(TEXT("fov_third"), Number))
		{
			FovThird = float(FMath::Clamp(Number, 50.0, 110.0));
		}
		if ((*View)->TryGetNumberField(TEXT("fov_first"), Number))
		{
			FovFirst = float(FMath::Clamp(Number, 50.0, 110.0));
		}
		(*View)->TryGetStringField(TEXT("quality"), Quality);
		if ((*View)->TryGetNumberField(TEXT("volume"), Number))
		{
			Volume = float(FMath::Clamp(Number, 0.0, 1.0));
		}
	}
}

TSharedRef<FJsonObject> FVerseAppSettings::ToJson() const
{
	TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	Json->SetStringField(TEXT("gore"), GoreToString(Gore));
	Json->SetBoolField(TEXT("reduced_motion"), bReducedMotion);
	Json->SetStringField(TEXT("return_key"), ReturnKey.GetFName().ToString());
	Json->SetBoolField(TEXT("ui_sound"), bUiSound);
	Json->SetBoolField(TEXT("level_sound"), bLevelSound);
	Json->SetStringField(TEXT("uniform"), Uniform);
	TSharedRef<FJsonObject> View = MakeShared<FJsonObject>();
	View->SetStringField(TEXT("mode"), ViewMode);
	View->SetNumberField(TEXT("sensitivity"), Sensitivity);
	View->SetBoolField(TEXT("invert_y"), bInvertY);
	View->SetNumberField(TEXT("fov_third"), FovThird);
	View->SetNumberField(TEXT("fov_first"), FovFirst);
	View->SetStringField(TEXT("quality"), Quality);
	View->SetNumberField(TEXT("volume"), Volume);
	Json->SetObjectField(TEXT("view"), View);
	return Json;
}

TSharedRef<FJsonObject> FVerseAppSettings::Diff(const FVerseAppSettings& Other) const
{
	TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	if (Gore != Other.Gore) { Json->SetStringField(TEXT("gore"), GoreToString(Other.Gore)); }
	if (bReducedMotion != Other.bReducedMotion) { Json->SetBoolField(TEXT("reduced_motion"), Other.bReducedMotion); }
	if (ReturnKey != Other.ReturnKey) { Json->SetStringField(TEXT("return_key"), Other.ReturnKey.GetFName().ToString()); }
	if (bUiSound != Other.bUiSound) { Json->SetBoolField(TEXT("ui_sound"), Other.bUiSound); }
	if (bLevelSound != Other.bLevelSound) { Json->SetBoolField(TEXT("level_sound"), Other.bLevelSound); }
	if (Uniform != Other.Uniform) { Json->SetStringField(TEXT("uniform"), Other.Uniform); }

	TSharedRef<FJsonObject> View = MakeShared<FJsonObject>();
	if (ViewMode != Other.ViewMode) { View->SetStringField(TEXT("mode"), Other.ViewMode); }
	if (!FMath::IsNearlyEqual(Sensitivity, Other.Sensitivity)) { View->SetNumberField(TEXT("sensitivity"), Other.Sensitivity); }
	if (bInvertY != Other.bInvertY) { View->SetBoolField(TEXT("invert_y"), Other.bInvertY); }
	if (!FMath::IsNearlyEqual(FovThird, Other.FovThird)) { View->SetNumberField(TEXT("fov_third"), Other.FovThird); }
	if (!FMath::IsNearlyEqual(FovFirst, Other.FovFirst)) { View->SetNumberField(TEXT("fov_first"), Other.FovFirst); }
	if (Quality != Other.Quality) { View->SetStringField(TEXT("quality"), Other.Quality); }
	if (!FMath::IsNearlyEqual(Volume, Other.Volume)) { View->SetNumberField(TEXT("volume"), Other.Volume); }
	if (View->Values.Num() > 0)
	{
		Json->SetObjectField(TEXT("view"), View);
	}
	return Json;
}

// ---------------------------------------------------------------------------------------------
// User settings

void UVerseUiUserSettings::Clamp()
{
	DuelFov = FMath::Clamp(DuelFov, DuelFovMin, DuelFovMax);
	Scalability = FMath::Clamp(Scalability, -1, 4);
	TextScale = FMath::Clamp(TextScale, 0.8f, 1.6f);
	static const FName Tiers[] = {TEXT("normal"), TEXT("hard"), TEXT("elite"), TEXT("adaptive")};
	bool bKnown = false;
	for (const FName& Tier : Tiers)
	{
		bKnown |= Tier == LastTier;
	}
	if (!bKnown)
	{
		LastTier = TEXT("hard");
	}
}

void UVerseUiUserSettings::SaveToDisk()
{
	Clamp();
	++SaveCount;
	SaveConfig(CPF_Config, *GetClass()->GetConfigName());
	if (GConfig)
	{
		GConfig->Flush(false, GetClass()->GetConfigName());
	}
}

void UVerseUiUserSettings::ReloadFromDisk()
{
	LoadConfig(GetClass(), *GetClass()->GetConfigName());
	Clamp();
}

// ---------------------------------------------------------------------------------------------
// Key map

FString FVerseKeyMap::DefaultPath()
{
	return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data"), TEXT("ui"), TEXT("keys.json"));
}

bool FVerseKeyMap::LoadFile(const FString& Path, FString* OutError)
{
	FString Json;
	if (!FFileHelper::LoadFileToString(Json, *Path))
	{
		if (OutError)
		{
			*OutError = FString::Printf(TEXT("cannot read %s"), *Path);
		}
		return false;
	}
	return LoadJson(Json, OutError);
}

bool FVerseKeyMap::LoadJson(const FString& Json, FString* OutError)
{
	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
	const TArray<TSharedPtr<FJsonValue>>* List = nullptr;
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid() || !Root->TryGetArrayField(TEXT("actions"), List))
	{
		if (OutError)
		{
			*OutError = TEXT("keys.json needs an \"actions\" array");
		}
		return false;
	}
	Actions.Reset();
	for (const TSharedPtr<FJsonValue>& Value : *List)
	{
		const TSharedPtr<FJsonObject>* Obj = nullptr;
		if (!Value.IsValid() || !Value->TryGetObject(Obj))
		{
			continue;
		}
		FAction Action;
		FString Text;
		(*Obj)->TryGetStringField(TEXT("action"), Text);
		Action.Action = FName(*Text);
		(*Obj)->TryGetStringField(TEXT("key"), Text);
		Action.DefaultKey = FKey(*Text);
		(*Obj)->TryGetStringField(TEXT("label"), Action.LabelKey);
		FString InputAction;
		if ((*Obj)->TryGetStringField(TEXT("input_action"), InputAction))
		{
			Action.InputAction = FName(*InputAction);
		}
		FString Command;
		if ((*Obj)->TryGetStringField(TEXT("ui"), Command))
		{
			Action.Command = Command == TEXT("return_to_app") ? EVerseUiCommand::ReturnToApp
				: Command == TEXT("esc_menu") ? EVerseUiCommand::EscMenu
				: Command == TEXT("skip_kill_cam") ? EVerseUiCommand::SkipKillCam
				: Command == TEXT("verse_bar") ? EVerseUiCommand::VerseBar
				: EVerseUiCommand::None;
		}
		if (Action.Action.IsNone() || !Action.DefaultKey.IsValid())
		{
			if (OutError)
			{
				*OutError = FString::Printf(TEXT("bad action entry %s"), *Action.Action.ToString());
			}
			return false;
		}
		Actions.Add(Action);
	}
	if (const FAction* Return = FindAction(ReturnAction()))
	{
		ReturnKey = Return->DefaultKey;
	}
	return Actions.Num() > 0;
}

const FVerseKeyMap::FAction* FVerseKeyMap::FindAction(FName Action) const
{
	return Actions.FindByPredicate([Action](const FAction& A) { return A.Action == Action; });
}

FKey FVerseKeyMap::GetKey(FName Action) const
{
	if (Action == ReturnAction())
	{
		return ReturnKey;
	}
	if (const FKey* Override = Overrides.Find(Action))
	{
		return *Override;
	}
	const FAction* Found = FindAction(Action);
	return Found ? Found->DefaultKey : EKeys::Invalid;
}

void FVerseKeyMap::SetBindings(const TArray<FVerseKeyBinding>& Bindings)
{
	Overrides.Reset();
	for (const FVerseKeyBinding& Binding : Bindings)
	{
		if (Binding.Action != ReturnAction() && FindAction(Binding.Action) && Binding.Key.IsValid())
		{
			Overrides.Add(Binding.Action, Binding.Key);
		}
	}
}

TArray<FVerseKeyBinding> FVerseKeyMap::GetBindings() const
{
	TArray<FVerseKeyBinding> Out;
	for (const FAction& Action : Actions)
	{
		if (Action.Action == ReturnAction())
		{
			continue;
		}
		const FKey Key = GetKey(Action.Action);
		if (Key != Action.DefaultKey)
		{
			FVerseKeyBinding Binding;
			Binding.Action = Action.Action;
			Binding.Key = Key;
			Out.Add(Binding);
		}
	}
	return Out;
}

bool FVerseKeyMap::IsReserved(const FKey& Key)
{
	return Key == EKeys::Escape || Key == EKeys::LeftCommand || Key == EKeys::RightCommand || !Key.IsValid();
}

FName FVerseKeyMap::Rebind(FName Action, const FKey& Key)
{
	if (IsReserved(Key) || !FindAction(Action))
	{
		return NAME_None;
	}
	const FKey Old = GetKey(Action);
	FName Swapped = NAME_None;
	for (const FAction& Other : Actions)
	{
		if (Other.Action != Action && GetKey(Other.Action) == Key)
		{
			Swapped = Other.Action;
			break;
		}
	}
	auto Assign = [this](FName Target, const FKey& NewKey)
	{
		if (Target == ReturnAction())
		{
			ReturnKey = NewKey;
		}
		else
		{
			Overrides.Add(Target, NewKey);
		}
	};
	Assign(Action, Key);
	if (!Swapped.IsNone())
	{
		Assign(Swapped, Old);
	}
	return Swapped;
}

EVerseUiCommand FVerseKeyMap::Route(const FKey& Key) const
{
	if (Key == EKeys::Escape)
	{
		return EVerseUiCommand::EscMenu;
	}
	for (const FAction& Action : Actions)
	{
		if (Action.Command != EVerseUiCommand::None && GetKey(Action.Action) == Key)
		{
			return Action.Command;
		}
	}
	return EVerseUiCommand::None;
}

int32 FVerseRenderTier::Resolve(int32 Choice, int32 EngineLevel)
{
	if (Choice >= 0 && Choice <= 4)
	{
		return Choice;
	}
	return EngineLevel >= 0 && EngineLevel <= 4 ? EngineLevel : -1;
}

const TCHAR* FVerseRenderTier::KeyFor(int32 Level)
{
	switch (Level)
	{
	case 0: return TEXT("verse.settings.quality.low");
	case 1: return TEXT("verse.settings.quality.medium");
	case 2: return TEXT("verse.settings.quality.high");
	case 3: return TEXT("verse.settings.quality.epic");
	case 4: return TEXT("verse.settings.quality.cinematic");
	default: return TEXT("verse.settings.quality.custom");
	}
}
