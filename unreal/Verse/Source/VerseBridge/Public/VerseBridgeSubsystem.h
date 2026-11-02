#pragma once

#include "CoreMinimal.h"
#include "Bridge/VerseBridgeClient.h"
#include "Containers/Ticker.h"
#include "Lifecycle/VerseLifecycle.h"
#include "Subsystems/GameInstanceSubsystem.h"

#include "VerseBridgeSubsystem.generated.h"

class FVerseEngineLifecycleHost;
class FVerseReturnKeyProcessor;

/**
 * The bridge for game code: one per game instance. Finds the backend (environment, or the dev
 * discovery file outside Shipping), keeps the link up, exposes the typed feeds and the command
 * sender, runs the lifecycle state machine against the engine, answers qa.exec through
 * UVerseQaRegistry, and holds the single-instance mutex (architecture 1.1).
 *
 *   UVerseBridgeSubsystem* Bridge = GetGameInstance()->GetSubsystem<UVerseBridgeSubsystem>();
 *   Bridge->Client().Roster.OnChanged.AddLambda(...);
 *   Bridge->Client().SendCommand(TEXT("pane.open"), Data, OnReply);
 */
UCLASS()
class VERSEBRIDGE_API UVerseBridgeSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	FVerseBridgeClient& Client() { return *BridgeClient; }
	FVerseLifecycleController& Lifecycle() { return *LifecycleController; }

	/** Whether this process owns the single-instance mutex (false: another Verse runs). */
	bool OwnsInstance() const { return bOwnsInstance; }

	/** Topics every Verse subscribes to; feeds of other topics subscribe on demand. */
	static TArray<FString> DefaultTopics();

private:
	bool Tick(float DeltaSeconds);
	void HandleServerCommand(const FVerseBridgeFrame& Frame);
	bool AcquireInstance();
	void ReleaseInstance();

	TUniquePtr<FVerseBridgeClient> BridgeClient;
	TUniquePtr<FVerseEngineLifecycleHost> EngineHost;
	TUniquePtr<FVerseLifecycleController> LifecycleController;
	TSharedPtr<FVerseReturnKeyProcessor> ReturnKey;
	FTSTicker::FDelegateHandle TickHandle;
	FDelegateHandle EndFrameHandle;
	bool bOwnsInstance = false;
	bool bConnected = false;
	void* InstanceMutex = nullptr;
};
