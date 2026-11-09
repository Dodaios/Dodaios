#pragma once

#include "Cells/VerseTerminalGrid.h"
#include "Components/SceneComponent.h"
#include "CoreMinimal.h"
#include "Render/VerseTerminalPainter.h"

#include "VerseTerminalMonitorComponent.generated.h"

class UMaterialInterface;
class UMeshComponent;
class UVerseScreenSurface;
class UVerseTerminalTheme;

/** What a terminal monitor shows. */
UENUM()
enum class EVerseMonitorPage : uint8
{
	/** No pane, or not watched (parity E-07). */
	Standby,
	/** The pane's cells. */
	Live,
	/** The pane closed, exited or is unknown (screens.gone). */
	Vacant
};

/**
 * A desk monitor showing one pane's live terminal cells (WP16.2), and the takeover use target of
 * its desk (WP16.5, parity S-15/S-16). Placed by zone owners on desk actors; the screens
 * subsystem watches, feeds and repaints it.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSESCREENS_API UVerseTerminalMonitorComponent : public USceneComponent
{
	GENERATED_BODY()

public:
	UVerseTerminalMonitorComponent();

	/** The panes at this desk (`<workspace_id>:<key>`). The monitor shows and offers takeover only with exactly one. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Monitor")
	TArray<FString> PaneIds;

	/** The engineering master station shows every pane and offers no takeover (parity S-15). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Monitor")
	bool bMasterStation = false;

	UPROPERTY(EditAnywhere, Category = "Monitor")
	FIntPoint Resolution = FIntPoint(1024, 640);

	/** Height / width of a cell; the IDE's 13 px font has cells about twice as tall as wide. */
	UPROPERTY(EditAnywhere, Category = "Monitor")
	float CellAspect = 2.f;

	UPROPERTY(EditAnywhere, Category = "Monitor")
	TObjectPtr<UVerseTerminalTheme> Theme;

	/** The mesh the screen is shown on (default: the first mesh of the owner). */
	UPROPERTY(EditAnywhere, Category = "Monitor")
	FComponentReference ScreenMesh;

	UPROPERTY(EditAnywhere, Category = "Monitor")
	int32 ScreenMaterialIndex = 0;

	/** Material with a texture parameter ScreenParameter (default: the mesh's own material). */
	UPROPERTY(EditAnywhere, Category = "Monitor")
	TObjectPtr<UMaterialInterface> ScreenMaterial;

	UPROPERTY(EditAnywhere, Category = "Monitor")
	FName ScreenParameter = TEXT("Screen");

	/** The pane id shown, or empty when the desk has none or several. */
	FString ShownPaneId() const;
	bool OffersTakeover() const;

	/** The pane's title for the takeover prompt (from the roster; parity S-16). */
	void SetPaneTitle(const FString& Title) { PaneTitle = Title; }
	const FString& GetPaneTitle() const { return PaneTitle; }

	/** Feeds a decoded frame; NeedsResync when a delta does not follow the last frame. */
	FVerseTerminalGrid::EApply ApplyFrame(FVerseCellFrame&& Frame);
	void ApplyMeta(const FString& Style, bool bCut);
	void ShowVacant();
	void ShowStandby();

	EVerseMonitorPage Page() const { return CurrentPage; }
	const FVerseTerminalGrid& Grid() const { return Cells; }
	FVerseTerminalLayout Layout() const;
	const FVerseTerminalPalette& Palette() const { return Colours; }

	/** Watch rate the subsystem bound this monitor at (10 near, 2 far; 0 = not watched). */
	int32 WatchHz = 0;

	/** Something to draw: dirty rows, a page change, or a cursor blink. */
	bool NeedsRedraw(double Now) const;
	/** Builds the draw list into Scratch and paints it; returns the rows drawn. */
	int32 Redraw(double Now, FVerseTerminalDrawList& Scratch);
	double LastRedrawTime() const { return LastDraw; }

	UVerseScreenSurface* Surface() const { return ScreenSurface; }

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

private:
	bool CursorPhase(double Now) const;

	UPROPERTY(Transient)
	TObjectPtr<UVerseScreenSurface> ScreenSurface;

	FVerseTerminalGrid Cells;
	FVerseTerminalPalette Colours;
	EVerseMonitorPage CurrentPage = EVerseMonitorPage::Standby;
	FString PaneTitle;
	FString PageLine;
	FString PaneStyle;
	bool bPaneCut = false;
	bool bPageDirty = true;
	bool bLastCursorPhase = true;
	double LastDraw = -1.0;
	int32 UseHandle = INDEX_NONE;
};
