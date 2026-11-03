#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "CoreMinimal.h"
#include "Engine/Engine.h"
#include "Engine/World.h"

/** A bare game world for the rules tests: subsystems (the event hub) but no game mode. */
struct FVerseRulesTestWorld
{
	UWorld* World = nullptr;

	FVerseRulesTestWorld()
	{
		World = UWorld::CreateWorld(EWorldType::Game, false);
		FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
		Context.SetCurrentWorld(World);
		World->InitializeActorsForPlay(FURL());
	}

	~FVerseRulesTestWorld()
	{
		GEngine->DestroyWorldContext(World);
		World->DestroyWorld(false);
	}

	template <class T>
	T* Spawn(const FVector& Location = FVector::ZeroVector)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		return World->SpawnActor<T>(T::StaticClass(), Location, FRotator::ZeroRotator, Params);
	}
};

#endif // WITH_DEV_AUTOMATION_TESTS
