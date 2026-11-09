#include "Qa/VerseQaEngineCommands.h"

#include "Camera/PlayerCameraManager.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/Engine.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Controller.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Materials/MaterialInterface.h"
#include "Qa/VerseQaRegistry.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/UObjectIterator.h"

namespace
{
	constexpr int32 MaxMaterialNames = 400;

	FString Print(const TSharedRef<FJsonObject>& Object)
	{
		FString Out;
		const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
			TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
		FJsonSerializer::Serialize(Object, Writer);
		return Out;
	}

	TSharedRef<FJsonValue> Vec3(const FVector& V)
	{
		TArray<TSharedPtr<FJsonValue>> Items = {
			MakeShared<FJsonValueNumber>(V.X), MakeShared<FJsonValueNumber>(V.Y), MakeShared<FJsonValueNumber>(V.Z) };
		return MakeShared<FJsonValueArray>(Items);
	}

	TSharedRef<FJsonObject> Pose(const FVector& Location, const FRotator& Rotation)
	{
		TSharedRef<FJsonObject> Out = MakeShared<FJsonObject>();
		Out->SetField(TEXT("location_cm"), Vec3(Location));
		Out->SetNumberField(TEXT("yaw"), FRotator::NormalizeAxis(Rotation.Yaw));
		Out->SetNumberField(TEXT("pitch"), FRotator::NormalizeAxis(Rotation.Pitch));
		Out->SetNumberField(TEXT("roll"), FRotator::NormalizeAxis(Rotation.Roll));
		return Out;
	}

	bool ParseNumber(const FString& Text, double& Out)
	{
		if (!Text.IsNumeric())
		{
			return false;
		}
		Out = FCString::Atod(*Text);
		return FMath::IsFinite(Out);
	}

	/** Parsed JSON text of a Dump section; an invalid producer result becomes null so Dump stays valid. */
	TSharedPtr<FJsonValue> ParseSection(const FString& Text)
	{
		const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
		TSharedPtr<FJsonValue> Value;
		if (FJsonSerializer::Deserialize(Reader, Value) && Value.IsValid())
		{
			return Value;
		}
		return MakeShared<FJsonValueNull>();
	}
}

FString VerseQaEngine::ErrorJson(const FString& Message)
{
	const TSharedRef<FJsonObject> Out = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("error"), Message);
	return Print(Out);
}

namespace
{
	TWeakObjectPtr<UWorld> GTestWorld;
}

void VerseQaEngine::SetWorldForTests(UWorld* World)
{
	GTestWorld = World;
}

UWorld* VerseQaEngine::FindGameWorld()
{
	if (UWorld* Test = GTestWorld.Get())
	{
		return Test;
	}
	if (GEngine == nullptr)
	{
		return nullptr;
	}
	for (const FWorldContext& Context : GEngine->GetWorldContexts())
	{
		if ((Context.WorldType == EWorldType::Game || Context.WorldType == EWorldType::PIE) && Context.World() != nullptr)
		{
			return Context.World();
		}
	}
	return nullptr;
}

TMap<FString, FString> VerseQaEngine::ParseKeyValues(const TArray<FString>& Args)
{
	TMap<FString, FString> Out;
	for (const FString& Arg : Args)
	{
		FString Key;
		FString Value;
		if (!Arg.Split(TEXT("="), &Key, &Value))
		{
			Key = Arg;
		}
		Out.Add(Key.ToLower(), Value);
	}
	return Out;
}

namespace
{
	// ---- Verse.QA.Dump (Q-02) ------------------------------------------------------------------

	FString DumpWorld(const TMap<FString, TFunction<FString()>>& Sections)
	{
		const TSharedRef<FJsonObject> Out = MakeShared<FJsonObject>();
		UWorld* World = VerseQaEngine::FindGameWorld();
		Out->SetStringField(TEXT("world"), World ? World->GetMapName() : FString());
		Out->SetNumberField(TEXT("time_s"), World ? World->GetTimeSeconds() : 0.0);

		TSharedPtr<FJsonObject> Camera;
		TArray<TSharedPtr<FJsonValue>> Pawns;
		if (World != nullptr)
		{
			if (const APlayerController* Player = World->GetFirstPlayerController())
			{
				if (const APlayerCameraManager* Manager = Player->PlayerCameraManager)
				{
					Camera = Pose(Manager->GetCameraLocation(), Manager->GetCameraRotation());
					Camera->SetNumberField(TEXT("fov"), Manager->GetFOVAngle());
				}
			}
			for (TActorIterator<APawn> It(World); It; ++It)
			{
				const APawn* Pawn = *It;
				const TSharedRef<FJsonObject> Entry = Pose(Pawn->GetActorLocation(), Pawn->GetActorRotation());
				Entry->SetStringField(TEXT("name"), Pawn->GetName());
				Entry->SetStringField(TEXT("class"), Pawn->GetClass()->GetName());
				Entry->SetField(TEXT("velocity_cm_s"), Vec3(Pawn->GetVelocity()));
				const AController* Controller = Pawn->GetController();
				Entry->SetStringField(TEXT("controller"), Controller == nullptr ? TEXT("none")
					: Controller->IsPlayerController() ? TEXT("player") : TEXT("ai"));
				Pawns.Add(MakeShared<FJsonValueObject>(Entry));
			}
		}
		if (Camera.IsValid())
		{
			Out->SetObjectField(TEXT("camera"), Camera);
		}
		else
		{
			Out->SetField(TEXT("camera"), MakeShared<FJsonValueNull>());
		}
		Out->SetArrayField(TEXT("pawns"), Pawns);

		// Crew statuses (and any other section a package registers) come from the sections.
		bool bHasCrew = false;
		for (const TPair<FString, TFunction<FString()>>& Section : Sections)
		{
			Out->SetField(Section.Key, ParseSection(Section.Value()));
			bHasCrew |= Section.Key == TEXT("crew");
		}
		if (!bHasCrew)
		{
			Out->SetArrayField(TEXT("crew"), TArray<TSharedPtr<FJsonValue>>());
		}
		return Print(Out);
	}

