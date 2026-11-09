#include "Settings/VerseGameSettings.h"

#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "VerseLog.h"

namespace
{
	const TCHAR* QualityNames[] = {TEXT("low"), TEXT("medium"), TEXT("high"), TEXT("epic"), TEXT("cinematic")};

	/** The Python catalogue's KEY_NAME and RESERVED_KEYS (game_settings.py). */
	bool IsKeyName(const FString& Text)
	{
		if (Text.IsEmpty() || Text.Len() > 24)
		{
			return false;
		}
		for (const TCHAR C : Text)
		{
			if (!FChar::IsAlnum(C) && C != TEXT('_') && C != TEXT('+') && C != TEXT('-'))
			{
				return false;
			}
		}
		static const TCHAR* Reserved[] = {TEXT("Escape"), TEXT("LeftCommand"), TEXT("RightCommand"), TEXT("LeftWindows"), TEXT("RightWindows")};
		for (const TCHAR* R : Reserved)
		{
			if (Text == R)
			{
				return false;
			}
		}
		return true;
	}
}

// ---------------------------------------------------------------------------------------------
// Entry

bool FVerseGameSettingDef::Check(const TSharedPtr<FJsonValue>& Value, TSharedPtr<FJsonValue>& Out) const
{
	if (!Value.IsValid())
	{
		return false;
	}
	switch (Kind)
	{
	case EVerseGameSettingKind::Toggle:
		if (Value->Type != EJson::Boolean)
		{
			return false;
		}
		Out = MakeShared<FJsonValueBoolean>(Value->AsBool());
		return true;
	case EVerseGameSettingKind::Choice:
	{
		FString Text;
		if (Value->Type != EJson::String || !Value->TryGetString(Text) || !Options.Contains(Text))
		{
			return false;
		}
		Out = MakeShared<FJsonValueString>(Text);
		return true;
	}
	case EVerseGameSettingKind::Range:
	{
		if (Value->Type != EJson::Number)
		{
			return false;
		}
		const double N = Value->AsNumber();
		if (!FMath::IsFinite(N) || N < Min - 1e-9 || N > Max + 1e-9)
		{
			return false;
		}
		Out = MakeShared<FJsonValueNumber>(FMath::Clamp(N, Min, Max));
		return true;
	}
	case EVerseGameSettingKind::Key:
	{
		FString Text;
		if (Value->Type != EJson::String || !Value->TryGetString(Text) || !IsKeyName(Text))
		{
			return false;
		}
		Out = MakeShared<FJsonValueString>(Text);
		return true;
	}
	}
	return false;
}

// ---------------------------------------------------------------------------------------------
// Catalogue

const FVerseGameSettingsCatalogue& FVerseGameSettingsCatalogue::Get()
{
	static const FVerseGameSettingsCatalogue Shipped = []
	{
		FVerseGameSettingsCatalogue Catalogue;
		FString Error;
		if (!Catalogue.LoadFile(DefaultPath(), &Error))
		{
			UE_LOG(LogVerseUI, Error, TEXT("VerseUI: game settings catalogue: %s"), *Error);
		}
		return Catalogue;
	}();
	return Shipped;
}

FString FVerseGameSettingsCatalogue::DefaultPath()
{
	return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data"), TEXT("ui"), TEXT("game_settings.json"));
}

bool FVerseGameSettingsCatalogue::LoadFile(const FString& Path, FString* OutError)
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

