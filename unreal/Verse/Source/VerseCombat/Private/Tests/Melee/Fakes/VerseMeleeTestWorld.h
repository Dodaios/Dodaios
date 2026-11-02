#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/CapsuleComponent.h"
#include "CoreMinimal.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/WorldSettings.h"
#include "HAL/FileManager.h"
#include "Melee/VerseMeleeComponent.h"
#include "Melee/VerseMeleeWorld.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

/**
 * A transient game world with placeholder pawns (plain characters with the combat state and
 * melee components, no mesh, movement off) ticked at the 60 Hz server rate. Standalone net
 * mode: the world is the server, RPCs run locally.
 */
struct FVerseMeleeTestWorld
{
	static constexpr double Tick = 1.0 / 60.0;

	UWorld* World = nullptr;

	FVerseMeleeTestWorld()
	{
		World = UWorld::CreateWorld(EWorldType::Game, false, FName(TEXT("VerseMeleeTestWorld")));
		FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
		Context.SetCurrentWorld(World);
		World->InitializeActorsForPlay(FURL());
		World->BeginPlay();
		if (!World->GetBegunPlay())
		{
			World->GetWorldSettings()->NotifyBeginPlay();
		}
	}

	~FVerseMeleeTestWorld()
	{
		GEngine->DestroyWorldContext(World);
		World->DestroyWorld(false);
	}

	/** A pawn whose capsule base is at Base, facing YawDeg. */
	ACharacter* Spawn(const FVector& Base, double YawDeg)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		ACharacter* Character = World->SpawnActor<ACharacter>(ACharacter::StaticClass(), Base, FRotator(0.0, YawDeg, 0.0), Params);
		Character->GetCharacterMovement()->SetMovementMode(MOVE_None);
		Character->GetCharacterMovement()->GravityScale = 0.f;
		const double Half = Character->GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
		Character->SetActorLocation(Base + FVector(0.0, 0.0, Half));
		UVerseCombatStateComponent* State = NewObject<UVerseCombatStateComponent>(Character, TEXT("CombatState"));
		State->RegisterComponent();
		UVerseMeleeComponent* Melee = NewObject<UVerseMeleeComponent>(Character, TEXT("Melee"));
		Melee->RegisterComponent();
		return Character;
	}

	static UVerseMeleeComponent* Melee(const APawn* Pawn) { return Pawn->FindComponentByClass<UVerseMeleeComponent>(); }
	static UVerseCombatStateComponent* State(const APawn* Pawn) { return Pawn->FindComponentByClass<UVerseCombatStateComponent>(); }

	IVerseMeleeWorld& Port() const { return *UVerseMeleeWorldSubsystem::Get(World); }

	double Now() const { return World->GetTimeSeconds(); }

	void Step(int32 Ticks = 1)
	{
		for (int32 I = 0; I < Ticks; ++I)
		{
			++GFrameCounter;
			World->Tick(LEVELTICK_All, float(Tick));
		}
	}
};

/** Evidence files land in Saved/Harness/proof/WP04/<sub-task>/ (work-packages.md 0.4). */
inline FString VerseWp04ProofPath(const TCHAR* SubTask, const TCHAR* File)
{
	return FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/WP04"), SubTask, File);
}

inline bool VerseWp04WriteProof(const TCHAR* SubTask, const TCHAR* File, const FString& Text)
{
	const FString Path = VerseWp04ProofPath(SubTask, File);
	IFileManager::Get().MakeDirectory(*FPaths::GetPath(Path), true);
	return FFileHelper::SaveStringToFile(Text, *Path, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

#endif // WITH_DEV_AUTOMATION_TESTS
