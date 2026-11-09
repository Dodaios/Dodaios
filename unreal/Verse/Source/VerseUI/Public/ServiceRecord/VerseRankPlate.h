#pragma once

#include "CoreMinimal.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SLeafWidget.h"

/**
 * The rank plate (parity R-03, art style bible 7.2): a brushed-steel plate with chamfered ends
 * and six elongated hexagon sockets in two rows of three. Slot index facing the wearer: top row
 * 0 1 2, bottom row 3 4 5. Every rank lights its own left-right-symmetric pattern, so no two
 * ranks share a plate even without the tier colour.
 */
struct VERSEUI_API FVerseRankPlate
{
	/** Six slots, top row then bottom row. */
	bool Lit[6] = {false, false, false, false, false, false};
	FName Tier;
	FLinearColor TileColour = FLinearColor::White;

	int32 NumLit() const;
	/** Both rows read the same from the left and from the right. */
	bool IsSymmetric() const;
	/** The pattern as the ladder writes it, "010|111". */
	FString Pattern() const;

	/** The plate of a rank id; an unknown id is the recruit's. */
	static FVerseRankPlate For(FName RankId);
	/** The plate a level holds. */
	static FVerseRankPlate ForLevel(int32 Level);
	/** The tile colour of a tier: steel, blue, copper, gold (style bible 7.2). */
	static FLinearColor TierColour(FName Tier);
	/** The cloth colour of a tier's uniform (style bible 7.1). */
	static FLinearColor UniformColour(FName Tier);
};

/** Draws a rank plate; Revealed < NumLit shows only that many tiles (the promotion lays them on one by one). */
class VERSEUI_API SVerseRankPlate : public SLeafWidget
{
public:
	SLATE_BEGIN_ARGS(SVerseRankPlate)
		: _Rank(FName(TEXT("recruit")))
		, _Width(54.f)
		, _Revealed(6)
	{
	}
	SLATE_ATTRIBUTE(FName, Rank)
	SLATE_ARGUMENT(float, Width)
	SLATE_ATTRIBUTE(int32, Revealed)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect, FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const override;
	virtual FVector2D ComputeDesiredSize(float LayoutScaleMultiplier) const override;

private:
	TAttribute<FName> Rank;
	TAttribute<int32> Revealed;
	float Width = 54.f;
};
