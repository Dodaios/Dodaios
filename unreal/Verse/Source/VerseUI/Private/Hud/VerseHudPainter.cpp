#include "Hud/VerseHudPainter.h"

#include "CanvasItem.h"
#include "CanvasTypes.h"
#include "Core/VerseUiStrings.h"
#include "Core/VerseUiTheme.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Engine/Texture2D.h"
#include "Fonts/FontMeasure.h"
#include "GlobalRenderResources.h"
#include "Framework/Application/SlateApplication.h"
#include "Hud/VerseCrosshair.h"
#include "Hud/VerseHudIcons.h"
#include "Rendering/SlateRenderer.h"
#include "Settings/VerseGameSettings.h"
#include "Styling/CoreStyle.h"

namespace
{
	const FName TagCrosshair(TEXT("crosshair"));
	const FName TagSpread(TEXT("crosshair.spread"));
	const FName TagDamage(TEXT("damage"));
	const FName TagVitals(TEXT("vitals"));
	const FName TagWeapon(TEXT("weapon"));
	const FName TagGadget(TEXT("gadget"));
	const FName TagScore(TEXT("score"));
	const FName TagFeed(TEXT("feed"));
	const FName TagCentre(TEXT("centre"));
	const FName TagDamageNumber(TEXT("damage.number"));
	const FName TagPerformance(TEXT("performance"));

	FName MarkerTag(EVerseHitMarkerKind Kind)
	{
		switch (Kind)
		{
		case EVerseHitMarkerKind::Hit: return TEXT("marker.hit");
		case EVerseHitMarkerKind::Headshot: return TEXT("marker.headshot");
		case EVerseHitMarkerKind::Kill: return TEXT("marker.kill");
		case EVerseHitMarkerKind::Blocked: return TEXT("marker.blocked");
		}
		return NAME_None;
	}

	FLinearColor WithAlpha(FLinearColor Colour, float Alpha)
	{
		Colour.A *= FMath::Clamp(Alpha, 0.f, 1.f);
		return Colour;
	}

	void Line(FVerseHudDrawList& Out, const FVector2D& A, const FVector2D& B, float Thickness, const FLinearColor& Colour, FName Tag)
	{
		Out.Lines.Add({A, B, Thickness, Colour, Tag});
	}

	void FillRect(FVerseHudDrawList& Out, const FVector2D& Min, const FVector2D& Size, const FLinearColor& Colour, FName Tag)
	{
		Out.Rects.Add({Min, Min + Size, Colour, Tag});
	}

	void Outline(FVerseHudDrawList& Out, const FVector2D& Min, const FVector2D& Size, float Thickness, const FLinearColor& Colour, FName Tag)
	{
		const FVector2D A = Min, B(Min.X + Size.X, Min.Y), C = Min + Size, D(Min.X, Min.Y + Size.Y);
		Line(Out, A, B, Thickness, Colour, Tag);
		Line(Out, B, C, Thickness, Colour, Tag);
		Line(Out, C, D, Thickness, Colour, Tag);
		Line(Out, D, A, Thickness, Colour, Tag);
	}

	/** Adds a label; Anchor is the left edge, centre or right edge of the label's top. Returns its size. */
	FVector2D Text(FVerseHudDrawList& Out, const FVerseTextMeasure& Measure, const FVector2D& Anchor, const FText& Value, int32 Size,
		bool bBold, const FLinearColor& Colour, EVerseTextAlign Align, float MaxWidth, FName Tag)
	{
		FVerseHudDrawList::FLabel Label;
		Label.Text = Value;
		Label.FontSize = Size;
		Label.bBold = bBold;
		Label.Colour = Colour;
		Label.Align = Align;
		Label.MaxWidth = MaxWidth;
		Label.Tag = Tag;
		Label.Size = Measure(Value, Size, bBold);
		FVector2D TopLeft = Anchor;
		if (Align == EVerseTextAlign::Centre)
		{
			TopLeft.X -= Label.Size.X * 0.5;
		}
		else if (Align == EVerseTextAlign::Right)
		{
			TopLeft.X -= Label.Size.X;
		}
		Label.Position = TopLeft;
		Out.Labels.Add(Label);
		return Label.Size;
	}

	// Numbers follow the Verse UI language, never the machine's culture.
	FText Num(const FVerseUiStrings& Strings, int32 Value)
	{
		return Strings.Number(Value, 0, false);
	}

	FText Seconds(const FVerseUiStrings& Strings, float Value)
	{
		return Strings.Number(FMath::Max(0.f, Value), 1, false);
	}

	FText PlayerName(const FVerseHudFrame& Frame, int32 PlayerId)
	{
		if (PlayerId != INDEX_NONE && Frame.Model && PlayerId == Frame.Model->GetLocalPlayerId())
		{
			return Frame.Strings->Get(TEXT("verse.hud.feed.you"));
		}
		if (PlayerId < 0)
		{
			return Frame.Strings->Get(TEXT("verse.hud.feed.world"));
		}
		if (Frame.Source)
		{
			if (Frame.Source->IsBot(PlayerId))
			{
				return Frame.Strings->Get(TEXT("verse.hud.feed.opponent"));
			}
			const FText Name = Frame.Source->GetDisplayName(PlayerId);
			if (!Name.IsEmpty())
			{
				return Name;
			}
		}
		return Frame.Strings->Get(TEXT("verse.hud.feed.opponent"));
	}

	FText ItemName(const FVerseUiStrings& Strings, FName ItemId)
	{
		return Strings.Get(FString::Printf(TEXT("verse.item.%s.name"), *ItemId.ToString().ToLower()));
	}
}

// ---------------------------------------------------------------------------------------------
// Draw list

void FVerseHudDrawList::Reset()
{
	Lines.Reset();
	Rects.Reset();
	Tris.Reset();
	Labels.Reset();
	Icons.Reset();
	CrosshairCentre = FVector2D::ZeroVector;
	bCrosshairVisible = false;
}

int32 FVerseHudDrawList::CountTag(FName Tag) const
{
	int32 Count = 0;
	for (const FLine& L : Lines) { Count += L.Tag == Tag; }
	for (const FRect& R : Rects) { Count += R.Tag == Tag; }
	for (const FTri& T : Tris) { Count += T.Tag == Tag; }
	for (const FLabel& T : Labels) { Count += T.Tag == Tag; }
	for (const FIcon& I : Icons) { Count += I.Tag == Tag; }
	return Count;
}

const FVerseHudDrawList::FLabel* FVerseHudDrawList::FindLabel(FName Tag) const
{
	return Labels.FindByPredicate([Tag](const FLabel& L) { return L.Tag == Tag; });
}

// ---------------------------------------------------------------------------------------------
// Painter

FVerseTextMeasure FVerseHudPainter::DefaultMeasure()
{
	return [](const FText& Value, int32 Size, bool bBold) -> FVector2D
	{
		if (FSlateApplication::IsInitialized())
		{
			const TSharedRef<FSlateFontMeasure> FontMeasure = FSlateApplication::Get().GetRenderer()->GetFontMeasureService();
			const FVector2D Measured = FontMeasure->Measure(Value, FCoreStyle::GetDefaultFontStyle(bBold ? "Bold" : "Regular", Size));
			return Measured;
		}
		// Without Slate: a generous estimate (wide glyphs count double).
		const FString& S = Value.ToString();
		double Width = 0.0;
		for (TCHAR Ch : S)
		{
			Width += Ch > 0x2E80 ? 1.0 : 0.62;
		}
		return FVector2D(Width * Size * 1.333, Size * 1.6);
	};
}

