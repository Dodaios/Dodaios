#pragma once

#include "CoreMinimal.h"
#include "Stream/VerseStreamSession.h"
#include "Subsystems/GameInstanceSubsystem.h"

#include "VerseStreamSubsystem.generated.h"

class AActor;
class UWorld;

/**
 * The IDE side panel stream inside Verse.exe (WP20). Owns one FVerseStreamSession with the
 * console driver. The verse host's bridge client and lifecycle (WP17) feed it:
 * `panel.visibility` -> HandlePanelVisibility, `panel.resize` -> HandlePanelResize, entering or
 * leaving the Visible state -> HandleFullViewVisible, and SetLink so `panel.stream_state` reaches
 * the backend. Until then a logging link stands in.
 *
 * Entering Panel moves the local player's view to the deck's panel camera (an actor tagged
 * `verse.panel_camera`), leaving it restores the previous view target.
 */
UCLASS()
class VERSESTREAM_API UVerseStreamSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	/** Actor tag of the panel camera a deck places (one per deck). */
	static const FName PanelCameraTag;

	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	void HandlePanelVisibility(bool bVisible, int32 W, int32 H, float Dpr);
	void HandlePanelResize(int32 W, int32 H, float Dpr);
	void HandleFullViewVisible(bool bVisible);

	void SetLink(TSharedRef<IVerseStreamLink> InLink);
	void SetDriver(TSharedRef<IVerseStreamDriver> InDriver);

	EVersePanelStreamState GetStreamState() const;
	bool IsPanelSession() const { return bPanelSession; }

	/** The first actor tagged PanelCameraTag in World, or null. */
	static AActor* FindPanelCamera(UWorld* World);

	/** The signalling URL from DODAIOS_VERSE_BRIDGE and DODAIOS_VERSE_TOKEN; empty without a launch. */
	static FString SignalUrlFromEnvironment();

private:
	void Rebuild();
	void EnterPanelView(bool bEnter);

	TSharedPtr<IVerseStreamDriver> Driver;
	TSharedPtr<IVerseStreamLink> Link;
	TUniquePtr<FVerseStreamSession> Session;
	TWeakObjectPtr<AActor> PreviousViewTarget;
	bool bPanelSession = false;
};