bool FVerseGameSettingsCatalogue::LoadJson(const FString& Json, FString* OutError)
{
	TSharedPtr<FJsonObject> Root;
	const TArray<TSharedPtr<FJsonValue>>* List = nullptr;
	if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Root) || !Root.IsValid() || !Root->TryGetArrayField(TEXT("settings"), List))
	{
		if (OutError)
		{
			*OutError = TEXT("game_settings.json needs a \"settings\" array");
		}
		return false;
	}
	Settings.Reset();
	Index.Reset();
	Tabs.Reset();
	PresetGroups.Reset();
	Root->TryGetStringArrayField(TEXT("tabs"), Tabs);
	Root->TryGetStringArrayField(TEXT("preset_groups"), PresetGroups);
	for (const TSharedPtr<FJsonValue>& Value : *List)
	{
		const TSharedPtr<FJsonObject>* Obj = nullptr;
		if (!Value.IsValid() || !Value->TryGetObject(Obj))
		{
			continue;
		}
		FVerseGameSettingDef Def;
		FString Kind;
		(*Obj)->TryGetStringField(TEXT("id"), Def.Id);
		(*Obj)->TryGetStringField(TEXT("tab"), Def.Tab);
		(*Obj)->TryGetStringField(TEXT("section"), Def.Section);
		(*Obj)->TryGetStringField(TEXT("kind"), Kind);
		Def.Kind = Kind == TEXT("choice") ? EVerseGameSettingKind::Choice
			: Kind == TEXT("range") ? EVerseGameSettingKind::Range
			: Kind == TEXT("key") ? EVerseGameSettingKind::Key
			: EVerseGameSettingKind::Toggle;
		(*Obj)->TryGetStringArrayField(TEXT("options"), Def.Options);
		(*Obj)->TryGetNumberField(TEXT("min"), Def.Min);
		(*Obj)->TryGetNumberField(TEXT("max"), Def.Max);
		(*Obj)->TryGetNumberField(TEXT("step"), Def.Step);
		(*Obj)->TryGetStringField(TEXT("unit"), Def.Unit);
		(*Obj)->TryGetStringField(TEXT("path"), Def.Path);
		(*Obj)->TryGetBoolField(TEXT("restart"), Def.bRestart);
		Def.Default = (*Obj)->TryGetField(TEXT("default"));
		TSharedPtr<FJsonValue> Checked;
		if (Def.Id.IsEmpty() || !Def.Check(Def.Default, Checked))
		{
			if (OutError)
			{
				*OutError = FString::Printf(TEXT("bad setting entry %s"), *Def.Id);
			}
			return false;
		}
		Def.Default = Checked;
		Def.bPresetGroup = PresetGroups.Contains(Def.Id);
		Index.Add(Def.Id, Settings.Num());
		Settings.Add(MoveTemp(Def));
	}
	return Settings.Num() > 0;
}

const FVerseGameSettingDef* FVerseGameSettingsCatalogue::Find(const FString& Id) const
{
	const int32* I = Index.Find(Id);
	return I ? &Settings[*I] : nullptr;
}

// ---------------------------------------------------------------------------------------------
// Values

bool FVerseGameSettings::SameValue(const TSharedPtr<FJsonValue>& A, const TSharedPtr<FJsonValue>& B)
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
	case EJson::Boolean: return A->AsBool() == B->AsBool();
	case EJson::Number: return FMath::IsNearlyEqual(A->AsNumber(), B->AsNumber(), 1e-6);
	case EJson::String: return A->AsString() == B->AsString();
	default: return false;
	}
}

int32 FVerseGameSettings::ApplyJson(const TSharedPtr<FJsonObject>& Game)
{
	if (!Game.IsValid())
	{
		return 0;
	}
	int32 Changed = 0;
	for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Game->Values)
	{
		const TSharedPtr<FJsonValue> Before = GetValue(Pair.Key);
		if (Set(Pair.Key, Pair.Value) && !SameValue(Before, GetValue(Pair.Key)))
		{
			++Changed;
		}
	}
	return Changed;
}

TSharedRef<FJsonObject> FVerseGameSettings::ToJson() const
{
	TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	for (const FVerseGameSettingDef& Def : FVerseGameSettingsCatalogue::Get().GetSettings())
	{
		if (Def.Path.IsEmpty())
		{
			Json->SetField(Def.Id, GetValue(Def.Id));
		}
	}
	return Json;
}