FVector2D FVerseHudPainter::MeasureFace(const FText& Value, int32 Size, FName Typeface)
{
	if (FSlateApplication::IsInitialized())
	{
		const TSharedRef<FSlateFontMeasure> FontMeasure = FSlateApplication::Get().GetRenderer()->GetFontMeasureService();
		return FontMeasure->Measure(Value, FCoreStyle::GetDefaultFontStyle(Typeface, Size));
	}
	// Without Slate: the bold estimate, narrower for a condensed face.
	const FVector2D Bold = DefaultMeasure()(Value, Size, true);
	return Typeface.ToString().Contains(TEXT("Condensed")) ? FVector2D(Bold.X * 0.82, Bold.Y) : Bold;
}

FIntVector FVerseHudPainter::MarkerShape(EVerseHitMarkerKind Kind)
{
	// Same code path as a frame: raise one marker through the model, draw it, count by tag.
	FVerseHudFrame Frame;
	FVerseHudDrawList List;
	List.CrosshairCentre = FVector2D(960, 540);
	const FName Tag = MarkerTag(Kind);
	FVerseHudModel Single;
	Single.SetLocalPlayerId(1);
	FVerseHitEvent Hit;
	Hit.InstigatorId = 1;
	Hit.VictimId = 2;
	Hit.bHeadshot = Kind == EVerseHitMarkerKind::Headshot;
	Hit.bKillingBlow = Kind == EVerseHitMarkerKind::Kill;
	Hit.bBlockedBySpawnProtection = Kind == EVerseHitMarkerKind::Blocked;
	Single.OnHit(Hit, 0.0);
	Frame.Model = &Single;
	Frame.Now = 0.0;
	PaintMarkers(Frame, List);
	FIntVector Shape(0, 0, 0);
	for (const FVerseHudDrawList::FLine& L : List.Lines) { Shape.X += L.Tag == Tag; }
	for (const FVerseHudDrawList::FRect& R : List.Rects) { Shape.Y += R.Tag == Tag; }
	for (const FVerseHudDrawList::FTri& T : List.Tris) { Shape.Z += T.Tag == Tag; }
	return Shape;
}

float FVerseHudPainter::IndicatorAngleDeg(const FVerseHudView& View, const FVector& FromDirection)
{
	const FRotator Yaw(0.f, View.Rotation.Yaw, 0.f);
	const FVector Local = Yaw.UnrotateVector(FromDirection);
	// X ahead, Y right: atan2(Y, X) is the clockwise angle from straight ahead.
	return float(FMath::RadiansToDegrees(FMath::Atan2(Local.Y, Local.X)));
}

void FVerseHudPainter::Paint(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure)
{
	Out.Reset();
	if (!Frame.Model || !Frame.Strings)
	{
		return;
	}
	const FVerseHudOptions& O = Frame.Options;
	if (Frame.bInDuel)
	{
		PaintCrosshair(Frame, Out);
		if (O.bHitMarkers)
		{
			PaintMarkers(Frame, Out);
		}
		if (O.bDamageNumbers)
		{
			PaintDamageNumber(Frame, Out, Measure);
		}
		if (O.bDamageDirection)
		{
			PaintDamage(Frame, Out);
		}
		PaintLoadout(Frame, Out, Measure);
		PaintScore(Frame, Out, Measure);
	}
	PaintFeed(Frame, Out, Measure);
	PaintCentre(Frame, Out, Measure);
	PaintPerformance(Frame, Out, Measure);

	// HUD opacity: every block but the crosshair, which keeps its own look.
	if (O.Opacity < 1.f)
	{
		auto Fade = [&O](FLinearColor& Colour, FName Tag)
		{
			if (Tag != TagCrosshair && Tag != TagSpread)
			{
				Colour.A *= O.Opacity;
			}
		};
		for (FVerseHudDrawList::FLine& L : Out.Lines) { Fade(L.Colour, L.Tag); }
		for (FVerseHudDrawList::FRect& R : Out.Rects) { Fade(R.Colour, R.Tag); }
		for (FVerseHudDrawList::FTri& T : Out.Tris) { Fade(T.Colour, T.Tag); }
		for (FVerseHudDrawList::FLabel& L : Out.Labels) { Fade(L.Colour, L.Tag); }
		for (FVerseHudDrawList::FIcon& I : Out.Icons) { Fade(I.Colour, I.Tag); }
	}
}

FLinearColor FVerseHudOptions::CrosshairColourByName(const FString& Name)
{
	if (Name == TEXT("white")) { return FLinearColor(0.95f, 0.95f, 0.93f, 1.f); }
	if (Name == TEXT("green")) { return FLinearColor(0.25f, 0.95f, 0.30f, 1.f); }
	if (Name == TEXT("cyan")) { return FLinearColor(0.10f, 0.88f, 0.95f, 1.f); }
	if (Name == TEXT("magenta")) { return FLinearColor(0.95f, 0.20f, 0.85f, 1.f); }
	return VerseUiTheme::Amber;
}

FVerseHudOptions FVerseHudOptions::FromSettings(const FVerseGameSettings& Game)
{
	FVerseHudOptions O;
	O.Opacity = FMath::Clamp(float(Game.GetNumber(TEXT("hud.opacity"))), 0.2f, 1.f);
	O.bHitMarkers = Game.GetBool(TEXT("hud.hit_markers"));
	O.bDamageNumbers = Game.GetBool(TEXT("hud.damage_numbers"));
	O.bDamageDirection = Game.GetBool(TEXT("hud.damage_direction"));
	const FString Perf = Game.GetString(TEXT("hud.performance_stats"));
	O.PerformanceStats = Perf == TEXT("full") ? 2 : Perf == TEXT("fps") ? 1 : 0;
	const FString Style = Game.GetString(TEXT("hud.crosshair_style"));
	O.CrosshairStyle = Style == TEXT("cross") ? EVerseCrosshairStyle::Cross
		: Style == TEXT("dot") ? EVerseCrosshairStyle::Dot
		: Style == TEXT("circle") ? EVerseCrosshairStyle::Circle
		: EVerseCrosshairStyle::CrossDot;
	O.CrosshairColour = CrosshairColourByName(Game.GetString(TEXT("hud.crosshair_color")));
	O.CrosshairSize = float(Game.GetNumber(TEXT("hud.crosshair_size")));
	O.CrosshairThickness = float(Game.GetNumber(TEXT("hud.crosshair_thickness")));
	O.CrosshairGap = float(Game.GetNumber(TEXT("hud.crosshair_gap")));
	O.bCrosshairOutline = Game.GetBool(TEXT("hud.crosshair_outline"));
	O.bCrosshairDynamic = Game.GetBool(TEXT("hud.crosshair_dynamic"));
	return O;
}

void FVerseHudPainter::PaintDamageNumber(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure)
{
	// The newest marker with damage: its number beside the crosshair, fading with the marker.
	const FVerseHitMarker* Newest = nullptr;
	for (const FVerseHitMarker& Marker : Frame.Model->GetHitMarkers())
	{
		if (Marker.Kind != EVerseHitMarkerKind::Blocked && Marker.Damage > 0.f && (!Newest || Marker.StartTime > Newest->StartTime))
		{
			Newest = &Marker;
		}
	}
	if (!Newest)
	{
		return;
	}
	const FVerseUiLayout& L = Frame.Layout;
	const float Alpha = FVerseHudModel::MarkerAlpha(*Newest, Frame.Now);
	const FLinearColor Colour = Newest->Kind == EVerseHitMarkerKind::Headshot ? VerseUiTheme::Gold
		: Newest->Kind == EVerseHitMarkerKind::Kill ? VerseUiTheme::Red
		: VerseUiTheme::Text;
	Text(Out, Measure, Out.CrosshairCentre + FVector2D(L.Px(24.f), -L.Px(34.f)), Num(*Frame.Strings, FMath::RoundToInt(Newest->Damage)),
		L.FontSize(18.f), true, WithAlpha(Colour, Alpha), EVerseTextAlign::Left, 0.f, TagDamageNumber);
}

