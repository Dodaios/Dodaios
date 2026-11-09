#include "Screens/VerseTerminalMonitorComponent.h"

#include "Components/MeshComponent.h"
#include "Engine/Font.h"
#include "GameFramework/Actor.h"
#include "Render/VerseTerminalTheme.h"
#include "Screens/VerseScreenSurface.h"
#include "Screens/VerseScreensSubsystem.h"
#include "Stations/VerseStationSubsystem.h"

namespace
{
	/** Cursor blink half period, as xterm's 600 ms. */
	constexpr double BlinkHalfPeriodS = 0.6;
}

UVerseTerminalMonitorComponent::UVerseTerminalMonitorComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
	Colours.Build(UVerseTerminalTheme::Default());
}

FString UVerseTerminalMonitorComponent::ShownPaneId() const
{
	return (!bMasterStation && PaneIds.Num() == 1) ? PaneIds[0] : FString();
}

bool UVerseTerminalMonitorComponent::OffersTakeover() const
{
	return !ShownPaneId().IsEmpty();
}

FVerseTerminalLayout UVerseTerminalMonitorComponent::Layout() const
{
	return FVerseTerminalLayout::Fit(Resolution.X, Resolution.Y, Cells.Cols(), Cells.Rows(), CellAspect);
}

FVerseTerminalGrid::EApply UVerseTerminalMonitorComponent::ApplyFrame(FVerseCellFrame&& Frame)
{
	const bool bWasSnapshot = Frame.Kind == EVerseCellsKind::Snapshot;
	const int32 OldCols = Cells.Cols();
	const int32 OldRows = Cells.Rows();
	const FVerseTerminalGrid::EApply Result = Cells.Apply(MoveTemp(Frame));
	if (Result == FVerseTerminalGrid::EApply::Applied)
	{
		if (CurrentPage != EVerseMonitorPage::Live || (bWasSnapshot && (OldCols != Cells.Cols() || OldRows != Cells.Rows())))
		{
			bPageDirty = true;
		}
		CurrentPage = EVerseMonitorPage::Live;
	}
	return Result;
}

void UVerseTerminalMonitorComponent::ApplyMeta(const FString& Style, bool bCut)
{
	PaneStyle = Style;
	bPaneCut = bCut;
}

void UVerseTerminalMonitorComponent::ShowVacant()
{
	if (CurrentPage != EVerseMonitorPage::Vacant)
	{
		CurrentPage = EVerseMonitorPage::Vacant;
		Cells.Reset();
		bPageDirty = true;
	}
}

void UVerseTerminalMonitorComponent::ShowStandby()
{
	if (CurrentPage != EVerseMonitorPage::Standby)
	{
		CurrentPage = EVerseMonitorPage::Standby;
		Cells.Reset();
		bPageDirty = true;
	}
}

bool UVerseTerminalMonitorComponent::CursorPhase(double Now) const
{
	return FMath::FloorToInt64(Now / BlinkHalfPeriodS) % 2 == 0;
}

bool UVerseTerminalMonitorComponent::NeedsRedraw(double Now) const
{
	if (bPageDirty)
	{
		return true;
	}
	if (CurrentPage != EVerseMonitorPage::Live)
	{
		return false;
	}
	if (Cells.IsDirty())
	{
		return true;
	}
	// Only near monitors blink: far ones repaint at 2 Hz and would stutter.
	return WatchHz >= 10 && Cells.CursorRow() >= 0 && CursorPhase(Now) != bLastCursorPhase;
}

int32 UVerseTerminalMonitorComponent::Redraw(double Now, FVerseTerminalDrawList& Scratch)
{
	const bool bCursorOn = CursorPhase(Now);
	FVerseTerminalLayout L = Layout();
	if (CurrentPage == EVerseMonitorPage::Live)
	{
		if (bCursorOn != bLastCursorPhase && Cells.CursorRow() >= 0)
		{
			FVerseCellFrame Touch;
			// Mark only the cursor row: an empty delta on top of the last seq moves nothing else.
			Touch.Kind = EVerseCellsKind::Delta;
			Touch.Seq = Cells.LastSeq();
			Touch.Base = Cells.LastSeq();
			Touch.Cols = uint16(Cells.Cols());
			Touch.Rows = uint16(Cells.Rows());
			Touch.CursorRow = int16(Cells.CursorRow());
			Touch.CursorCol = int16(Cells.CursorCol());
			Cells.Apply(MoveTemp(Touch));
		}
		VerseTerminalPainter::Build(Cells, Colours, L, bPageDirty, bCursorOn, Scratch);
	}
	else
	{
		const UVerseStationSubsystem* Stations = UVerseStationSubsystem::Get(this);
		const bool bVacant = CurrentPage == EVerseMonitorPage::Vacant;
		const FString Key = bVacant ? TEXT("verse.screen.vacant") : TEXT("verse.screen.standby");
		const FString Fallback = bVacant ? TEXT("VACANT") : TEXT("STANDBY");
		PageLine = Stations ? Stations->Localize(Key, Fallback) : Fallback;
		VerseTerminalPainter::BuildPage(Colours, Resolution.X, Resolution.Y, PageLine, bVacant ? Colours.Index(3) : Colours.Index(8), Scratch);
		L.CellH = FMath::Max(8.f, float(Resolution.Y) / 8.f);
		L.CellW = L.CellH * 0.5f;
	}
	if (ScreenSurface && ScreenSurface->CanPaint())
	{
		UFont* Font = (Theme ? Theme.Get() : &UVerseTerminalTheme::Default())->Font.LoadSynchronous();
		ScreenSurface->Paint([&](UCanvas* Canvas, int32, int32) { VerseTerminalPainter::Submit(Canvas, Font, L, Scratch); });
	}
	const int32 Drawn = Scratch.RowsDrawn;
	Cells.ClearDirty();
	bPageDirty = false;
	bLastCursorPhase = bCursorOn;
	LastDraw = Now;
	return Drawn;
}

void UVerseTerminalMonitorComponent::BeginPlay()
{
	Super::BeginPlay();
	Colours.Build(Theme ? *Theme : UVerseTerminalTheme::Default());
	ScreenSurface = NewObject<UVerseScreenSurface>(this);
	if (ScreenSurface->Init(this, Resolution.X, Resolution.Y, FLinearColor(Colours.Ground)))
	{
		UMeshComponent* Mesh = Cast<UMeshComponent>(ScreenMesh.GetComponent(GetOwner()));
		if (!Mesh && GetOwner())
		{
			Mesh = GetOwner()->FindComponentByClass<UMeshComponent>();
		}
		ScreenSurface->Bind(Mesh, ScreenMaterialIndex, ScreenParameter, ScreenMaterial);
	}
	if (UVerseScreensSubsystem* Screens = UVerseScreensSubsystem::Get(this))
	{
		Screens->RegisterMonitor(this);
		UseHandle = Screens->AddTakeoverTarget(this);
	}
}

void UVerseTerminalMonitorComponent::EndPlay(const EEndPlayReason::Type Reason)
{
	if (UVerseScreensSubsystem* Screens = UVerseScreensSubsystem::Get(this))
	{
		Screens->UnregisterMonitor(this);
	}
	if (UVerseStationSubsystem* Stations = UVerseStationSubsystem::Get(this))
	{
		Stations->RemoveUseTarget(UseHandle);
	}
	UseHandle = INDEX_NONE;
	Super::EndPlay(Reason);
}
