#include "Hud/VerseHudPainter.h"

#include "CanvasItem.h"
#include "CanvasTypes.h"
#include "Core/VerseUiStrings.h"
#include "Core/VerseUiTheme.h"
#include "Engine/Canvas.h"
#include "Fonts/FontMeasure.h"
#include "GlobalRenderResources.h"
#include "Framework/Application/SlateApplication.h"
#include "Hud/VerseCrosshair.h"
#include "Rendering/SlateRenderer.h"
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

	FText Num(int32 Value)
	{
		return FText::AsNumber(Value, &FNumberFormattingOptions::DefaultNoGrouping());
	}

	FText Seconds(float Value)
	{
		FNumberFormattingOptions Options;
		Options.MinimumFractionalDigits = 1;
		Options.MaximumFractionalDigits = 1;
		return FText::AsNumber(FMath::Max(0.f, Value), &Options);
	}

	FString StanceKey(EVerseStance Stance)
	{
		switch (Stance)
		{
		case EVerseStance::Stand: return TEXT("verse.hud.stance.stand");
		case EVerseStance::Crouch: return TEXT("verse.hud.stance.crouch");
		case EVerseStance::Prone: return TEXT("verse.hud.stance.prone");
		case EVerseStance::Slide: return TEXT("verse.hud.stance.slide");
		}
		return TEXT("verse.hud.stance.stand");
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
	if (Frame.bInDuel)
	{
		PaintCrosshair(Frame, Out);
		PaintMarkers(Frame, Out);
		PaintDamage(Frame, Out);
		PaintVitals(Frame, Out, Measure);
		PaintWeapon(Frame, Out, Measure);
		PaintScore(Frame, Out, Measure);
	}
	PaintFeed(Frame, Out, Measure);
	PaintCentre(Frame, Out, Measure);
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

	const bool bHidden = Frame.bKillCam || Frame.Model->IsLocalDead() || Frame.Pawn.Phase != EVerseCombatPhase::Alive;
	if (bHidden)
	{
		return;
	}
	Out.bCrosshairVisible = true;

	const float Gap = FMath::Max(L.Px(5.f), Spread);
	const float Length = L.Px(9.f);
	const float Thick = FMath::Max(1.f, L.Px(2.f));
	const FVector2D Dirs[4] = {FVector2D(1, 0), FVector2D(-1, 0), FVector2D(0, 1), FVector2D(0, -1)};
	for (const FVector2D& D : Dirs)
	{
		Line(Out, Centre + D * Gap, Centre + D * (Gap + Length), Thick + 2.f, VerseUiTheme::Shadow, TagCrosshair);
	}
	for (const FVector2D& D : Dirs)
	{
		Line(Out, Centre + D * Gap, Centre + D * (Gap + Length), Thick, VerseUiTheme::Text, TagCrosshair);
	}
	const float Dot = FMath::Max(2.f, L.Px(2.f));
	FillRect(Out, Centre - FVector2D(Dot, Dot) * 0.5, FVector2D(Dot, Dot), VerseUiTheme::Amber, TagCrosshair);

	if (Spread > Gap * 0.5f && Spread > L.Px(6.f))
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
				Line(Out, C + N * L.Px(8.f), C + N * L.Px(15.f), FMath::Max(1.f, L.Px(2.f)), WithAlpha(VerseUiTheme::Text, Alpha), Tag);
			}
			break;
		}
		case EVerseHitMarkerKind::Headshot:
		{
			// Shape: diagonal ticks plus a diamond.
			for (const FVector2D& D : Diagonals)
			{
				const FVector2D N = D.GetSafeNormal();
				Line(Out, C + N * L.Px(8.f), C + N * L.Px(17.f), FMath::Max(1.f, L.Px(2.5f)), WithAlpha(VerseUiTheme::Gold, Alpha), Tag);
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
		const FVector2D Base = C + Dir * Radius;
		const FVector2D Tip = C + Dir * (Radius + L.Px(22.f));
		Out.Tris.Add({Tip, Base + Side * L.Px(20.f), Base - Side * L.Px(20.f), WithAlpha(VerseUiTheme::Red, Alpha), TagDamage});
	}
}