void FVerseHudPainter::PaintPerformance(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure)
{
	const FVerseHudOptions& O = Frame.Options;
	if (O.PerformanceStats <= 0)
	{
		return;
	}
	FFormatNamedArguments Args;
	Args.Add(TEXT("fps"), Num(*Frame.Strings, FMath::RoundToInt(O.Fps)));
	Args.Add(TEXT("ms"), Frame.Strings->Number(O.FrameMs, 1, false));
	const FText Value = Frame.Strings->Format(O.PerformanceStats >= 2 ? TEXT("verse.hud.perf.full") : TEXT("verse.hud.perf.fps"), Args);
	const FVerseUiLayout& L = Frame.Layout;
	const int32 Size = L.FontSize(13.f);
	const FVector2D Measured = Measure(Value, Size, false);
	Text(Out, Measure, L.Place(EVerseUiAnchor::TopRight, Measured, FVector2D::ZeroVector) + FVector2D(Measured.X, 0.0), Value, Size, false,
		VerseUiTheme::TextDim, EVerseTextAlign::Right, 0.f, TagPerformance);
}

void FVerseHudPainter::PaintCrosshair(const FVerseHudFrame& Frame, FVerseHudDrawList& Out)
{
	const FVerseUiLayout& L = Frame.Layout;
	FVector2D Centre = L.Viewport * 0.5;
	float Spread = 0.f;
	if (Frame.bHasView && Frame.Source)
	{
		FVector Dir;
		float HalfAngle = 0.f;
		if (Frame.Source->GetPredictedBoltDirection(Dir, HalfAngle))
		{
			FVector2D Pixel;
			if (FVerseCrosshair::ProjectDirection(Frame.View, L.Viewport, Dir, Pixel))
			{
				Centre = Pixel;
			}
			Spread = FVerseCrosshair::SpreadRadiusPx(Frame.View, L.Viewport, HalfAngle);
		}
	}
	// Markers centre on the crosshair even while it is hidden.
	Out.CrosshairCentre = Centre;

	const bool bHidden = Frame.bKillCam || Frame.Model->IsLocalDead() || Frame.Pawn.Phase != EVerseCombatPhase::Alive
		|| (Frame.Source && Frame.Source->IsAimingThroughOptic());
	if (bHidden)
	{
		return;
	}
	Out.bCrosshairVisible = true;

	// The person's crosshair (settings.game hud.crosshair_*). The catalogue defaults draw lines
	// 9 px long and 2 px thick, 5 px from the centre, at 1080p.
	const FVerseHudOptions& O = Frame.Options;
	const float CrossScale = O.CrosshairScale > 0.f ? O.CrosshairScale : L.Scale;
	auto Px = [CrossScale](float Reference) { return Reference * CrossScale; };
	const float BaseGap = Px(O.CrosshairGap * 5.f / 3.f);
	const float Gap = O.bCrosshairDynamic ? FMath::Max(BaseGap, Spread) : BaseGap;
	const float Length = Px(O.CrosshairSize * 2.25f);
	const float Thick = FMath::Max(1.f, Px(O.CrosshairThickness));
	const FLinearColor Colour = O.CrosshairColour;
	const bool bLines = O.CrosshairStyle == EVerseCrosshairStyle::Cross || O.CrosshairStyle == EVerseCrosshairStyle::CrossDot;
	const bool bDot = O.CrosshairStyle != EVerseCrosshairStyle::Cross;
	if (bLines)
	{
		const FVector2D Dirs[4] = {FVector2D(1, 0), FVector2D(-1, 0), FVector2D(0, 1), FVector2D(0, -1)};
		if (O.bCrosshairOutline)
		{
			for (const FVector2D& D : Dirs)
			{
				Line(Out, Centre + D * Gap, Centre + D * (Gap + Length), Thick + 2.f, VerseUiTheme::Shadow, TagCrosshair);
			}
		}
		for (const FVector2D& D : Dirs)
		{
			Line(Out, Centre + D * Gap, Centre + D * (Gap + Length), Thick, Colour, TagCrosshair);
		}
	}
	if (O.CrosshairStyle == EVerseCrosshairStyle::Circle)
	{
		const float Radius = Gap + Length * 0.5f;
		const int32 Segments = 24;
		for (int32 Pass = O.bCrosshairOutline ? 0 : 1; Pass < 2; ++Pass)
		{
			for (int32 I = 0; I < Segments; ++I)
			{
				const double A0 = 2.0 * PI * I / Segments;
				const double A1 = 2.0 * PI * (I + 1) / Segments;
				Line(Out, Centre + FVector2D(FMath::Cos(A0), FMath::Sin(A0)) * Radius, Centre + FVector2D(FMath::Cos(A1), FMath::Sin(A1)) * Radius,
					Pass == 0 ? Thick + 2.f : Thick, Pass == 0 ? VerseUiTheme::Shadow : Colour, TagCrosshair);
			}
		}
	}
	if (bDot)
	{
		const float Dot = FMath::Max(2.f, Px(O.CrosshairThickness));
		if (O.bCrosshairOutline && !bLines)
		{
			FillRect(Out, Centre - FVector2D(Dot + 2.f, Dot + 2.f) * 0.5, FVector2D(Dot + 2.f, Dot + 2.f), VerseUiTheme::Shadow, TagCrosshair);
		}
		FillRect(Out, Centre - FVector2D(Dot, Dot) * 0.5, FVector2D(Dot, Dot), Colour, TagCrosshair);
	}

	if (O.bCrosshairDynamic && Spread > Gap * 0.5f && Spread > L.Px(6.f))
	{
		// Spread circle: thin, faint, 32 segments.
		const int32 Segments = 32;
		for (int32 I = 0; I < Segments; ++I)
		{
			const double A0 = 2.0 * PI * I / Segments;
			const double A1 = 2.0 * PI * (I + 1) / Segments;
			Line(Out, Centre + FVector2D(FMath::Cos(A0), FMath::Sin(A0)) * Spread,
				Centre + FVector2D(FMath::Cos(A1), FMath::Sin(A1)) * Spread, 1.f, WithAlpha(VerseUiTheme::Text, 0.25f), TagSpread);
		}
	}
}

