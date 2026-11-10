#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "AI/NavigationSystemBase.h"
#include "Components/BrushComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Crew/VerseCrewDeck.h"
#include "Crew/VerseCrewPawn.h"
#include "Crew/VerseCrewSubsystem.h"
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "GameFramework/Volume.h"
#include "HAL/PlatformTime.h"
#include "Misc/CoreMisc.h"
#include "Misc/FileHelper.h"
#include "PhysicsEngine/BodySetup.h"
#include "UObject/EnumProperty.h"

#if PLATFORM_WINDOWS
#include "Windows/WindowsHWrapper.h"
#include <realtimeapiset.h>
#elif PLATFORM_LINUX || PLATFORM_MAC
#include <time.h>
#endif
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

/**
 * Stand-in for the WP17 bridge client feeds (work-packages.md 0.3): it plays the G0.11 golden
 * fixtures and fake_bridge.py scenarios (unreal/Verse/Tests/Data/bridge/) into the crew
 * subsystem exactly as the client would hand them over, with a per-connection seq and base
 * on deltas, and records every command crew life sends.
 */
class FFakeVerseCrewBridge
{
public:
	struct FCommand
	{
		FString Type;
		TSharedRef<FJsonObject> Data;
		double At;
	};

	TArray<FCommand> Commands;
	int64 Seq = 100;
	TMap<FString, int64> TopicSeq;

	static FString DataDir()
	{
		return FPaths::ConvertRelativePathToFull(FPaths::ProjectDir() / TEXT("Tests/Data/bridge"));
	}

	static TSharedPtr<FJsonValue> LoadJson(const FString& Path)
	{
		FString Text;
		if (!FFileHelper::LoadFileToString(Text, *Path))
		{
			return nullptr;
		}
		TSharedPtr<FJsonValue> Value;
		const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
		FJsonSerializer::Deserialize(Reader, Value);
		return Value;
	}

	/** Every frame of a golden message file (messages/<type>.json). */
	static TArray<TSharedRef<FJsonObject>> GoldenFrames(const FString& Type)
	{
		TArray<TSharedRef<FJsonObject>> Out;
		const TSharedPtr<FJsonValue> Value = LoadJson(DataDir() / TEXT("messages") / (Type + TEXT(".json")));
		if (Value.IsValid() && Value->Type == EJson::Array)
		{
			for (const TSharedPtr<FJsonValue>& Item : Value->AsArray())
			{
				if (Item->AsObject().IsValid())
				{
					Out.Add(Item->AsObject().ToSharedRef());
				}
			}
		}
		return Out;
	}

	static TSharedPtr<FJsonObject> Scenario(const FString& Name)
	{
		const TSharedPtr<FJsonValue> Value = LoadJson(DataDir() / TEXT("scenarios") / (Name + TEXT(".json")));
		return Value.IsValid() ? Value->AsObject() : nullptr;
	}

	void Bind(UVerseCrewSubsystem* Crew)
	{
		Crew->SetCommandSink([this, Crew](const FString& Type, const TSharedRef<FJsonObject>& Data) {
			Commands.Add({ Type, Data, Crew->GetClockSeconds() });
		});
	}

	/** Sends a frame with a fresh seq (and the topic's last seq as base for deltas). */
	void Send(UVerseCrewSubsystem* Crew, const FString& Type, const TSharedRef<FJsonObject>& Data, TOptional<int64> BaseOverride = {})
	{
		FString Topic;
		FString Verb;
		Type.Split(TEXT("."), &Topic, &Verb);
		const TSharedRef<FJsonObject> Frame = MakeShared<FJsonObject>();
		Frame->SetStringField(TEXT("type"), Type);
		Frame->SetNumberField(TEXT("seq"), static_cast<double>(++Seq));
		Frame->SetNumberField(TEXT("ts"), 1793612340.0 + Seq * 0.01);
		if (Verb == TEXT("delta"))
		{
			const int64* Last = TopicSeq.Find(Topic);
			Frame->SetNumberField(TEXT("base"), static_cast<double>(BaseOverride.IsSet() ? BaseOverride.GetValue() : (Last ? *Last : 0)));
		}
		Frame->SetObjectField(TEXT("data"), Data);
		TopicSeq.Add(Topic, Seq);
		Crew->HandleBridgeObject(Frame);
	}

