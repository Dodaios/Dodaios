#include "Capture/VerseCaptureDirector.h"

#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformMisc.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "ShaderCompiler.h"
#include "UnrealClient.h"
#include "UObject/UObjectGlobals.h"
#include "VerseLog.h"

namespace VerseCapturePrivate
{
	bool ReadVector(const TSharedPtr<FJsonObject>& Obj, const TCHAR* Field, FVector& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Obj->TryGetArrayField(Field, Values) || Values->Num() != 3)
		{
			return false;
		}
		Out = FVector((*Values)[0]->AsNumber(), (*Values)[1]->AsNumber(), (*Values)[2]->AsNumber());
		return true;
	}

	bool ReadView(const TSharedPtr<FJsonObject>& Obj, FVerseCaptureView& Out, bool bNeedPose)
	{
		if (!Obj.IsValid())
		{
			return false;
		}
		Obj->TryGetStringField(TEXT("id"), Out.Id);
		double Number = 0.0;
		if (Obj->TryGetNumberField(TEXT("t"), Number) || Obj->TryGetNumberField(TEXT("atS"), Number))
		{
			Out.T = Number;
		}
		if (Obj->TryGetNumberField(TEXT("fovDeg"), Number))
		{
			Out.FovDeg = float(Number);
		}
		FVector Location = FVector::ZeroVector;
		FVector Rotation = FVector::ZeroVector;
		const bool bPose = ReadVector(Obj, TEXT("location"), Location) && ReadVector(Obj, TEXT("rotation"), Rotation);
		if (bPose)
		{
			Out.Location = Location;
			Out.Rotation = FRotator(Rotation.X, Rotation.Y, Rotation.Z);
		}
		return bPose || !bNeedPose;
	}
}

bool FVerseCaptureScript::Parse(const FString& JsonText, FVerseCaptureScript& Out, FString& OutError)
{
	using namespace VerseCapturePrivate;

	TSharedPtr<FJsonObject> Root;
	if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(JsonText), Root) || !Root.IsValid())
	{
		OutError = TEXT("not a JSON object");
		return false;
	}
	if (Root->GetStringField(TEXT("schema")) != TEXT("verse.capture/1"))
	{
		OutError = TEXT("schema is not verse.capture/1");
		return false;
	}
	Out = FVerseCaptureScript();
	Root->TryGetStringField(TEXT("id"), Out.Id);
	Root->TryGetNumberField(TEXT("settleFrames"), Out.SettleFrames);
	Root->TryGetNumberField(TEXT("warmupS"), Out.WarmupS);
	const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
	if (Root->TryGetArrayField(TEXT("views"), Values))
	{
		for (const TSharedPtr<FJsonValue>& Value : *Values)
		{
			FVerseCaptureView View;
			if (!ReadView(Value->AsObject(), View, true) || View.Id.IsEmpty())
			{
				OutError = TEXT("a view needs id, location and rotation");
				return false;
			}
			Out.Views.Add(View);
		}
	}
	const TSharedPtr<FJsonObject>* Fly = nullptr;
	if (Root->TryGetObjectField(TEXT("flythrough"), Fly))
	{
		(*Fly)->TryGetNumberField(TEXT("durationS"), Out.FlythroughS);
		if ((*Fly)->TryGetArrayField(TEXT("keys"), Values))
		{
			for (const TSharedPtr<FJsonValue>& Value : *Values)
			{
				FVerseCaptureView Key;
				if (!ReadView(Value->AsObject(), Key, true))
				{
					OutError = TEXT("a flythrough key needs t, location and rotation");
					return false;
				}
				Out.Keys.Add(Key);
			}
		}
		Out.Keys.Sort([](const FVerseCaptureView& L, const FVerseCaptureView& R) { return L.T < R.T; });
	}
	if (Root->TryGetArrayField(TEXT("shots"), Values))
	{
		for (const TSharedPtr<FJsonValue>& Value : *Values)
		{
			FVerseCaptureView Shot;
			ReadView(Value->AsObject(), Shot, false);
			Out.Shots.Add(Shot);
		}
		Out.Shots.Sort([](const FVerseCaptureView& L, const FVerseCaptureView& R) { return L.T < R.T; });
	}
	if (Out.Views.Num() == 0 && Out.Keys.Num() == 0)
	{
		OutError = TEXT("a capture needs views or flythrough keys");
		return false;
	}
	return true;
}

FVerseCaptureView FVerseCaptureScript::Sample(double T) const
{
	if (Keys.Num() == 0)
	{
		return FVerseCaptureView();
	}
	if (T <= Keys[0].T)
	{
		return Keys[0];
	}
	for (int32 Index = 1; Index < Keys.Num(); ++Index)
	{
		const FVerseCaptureView& A = Keys[Index - 1];
		const FVerseCaptureView& B = Keys[Index];
		if (T <= B.T)
		{
			const double Span = FMath::Max(B.T - A.T, 1.0e-6);
			const float Alpha = float((T - A.T) / Span);
			FVerseCaptureView Out;
			Out.T = T;
			Out.Location = FMath::Lerp(A.Location, B.Location, Alpha);
			Out.Rotation = FMath::Lerp(A.Rotation, B.Rotation, Alpha);
			Out.FovDeg = FMath::Lerp(A.FovDeg, B.FovDeg, Alpha);
			return Out;
		}
	}
	return Keys.Last();
}