void FVerseHudPainter::PaintMarkers(const FVerseHudFrame& Frame, FVerseHudDrawList& Out)
{
	const FVerseUiLayout& L = Frame.Layout;
	const FVector2D C = Out.CrosshairCentre;
	const FVector2D Diagonals[4] = {FVector2D(1, 1), FVector2D(-1, 1), FVector2D(1, -1), FVector2D(-1, -1)};
	for (const FVerseHitMarker& Marker : Frame.Model->GetHitMarkers())
	{
		const float Alpha = FVerseHudModel::MarkerAlpha(Marker, Frame.Now);
		const FName Tag = MarkerTag(Marker.Kind);
		switch (Marker.Kind)
		{
		case EVerseHitMarkerKind::Hit:
		{
			// Shape: four short diagonal ticks.
			for (const FVector2D& D : Diagonals)
			{
				const FVector2D N = D.GetSafeNormal();
				Line(Out, C + N * L.Px(9.f), C + N * L.Px(19.f), FMath::Max(1.f, L.Px(2.5f)), WithAlpha(VerseUiTheme::Text, Alpha), Tag);
			}
			break;
		}
		case EVerseHitMarkerKind::Headshot:
		{
			// Shape: diagonal ticks plus a diamond.
			for (const FVector2D& D : Diagonals)
			{
				const FVector2D N = D.GetSafeNormal();
				Line(Out, C + N * L.Px(9.f), C + N * L.Px(21.f), FMath::Max(1.f, L.Px(3.f)), WithAlpha(VerseUiTheme::Gold, Alpha), Tag);
			}
			const float R = L.Px(5.f);
			const FVector2D Up(0, -R), Right(R, 0), Down(0, R), Left(-R, 0);
			Line(Out, C + Up, C + Right, FMath::Max(1.f, L.Px(1.5f)), WithAlpha(VerseUiTheme::Gold, Alpha), Tag);
			Line(Out, C + Right, C + Down, FMath::Max(1.f, L.Px(1.5f)), WithAlpha(VerseUiTheme::Gold, Alpha), Tag);
			Line(Out, C + Down, C + Left, FMath::Max(1.f, L.Px(1.5f)), WithAlpha(VerseUiTheme::Gold, Alpha), Tag);
			Line(Out, C + Left, C + Up, FMath::Max(1.f, L.Px(1.5f)), WithAlpha(VerseUiTheme::Gold, Alpha), Tag);
			break;
		}
		case EVerseHitMarkerKind::Kill:
		{
			// Shape: long thick diagonals plus a ring.
			for (const FVector2D& D : Diagonals)
			{
				const FVector2D N = D.GetSafeNormal();
				Line(Out, C + N * L.Px(8.f), C + N * L.Px(22.f), FMath::Max(1.f, L.Px(3.f)), WithAlpha(VerseUiTheme::Red, Alpha), Tag);
			}
			const int32 Segments = 16;
			const float R = L.Px(27.f);
			for (int32 I = 0; I < Segments; ++I)
			{
				const double A0 = 2.0 * PI * I / Segments;
				const double A1 = 2.0 * PI * (I + 1) / Segments;
				Line(Out, C + FVector2D(FMath::Cos(A0), FMath::Sin(A0)) * R, C + FVector2D(FMath::Cos(A1), FMath::Sin(A1)) * R,
					FMath::Max(1.f, L.Px(2.f)), WithAlpha(VerseUiTheme::Red, Alpha), Tag);
			}
			break;
		}
		case EVerseHitMarkerKind::Blocked:
		{
			// Shape: a square plate with a bar: the shot hit a protected player.
			const float S = L.Px(18.f);
			Outline(Out, C - FVector2D(S, S) * 0.5, FVector2D(S, S), FMath::Max(1.f, L.Px(2.f)), WithAlpha(VerseUiTheme::Blocked, Alpha), Tag);
			FillRect(Out, C - FVector2D(S * 0.35, L.Px(1.5f)), FVector2D(S * 0.7, L.Px(3.f)), WithAlpha(VerseUiTheme::Blocked, Alpha), Tag);
			break;
		}
		}
	}
}

void FVerseHudPainter::PaintDamage(const FVerseHudFrame& Frame, FVerseHudDrawList& Out)
{
	if (!Frame.bHasView)
	{
		return;
	}
	const FVerseUiLayout& L = Frame.Layout;
	const FVector2D C = L.Viewport * 0.5;
	const float Radius = L.Px(150.f);
	for (const FVerseDamageIndicator& D : Frame.Model->GetDamageIndicators())
	{
		const float T = float((Frame.Now - D.StartTime) / FMath::Max(0.01f, D.Duration));
		const float Alpha = D.Strength * FMath::Clamp(1.f - T, 0.f, 1.f);
		const float Angle = FMath::DegreesToRadians(IndicatorAngleDeg(Frame.View, D.FromDirection));
		const FVector2D Dir(FMath::Sin(Angle), -FMath::Cos(Angle));
		const FVector2D Side(-Dir.Y, Dir.X);
		// A wide red wedge pointing out towards the shooter, with a dim arc band behind it.
		const FVector2D Base = C + Dir * Radius;
		const FVector2D Tip = C + Dir * (Radius + L.Px(30.f));
		Out.Tris.Add({Tip, Base + Side * L.Px(30.f), Base - Side * L.Px(30.f), WithAlpha(VerseUiTheme::Red, Alpha), TagDamage});
		const FVector2D Inner = C + Dir * (Radius - L.Px(10.f));
		Out.Tris.Add({Base + Side * L.Px(30.f), Base - Side * L.Px(30.f), Inner, WithAlpha(VerseUiTheme::Red, Alpha * 0.45f), TagDamage});
	}
}

namespace
{
	const FName FaceNumber(TEXT("BoldCondensed"));
	const FName FaceBold(TEXT("Bold"));

	/** Dark ink for text and icons on the lit row. */
	const FLinearColor Ink(0.030f, 0.028f, 0.026f, 1.f);
	/** Dark amber that reads on the lit row. */
	const FLinearColor InkAmber(0.62f, 0.30f, 0.02f, 1.f);
	/** Plates of the unlit rows and chips. */
	const FLinearColor PlateTone(0.016f, 0.016f, 0.018f, 0.68f);

	/** A label in one face of the default font, without the drop shadow (it sits on a plate). */
	FVector2D Label(FVerseHudDrawList& Out, const FVector2D& Anchor, const FText& Value, int32 Size, FName Face, const FLinearColor& Colour,
		EVerseTextAlign Align, float MaxWidth, FName Tag)
	{
		FVerseHudDrawList::FLabel L;
		L.Text = Value;
		L.FontSize = Size;
		L.bBold = true;
		L.Typeface = Face;
		L.bShadow = false;
		L.Colour = Colour;
		L.Align = Align;
		L.MaxWidth = MaxWidth;
		L.Tag = Tag;
		L.Size = FVerseHudPainter::MeasureFace(Value, Size, Face);
		FVector2D TopLeft = Anchor;
		if (Align == EVerseTextAlign::Centre)
		{
			TopLeft.X -= L.Size.X * 0.5;
		}
		else if (Align == EVerseTextAlign::Right)
		{
			TopLeft.X -= L.Size.X;
		}
		L.Position = TopLeft;
		Out.Labels.Add(L);
		return L.Size;
	}

	/** Places an item icon: Height tall (less if MaxWidth binds), its left edge at X, centred on CentreY. Returns its width. */
	float Icon(FVerseHudDrawList& Out, FName ItemId, float X, float CentreY, float Height, float MaxWidth, const FLinearColor& Colour, FName Tag)
	{
		const float Aspect = VerseHudIcons::Aspect(ItemId);
		if (Aspect <= 0.f)
		{
			return 0.f;
		}
		const float W = FMath::Min(Height * Aspect, MaxWidth);
		const float H = W / Aspect;
		Out.Icons.Add({FVector2D(X, CentreY - H * 0.5f), FVector2D(X + W, CentreY + H * 0.5f), ItemId, Colour, Tag});
		return W;
	}

	/** The selected row: a light plate, brightest at the left, fading towards the numbers. */
	void LitPlate(FVerseHudDrawList& Out, const FVector2D& Min, const FVector2D& Size, FName Tag)
	{
		const int32 Slices = 40;
		const double SliceW = Size.X / Slices;
		for (int32 I = 0; I < Slices; ++I)
		{
			const float T = float(I) / (Slices - 1);
			FillRect(Out, FVector2D(Min.X + I * SliceW, Min.Y), FVector2D(SliceW, Size.Y), WithAlpha(VerseUiTheme::Text, FMath::Lerp(0.96f, 0.72f, T)), Tag);
		}
	}

	/** A key cap with its key name; Light = light cap with dark letter. Returns its width. */
	float KeyChip(FVerseHudDrawList& Out, const FVerseUiLayout& L, const FVector2D& Min, float Side, const FText& Key, bool bLight, FName Tag)
	{
		const int32 Size = L.FontSize(Side * 0.62f / L.Scale);
		const FVector2D TextSize = FVerseHudPainter::MeasureFace(Key, Size, FaceBold);
		const float W = FMath::Max(Side, float(TextSize.X) + L.Px(7.f));
		FillRect(Out, Min, FVector2D(W, Side), bLight ? VerseUiTheme::Text : Ink, Tag);
		Label(Out, FVector2D(Min.X + W * 0.5f, Min.Y + (Side - TextSize.Y) * 0.5f), Key, Size, FaceBold, bLight ? Ink : VerseUiTheme::Text,
			EVerseTextAlign::Centre, 0.f, Tag);
		return W;
	}