void FVerseHudPainter::PaintVitals(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure)
{
	if (!Frame.Pawn.bValid)
	{
		return;
	}
	const FVerseUiLayout& L = Frame.Layout;
	const FVerseUiStrings& S = *Frame.Strings;
	const FVector2D BlockSize(L.Px(340.f), L.Px(104.f));
	const FVector2D P = L.Place(EVerseUiAnchor::BottomLeft, BlockSize, FVector2D(8.f, 8.f));
	FillRect(Out, P, BlockSize, VerseUiTheme::Steel, TagVitals);
	FillRect(Out, P, FVector2D(L.Px(3.f), BlockSize.Y), VerseUiTheme::Amber, TagVitals);

	const float Pad = L.Px(14.f);
	const float MaxLabel = BlockSize.X - 2 * Pad;
	Text(Out, Measure, P + FVector2D(Pad, L.Px(8.f)), S.Get(TEXT("verse.hud.health")), L.FontSize(10.f), true, VerseUiTheme::TextDim,
		EVerseTextAlign::Left, MaxLabel * 0.5f, TEXT("vitals.health_label"));

	const float Fraction = Frame.Pawn.MaxHealth > 0.f ? FMath::Clamp(Frame.Pawn.Health / Frame.Pawn.MaxHealth, 0.f, 1.f) : 0.f;
	const bool bLow = Fraction < 0.3f;
	Text(Out, Measure, P + FVector2D(Pad, L.Px(24.f)), Num(FMath::CeilToInt(Frame.Pawn.Health)), L.FontSize(26.f), true,
		bLow ? VerseUiTheme::Red : VerseUiTheme::Text, EVerseTextAlign::Left, 0.f, TEXT("vitals.health"));

	const FVector2D BarPos = P + FVector2D(Pad, L.Px(72.f));
	const FVector2D BarSize(BlockSize.X - 2 * Pad, L.Px(8.f));
	FillRect(Out, BarPos, BarSize, VerseUiTheme::SteelLight, TagVitals);
	FillRect(Out, BarPos, FVector2D(BarSize.X * Fraction, BarSize.Y), bLow ? VerseUiTheme::Red : VerseUiTheme::Amber, TagVitals);
	// Low health also shows as notches (not colour alone).
	if (bLow)
	{
		for (int32 I = 1; I <= 3; ++I)
		{
			const float X = BarPos.X + BarSize.X * (0.1f * I);
			Line(Out, FVector2D(X, BarPos.Y - L.Px(4.f)), FVector2D(X, BarPos.Y), FMath::Max(1.f, L.Px(2.f)), VerseUiTheme::Red, TagVitals);
		}
	}

	Text(Out, Measure, P + FVector2D(BlockSize.X - Pad, L.Px(8.f)), S.Get(StanceKey(Frame.Pawn.Stance)), L.FontSize(10.f), true,
		VerseUiTheme::Text, EVerseTextAlign::Right, MaxLabel * 0.5f, TEXT("vitals.stance"));

	if (Frame.Pawn.bSpawnProtected)
	{
		FFormatNamedArguments Args;
		Args.Add(TEXT("seconds"), Seconds(Frame.Pawn.SpawnProtectionRemaining));
		const FVector2D Above = P - FVector2D(0, L.Px(34.f));
		const float Sq = L.Px(16.f);
		Outline(Out, Above + FVector2D(0, L.Px(4.f)), FVector2D(Sq, Sq), FMath::Max(1.f, L.Px(2.f)), VerseUiTheme::Blocked, TEXT("vitals.protected"));
		Text(Out, Measure, Above + FVector2D(Sq + L.Px(8.f), 0), S.Format(TEXT("verse.hud.protected"), Args), L.FontSize(12.f), true,
			VerseUiTheme::Blocked, EVerseTextAlign::Left, BlockSize.X - Sq - L.Px(8.f), TEXT("vitals.protected"));
	}
}