	/** Plays a scenario: the snapshots of its state, then every frame step (time is ignored). */
	int32 PlayScenario(UVerseCrewSubsystem* Crew, const FString& Name)
	{
		const TSharedPtr<FJsonObject> S = Scenario(Name);
		if (!S.IsValid())
		{
			return -1;
		}
		int32 Frames = 0;
		const TSharedPtr<FJsonObject>* State = nullptr;
		if (S->TryGetObjectField(TEXT("state"), State) && State)
		{
			for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*State)->Values)
			{
				if (Pair.Key.EndsWith(TEXT(".snapshot")) && Pair.Value->AsObject().IsValid())
				{
					Send(Crew, Pair.Key, Pair.Value->AsObject().ToSharedRef());
					++Frames;
				}
			}
		}
		const TArray<TSharedPtr<FJsonValue>>* Steps = nullptr;
		if (S->TryGetArrayField(TEXT("steps"), Steps))
		{
			for (const TSharedPtr<FJsonValue>& Step : *Steps)
			{
				const TSharedPtr<FJsonObject>* Frame = nullptr;
				if (Step->AsObject()->TryGetObjectField(TEXT("frame"), Frame) && Frame)
				{
					const FString Type = (*Frame)->GetStringField(TEXT("type"));
					const TSharedPtr<FJsonObject>* Data = nullptr;
					if ((*Frame)->TryGetObjectField(TEXT("data"), Data) && Data)
					{
						Send(Crew, Type, Data->ToSharedRef());
						++Frames;
					}
				}
			}
		}
		return Frames;
	}

	int32 Count(const FString& Type, const FString& Action = FString()) const
	{
		int32 N = 0;
		for (const FCommand& C : Commands)
		{
			if (C.Type == Type && (Action.IsEmpty() || C.Data->GetStringField(TEXT("action")) == Action))
			{
				++N;
			}
		}
		return N;
	}
};

/**
 * CPU time of the calling thread in seconds. The machine is shared by many agents, so wall
 * time of a sub-millisecond tick includes the scheduler handing the core to someone else;
 * the crew's game-thread cost is the time this thread actually ran.
 */
struct FVerseCrewThreadClock
{
	double CyclesPerSecond = 0.0;

	static uint64 Cycles()
	{
#if PLATFORM_WINDOWS
		ULONG64 Value = 0;
		::QueryThreadCycleTime(::GetCurrentThread(), &Value);
		return Value;
#elif PLATFORM_LINUX || PLATFORM_MAC
		struct timespec Ts;
		clock_gettime(CLOCK_THREAD_CPUTIME_ID, &Ts);
		return static_cast<uint64>(Ts.tv_sec) * 1000000000ull + static_cast<uint64>(Ts.tv_nsec);
#else
		return static_cast<uint64>(FPlatformTime::Seconds() * 1.0e9);
#endif
	}

	/** Thread cycles run at the invariant TSC rate on Windows: measured against wall time while spinning. */
	void Calibrate()
	{
#if PLATFORM_WINDOWS
		double Best = 0.0;
		for (int32 Try = 0; Try < 5; ++Try)
		{
			const uint64 C0 = Cycles();
			const double T0 = FPlatformTime::Seconds();
			double T1 = T0;
			while (T1 - T0 < 0.03)
			{
				T1 = FPlatformTime::Seconds();
			}
			const uint64 C1 = Cycles();
			// A preempted try counts fewer cycles for the same wall time: keep the fastest.
			Best = FMath::Max(Best, static_cast<double>(C1 - C0) / (T1 - T0));
		}
		CyclesPerSecond = Best;
#else
		CyclesPerSecond = 1.0e9;
#endif
	}

	double Ms(uint64 From, uint64 To) const
	{
		return CyclesPerSecond > 0.0 ? static_cast<double>(To - From) / CyclesPerSecond * 1000.0 : 0.0;
	}
};

/** A bare game world with the crew subsystem, ticked by hand. */
struct FVerseCrewTestWorld
{
	UWorld* World = nullptr;
	UVerseCrewSubsystem* Crew = nullptr;
	FFakeVerseCrewBridge Bridge;