TSharedRef<FJsonObject> FVerseGameSettings::Diff(const FVerseGameSettings& Other) const
{
	TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	for (const FVerseGameSettingDef& Def : FVerseGameSettingsCatalogue::Get().GetSettings())
	{
		if (Def.Path.IsEmpty())
		{
			const TSharedPtr<FJsonValue> Theirs = Other.GetValue(Def.Id);
			if (!SameValue(GetValue(Def.Id), Theirs))
			{
				Json->SetField(Def.Id, Theirs);
			}
		}
	}
	return Json;
}

TSharedPtr<FJsonValue> FVerseGameSettings::GetValue(const FString& Id) const
{
	const FVerseGameSettingDef* Def = FVerseGameSettingsCatalogue::Get().Find(Id);
	if (!Def || !Def->Path.IsEmpty())
	{
		return nullptr;
	}
	const TSharedPtr<FJsonValue>* Value = Values.Find(Id);
	return Value ? *Value : Def->Default;
}

bool FVerseGameSettings::Set(const FString& Id, const TSharedPtr<FJsonValue>& Value)
{
	const FVerseGameSettingDef* Def = FVerseGameSettingsCatalogue::Get().Find(Id);
	TSharedPtr<FJsonValue> Checked;
	if (!Def || !Def->Path.IsEmpty() || !Def->Check(Value, Checked))
	{
		return false;
	}
	Values.Add(Id, Checked);
	return true;
}

bool FVerseGameSettings::GetBool(const FString& Id) const
{
	const TSharedPtr<FJsonValue> V = GetValue(Id);
	return V.IsValid() && V->Type == EJson::Boolean && V->AsBool();
}

double FVerseGameSettings::GetNumber(const FString& Id) const
{
	const TSharedPtr<FJsonValue> V = GetValue(Id);
	return V.IsValid() && V->Type == EJson::Number ? V->AsNumber() : 0.0;
}

FString FVerseGameSettings::GetString(const FString& Id) const
{
	const TSharedPtr<FJsonValue> V = GetValue(Id);
	return V.IsValid() && V->Type == EJson::String ? V->AsString() : FString();
}

int32 FVerseGameSettings::QualityIndex(const FString& Level)
{
	for (int32 I = 0; I < UE_ARRAY_COUNT(QualityNames); ++I)
	{
		if (Level == QualityNames[I])
		{
			return I;
		}
	}
	return -1;
}

FString FVerseGameSettings::QualityName(int32 Index)
{
	return Index >= 0 && Index < UE_ARRAY_COUNT(QualityNames) ? FString(QualityNames[Index]) : FString(TEXT("auto"));
}

// ---------------------------------------------------------------------------------------------
// Plans

