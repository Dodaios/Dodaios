#pragma once

#include "Core/VerseUiLayout.h"
#include "Core/VerseUiPorts.h"
#include "CoreMinimal.h"
#include "Hud/VerseHudModel.h"

class FVerseUiStrings;
class UCanvas;

enum class EVerseTextAlign : uint8
{
	Left,
	Centre,
	Right,
};

/**
 * A flat list of what the HUD draws this frame. The painter fills it from pure inputs (so tests
 * read exactly what would be drawn); FVerseHudCanvasRenderer turns it into canvas items.
 */
struct VERSEUI_API FVerseHudDrawList
{
	struct FLine
	{
		FVector2D A, B;
		float Thickness = 1.f;
		FLinearColor Colour;
		FName Tag;
	};
	struct FRect
	{
		FVector2D Min, Max;
		FLinearColor Colour;
		FName Tag;
	};
	struct FTri
	{
		FVector2D A, B, C;
		FLinearColor Colour;
		FName Tag;
	};
	struct FLabel
	{
		/** Anchor point; meaning depends on Align (left edge, centre or right edge of the top). */
		FVector2D Position;
		FText Text;
		int32 FontSize = 12;
		bool bBold = false;
		FLinearColor Colour;
		EVerseTextAlign Align = EVerseTextAlign::Left;
		/** Width the layout reserved (0 = unbounded); A18.4 checks text fits it. */
		float MaxWidth = 0.f;
		/** Measured size, filled by the painter. */
		FVector2D Size = FVector2D::ZeroVector;
		FName Tag;
	};

	TArray<FLine> Lines;
	TArray<FRect> Rects;
	TArray<FTri> Tris;
	TArray<FLabel> Labels;

	/** Where the crosshair centre was drawn (A18.1). */
	FVector2D CrosshairCentre = FVector2D::ZeroVector;
	bool bCrosshairVisible = false;

	void Reset();
	int32 Num() const { return Lines.Num() + Rects.Num() + Tris.Num() + Labels.Num(); }
	int32 CountTag(FName Tag) const;
	const FLabel* FindLabel(FName Tag) const;
};

/** Text measure: text, point size, bold -> size in pixels. */
using FVerseTextMeasure = TFunction<FVector2D(const FText&, int32, bool)>;

/** Everything one HUD frame depends on. */
struct VERSEUI_API FVerseHudFrame
{
	const FVerseHudModel* Model = nullptr;
	const FVerseUiStrings* Strings = nullptr;
	const IVerseHudSource* Source = nullptr;
	FVerseUiLayout Layout;
	FVerseHudPawnState Pawn;
	FVerseHudView View;
	bool bHasView = false;
	double Now = 0.0;
	double ServerTime = 0.0;
	/** Kill cam running: crosshair and ammo hide, the banner shows. */
	bool bKillCam = false;
	int32 KillCamKillerId = INDEX_NONE;
	/** Key name shown on the skip hint, for example "Space". */
	FText SkipKeyName;
	bool bReducedMotion = false;
	/** Hide the duel blocks outside a duel (only the crosshair-free deck HUD stays). */
	bool bInDuel = true;
};

/** Builds the HUD draw list (WP18.1-18.4, 18.10). */
class VERSEUI_API FVerseHudPainter
{
public:
	/** Slate font measure when Slate runs, else a monospace estimate. */
	static FVerseTextMeasure DefaultMeasure();

	static void Paint(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);

	/** Shape signature of a marker kind (line count, rect count, tri count), for WP18.10 tests. */
	static FIntVector MarkerShape(EVerseHitMarkerKind Kind);

	/** Point on screen a damage indicator points to, clockwise angle from straight ahead. */
	static float IndicatorAngleDeg(const FVerseHudView& View, const FVector& FromDirection);

private:
	static void PaintCrosshair(const FVerseHudFrame& Frame, FVerseHudDrawList& Out);
	static void PaintMarkers(const FVerseHudFrame& Frame, FVerseHudDrawList& Out);
	static void PaintDamage(const FVerseHudFrame& Frame, FVerseHudDrawList& Out);
	static void PaintVitals(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);
	static void PaintWeapon(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);
	static void PaintScore(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);
	static void PaintFeed(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);
	static void PaintCentre(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);
};

/** Draws a list on a canvas (game HUD post-render, or a render target for captures). */
class VERSEUI_API FVerseHudCanvasRenderer
{
public:
	static void Render(UCanvas* Canvas, const FVerseHudDrawList& List);
};