	FVerseCrewTestWorld()
	{
		World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("VerseCrewTestWorld"));
		Crew = World ? World->GetSubsystem<UVerseCrewSubsystem>() : nullptr;
		if (Crew)
		{
			Crew->SetAutoTick(false);
			Crew->SetEpochMs(1790000000000LL);
			Bridge.Bind(Crew);
		}
	}

	~FVerseCrewTestWorld()
	{
		if (World)
		{
			World->DestroyWorld(false);
		}
	}

	bool IsValid() const { return World && Crew; }

	/** Loads fixture decks side by side, 200 m apart, and puts their crew on screen. */
	bool LoadDecks(const TArray<FName>& DeckIds, FString& Error)
	{
		TMap<FName, FVector> Origins;
		for (int32 I = 0; I < DeckIds.Num(); ++I)
		{
			Origins.Add(DeckIds[I], FVector(20000.0 * I, 0.0, 0.0));
		}
		if (!Crew->RegisterFixtureDecks(Origins, Error))
		{
			return false;
		}
		Crew->SetLoadedDecks(DeckIds);
		return true;
	}

	/**
	 * Recast over the WP15 walk fixtures of the given (registered) decks: floor slabs from
	 * Content/Verse/Test/WP15/Decks/<deck>.walk.json, one nav bounds volume per deck, a game-mode
	 * navigation system and a blocking build. The engine's navigation classes are reached by
	 * name (VerseCrew links Engine only). Returns false with Error when anything is missing.
	 */
	/** What BuildNav saw (bounds, slabs, the navmesh's generation mode), for the test log. */
	FString NavDiag;

	bool BuildNav(const TArray<FName>& DeckIds, FString& Error, double* OutBuildMs = nullptr)
	{
		int32 Slabs = 0;
		const double Start = FPlatformTime::Seconds();
		UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
		UClass* BoundsClass = FindObject<UClass>(nullptr, TEXT("/Script/NavigationSystem.NavMeshBoundsVolume"));
		UClass* RecastClass = FindObject<UClass>(nullptr, TEXT("/Script/NavigationSystem.RecastNavMesh"));
		if (!Cube || !BoundsClass || !RecastClass)
		{
			Error = TEXT("engine cube, NavMeshBoundsVolume or RecastNavMesh class missing");
			return false;
		}
		constexpr float SlabCm = 20.f;
		for (const FName& DeckId : DeckIds)
		{
			const FVerseCrewDeck* Deck = Crew->FindDeck(DeckId);
			const TSharedPtr<FJsonValue> Doc = FFakeVerseCrewBridge::LoadJson(VerseCrew::FixtureDeckDir() / (DeckId.ToString() + TEXT(".walk.json")));
			const TArray<TSharedPtr<FJsonValue>>* Boxes = nullptr;
			if (!Deck || !Doc.IsValid() || !Doc->AsObject().IsValid() || !Doc->AsObject()->TryGetArrayField(TEXT("boxes"), Boxes))
			{
				Error = FString::Printf(TEXT("no deck or walk fixture for %s"), *DeckId.ToString());
				return false;
			}
			FBox Bounds(ForceInit);
			for (const TSharedPtr<FJsonValue>& Value : *Boxes)
			{
				const TArray<TSharedPtr<FJsonValue>>& B = Value->AsArray();
				const FVector Min = Deck->OriginCm + FVector(B[0]->AsNumber(), B[1]->AsNumber(), B[4]->AsNumber() - SlabCm);
				const FVector Max = Deck->OriginCm + FVector(B[2]->AsNumber(), B[3]->AsNumber(), B[4]->AsNumber());
				Bounds += FBox(Min, Max);
				const FTransform Xf(FRotator::ZeroRotator, (Min + Max) * 0.5f, (Max - Min) / 100.f);
				AStaticMeshActor* Slab = World->SpawnActorDeferred<AStaticMeshActor>(AStaticMeshActor::StaticClass(), Xf);
				if (!Slab)
				{
					Error = TEXT("floor slab did not spawn");
					return false;
				}
				Slab->GetStaticMeshComponent()->SetStaticMesh(Cube);
				Slab->FinishSpawning(Xf);
				++Slabs;
			}
			Bounds = Bounds.ExpandBy(FVector(200.f, 200.f, 300.f));
			const FTransform VolumeXf(Bounds.GetCenter());
			AVolume* Volume = World->SpawnActorDeferred<AVolume>(BoundsClass, VolumeXf);
			if (!Volume || !Volume->GetBrushComponent())
			{
				Error = TEXT("nav bounds volume did not spawn");
				return false;
			}
			UBrushComponent* Brush = Volume->GetBrushComponent();
			UBodySetup* Shape = NewObject<UBodySetup>(Brush);
			const FVector Size = Bounds.GetSize();
			Shape->AggGeom.BoxElems.Add(FKBoxElem(Size.X, Size.Y, Size.Z));
			Brush->BrushBodySetup = Shape;
			Volume->FinishSpawning(VolumeXf);
			// Construction can replace the brush's body setup; the bounds the navigation system
			// gathers come from it, so set it again and refresh the bounds.
			Brush->BrushBodySetup = Shape;
			Brush->UpdateBounds();
			const FBox Got = Volume->GetComponentsBoundingBox(true);
			if (!Got.IsValid || Got.GetSize().X < 100.f)
			{
				Error = FString::Printf(TEXT("nav bounds volume for %s has no size (%s)"), *DeckId.ToString(), *Got.ToString());
				return false;
			}
			NavDiag += FString::Printf(TEXT("%s volume %s (registered %d); "), *DeckId.ToString(), *Volume->GetComponentsBoundingBox(true).ToString(),
				Volume->HasActorRegisteredAllComponents() ? 1 : 0);
		}
		NavDiag += FString::Printf(TEXT("slabs %d; "), Slabs);
		// The project builds no navmesh at runtime (RuntimeGeneration=Static); the test's navmesh
		// is generated, so the RecastNavMesh default is dynamic while its instance spawns.
		UObject* RecastDefaults = RecastClass->GetDefaultObject();
		FEnumProperty* Generation = CastField<FEnumProperty>(RecastClass->FindPropertyByName(TEXT("RuntimeGeneration")));
		int64 OldGeneration = 0;
		if (Generation)
		{
			void* Ptr = Generation->ContainerPtrToValuePtr<void>(RecastDefaults);
			OldGeneration = Generation->GetUnderlyingProperty()->GetSignedIntPropertyValue(Ptr);
			int64 Dynamic = Generation->GetEnum()->GetValueByNameString(TEXT("Dynamic"));
			Generation->GetUnderlyingProperty()->SetIntPropertyValue(Ptr, Dynamic == INDEX_NONE ? int64(2) : Dynamic);
		}
		FNavigationSystem::AddNavigationSystemToWorld(*World, FNavigationSystemRunMode::GameMode, nullptr, true, true);
		FSelfRegisteringExec::StaticExec(World, TEXT("RebuildNavigation"), *GLog);
		if (Generation)
		{
			for (TObjectIterator<UObject> It; It; ++It)
			{
				if (It->GetWorld() == World && It->IsA(RecastClass) && !It->HasAnyFlags(RF_ClassDefaultObject))
				{
					NavDiag += FString::Printf(TEXT("navmesh %s generation %lld; "), *It->GetName(),
						Generation->GetUnderlyingProperty()->GetSignedIntPropertyValue(Generation->ContainerPtrToValuePtr<void>(*It)));
				}
			}
			Generation->GetUnderlyingProperty()->SetIntPropertyValue(Generation->ContainerPtrToValuePtr<void>(RecastDefaults), OldGeneration);
		}
		else
		{
			NavDiag += TEXT("RuntimeGeneration property not found; ");
		}
		if (const UNavigationSystemBase* Nav = World->GetNavigationSystem())
		{
			NavDiag += FString::Printf(TEXT("navigable bounds %s"), *Nav->GetNavigableWorldBounds().ToString());
		}
		if (OutBuildMs)
		{
			*OutBuildMs = (FPlatformTime::Seconds() - Start) * 1000.0;
		}
		if (!Crew->HasNavigation())
		{
			Error = Generation ? TEXT("the navigation system has no navmesh after the build") : TEXT("RecastNavMesh.RuntimeGeneration not found");
			return false;
		}
		return true;
	}

	void Run(float Seconds, float Step = 1.f / 30.f)
	{
		for (float T = 0.f; T < Seconds - KINDA_SMALL_NUMBER; T += Step)
		{
			Crew->Tick(Step);
		}
	}

	static TSharedRef<FJsonObject> Agent(const FString& Id, const FString& Name, const FString& Duty, int32 Level = 6, const FString& Tier = TEXT("specialist"))
	{
		const TSharedRef<FJsonObject> A = MakeShared<FJsonObject>();
		A->SetStringField(TEXT("agent_id"), Id);
		A->SetStringField(TEXT("name"), Name);
		A->SetStringField(TEXT("title"), TEXT("Crew member"));
		A->SetStringField(TEXT("tier"), Tier);
		A->SetStringField(TEXT("lifecycle"), TEXT("active"));
		A->SetStringField(TEXT("run_state"), Duty == TEXT("error") ? TEXT("idle") : Duty);
		A->SetStringField(TEXT("duty"), Duty);
		A->SetNumberField(TEXT("level"), Level);
		A->SetStringField(TEXT("rank"), TEXT("ensign"));
		A->SetStringField(TEXT("look"), TEXT("look_01"));
		A->SetArrayField(TEXT("team_ids"), {});
		A->SetField(TEXT("pane"), MakeShared<FJsonValueNull>());
		return A;
	}

	static TSharedRef<FJsonObject> Pane(const FString& Id, const FString& Duty)
	{
		FString Workspace;
		FString Key;
		Id.Split(TEXT(":"), &Workspace, &Key);
		const TSharedRef<FJsonObject> P = MakeShared<FJsonObject>();
		P->SetStringField(TEXT("pane_id"), Id);
		P->SetStringField(TEXT("workspace_id"), Workspace);
		P->SetStringField(TEXT("key"), Key);
		P->SetStringField(TEXT("history_id"), TEXT("h_") + Key);
		P->SetStringField(TEXT("name"), Key);
		P->SetStringField(TEXT("display_name"), TEXT("Coding agent"));
		P->SetStringField(TEXT("agent"), TEXT("agent"));
		P->SetStringField(TEXT("status"), TEXT("live"));
		P->SetStringField(TEXT("activity"), Duty == TEXT("working") ? TEXT("working") : TEXT("waiting"));
		P->SetStringField(TEXT("duty"), Duty);
		P->SetNumberField(TEXT("cols"), 132);
		P->SetNumberField(TEXT("rows"), 40);
		return P;
	}

	static TSharedRef<FJsonObject> Snapshot(const TArray<TSharedRef<FJsonObject>>& Agents, const TArray<TSharedRef<FJsonObject>>& Panes)
	{
		const TSharedRef<FJsonObject> D = MakeShared<FJsonObject>();
		const TSharedRef<FJsonObject> C = MakeShared<FJsonObject>();
		C->SetStringField(TEXT("subject_id"), TEXT("person"));
		C->SetNumberField(TEXT("level"), 14);
		C->SetStringField(TEXT("rank"), TEXT("lieutenant"));
		C->SetStringField(TEXT("title"), TEXT("Lieutenant"));
		C->SetStringField(TEXT("uniform"), TEXT("standard"));
		D->SetObjectField(TEXT("commander"), C);
		TArray<TSharedPtr<FJsonValue>> A;
		for (const TSharedRef<FJsonObject>& X : Agents) A.Add(MakeShared<FJsonValueObject>(X));
		TArray<TSharedPtr<FJsonValue>> P;
		for (const TSharedRef<FJsonObject>& X : Panes) P.Add(MakeShared<FJsonValueObject>(X));
		D->SetArrayField(TEXT("agents"), A);
		D->SetArrayField(TEXT("panes"), P);
		return D;
	}

	static TSharedRef<FJsonObject> Delta(const TArray<TSharedRef<FJsonObject>>& Agents, const TArray<FString>& RemoveAgents = {},
		const TArray<TSharedRef<FJsonObject>>& Panes = {}, const TArray<FString>& RemovePanes = {})
	{
		const TSharedRef<FJsonObject> D = MakeShared<FJsonObject>();
		const TSharedRef<FJsonObject> Up = MakeShared<FJsonObject>();
		const TSharedRef<FJsonObject> Rm = MakeShared<FJsonObject>();
		TArray<TSharedPtr<FJsonValue>> A, P, RA, RP;
		for (const TSharedRef<FJsonObject>& X : Agents) A.Add(MakeShared<FJsonValueObject>(X));
		for (const TSharedRef<FJsonObject>& X : Panes) P.Add(MakeShared<FJsonValueObject>(X));
		for (const FString& X : RemoveAgents) RA.Add(MakeShared<FJsonValueString>(X));
		for (const FString& X : RemovePanes) RP.Add(MakeShared<FJsonValueString>(X));
		Up->SetArrayField(TEXT("agents"), A);
		Up->SetArrayField(TEXT("panes"), P);
		Rm->SetArrayField(TEXT("agents"), RA);
		Rm->SetArrayField(TEXT("panes"), RP);
		D->SetObjectField(TEXT("upsert"), Up);
		D->SetObjectField(TEXT("remove"), Rm);
		D->SetField(TEXT("commander"), MakeShared<FJsonValueNull>());
		return D;
	}

	/** Proof folder of work-packages.md 0.4 (ignored by git). */
	static FString ProofDir(const FString& SubTask)
	{
		return FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("Harness/proof/WP15") / SubTask);
	}

	static void WriteProof(const FString& SubTask, const FString& File, const TSharedRef<FJsonObject>& Object)
	{
		FString Text;
		const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
		FJsonSerializer::Serialize(Object, Writer);
		FFileHelper::SaveStringToFile(Text, *(ProofDir(SubTask) / File));
	}
};

#endif // WITH_DEV_AUTOMATION_TESTS