	FText KeyFor(const FVerseHudKeys& Keys, EVerseLoadoutSlot Slot)
	{
		auto Or = [](const FText& Value, const TCHAR* Fallback) { return Value.IsEmpty() ? FText::AsCultureInvariant(Fallback) : Value; };
		switch (Slot)
		{
		case EVerseLoadoutSlot::Primary: return Or(Keys.Primary, TEXT("1"));
		case EVerseLoadoutSlot::Secondary: return Or(Keys.Secondary, TEXT("2"));
		case EVerseLoadoutSlot::Melee: return Or(Keys.Melee, TEXT("3"));
		case EVerseLoadoutSlot::GadgetA: return Or(Keys.GadgetA, TEXT("G"));
		case EVerseLoadoutSlot::GadgetB: return Or(Keys.GadgetB, TEXT("T"));
		}
		return FText::GetEmpty();
	}

	/** Magazine and reserve of a holstered weapon, right-aligned at Right; both boxes end on one line (one baseline). Returns the left edge. */
	float AmmoPair(FVerseHudDrawList& Out, const FVerseUiLayout& L, float Right, float RowY, float RowH, const FText& Mag, int32 MagSize, const FText& Reserve,
		int32 ReserveSize, FName MagTag, FName ReserveTag)
	{
		const FVector2D MagMeasured = FVerseHudPainter::MeasureFace(Mag, MagSize, FaceNumber);
		const FVector2D ReserveMeasured = FVerseHudPainter::MeasureFace(Reserve, ReserveSize, FaceNumber);
		const float MagTop = RowY + (RowH - MagMeasured.Y) * 0.5f;
		const float Bottom = MagTop + MagMeasured.Y;
		Label(Out, FVector2D(Right, Bottom - ReserveMeasured.Y), Reserve, ReserveSize, FaceNumber, VerseUiTheme::TextDim, EVerseTextAlign::Right, 0.f,
			ReserveTag);
		const float MagRight = Right - float(ReserveMeasured.X) - L.Px(5.f);
		Label(Out, FVector2D(MagRight, MagTop), Mag, MagSize, FaceNumber, VerseUiTheme::Text, EVerseTextAlign::Right, 0.f, MagTag);
		return MagRight - float(MagMeasured.X);
	}
}

