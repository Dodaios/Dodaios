#pragma once

#include "DeckHud/VerseDeckHudModel.h"
#include "DeckHud/VerseDialogStack.h"
#include "Lift/VerseLiftModel.h"
#include "Loading/VerseLoadingModel.h"
#include "Notices/VerseNoticeLine.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseDeckHudSubsystem.generated.h"

class SWidget;
class SVerseDeckHud;
class SVerseLoadingScreen;
class UVerseEventHub;
class UVerseUiSubsystem;
class UVerseServiceRecordSubsystem;
class FVerseServiceRecordModel;

/**
 * The deck's fixed HUD (WP18 gap rows, stream S6): the loading screen until the first deck
 * frame, the deck title with the crew counts and the rank card, the tool rail, the one-line
 * notice and help text, the lift panel with its doors, and the modal bookkeeping every dialog
 * shares (cursor shown, mouse look stopped, focus trapped and returned).
 *
 * Everything the screen shows is a plain model in this class, so tests drive it with a pinned
 * clock and no viewport. The widgets only read the models.
 */
UCLASS()
class VERSEUI_API UVerseDeckHudSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	static UVerseDeckHudSubsystem* Get(const UObject* WorldContextObject);

	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;

	// Models
	FVerseLiftModel& GetLift() { return Lift; }
	FVerseNoticeLine& GetNotice() { return Notice; }
	FVerseLoadingModel& GetLoading() { return Loading; }
	FVerseDialogStack& GetDialogs() { return Dialogs; }
	const FVerseLiftModel& GetLift() const { return Lift; }
	const FVerseLoadingModel& GetLoading() const { return Loading; }

	// Deck, crew and view
	void SetDeck(FName Deck);
	FName GetDeck() const { return Lift.GetCurrentDeck(); }
	/** The officers on the current deck (the roster feeds this). */
	void SetCrew(const TArray<FVerseDeckCrewRow>& Rows);
	FVerseDeckTitle GetTitle() const;
	void SetView(EVerseDeckView View);
	EVerseDeckView GetView() const { return ToolContext.View; }
	/** Overview is the bird's-eye view; the other two are at eye level. */
	bool IsEyeLevel() const { return ToolContext.View != EVerseDeckView::Overview; }
	void SetToolContext(const FVerseToolRailContext& Context);
	const FVerseToolRailContext& GetToolContext() const { return ToolContext; }
	TArray<FVerseToolEntry> GetTools() const { return FVerseToolRail::Build(ToolContext); }
	/** The mouse was taken by the eye-level view (a click on it); the hint then goes. */
	void SetMouseTaken(bool bTaken) { bMouseTaken = bTaken; }
	bool ShowsClickToLook() const;

	/** A tool of the rail was used. */
	void ActivateTool(EVerseTool Tool);
	FSimpleMulticastDelegate OnCommanderRequested;
	DECLARE_MULTICAST_DELEGATE_OneParam(FOnViewRequested, EVerseDeckView);
	FOnViewRequested OnViewRequested;
	DECLARE_MULTICAST_DELEGATE_OneParam(FOnBoardRequested, bool);
	FOnBoardRequested OnBoardRequested;

	// Notices
	void PostNoticeKey(const FString& Key);
	void ShowHelp();
	FText GetNoticeText() const { return Notice.GetText(Now()); }

	// Lift
	void OpenLift(EVerseLiftSource Source);
	void CloseLift();
	/** Picks a deck on the open panel: rides, or closes when it is the same deck. */
	bool ChooseDeck(FName Deck);
	/** The first frame of Deck is on screen (the decks module calls it; the tick infers it from the game port otherwise). */
	void NotifyDeckFrame(FName Deck);

	// Dialogs (parity H-12, H-13)
	/** Opens the rank card's service record on a page. */
	void OpenServiceRecord(int32 TabIndex = 0);
	bool ReleasesMouseLook() const { return Dialogs.BlocksLookInput() || MenuOpen(); }
	bool ShowsCursor() const { return Dialogs.ShouldShowCursor() || MenuOpen(); }
	/** Syncs the dialog stack with the screens that exist (menu screen, service record). */
	void SyncDialogs();

	// Strings, time
	const FVerseUiStrings& Strings() const;
	FText S(const FString& Key) const;
	double Now() const { return Clock ? Clock() : FPlatformTime::Seconds(); }
	TFunction<double()> Clock;

	/** The service record model, for the rank card; null before the game instance has one. */
	TSharedPtr<FVerseServiceRecordModel> GetRecordModel() const;
	UVerseServiceRecordSubsystem* GetRecordSubsystem() const;
	UVerseUiSubsystem* GetUi() const;

	/** Test and tool hook: mount the widgets on the viewport. */
	void AttachSlate();
	void DetachSlate();
	bool IsAttached() const { return HudWidget.IsValid(); }

private:
	bool MenuOpen() const;
	void ApplyInputMode();
	void BindHub();
	void UnbindHub();
	void TickLoading(double Now);
	void TickLift(double Now);
	void RefreshHud();
	void SetDialogOpen(FName Id, bool bOpen);

	FVerseLiftModel Lift;
	FVerseNoticeLine Notice;
	FVerseLoadingModel Loading;
	FVerseDialogStack Dialogs;
	FVerseToolRailContext ToolContext;
	TArray<FVerseDeckCrewRow> Crew;
	bool bMouseTaken = false;
	bool bLookIgnored = false;
	int32 LastDialogSignature = 0;
	double BeganAt = 0.0;
	int32 TicksSinceBegin = 0;

	TWeakObjectPtr<UVerseEventHub> BoundHub;
	FDelegateHandle StationHandle;

	TSharedPtr<SVerseDeckHud> HudWidget;
	TSharedPtr<SWidget> LiftWidget;
	TSharedPtr<SWidget> DoorsWidget;
	TSharedPtr<SVerseLoadingScreen> LoadingWidget;
};