FVerseGraphicsPlan FVerseGraphicsPlan::Build(const FVerseGameSettings& Game, const FIntPoint& Desktop)
{
	FVerseGraphicsPlan Plan;
	const FString Mode = Game.GetString(TEXT("display.window_mode"));
	Plan.WindowMode = Mode == TEXT("fullscreen") ? EWindowMode::Fullscreen
		: Mode == TEXT("windowed") ? EWindowMode::Windowed
		: EWindowMode::WindowedFullscreen;

	Plan.Resolution = Desktop;
	FString W, H;
	if (Game.GetString(TEXT("display.resolution")).Split(TEXT("x"), &W, &H) && W.IsNumeric() && H.IsNumeric())
	{
		Plan.Resolution = FIntPoint(FCString::Atoi(*W), FCString::Atoi(*H));
	}
	const FString Limit = Game.GetString(TEXT("display.frame_limit"));
	Plan.FrameLimit = Limit.IsNumeric() ? FCString::Atof(*Limit) : 0.f;
	Plan.bVSync = Game.GetBool(TEXT("display.vsync"));
	Plan.bHdr = Game.GetBool(TEXT("display.hdr"));
	Plan.DisplayGamma = 2.2f + float((Game.GetNumber(TEXT("display.brightness")) - 50.0) / 50.0) * 0.6f;

	const FString Aa = Game.GetString(TEXT("graphics.anti_aliasing"));
	Plan.AntiAliasingMethod = Aa == TEXT("off") ? 0 : Aa == TEXT("fxaa") ? 1 : Aa == TEXT("taa") ? 2 : 4;
	Plan.ScreenPercentage = float(Game.GetNumber(TEXT("graphics.resolution_scale")));
	Plan.Sharpen = float(Game.GetNumber(TEXT("graphics.sharpening")) / 100.0);

	Plan.bAutoQuality = Game.GetString(TEXT("graphics.preset")) == TEXT("auto");
	auto Level = [&Game](const TCHAR* Id) { return FMath::Max(0, FVerseGameSettings::QualityIndex(Game.GetString(Id))); };
	Scalability::FQualityLevels& Q = Plan.Quality;
	Q.ResolutionQuality = Plan.ScreenPercentage;
	Q.ViewDistanceQuality = Level(TEXT("graphics.view_distance"));
	Q.ShadowQuality = Level(TEXT("graphics.shadows"));
	Q.GlobalIlluminationQuality = Level(TEXT("graphics.global_illumination"));
	Q.ReflectionQuality = Level(TEXT("graphics.reflections"));
	Q.TextureQuality = Level(TEXT("graphics.textures"));
	Q.EffectsQuality = Level(TEXT("graphics.effects"));
	Q.PostProcessQuality = Level(TEXT("graphics.post_processing"));
	Q.FoliageQuality = Level(TEXT("graphics.foliage"));
	Q.ShadingQuality = Level(TEXT("graphics.shading"));
	// No groups of their own in the menu: anti-aliasing follows post-processing, landscape the view distance.
	Q.AntiAliasingQuality = Q.PostProcessQuality;
	Q.LandscapeQuality = Q.ViewDistanceQuality;

	Plan.bMotionBlur = Game.GetBool(TEXT("graphics.motion_blur"));
	Plan.bDepthOfField = Game.GetBool(TEXT("graphics.depth_of_field"));
	Plan.bFilmGrain = Game.GetBool(TEXT("graphics.film_grain"));
	Plan.bChromaticAberration = Game.GetBool(TEXT("graphics.chromatic_aberration"));
	Plan.bLensFlares = Game.GetBool(TEXT("graphics.lens_flares"));
	Plan.bBloom = Game.GetBool(TEXT("graphics.bloom"));
	return Plan;
}

FVerseAudioPlan FVerseAudioPlan::Build(const FVerseGameSettings& Game, bool bUiSound)
{
	FVerseAudioPlan Plan;
	Plan.BusGain.Init(1.f, VerseAudioBusCount);
	const float Effects = float(Game.GetNumber(TEXT("audio.effects")));
	for (const EVerseAudioBus Bus : {EVerseAudioBus::Weapons, EVerseAudioBus::Impacts, EVerseAudioBus::Foley, EVerseAudioBus::Destruction, EVerseAudioBus::Gadgets})
	{
		Plan.BusGain[int32(Bus)] = Effects;
	}
	Plan.BusGain[int32(EVerseAudioBus::Ambience)] = float(Game.GetNumber(TEXT("audio.ambience")));
	Plan.BusGain[int32(EVerseAudioBus::UI)] = bUiSound ? 1.f : 0.f;
	// Night mode: the loudest buses 6 dB down, so shots and destruction do not tower over the rest.
	if (Game.GetString(TEXT("audio.mix")) == TEXT("night"))
	{
		for (const EVerseAudioBus Bus : {EVerseAudioBus::Weapons, EVerseAudioBus::Destruction})
		{
			Plan.BusGain[int32(Bus)] *= 0.5f;
		}
	}
	Plan.bMuteUnfocused = Game.GetBool(TEXT("audio.mute_unfocused"));
	return Plan;
}