void FVerseHudPainter::PaintLoadout(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure)
{
	if (!Frame.Pawn.bValid)
	{
		return;
	}
	const FVerseUiLayout& L = Frame.Layout;
	const FVerseUiStrings& S = *Frame.Strings;
	const FVerseHudPawnState& Pawn = Frame.Pawn;

	// The loadout: the source's list, or the active weapon alone when the source has no list.
	TArray<FVerseHudWeaponSlot> Weapons = Pawn.Weapons;
	if (Weapons.Num() == 0 && Pawn.bHasWeapon)
	{
		FVerseHudWeaponSlot Active;
		Active.Slot = Pawn.ActiveSlot;
		Active.WeaponId = Pawn.WeaponId;
		Active.Magazine = Pawn.Magazine;
		Active.MagazineSize = Pawn.MagazineSize;
		Active.Reserve = Pawn.Reserve;
		Active.bUsesAmmo = Pawn.ActiveSlot != EVerseLoadoutSlot::Melee;
		Weapons.Add(Active);
	}
	// The kill cam keeps only the health line.
	const bool bShowKit = !Frame.bKillCam;
	if (!bShowKit)
	{
		Weapons.Reset();
	}

	// Sizes at 1080p: one narrow column; the drawn weapon's row is taller and lit.
	const float W = L.Px(250.f);
	const float Gap = L.Px(3.f);
	const float ActiveH = L.Px(44.f);
	const float RowH = L.Px(30.f);
	const float HealthH = L.Px(26.f);
	const float ChipH = L.Px(28.f);
	const float Pad = L.Px(8.f);
	const bool bGadgets = bShowKit && Pawn.Gadgets.Num() > 0;

	auto IsActive = [&Pawn](const FVerseHudWeaponSlot& Slot) { return Pawn.bHasWeapon && Slot.Slot == Pawn.ActiveSlot; };
	float Height = HealthH;
	for (const FVerseHudWeaponSlot& Slot : Weapons)
	{
		Height += Gap + (IsActive(Slot) ? ActiveH : RowH);
	}
	if (bGadgets)
	{
		Height += L.Px(6.f) + ChipH;
	}
	const FVector2D Origin = L.Place(EVerseUiAnchor::BottomRight, FVector2D(W, Height), FVector2D(8.f, 8.f));
	const float Right = Origin.X + W;
	float Y = Origin.Y;

	// Gadgets: one chip each on a line above the weapons, right-aligned: key, icon, charges.
	if (bGadgets)
	{
		float X = Right;
		for (int32 I = Pawn.Gadgets.Num() - 1; I >= 0; --I)
		{
			const FVerseHudGadgetState& G = Pawn.Gadgets[I];
			const bool bReady = G.Charges > 0 && G.CooldownRemaining <= 0.f;
			FText Count;
			if (G.CooldownRemaining > 0.f)
			{
				FFormatNamedArguments Args;
				Args.Add(TEXT("seconds"), Num(S, FMath::CeilToInt(G.CooldownRemaining)));
				Count = S.Format(TEXT("verse.hud.cooldown"), Args);
			}
			else
			{
				Count = Num(S, G.Charges);
			}
			const int32 CountSize = L.FontSize(15.f);
			const FVector2D CountMeasured = MeasureFace(Count, CountSize, FaceNumber);
			const FText Key = KeyFor(Frame.Keys, I == 0 ? EVerseLoadoutSlot::GadgetA : EVerseLoadoutSlot::GadgetB);
			const float KeySide = L.Px(16.f);
			const float KeyW = FMath::Max(KeySide, float(MeasureFace(Key, L.FontSize(KeySide * 0.62f / L.Scale), FaceBold).X) + L.Px(7.f));
			const bool bHasIcon = VerseHudIcons::Has(G.GadgetId);
			const FText ShortName = S.Get(FString::Printf(TEXT("verse.item.%s.short"), *G.GadgetId.ToString().ToLower()));
			const float IconH = L.Px(18.f);
			const float IconW = bHasIcon ? IconH * VerseHudIcons::Aspect(G.GadgetId) : float(MeasureFace(ShortName, L.FontSize(10.f), FaceBold).X);
			const float ChipW = L.Px(6.f) + KeyW + L.Px(8.f) + IconW + L.Px(8.f) + float(CountMeasured.X) + L.Px(9.f);
			X -= ChipW;
			const FVector2D CP(X, Y);
			X -= L.Px(4.f);
			FillRect(Out, CP, FVector2D(ChipW, ChipH), PlateTone, TagGadget);
			float CX = CP.X + L.Px(6.f);
			KeyChip(Out, L, FVector2D(CX, CP.Y + (ChipH - KeySide) * 0.5f), KeySide, Key, true, TEXT("gadget.key"));
			CX += KeyW + L.Px(8.f);
			const FLinearColor Tone = bReady ? VerseUiTheme::Text : WithAlpha(VerseUiTheme::TextDim, 0.9f);
			if (bHasIcon)
			{
				Icon(Out, G.GadgetId, CX, CP.Y + ChipH * 0.5f, IconH, IconW, Tone, TEXT("gadget.icon"));
			}
			else
			{
				// Unknown gadget: its short name stands in for the icon.
				const FVector2D NameSize = MeasureFace(ShortName, L.FontSize(10.f), FaceBold);
				Label(Out, FVector2D(CX, CP.Y + (ChipH - NameSize.Y) * 0.5f), ShortName, L.FontSize(10.f), FaceBold, Tone, EVerseTextAlign::Left, 0.f,
					TEXT("gadget.name"));
			}
			CX += IconW + L.Px(8.f);
			Label(Out, FVector2D(CX, CP.Y + (ChipH - CountMeasured.Y) * 0.5f), Count, CountSize, FaceNumber,
				G.CooldownRemaining > 0.f ? VerseUiTheme::TextDim : Tone, EVerseTextAlign::Left, 0.f,
				G.CooldownRemaining > 0.f ? FName(TEXT("gadget.cooldown")) : FName(TEXT("gadget.charges")));
		}
		Y += ChipH + L.Px(6.f);
	}

	// Weapons: one row per slot in slot order.
	for (const FVerseHudWeaponSlot& Slot : Weapons)
	{
		const bool bActive = IsActive(Slot);
		const float H = bActive ? ActiveH : RowH;
		const FVector2D RP(Origin.X, Y);
		Y += H + Gap;
		const float NumRight = RP.X + W - Pad - L.Px(4.f);

		if (bActive)
		{
			LitPlate(Out, RP, FVector2D(W, H), TagWeapon);
			FillRect(Out, RP, FVector2D(L.Px(3.f), H), VerseUiTheme::Amber, TagWeapon);
		}
		else
		{
			FillRect(Out, RP, FVector2D(W, H), PlateTone, TagWeapon);
		}

		const float KeySide = bActive ? L.Px(19.f) : L.Px(16.f);
		const float KeyX = RP.X + Pad + L.Px(3.f);
		const float KeyW = KeyChip(Out, L, FVector2D(KeyX, RP.Y + (H - KeySide) * 0.5f), KeySide, KeyFor(Frame.Keys, Slot.Slot), !bActive,
			bActive ? FName(TEXT("weapon.key")) : FName(TEXT("weapon.slot_key")));
		const float IconX = KeyX + KeyW + L.Px(12.f);
		const FLinearColor Tone = bActive ? Ink : WithAlpha(VerseUiTheme::Text, 0.82f);
		// The icon takes the room the numbers leave (they are laid out first).
		auto DrawIcon = [&](float NumbersLeft)
		{
			const float Room = FMath::Max(0.f, NumbersLeft - L.Px(12.f) - IconX);
			if (VerseHudIcons::Has(Slot.WeaponId))
			{
				Icon(Out, Slot.WeaponId, IconX, RP.Y + H * 0.5f, bActive ? L.Px(26.f) : L.Px(20.f), FMath::Min(Room, bActive ? L.Px(108.f) : L.Px(72.f)), Tone,
					bActive ? FName(TEXT("weapon.icon")) : FName(TEXT("weapon.slot_icon")));
			}
			else
			{
				// Unknown weapon: its name stands in for the icon.
				const int32 NameSize = L.FontSize(bActive ? 12.f : 10.f);
				const FText Name = ItemName(S, Slot.WeaponId);
				Label(Out, FVector2D(IconX, RP.Y + (H - MeasureFace(Name, NameSize, FaceBold).Y) * 0.5f), Name, NameSize, FaceBold, Tone, EVerseTextAlign::Left,
					Room, bActive ? FName(TEXT("weapon.name")) : FName(TEXT("weapon.slot_name")));
			}
		};

		if (!Slot.bUsesAmmo)
		{
			DrawIcon(NumRight);
			continue;
		}
		if (!bActive)
		{
			DrawIcon(AmmoPair(Out, L, NumRight, RP.Y, H, Num(S, Slot.Magazine), L.FontSize(16.f), Num(S, Slot.Reserve), L.FontSize(11.f),
				TEXT("weapon.slot_magazine"), TEXT("weapon.slot_reserve")));
			continue;
		}

		const bool bLow = Pawn.MagazineSize > 0 && Pawn.Magazine * 4 <= Pawn.MagazineSize;
		const FLinearColor MagInk = bLow ? VerseUiTheme::Red : Pawn.bReloading ? WithAlpha(Ink, 0.45f) : Ink;
		FText Second;
		FName SecondFace = FaceNumber;
		FLinearColor SecondInk = WithAlpha(Ink, 0.55f);
		FName SecondTag = TEXT("weapon.reserve");
		int32 SecondSize = L.FontSize(15.f);
		if (Pawn.bReloading)
		{
			Second = S.Get(Pawn.bTacticalReload ? TEXT("verse.hud.reload_tactical") : TEXT("verse.hud.reload_empty"));
			SecondFace = FaceBold;
			SecondInk = InkAmber;
			SecondTag = TEXT("weapon.reload");
			SecondSize = L.FontSize(10.f);
		}
		else
		{
			Second = Num(S, Pawn.Reserve);
		}
		// Right to left: reserve (or the reload label), a small "+1" for the chambered round, the magazine.
		const FText Mag = Num(S, Pawn.Magazine);
		const int32 MagSize = L.FontSize(28.f);
		const FVector2D MagMeasured = MeasureFace(Mag, MagSize, FaceNumber);
		const float MagTop = RP.Y + (H - MagMeasured.Y) * 0.5f;
		const float MagBottom = MagTop + MagMeasured.Y;
		const FVector2D SecondMeasured = MeasureFace(Second, SecondSize, SecondFace);
		// The reload label may take half the row; the icon shrinks to what is left.
		Label(Out, FVector2D(NumRight, MagBottom - SecondMeasured.Y), Second, SecondSize, SecondFace, SecondInk, EVerseTextAlign::Right, W * 0.5f, SecondTag);
		float MagRight = NumRight - float(SecondMeasured.X) - L.Px(6.f);
		if (Pawn.bChambered && Pawn.Magazine > 0)
		{
			const FVector2D PlusSize = Label(Out, FVector2D(MagRight, MagTop + L.Px(4.f)), S.Get(TEXT("verse.hud.chambered")), L.FontSize(11.f), FaceBold,
				InkAmber, EVerseTextAlign::Right, 0.f, TEXT("weapon.chambered"));
			MagRight -= float(PlusSize.X) + L.Px(1.f);
		}
		Label(Out, FVector2D(MagRight, MagTop), Mag, MagSize, FaceNumber, MagInk, EVerseTextAlign::Right, 0.f, TEXT("weapon.magazine"));
		DrawIcon(MagRight - float(MagMeasured.X));
		if (bLow)
		{
			// Low ammo is also a mark under the number (never colour alone).
			FillRect(Out, FVector2D(MagRight - float(MagMeasured.X), MagBottom - L.Px(5.f)), FVector2D(float(MagMeasured.X), L.Px(2.f)), VerseUiTheme::Red,
				TagWeapon);
		}
		if (Pawn.bReloading)
		{
			const FVector2D BarPos(RP.X + L.Px(3.f), RP.Y + H - L.Px(3.f));
			const float BarW = W - L.Px(3.f);
			FillRect(Out, BarPos, FVector2D(BarW, L.Px(3.f)), WithAlpha(Ink, 0.18f), TagWeapon);
			FillRect(Out, BarPos, FVector2D(BarW * FMath::Clamp(Pawn.ReloadProgress, 0.f, 1.f), L.Px(3.f)), VerseUiTheme::Amber, TagWeapon);
		}
	}

	// Health: one slim row at the foot of the column.
	{
		const FVector2D HP(Origin.X, Origin.Y + Height - HealthH);
		FillRect(Out, HP, FVector2D(W, HealthH), PlateTone, TagVitals);
		const float Fraction = Pawn.MaxHealth > 0.f ? FMath::Clamp(Pawn.Health / Pawn.MaxHealth, 0.f, 1.f) : 0.f;
		const bool bLow = Fraction < 0.3f;
		const FLinearColor Tone = bLow ? VerseUiTheme::Red : VerseUiTheme::Text;

		const float CrossS = L.Px(11.f);
		const float CrossT = FMath::Max(1.f, L.Px(3.f));
		const FVector2D CC(HP.X + Pad + L.Px(3.f) + CrossS * 0.5f, HP.Y + HealthH * 0.5f);
		FillRect(Out, CC - FVector2D(CrossS * 0.5f, CrossT * 0.5f), FVector2D(CrossS, CrossT), Tone, TagVitals);
		FillRect(Out, CC - FVector2D(CrossT * 0.5f, CrossS * 0.5f), FVector2D(CrossT, CrossS), Tone, TagVitals);
		const FText Value = Num(S, FMath::CeilToInt(Pawn.Health));
		const int32 ValueSize = L.FontSize(17.f);
		const FVector2D ValueMeasured = MeasureFace(Value, ValueSize, FaceNumber);
		const float NumX = CC.X + CrossS * 0.5f + L.Px(8.f);
		Label(Out, FVector2D(NumX, HP.Y + (HealthH - ValueMeasured.Y) * 0.5f), Value, ValueSize, FaceNumber, Tone, EVerseTextAlign::Left, 0.f,
			TEXT("vitals.health"));

		const float BarX = NumX + FMath::Max<float>(L.Px(30.f), float(ValueMeasured.X) + L.Px(10.f));
		const FVector2D BarPos(BarX, HP.Y + HealthH * 0.5f - L.Px(2.f));
		const FVector2D BarSize(Right - Pad - L.Px(4.f) - BarX, L.Px(4.f));
		FillRect(Out, BarPos, BarSize, WithAlpha(VerseUiTheme::Text, 0.14f), TagVitals);
		FillRect(Out, BarPos, FVector2D(BarSize.X * Fraction, BarSize.Y), Tone, TagVitals);
		// Low health also shows as notches (not colour alone).
		if (bLow)
		{
			for (int32 I = 1; I <= 3; ++I)
			{
				const float NX = BarPos.X + BarSize.X * (0.1f * I);
				Line(Out, FVector2D(NX, BarPos.Y - L.Px(3.f)), FVector2D(NX, BarPos.Y), FMath::Max(1.f, L.Px(1.5f)), VerseUiTheme::Red, TagVitals);
			}
		}
	}

	// Spawn protection: one line above the column.
	if (Pawn.bSpawnProtected)
	{
		FFormatNamedArguments Args;
		Args.Add(TEXT("seconds"), Seconds(S, Pawn.SpawnProtectionRemaining));
		const FText Text = S.Format(TEXT("verse.hud.protected"), Args);
		const int32 Size = L.FontSize(11.f);
		const FVector2D Measured = MeasureFace(Text, Size, FaceBold);
		const float Sq = L.Px(11.f);
		const float MaxText = W - Sq - L.Px(6.f);
		const float LineY = Origin.Y - L.Px(8.f) - FMath::Max<float>(float(Measured.Y), Sq);
		Label(Out, FVector2D(Right, LineY), Text, Size, FaceBold, VerseUiTheme::Blocked, EVerseTextAlign::Right, MaxText, TEXT("vitals.protected"));
		Out.Labels.Last().bShadow = true;
		const float TextW = FMath::Min<float>(float(Measured.X), MaxText);
		Outline(Out, FVector2D(Right - TextW - L.Px(6.f) - Sq, LineY + (float(Measured.Y) - Sq) * 0.5f), FVector2D(Sq, Sq), FMath::Max(1.f, L.Px(1.5f)),
			VerseUiTheme::Blocked, TEXT("vitals.protected"));
	}
	(void)Measure;
}

