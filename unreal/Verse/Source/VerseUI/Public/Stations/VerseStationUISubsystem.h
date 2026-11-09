#pragma once

#include "CoreMinimal.h"
#include "Stations/VerseStationController.h"
#include "Stations/VerseStationSubsystem.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseStationUISubsystem.generated.h"

class SVerseStationPanel;
struct FVerseStationUsedEvent;

/**
 * Station views of a game world (WP16.7): listens to FVerseStationUsedEvent on the hub, runs the
 * station controller, and shows the prompt, the notice line and the launcher and simulator
 * panels as a plain Slate overlay until WP18's UI root takes them in.
 */
UCLASS()
class VERSEUI_API UVerseStationUISubsystem : public UWorldSubsystem
{
	GENERATED_BODY()

public:
	static UVerseStationUISubsystem* Get(const UObject* WorldContext);

	FVerseStationController& Controller() { return StationController; }
	const FVerseStationController& Controller() const { return StationController; }

	/** groups.snapshot, groups.delta, meetings.update from the bridge client. */
	void HandleBridgeFrame(const FJsonObject& Envelope) { StationController.HandleBridgeFrame(Envelope); }

	const FVerseStationPrompt& Prompt() const { return CurrentPrompt; }
	/** The notice line, empty once it expired (4 s). */
	FString Notice(double Now) const { return Now < NoticeUntil ? NoticeText : FString(); }

	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;

private:
	void HandleStationUsed(const FVerseStationUsedEvent& Event);
	void ShowNotice(const FString& Text);

	FVerseStationController StationController;
	FVerseStationPrompt CurrentPrompt;
	FString NoticeText;
	double NoticeUntil = 0.0;
	TWeakObjectPtr<UVerseStationSubsystem> Stations;
	TSharedPtr<SVerseStationPanel> Panel;
	FDelegateHandle UsedHandle;
};