bool UVerseCaptureDirector::Start(UWorld* InWorld, const FVerseCaptureScript& InScript, const FString& InOutDir,
	bool bInPerf, FString& OutError)
{
	if (!InWorld)
	{
		OutError = TEXT("no game world");
		return false;
	}
	World = InWorld;
	Script = InScript;
	OutDir = InOutDir;
	bPerf = bInPerf;
	SettleLeft = Script.SettleFrames;
	IFileManager::Get().MakeDirectory(*OutDir, true);
	return true;
}

bool UVerseCaptureDirector::EnsureCamera()
{
	if (Camera.IsValid())
	{
		return true;
	}
	UWorld* W = World.Get();
	APlayerController* PC = W ? W->GetFirstPlayerController() : nullptr;
	if (!PC)
	{
		return false;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	ACameraActor* Spawned = W->SpawnActor<ACameraActor>(Params);
	if (!Spawned)
	{
		return false;
	}
	Spawned->GetCameraComponent()->bConstrainAspectRatio = false;
	PC->SetViewTarget(Spawned);
	Camera = Spawned;
	return true;
}

bool UVerseCaptureDirector::SceneIsReady() const
{
	const bool bShaders = GShaderCompilingManager && GShaderCompilingManager->IsCompiling();
	return !bShaders && !IsAsyncLoading();
}

void UVerseCaptureDirector::Place(const FVerseCaptureView& View)
{
	if (ACameraActor* Cam = Camera.Get())
	{
		Cam->SetActorLocationAndRotation(View.Location, View.Rotation);
		Cam->GetCameraComponent()->SetFieldOfView(View.FovDeg);
	}
}

void UVerseCaptureDirector::Shoot(const FString& Id)
{
	PendingFile = FPaths::Combine(OutDir, Id + TEXT(".png"));
	IFileManager::Get().Delete(*PendingFile, false, true, true);
	// UI hidden (bShowUI false), exact file name (no suffix): orchestration.md 5.3.
	FScreenshotRequest::RequestScreenshot(PendingFile, false, false);
	PendingFrames = 120;
	UE_LOG(LogVerseHarness, Display, TEXT("[VerseCapture] shot %s"), *PendingFile);
}

bool UVerseCaptureDirector::Tick(float DeltaS)
{
	if (bDone)
	{
		return false;
	}
	if (!EnsureCamera())
	{
		return true;
	}
	if (PendingFrames > 0)
	{
		--PendingFrames;
		if (IFileManager::Get().FileExists(*PendingFile) || PendingFrames == 0)
		{
			Written.Add(PendingFile);
			PendingFrames = 0;
		}
		return true;
	}

	if (Script.Keys.Num() > 0)
	{
		// Perf replay along the fixed path.
		if (FlyStartS < 0.0)
		{
			if (!SceneIsReady())
			{
				return true;
			}
			FlyStartS = 0.0;
			ElapsedS = -Script.WarmupS;
		}
		ElapsedS += DeltaS;
		Place(Script.Sample(FMath::Max(ElapsedS, 0.0)));
		UWorld* W = World.Get();
		if (bPerf && !bProfiling && ElapsedS >= 0.0 && GEngine)
		{
			GEngine->Exec(W, TEXT("CsvProfile Start"));
			bProfiling = true;
		}
		if (Script.Shots.IsValidIndex(NextShot) && ElapsedS >= Script.Shots[NextShot].T)
		{
			Shoot(Script.Shots[NextShot].Id.IsEmpty() ? FString::Printf(TEXT("shot%d"), NextShot) : Script.Shots[NextShot].Id);
			++NextShot;
			return true;
		}
		if (ElapsedS >= Script.FlythroughS)
		{
			if (bProfiling && StopAtS < 0.0 && GEngine)
			{
				GEngine->Exec(W, TEXT("CsvProfile Stop"));
				StopAtS = ElapsedS + 3.0;
			}
			if (StopAtS < 0.0 || ElapsedS >= StopAtS)
			{
				Finish();
			}
		}
		return !bDone;
	}

	// Reference views.
	if (!Script.Views.IsValidIndex(ViewIndex))
	{
		Finish();
		return false;
	}
	if (SettleLeft == Script.SettleFrames)
	{
		Place(Script.Views[ViewIndex]);
		if (UWorld* W = World.Get())
		{
			W->BlockTillLevelStreamingCompleted();
		}
	}
	if (!SceneIsReady() || --SettleLeft > 0)
	{
		return true;
	}
	Shoot(Script.Views[ViewIndex].Id);
	++ViewIndex;
	SettleLeft = Script.SettleFrames;
	return true;
}

void UVerseCaptureDirector::Finish()
{
	if (bDone)
	{
		return;
	}
	bDone = true;
	UE_LOG(LogVerseHarness, Display, TEXT("[VerseCapture] done: %d images in %s"), Written.Num(), *OutDir);
}