void FVerseHudPainter::PaintScore(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure)
{
	const FVerseUiLayout& L = Frame.Layout;
	const FVerseUiStrings& S = *Frame.Strings;
	const FVector2D BlockSize(L.Px(300.f), L.Px(66.f));
	const FVector2D P = L.Place(EVerseUiAnchor::Top, BlockSize, FVector2D(0.f, 4.f));
	FillRect(Out, P, BlockSize, VerseUiTheme::Steel, TagScore);
	const float Mid = P.X + BlockSize.X * 0.5f;
	const float Half = BlockSize.X * 0.5f - L.Px(42.f);

	Text(Out, Measure, FVector2D(Mid - L.Px(14.f), P.Y + L.Px(4.f)), Num(*Frame.Strings, Frame.Model->GetScoreSelf()), L.FontSize(22.f), true, VerseUiTheme::Amber,
		EVerseTextAlign::Right, 0.f, TEXT("score.self"));
	Text(Out, Measure, FVector2D(Mid, P.Y + L.Px(4.f)), S.Get(TEXT("verse.hud.score.separator")), L.FontSize(22.f), true, VerseUiTheme::TextDim,
		EVerseTextAlign::Centre, 0.f, TEXT("score.separator"));
	Text(Out, Measure, FVector2D(Mid + L.Px(14.f), P.Y + L.Px(4.f)), Num(*Frame.Strings, Frame.Model->GetScoreOpponent()), L.FontSize(22.f), true, VerseUiTheme::Red,
		EVerseTextAlign::Left, 0.f, TEXT("score.opponent"));

	Text(Out, Measure, FVector2D(P.X + L.Px(10.f), P.Y + L.Px(14.f)), S.Get(TEXT("verse.hud.score.you")), L.FontSize(9.f), true, VerseUiTheme::TextDim,
		EVerseTextAlign::Left, Half - L.Px(10.f), TEXT("score.you_label"));
	Text(Out, Measure, FVector2D(P.X + BlockSize.X - L.Px(10.f), P.Y + L.Px(14.f)), S.Get(TEXT("verse.hud.score.opponent")), L.FontSize(9.f), true,
		VerseUiTheme::TextDim, EVerseTextAlign::Right, Half - L.Px(10.f), TEXT("score.opponent_label"));

	FFormatNamedArguments Args;
	Args.Add(TEXT("set"), Num(*Frame.Strings, Frame.Model->GetSetIndex()));
	Args.Add(TEXT("target"), Num(*Frame.Strings, Frame.Model->Timing.SetTarget));
	Text(Out, Measure, FVector2D(Mid, P.Y + L.Px(44.f)), S.Format(TEXT("verse.hud.score.set"), Args), L.FontSize(9.f), false, VerseUiTheme::TextDim,
		EVerseTextAlign::Centre, BlockSize.X - L.Px(16.f), TEXT("score.set"));
}