	// ---- Verse.QA.Tune (Q-06) ------------------------------------------------------------------

	struct FTuneState
	{
		TWeakObjectPtr<APostProcessVolume> Volume;
		TOptional<double> Exposure;
		TOptional<double> Bloom;
	};
	FTuneState GTune;

	FString TuneJson()
	{
		const TSharedRef<FJsonObject> Out = MakeShared<FJsonObject>();
		if (GTune.Exposure.IsSet())
		{
			Out->SetNumberField(TEXT("exposure"), GTune.Exposure.GetValue());
		}
		else
		{
			Out->SetField(TEXT("exposure"), MakeShared<FJsonValueNull>());
		}
		if (GTune.Bloom.IsSet())
		{
			Out->SetNumberField(TEXT("bloom"), GTune.Bloom.GetValue());
		}
		else
		{
			Out->SetField(TEXT("bloom"), MakeShared<FJsonValueNull>());
		}
		Out->SetBoolField(TEXT("volume"), GTune.Volume.IsValid());
		return Print(Out);
	}

	void ApplyTune(UWorld* World)
	{
		if (!GTune.Exposure.IsSet() && !GTune.Bloom.IsSet())
		{
			if (APostProcessVolume* Old = GTune.Volume.Get())
			{
				Old->Destroy();
			}
			GTune.Volume.Reset();
			return;
		}
		APostProcessVolume* Volume = GTune.Volume.Get();
		if (Volume == nullptr || Volume->GetWorld() != World)
		{
			FActorSpawnParameters Params;
			Params.ObjectFlags |= RF_Transient;
			Volume = World->SpawnActor<APostProcessVolume>(FVector::ZeroVector, FRotator::ZeroRotator, Params);
			if (Volume == nullptr)
			{
				return;
			}
			Volume->bUnbound = true;
			Volume->Priority = 1000.0f;
			Volume->BlendWeight = 1.0f;
			GTune.Volume = Volume;
		}
		FPostProcessSettings& Settings = Volume->Settings;
		Settings.bOverride_AutoExposureBias = GTune.Exposure.IsSet();
		Settings.AutoExposureBias = static_cast<float>(GTune.Exposure.Get(0.0));
		Settings.bOverride_BloomIntensity = GTune.Bloom.IsSet();
		Settings.BloomIntensity = static_cast<float>(GTune.Bloom.Get(0.0));
	}

	FString Tune(const TArray<FString>& Args)
	{
		if (Args.IsEmpty())
		{
			return TuneJson();
		}
		UWorld* World = VerseQaEngine::FindGameWorld();
		if (World == nullptr)
		{
			return VerseQaEngine::ErrorJson(TEXT("no game world"));
		}
		TOptional<double> Exposure = GTune.Exposure;
		TOptional<double> Bloom = GTune.Bloom;
		for (const TPair<FString, FString>& Pair : VerseQaEngine::ParseKeyValues(Args))
		{
			double Value = 0.0;
			if (Pair.Key == TEXT("reset"))
			{
				Exposure.Reset();
				Bloom.Reset();
			}
			else if ((Pair.Key == TEXT("exposure") || Pair.Key == TEXT("bloom")) && ParseNumber(Pair.Value, Value))
			{
				if (Pair.Key == TEXT("exposure"))
				{
					Exposure = Value;
				}
				else
				{
					Bloom = Value;
				}
			}
			else
			{
				return VerseQaEngine::ErrorJson(TEXT("usage: Verse.QA.Tune [exposure=<ev>] [bloom=<intensity>] [reset]"));
			}
		}
		GTune.Exposure = Exposure;
		GTune.Bloom = Bloom;
		ApplyTune(World);
		return TuneJson();
	}

	// ---- Verse.QA.Materials (Q-06) -------------------------------------------------------------