void FVerseHudPainter::PaintWeapon(const FVerseHudFrame& Frame, FVerseHudDrawList& Out, const FVerseTextMeasure& Measure)
{
	if (!Frame.Pawn.bValid || Frame.bKillCam)
	{
		return;
	}
	const FVerseUiLayout& L = Frame.Layout;
	const FVerseUiStrings& S = *Frame.Strings;
	const FVerseHudPawnState& Pawn = Frame.Pawn;
	const FVector2D BlockSize(L.Px(380.f), L.Px(104.f));
	const FVector2D P = L.Place(EVerseUiAnchor::BottomRight, BlockSize, FVector2D(8.f, 8.f));
	const float Pad = L.Px(14.f);
	const FVector2D RightTop(P.X + BlockSize.X - Pad, P.Y);

	if (Pawn.bHasWeapon)
	{
		FillRect(Out, P, BlockSize, VerseUiTheme::Steel, TagWeapon);
		FillRect(Out, FVector2D(P.X + BlockSize.X - L.Px(3.f), P.Y), FVector2D(L.Px(3.f), BlockSize.Y), VerseUiTheme::Amber, TagWeapon);
		Text(Out, Measure, RightTop + FVector2D(0, L.Px(8.f)), ItemName(S, Pawn.WeaponId), L.FontSize(11.f), true, VerseUiTheme::Text,
			EVerseTextAlign::Right, BlockSize.X * 0.6f, TEXT("weapon.name"));

		const bool bLow = Pawn.MagazineSize > 0 && Pawn.Magazine * 4 <= Pawn.MagazineSize;
		FFormatNamedArguments Reserve;
		Reserve.Add(TEXT("reserve"), Num(Pawn.Reserve));
		const FVector2D ReserveSize = Text(Out, Measure, RightTop + FVector2D(0, L.Px(40.f)), S.Format(TEXT("verse.hud.reserve"), Reserve),
			L.FontSize(14.f), false, VerseUiTheme::TextDim, EVerseTextAlign::Right, 0.f, TEXT("weapon.reserve"));
		float X = RightTop.X - ReserveSize.X - L.Px(10.f);
		if (Pawn.bChambered && Pawn.Magazine > 0)
		{
			const FVector2D Plus = Text(Out, Measure, FVector2D(X, P.Y + L.Px(30.f)), S.Get(TEXT("verse.hud.chambered")), L.FontSize(12.f), true,
				VerseUiTheme::Gold, EVerseTextAlign::Right, 0.f, TEXT("weapon.chambered"));
			X -= Plus.X + L.Px(4.f);
		}
		Text(Out, Measure, FVector2D(X, P.Y + L.Px(22.f)), Num(Pawn.Magazine), L.FontSize(30.f), true, bLow ? VerseUiTheme::Red : VerseUiTheme::Text,
			EVerseTextAlign::Right, 0.f, TEXT("weapon.magazine"));

		if (Pawn.bReloading)
		{
			const FString Key = Pawn.bTacticalReload ? TEXT("verse.hud.reload_tactical") : TEXT("verse.hud.reload_empty");
			Text(Out, Measure, FVector2D(P.X + Pad, P.Y + L.Px(8.f)), S.Get(Key), L.FontSize(11.f), true, VerseUiTheme::Amber, EVerseTextAlign::Left,
				BlockSize.X * 0.4f - Pad, TEXT("weapon.reload"));
			const FVector2D BarPos(P.X + Pad, P.Y + BlockSize.Y - L.Px(14.f));
			const FVector2D BarSize(BlockSize.X - 2 * Pad, L.Px(4.f));
			FillRect(Out, BarPos, BarSize, VerseUiTheme::SteelLight, TagWeapon);
			FillRect(Out, BarPos, FVector2D(BarSize.X * FMath::Clamp(Pawn.ReloadProgress, 0.f, 1.f), BarSize.Y), VerseUiTheme::Amber, TagWeapon);
		}
	}

	// Gadgets sit above the weapon block, right-aligned: name, charge pips, cooldown.
	float GX = P.X + BlockSize.X;
	const float GW = L.Px(150.f);
	const float GH = L.Px(40.f);
	for (int32 I = Pawn.Gadgets.Num() - 1; I >= 0; --I)
	{
		const FVerseHudGadgetState& G = Pawn.Gadgets[I];
		GX -= GW;
		const FVector2D GP(GX, P.Y - GH - L.Px(8.f));
		GX -= L.Px(8.f);
		FillRect(Out, GP, FVector2D(GW, GH), VerseUiTheme::Steel, TagGadget);
		const bool bReady = G.Charges > 0 && G.CooldownRemaining <= 0.f;
		Text(Out, Measure, GP + FVector2D(L.Px(8.f), L.Px(4.f)), S.Get(FString::Printf(TEXT("verse.item.%s.short"), *G.GadgetId.ToString().ToLower())),
			L.FontSize(10.f), true, bReady ? VerseUiTheme::Text : VerseUiTheme::TextDim, EVerseTextAlign::Left, GW - L.Px(16.f), TEXT("gadget.name"));
		const float Pip = L.Px(9.f);
		for (int32 C = 0; C < FMath::Max(G.MaxCharges, G.Charges); ++C)
		{
			const FVector2D PipPos = GP + FVector2D(L.Px(8.f) + C * (Pip + L.Px(5.f)), GH - Pip - L.Px(6.f));
			if (C < G.Charges)
			{
				FillRect(Out, PipPos, FVector2D(Pip, Pip), VerseUiTheme::Amber, TagGadget);
			}
			else
			{
				Outline(Out, PipPos, FVector2D(Pip, Pip), 1.f, VerseUiTheme::TextDim, TagGadget);
			}
		}
		if (G.CooldownRemaining > 0.f)
		{
			FFormatNamedArguments Args;
			Args.Add(TEXT("seconds"), FText::AsNumber(FMath::CeilToInt(G.CooldownRemaining)));
			Text(Out, Measure, GP + FVector2D(GW - L.Px(8.f), GH - L.Px(22.f)), S.Format(TEXT("verse.hud.cooldown"), Args), L.FontSize(10.f), false,
				VerseUiTheme::TextDim, EVerseTextAlign::Right, GW * 0.5f, TEXT("gadget.cooldown"));
		}
	}
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

	Text(Out, Measure, FVector2D(Mid - L.Px(14.f), P.Y + L.Px(4.f)), Num(Frame.Model->GetScoreSelf()), L.FontSize(22.f), true, VerseUiTheme::Amber,
		EVerseTextAlign::Right, 0.f, TEXT("score.self"));
	Text(Out, Measure, FVector2D(Mid, P.Y + L.Px(4.f)), S.Get(TEXT("verse.hud.score.separator")), L.FontSize(22.f), true, VerseUiTheme::TextDim,
		EVerseTextAlign::Centre, 0.f, TEXT("score.separator"));
	Text(Out, Measure, FVector2D(Mid + L.Px(14.f), P.Y + L.Px(4.f)), Num(Frame.Model->GetScoreOpponent()), L.FontSize(22.f), true, VerseUiTheme::Red,
		EVerseTextAlign::Left, 0.f, TEXT("score.opponent"));

	Text(Out, Measure, FVector2D(P.X + L.Px(10.f), P.Y + L.Px(14.f)), S.Get(TEXT("verse.hud.score.you")), L.FontSize(9.f), true, VerseUiTheme::TextDim,
		EVerseTextAlign::Left, Half - L.Px(10.f), TEXT("score.you_label"));
	Text(Out, Measure, FVector2D(P.X + BlockSize.X - L.Px(10.f), P.Y + L.Px(14.f)), S.Get(TEXT("verse.hud.score.opponent")), L.FontSize(9.f), true,
		VerseUiTheme::TextDim, EVerseTextAlign::Right, Half - L.Px(10.f), TEXT("score.opponent_label"));

	FFormatNamedArguments Args;
	Args.Add(TEXT("set"), Num(Frame.Model->GetSetIndex()));
	Args.Add(TEXT("target"), Num(Frame.Model->Timing.SetTarget));
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
			Args.Add(TEXT("name"), PlayerName(Frame, E.VictimId));
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
		Args.Add(TEXT("name"), PlayerName(Frame, Frame.KillCamKillerId));
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
		Args.Add(TEXT("seconds"), Seconds(Frame.Model->GetRespawnRemaining(Frame.ServerTime)));
		const float Y = L.SafeMin.Y + L.SafeSize().Y * 0.70f;
		Text(Out, Measure, FVector2D(Mid, Y), S.Format(TEXT("verse.hud.respawn_in"), Args), L.FontSize(20.f), true, VerseUiTheme::Text,
			EVerseTextAlign::Centre, Width, TEXT("centre.respawn"));
	}
}

// ---------------------------------------------------------------------------------------------
// Canvas renderer

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
	for (const FVerseHudDrawList::FLine& L : List.Lines)
	{
		FCanvasLineItem Line(L.A, L.B);
		Line.LineThickness = L.Thickness;
		Line.SetColor(L.Colour);
		Line.BlendMode = SE_BLEND_Translucent;
		C->DrawItem(Line);
	}
	for (const FVerseHudDrawList::FLabel& T : List.Labels)
	{
		FCanvasTextItem Text(T.Position, T.Text, FCoreStyle::GetDefaultFontStyle(T.bBold ? "Bold" : "Regular", T.FontSize), T.Colour);
		Text.EnableShadow(FLinearColor(0.f, 0.f, 0.f, 0.8f * T.Colour.A), FVector2D(1.0, 1.0));
		Text.BlendMode = SE_BLEND_Translucent;
		C->DrawItem(Text);
	}
}
