#pragma once

#include "AbilitySystemComponent.h"
#include "Combat/VerseGadgetDefinition.h"
#include "Combat/VerseWeaponDefinition.h"
#include "Components/SceneComponent.h"
#include "CoreMinimal.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Damage/VerseDamageService.h"
#include "Inventory/VerseWeaponSlot.h"
#include "Damage/VerseHealthSet.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "HAL/FileManager.h"
#include "LagComp/VerseLagCompensation.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Policies/PrettyJsonPrintPolicy.h"
#include "Serialization/JsonSerializer.h"
#include "Weapons/VerseDefinitionJson.h"
#include "Weapons/VerseWeaponRegistry.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_WP02_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseWp02Test
{
	inline constexpr float Tick = 1.f / 60.f;

	/** Every weapon definition from Data/weapons, imported fresh (rooted for the test's life by the caller's world or registry). */
	inline TArray<const UVerseWeaponDefinition*> AllWeapons(FAutomationTestBase& Test)
	{
		TArray<FString> Errors;
		TArray<UVerseWeaponDefinition*> Loaded = FVerseDefinitionJson::LoadAllWeapons(GetTransientPackage(), Errors);
		for (const FString& E : Errors)
		{
			Test.AddError(E);
		}
		TArray<const UVerseWeaponDefinition*> Out;
		for (UVerseWeaponDefinition* W : Loaded)
		{
			W->AddToRoot(); // survive a GC during the test; tests are short-lived processes
			Out.Add(W);
		}
		return Out;
	}

	inline const UVerseWeaponDefinition* Weapon(FAutomationTestBase& Test, const TCHAR* Id)
	{
		const UVerseWeaponDefinition* W = FVerseWeaponRegistry::FindWeapon(FName(Id));
		Test.TestNotNull(FString::Printf(TEXT("weapon %s loads"), Id), W);
		return W;
	}

	inline const UVerseGadgetDefinition* Gadget(FAutomationTestBase& Test, const TCHAR* Id)
	{
		const UVerseGadgetDefinition* G = FVerseWeaponRegistry::FindGadget(FName(Id));
		Test.TestNotNull(FString::Printf(TEXT("gadget %s loads"), Id), G);
		return G;
	}

	/** A standalone game world for one test (authority, physics scene, subsystems), destroyed with the scope. */
	struct FTestWorld
	{
		UWorld* World = nullptr;

		FTestWorld()
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, MakeUniqueObjectName(GetTransientPackage(), UWorld::StaticClass(), TEXT("VerseWp02Test")));
			FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
			Context.SetCurrentWorld(World);
			const FURL Url;
			World->InitializeActorsForPlay(Url);
			World->BeginPlay();
		}

		~FTestWorld()
		{
			if (World)
			{
				World->BeginTearingDown();
				GEngine->DestroyWorldContext(World);
				World->DestroyWorld(false);
				World = nullptr;
			}
		}

		void TickFrames(int32 N, float Dt = Tick)
		{
			for (int32 I = 0; I < N; ++I)
			{
				World->Tick(LEVELTICK_All, Dt);
			}
		}
	};

	/** A pawn with a root, an ability system with UVerseHealthSet, and a combat state component. */
	inline APawn* SpawnTarget(UWorld* World, const FVector& Location, float MaxHealth = 100.f, const FRotator& Rotation = FRotator::ZeroRotator)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		APawn* Pawn = World->SpawnActor<APawn>(APawn::StaticClass(), FTransform::Identity, Params);
		USceneComponent* Root = NewObject<USceneComponent>(Pawn, TEXT("Root"));
		Pawn->SetRootComponent(Root);
		Root->RegisterComponent();
		Pawn->SetActorLocationAndRotation(Location, Rotation);

		UAbilitySystemComponent* Asc = NewObject<UAbilitySystemComponent>(Pawn, TEXT("Abilities"));
		Asc->RegisterComponent();
		UVerseHealthSet* Set = NewObject<UVerseHealthSet>(Pawn, TEXT("Health"));
		Asc->AddAttributeSetSubobject(Set);
		Asc->InitAbilityActorInfo(Pawn, Pawn);
		Asc->SetNumericAttributeBase(UVerseHealthSet::GetMaxHealthAttribute(), MaxHealth);
		Asc->SetNumericAttributeBase(UVerseHealthSet::GetHealthAttribute(), MaxHealth);

		UVerseCombatStateComponent* State = NewObject<UVerseCombatStateComponent>(Pawn, TEXT("CombatState"));
		State->RegisterComponent();
		return Pawn;
	}

	inline float HealthOf(const AActor* Actor)
	{
		const UAbilitySystemComponent* Asc = Actor ? Actor->FindComponentByClass<UAbilitySystemComponent>() : nullptr;
		const UVerseHealthSet* Set = Asc ? Asc->GetSet<UVerseHealthSet>() : nullptr;
		return Set ? Set->GetHealth() : -1.f;
	}

	/** Hit bodies of a standing human, relative to its root on the floor: legs, torso, neck, head. */
	inline void HumanCapsules(const FVector& Root, TArray<FVerseHitCapsule>& Out)
	{
		auto Add = [&Out, &Root](const TCHAR* Bone, const FVector& A, const FVector& B, float R)
		{
			FVerseHitCapsule& C = Out.AddDefaulted_GetRef();
			C.Bone = FName(Bone);
			C.Zone = UVerseLagCompSubsystem::ZoneForBone(C.Bone);
			C.A = Root + A;
			C.B = Root + B;
			C.Radius = R;
			C.BoneTransform = FTransform(Root + 0.5 * (A + B));
		};
		Add(TEXT("Calf_L"), FVector(0, -12, 10), FVector(0, -12, 50), 8.f);
		Add(TEXT("Calf_R"), FVector(0, 12, 10), FVector(0, 12, 50), 8.f);
		Add(TEXT("Thigh_L"), FVector(0, -12, 55), FVector(0, -12, 90), 10.f);
		Add(TEXT("Thigh_R"), FVector(0, 12, 55), FVector(0, 12, 90), 10.f);
		Add(TEXT("Hips"), FVector(0, -8, 98), FVector(0, 8, 98), 14.f);
		Add(TEXT("Spine_01"), FVector(0, 0, 108), FVector(0, 0, 118), 15.f);
		Add(TEXT("Spine_03"), FVector(0, 0, 125), FVector(0, 0, 145), 18.f);
		Add(TEXT("Neck"), FVector(0, 0, 152), FVector(0, 0, 158), 6.f);
		Add(TEXT("Head"), FVector(0, 0, 168), FVector(0, 0, 172), 11.f);
	}

	/** Proof files of section 0.4: Saved/Harness/proof/WP02/<sub-task>/<name>. */
	inline FString ProofPath(const TCHAR* SubTask, const TCHAR* Name)
	{
		return FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness"), TEXT("proof"), TEXT("WP02"), SubTask, Name);
	}

	inline void WriteProof(const TCHAR* SubTask, const TCHAR* Name, const TSharedRef<FJsonObject>& Json)
	{
		FString Text;
		const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer = TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Text);
		FJsonSerializer::Serialize(Json, Writer);
		const FString Path = ProofPath(SubTask, Name);
		IFileManager::Get().MakeDirectory(*FPaths::GetPath(Path), true);
		FFileHelper::SaveStringToFile(Text, *Path);
	}
}

#endif // WITH_DEV_AUTOMATION_TESTS