	FString Materials(const TArray<FString>& Args)
	{
		const FString Filter = Args.IsEmpty() ? FString() : Args[0];
		TArray<FString> Names;
		int32 Total = 0;
		for (TObjectIterator<UMaterialInterface> It; It; ++It)
		{
			++Total;
			const FString Path = It->GetPathName();
			// Project content only: the engine's own defaults are not what a deck loads.
			if (!(Path.StartsWith(TEXT("/Game/")) || Path.StartsWith(TEXT("/Verse"))))
			{
				continue;
			}
			if (Filter.IsEmpty() || Path.Contains(Filter, ESearchCase::IgnoreCase))
			{
				Names.Add(Path);
			}
		}
		Names.Sort();
		const int32 Matched = Names.Num();
		if (Names.Num() > MaxMaterialNames)
		{
			Names.SetNum(MaxMaterialNames);
		}
		const TSharedRef<FJsonObject> Out = MakeShared<FJsonObject>();
		Out->SetNumberField(TEXT("total_loaded"), Total);
		Out->SetNumberField(TEXT("count"), Matched);
		TArray<TSharedPtr<FJsonValue>> Items;
		for (const FString& Name : Names)
		{
			Items.Add(MakeShared<FJsonValueString>(Name));
		}
		Out->SetArrayField(TEXT("names"), Items);
		return Print(Out);
	}

#if !UE_BUILD_SHIPPING
	// ---- Verse.QA.Viewmodel (Q-08, non-shipping) -----------------------------------------------

	FString LayoutJson(const FVerseViewmodelLayout& Layout)
	{
		const TSharedRef<FJsonObject> Out = MakeShared<FJsonObject>();
		Out->SetNumberField(TEXT("x"), Layout.OffsetCm.X);
		Out->SetNumberField(TEXT("y"), Layout.OffsetCm.Y);
		Out->SetNumberField(TEXT("z"), Layout.OffsetCm.Z);
		Out->SetNumberField(TEXT("scale"), Layout.Scale);
		Out->SetNumberField(TEXT("fov"), Layout.FovDeg);
		return Print(Out);
	}

	FString Viewmodel(UVerseQaRegistry* Self, const TArray<FString>& Args)
	{
		if (Self == nullptr)
		{
			return VerseQaEngine::ErrorJson(TEXT("no registry"));
		}
		const FString Usage = TEXT("usage: Verse.QA.Viewmodel [x=] [y=] [z=] [scale=] [fov=] [reset]");
		FVerseViewmodelLayout Layout = Self->GetViewmodelLayout();
		for (const TPair<FString, FString>& Pair : VerseQaEngine::ParseKeyValues(Args))
		{
			double Value = 0.0;
			if (Pair.Key == TEXT("reset"))
			{
				Layout = FVerseViewmodelLayout();
				continue;
			}
			if (!ParseNumber(Pair.Value, Value))
			{
				return VerseQaEngine::ErrorJson(Usage);
			}
			if (Pair.Key == TEXT("x"))
			{
				Layout.OffsetCm.X = Value;
			}
			else if (Pair.Key == TEXT("y"))
			{
				Layout.OffsetCm.Y = Value;
			}
			else if (Pair.Key == TEXT("z"))
			{
				Layout.OffsetCm.Z = Value;
			}
			else if (Pair.Key == TEXT("scale") && Value > 0.0)
			{
				Layout.Scale = static_cast<float>(Value);
			}
			else if (Pair.Key == TEXT("fov") && Value >= 0.0 && Value < 180.0)
			{
				Layout.FovDeg = static_cast<float>(Value);
			}
			else
			{
				return VerseQaEngine::ErrorJson(FString::Printf(TEXT("bad field '%s'"), *Pair.Key));
			}
		}
		if (!Args.IsEmpty())
		{
			Self->SetViewmodelLayout(Layout);
		}
		return LayoutJson(Self->GetViewmodelLayout());
	}
#endif
}

void VerseQaEngine::RegisterCommands(UVerseQaRegistry& Registry)
{
	TWeakObjectPtr<UVerseQaRegistry> Weak(&Registry);
	Registry.Register(TEXT("Verse.QA.Dump"), TEXT("Verse.QA.Dump: camera, every pawn pose, crew statuses"),
		[Weak](const TArray<FString>&) -> FString
		{
			const UVerseQaRegistry* Self = Weak.Get();
			return Self ? DumpWorld(Self->GetDumpSectionsForQa()) : ErrorJson(TEXT("no registry"));
		});
	Registry.Register(TEXT("Verse.QA.Tune"), TEXT("Verse.QA.Tune [exposure=<ev>] [bloom=<intensity>] [reset]"), &Tune);
	Registry.Register(TEXT("Verse.QA.Materials"), TEXT("Verse.QA.Materials [filter]: loaded project materials"), &Materials);
#if !UE_BUILD_SHIPPING
	Registry.Register(TEXT("Verse.QA.Viewmodel"),
		TEXT("Verse.QA.Viewmodel [x=<cm>] [y=<cm>] [z=<cm>] [scale=<f>] [fov=<deg>] [reset]"),
		[Weak](const TArray<FString>& Args) -> FString { return Viewmodel(Weak.Get(), Args); });
#endif
}
