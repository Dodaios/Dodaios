#pragma once

#include "CoreMinimal.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/SLeafWidget.h"

class UVerseDeckHudSubsystem;

/** The lift panel (parity L-01): the decks top to bottom, the current one marked and focused. */
class SVerseLiftPanel : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SVerseLiftPanel) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs, UVerseDeckHudSubsystem* InOwner);
};

/** Two door leaves that slide shut and open over the whole screen (parity L-02). */
class SVerseLiftDoors : public SLeafWidget
{
public:
	SLATE_BEGIN_ARGS(SVerseLiftDoors) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs, UVerseDeckHudSubsystem* InOwner);

	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect, FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const override;
	virtual FVector2D ComputeDesiredSize(float LayoutScaleMultiplier) const override { return FVector2D(1.0, 1.0); }

private:
	TWeakObjectPtr<UVerseDeckHudSubsystem> Owner;
};