void FVerseHudPainter::PaintFeed(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure)
{
	const FVerseUiLayout& L = Frame.Layout;
	const FVerseUiStrings& S = *Frame.Strings;
	const float Width = L.Px(560.f);
	const float LineH = L.Px(30.f);
	const FVector2D Origin = L.Place(EVerseUiAnchor::TopRight, FVector2D(Width, LineH), FVector2D(4.f, 4.f));
	const TArray<FVerseKillFeedEntry>& Feed = Frame.Model->GetKillFeed();
	const int32 LocalId = Frame.Model->GetLocalPlayerId();
	for (int32 I = 0; I < Feed.Num(); ++I)
	{
		const FVerseKillFeedEntry& E = Feed[I];
		const float Age = float(Frame.Now - E.Time);
		const float Alpha = FMath::Clamp((Frame.Model->Timing.FeedEntry - Age) / 0.6f, 0.f, 1.f);
		FText Line;
		FLinearColor Colour = VerseUiTheme::Text;
		if (E.Kind == EVerseFeedKind::Kill)
		{
			FText How;
			switch (E.Cause)
			{
			case EVerseDamageSource::Finisher: How = S.Get(TEXT("verse.hud.feed.finisher")); break;
			case EVerseDamageSource::Melee:
				How = E.WeaponId.IsNone() ? S.Get(TEXT("verse.hud.feed.melee")) : ItemName(S, E.WeaponId);
				break;
			default: How = E.WeaponId.IsNone() ? S.Get(TEXT("verse.hud.feed.unknown")) : ItemName(S, E.WeaponId); break;
			}
			FFormatNamedArguments Args;
			Args.Add(TEXT("killer"), PlayerName(Frame, E.KillerId));
			Args.Add(TEXT("weapon"), How);
			Args.Add(TEXT("victim"), PlayerName(Frame, E.VictimId));
			FString Composed = S.Format(TEXT("verse.hud.feed.kill"), Args).ToString();
			if (E.bHeadshot)
			{
				Composed += S.Get(TEXT("verse.hud.feed.headshot")).ToString();
			}
			if (E.bWallShot)
			{
				Composed += S.Get(TEXT("verse.hud.feed.wallshot")).ToString();
			}
			Line = FText::AsCultureInvariant(Composed);
			Colour = E.KillerId == LocalId ? VerseUiTheme::Amber : (E.VictimId == LocalId ? VerseUiTheme::Red : VerseUiTheme::Text);
		}
		else if (E.Kind == EVerseFeedKind::Respawn)
		{
			FFormatNamedArguments Args;
			Args.Add(TEXT("player"), PlayerName(Frame, E.VictimId));
			Line = S.Format(TEXT("verse.hud.feed.respawn"), Args);
			Colour = VerseUiTheme::TextDim;
		}
		else
		{
			const TCHAR* Key = E.Outcome == EVerseSetOutcome::Won ? TEXT("verse.hud.feed.set_won")
				: E.Outcome == EVerseSetOutcome::Lost ? TEXT("verse.hud.feed.set_lost")
				: TEXT("verse.hud.feed.set_unfinished");
			Line = S.Get(Key);
			Colour = E.Outcome == EVerseSetOutcome::Won ? VerseUiTheme::Gold : VerseUiTheme::Text;
		}
		const FVector2D Row(Origin.X, Origin.Y + I * (LineH + L.Px(4.f)));
		const FVector2D Size = Measure(Line, L.FontSize(11.f), true);
		const float Plate = FMath::Min<float>(Size.X, Width) + L.Px(20.f);
		FillRect(Out, FVector2D(Row.X + Width - Plate, Row.Y), FVector2D(Plate, LineH), WithAlpha(VerseUiTheme::Steel, Alpha), TagFeed);
		Text(Out, Measure, FVector2D(Row.X + Width - L.Px(10.f), Row.Y + (LineH - Size.Y) * 0.5f), Line, L.FontSize(11.f), true,
			WithAlpha(Colour, Alpha), EVerseTextAlign::Right, Width - L.Px(20.f), TagFeed);
	}
}

void FVerseHudPainter::PaintCentre(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure)
{
	const FVerseUiLayout& L = Frame.Layout;
	const FVerseUiStrings& S = *Frame.Strings;
	const float Width = L.SafeSize().X * 0.6f;
	const float Mid = L.SafeMin.X + L.SafeSize().X * 0.5f;

	if (Frame.bKillCam)
	{
		FFormatNamedArguments Args;
		Args.Add(TEXT("player"), PlayerName(Frame, Frame.KillCamKillerId));
		const float Y = L.SafeMin.Y + L.Px(96.f);
		const FVector2D Size = Measure(S.Format(TEXT("verse.hud.killcam"), Args), L.FontSize(16.f), true);
		FillRect(Out, FVector2D(Mid - Size.X * 0.5f - L.Px(16.f), Y - L.Px(6.f)), FVector2D(Size.X + L.Px(32.f), Size.Y + L.Px(12.f)), VerseUiTheme::Steel, TagCentre);
		FillRect(Out, FVector2D(Mid - Size.X * 0.5f - L.Px(16.f), Y - L.Px(6.f)), FVector2D(L.Px(4.f), Size.Y + L.Px(12.f)), VerseUiTheme::Red, TagCentre);
		Text(Out, Measure, FVector2D(Mid, Y), S.Format(TEXT("verse.hud.killcam"), Args), L.FontSize(16.f), true, VerseUiTheme::Text,
			EVerseTextAlign::Centre, Width, TEXT("centre.killcam"));
		FFormatNamedArguments Skip;
		Skip.Add(TEXT("key"), Frame.SkipKeyName);
		Text(Out, Measure, FVector2D(Mid, Y + Size.Y + L.Px(14.f)), S.Format(TEXT("verse.hud.killcam_skip"), Skip), L.FontSize(10.f), false,
			VerseUiTheme::TextDim, EVerseTextAlign::Centre, Width, TEXT("centre.killcam_skip"));
	}

	if (Frame.Model->IsLocalDead())
	{
		FFormatNamedArguments Args;
		Args.Add(TEXT("seconds"), Seconds(*Frame.Strings, Frame.Model->GetRespawnRemaining(Frame.ServerTime)));
		const float Y = L.SafeMin.Y + L.SafeSize().Y * 0.70f;
		Text(Out, Measure, FVector2D(Mid, Y), S.Format(TEXT("verse.hud.respawn_in"), Args), L.FontSize(20.f), true, VerseUiTheme::Text,
			EVerseTextAlign::Centre, Width, TEXT("centre.respawn"));
	}
}

// ---------------------------------------------------------------------------------------------
// Canvas renderer

const UFont* FVerseHudCanvasRenderer::LabelFont()
{
	static TWeakObjectPtr<const UFont> Cached;
	if (const UFont* Font = Cached.Get())
	{
		return Font;
	}
	const UFont* Font = GEngine ? GEngine->GetMediumFont() : nullptr;
	if (!Font || Font->FontCacheType != EFontCacheType::Runtime)
	{
		Font = LoadObject<UFont>(nullptr, TEXT("/Engine/EngineFonts/Roboto.Roboto"));
	}
	Cached = Font;
	return Font;
}

void FVerseHudCanvasRenderer::Render(UCanvas* Canvas, const FVerseHudDrawList& List)
{
	if (!Canvas || !Canvas->Canvas)
	{
		return;
	}
	FCanvas* C = Canvas->Canvas;
	for (const FVerseHudDrawList::FRect& R : List.Rects)
	{
		FCanvasTileItem Tile(R.Min, R.Max - R.Min, R.Colour);
		Tile.BlendMode = SE_BLEND_Translucent;
		C->DrawItem(Tile);
	}
	for (const FVerseHudDrawList::FTri& T : List.Tris)
	{
		FCanvasTriangleItem Tri(T.A, T.B, T.C, GWhiteTexture);
		Tri.SetColor(T.Colour);
		Tri.BlendMode = SE_BLEND_Translucent;
		C->DrawItem(Tri);
	}
	for (const FVerseHudDrawList::FIcon& I : List.Icons)
	{
		const FVector2D Box = I.Max - I.Min;
		UTexture2D* Texture = VerseHudIcons::Texture(I.ItemId, float(Box.Y));
		if (!Texture || !Texture->GetResource())
		{
			continue;
		}
		FCanvasTileItem Tile(I.Min, Texture->GetResource(), Box, I.Colour);
		Tile.BlendMode = SE_BLEND_Translucent;
		C->DrawItem(Tile);
	}
	for (const FVerseHudDrawList::FLine& L : List.Lines)
	{
		FCanvasLineItem Line(L.A, L.B);
		Line.LineThickness = L.Thickness;
		Line.SetColor(L.Colour);
		Line.BlendMode = SE_BLEND_Translucent;
		C->DrawItem(Line);
	}
	const UFont* Font = LabelFont();
	if (!Font)
	{
		return;
	}
	for (const FVerseHudDrawList::FLabel& T : List.Labels)
	{
		const FName Face = !T.Typeface.IsNone() ? T.Typeface : FName(T.bBold ? TEXT("Bold") : TEXT("Regular"));
		FCanvasTextItem Text(T.Position, T.Text, FCoreStyle::GetDefaultFontStyle(Face, T.FontSize), T.Colour);
		Text.Font = Font;
		if (T.bShadow)
		{
			Text.EnableShadow(FLinearColor(0.f, 0.f, 0.f, 0.8f * T.Colour.A), FVector2D(1.0, 1.0));
		}
		Text.BlendMode = SE_BLEND_Translucent;
		C->DrawItem(Text);
	}
}
