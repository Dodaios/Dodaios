#pragma once

#include "Core/VerseUiLayout.h"
#include "Core/VerseUiPorts.h"
#include "CoreMinimal.h"
#include "Hud/VerseHudModel.h"

class FVerseUiStrings;
struct FVerseGameSettings;
class UCanvas;
class UFont;

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
		/** Font face of the default font ("BoldCondensed", ...); None = Bold or Regular from bBold. */
		FName Typeface;
		/** A soft drop shadow (off for text on a plate, where it only blurs). */
		bool bShadow = true;
	};
	/** An item icon (Data/ui/icons), tinted, fitted into Box keeping its aspect. */
	struct FIcon
	{
		FVector2D Min, Max;
		FName ItemId;
		FLinearColor Colour;
		FName Tag;
	};

	TArray<FLine> Lines;
	TArray<FRect> Rects;
	TArray<FTri> Tris;
	TArray<FLabel> Labels;
	TArray<FIcon> Icons;

	/** Where the crosshair centre was drawn (A18.1). */
	FVector2D CrosshairCentre = FVector2D::ZeroVector;
	bool bCrosshairVisible = false;

	void Reset();
	int32 Num() const { return Lines.Num() + Rects.Num() + Tris.Num() + Labels.Num() + Icons.Num(); }
	int32 CountTag(FName Tag) const;
	const FLabel* FindLabel(FName Tag) const;
};

/** Text measure: text, point size, bold -> size in pixels. */
using FVerseTextMeasure = TFunction<FVector2D(const FText&, int32, bool)>;

enum class EVerseCrosshairStyle : uint8
{
	Cross,
	Dot,
	CrossDot,
	Circle,
};

/** The person's HUD and crosshair choices (settings.game hud.*); defaults are the catalogue's. */
struct VERSEUI_API FVerseHudOptions
{
	/** Alpha of every block but the crosshair, 0.2 .. 1. */
	float Opacity = 1.f;
	bool bHitMarkers = true;
	bool bDamageNumbers = false;
	bool bDamageDirection = true;
	/** hud.performance_stats: 0 off, 1 frame rate, 2 frame rate and frame time. */
	int32 PerformanceStats = 0;
	float Fps = 0.f;
	float FrameMs = 0.f;

	EVerseCrosshairStyle CrosshairStyle = EVerseCrosshairStyle::CrossDot;
	FLinearColor CrosshairColour = FLinearColor(1.00f, 0.55f, 0.08f, 1.f);
	/** Catalogue units: size 1 .. 10, thickness 1 .. 4, gap 0 .. 10. */
	float CrosshairSize = 4.f;
	float CrosshairThickness = 2.f;
	float CrosshairGap = 3.f;
	bool bCrosshairOutline = true;
	/** The lines open with the weapon's spread, and the spread circle shows. */
	bool bCrosshairDynamic = true;
	/** Geometry scale of the crosshair (the viewport's, without the HUD size choice); 0 = the layout's. */
	float CrosshairScale = 0.f;

	static FVerseHudOptions FromSettings(const FVerseGameSettings& Game);
	static FLinearColor CrosshairColourByName(const FString& Name);
};

/** Key names on the loadout chips (keys.json slot_* and gadget_*); empty = the default key. */
struct VERSEUI_API FVerseHudKeys
{
	FText Primary;
	FText Secondary;
	FText Melee;
	FText GadgetA;
	FText GadgetB;
};

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
	FVerseHudKeys Keys;
	bool bReducedMotion = false;
	/** Hide the duel blocks outside a duel (only the crosshair-free deck HUD stays). */
	bool bInDuel = true;
	FVerseHudOptions Options;
};

/** Builds the HUD draw list (WP18.1-18.4, 18.10). */
class VERSEUI_API FVerseHudPainter
{
public:
	/** Slate font measure when Slate runs, else a monospace estimate. */
	static FVerseTextMeasure DefaultMeasure();

	/** Measure of one face of the default font (the HUD's condensed numbers). */
	static FVector2D MeasureFace(const FText& Value, int32 Size, FName Typeface);

	static void Paint(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);

	/** Shape signature of a marker kind (line count, rect count, tri count), for WP18.10 tests. */
	static FIntVector MarkerShape(EVerseHitMarkerKind Kind);

	/** Point on screen a damage indicator points to, clockwise angle from straight ahead. */
	static float IndicatorAngleDeg(const FVerseHudView& View, const FVector& FromDirection);

private:
	static void PaintCrosshair(const FVerseHudFrame& Frame, FVerseHudDrawList& Out);
	static void PaintMarkers(const FVerseHudFrame& Frame, FVerseHudDrawList& Out);
	static void PaintDamage(const FVerseHudFrame& Frame, FVerseHudDrawList& Out);
	/** Health, weapon list and gadgets as one compact block in the bottom-right corner. */
	static void PaintLoadout(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);
	static void PaintScore(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);
	static void PaintFeed(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);
	static void PaintCentre(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);
	static void PaintDamageNumber(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);
	static void PaintPerformance(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure);
};

/** Draws a list on a canvas (game HUD post-render, or a render target for captures). */
class VERSEUI_API FVerseHudCanvasRenderer
{
public:
	static void Render(UCanvas* Canvas, const FVerseHudDrawList& List);

	/**
	 * The runtime-cache engine font every label item carries. A canvas text item built from a
	 * Slate font alone has no UFont and draws nothing (the engine's HasValidText checks the
	 * UFont); with this one set, the Slate font info still picks the face and size.
	 */
	static const UFont* LabelFont();
};
