#include "CanvasItem.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Input/VerseDeckControlComponent.h"

// The deck overlay (stream S5): the reticle at eye level, the "click to look" hint and the
// station label on hover in the overview (parity H-09, H-10, S-14). Military-Industrial Noir:
// black steel plates, warm off-white text, amber only where something can be used.

namespace VerseDeckOverlayPrivate
{
	const FLinearColor Plate(0.010f, 0.010f, 0.011f, 0.82f);
	const FLinearColor Edge(0.20f, 0.17f, 0.12f, 1.f);
	const FLinearColor Text(0.86f, 0.82f, 0.74f, 1.f);
	const FLinearColor TextDim(0.62f, 0.58f, 0.52f, 0.9f);
	const FLinearColor Amber(1.00f, 0.55f, 0.08f, 1.f);
	const FLinearColor Shadow(0.f, 0.f, 0.f, 0.75f);

	void Line(UCanvas* Canvas, const FVector2D& A, const FVector2D& B, const FLinearColor& Colour, float Thickness)
	{
		FCanvasLineItem Item(A, B);
		Item.SetColor(Colour);
		Item.LineThickness = Thickness;
		Canvas->DrawItem(Item);
	}

	void Box(UCanvas* Canvas, const FVector2D& At, const FVector2D& Size, const FLinearColor& Colour)
	{
		FCanvasTileItem Item(At, Size, Colour);
		Item.BlendMode = SE_BLEND_Translucent;
		Canvas->DrawItem(Item);
	}

	FVector2D LabelSize(UCanvas* Canvas, const UFont* Font, const FText& Words, float Scale)
	{
		float W = 0.f;
		float H = 0.f;
		Canvas->TextSize(Font, Words.ToString(), W, H, Scale, Scale);
		return FVector2D(W + 24.f * Scale, H + 10.f * Scale);
	}

	/** A label on a steel plate with an edge on the left (amber when it can be used). */
	void Label(UCanvas* Canvas, const FVector2D& At, const FText& Words, bool bUsable, float Scale)
	{
		const UFont* Font = GEngine ? GEngine->GetMediumFont() : nullptr;
		if (Font == nullptr || Words.IsEmpty())
		{
			return;
		}
		const FVector2D Size = LabelSize(Canvas, Font, Words, Scale);
		Box(Canvas, At, Size, Plate);
		Box(Canvas, At, FVector2D(3.f * Scale, Size.Y), bUsable ? Amber : Edge);
		Box(Canvas, At + FVector2D(0.f, Size.Y - 1.f), FVector2D(Size.X, 1.f), Edge);
		FCanvasTextItem Item(At + FVector2D(12.f * Scale, 5.f * Scale), Words, Font, Text);
		Item.Scale = FVector2D(Scale, Scale);
		Item.EnableShadow(Shadow);
		Canvas->DrawItem(Item);
	}
}

void UVerseDeckControlComponent::DrawOverlay(UCanvas* Canvas) const
{
	using namespace VerseDeckOverlayPrivate;
	if (Canvas == nullptr || !bDrawOverlay || !IsDeckActive())
	{
		return;
	}
	const FVerseDeckPointerState& State = GetPointer();
	const FVector2D Size(Canvas->ClipX, Canvas->ClipY);
	// Sizes follow the screen height so the overlay reads the same at 1080p and 1440p.
	const float Scale = FMath::Clamp(static_cast<float>(Size.Y / 1080.0), 0.75f, 2.0f);

	if (State.bReticle)
	{
		const FVector2D C = Size * 0.5;
		const float Thick = 1.5f * Scale;
		if (State.bReticleMarked)
		{
			// Something usable under it: four amber corners close around the centre.
			const float Reach = 11.f * Scale;
			const float Arm = 6.f * Scale;
			for (const FVector2D& S : { FVector2D(-1, -1), FVector2D(1, -1), FVector2D(1, 1), FVector2D(-1, 1) })
			{
				const FVector2D Corner = C + S * Reach;
				Line(Canvas, Corner, Corner - FVector2D(S.X * Arm, 0.f), Amber, Thick);
				Line(Canvas, Corner, Corner - FVector2D(0.f, S.Y * Arm), Amber, Thick);
			}
			Box(Canvas, C - FVector2D(1.5f, 1.5f) * Scale, FVector2D(3.f, 3.f) * Scale, Amber);
		}
		else
		{
			// Four short ticks with a gap, off-white.
			const float Gap = 5.f * Scale;
			const float Len = 7.f * Scale;
			Line(Canvas, C + FVector2D(Gap, 0), C + FVector2D(Gap + Len, 0), Text, Thick);
			Line(Canvas, C - FVector2D(Gap, 0), C - FVector2D(Gap + Len, 0), Text, Thick);
			Line(Canvas, C + FVector2D(0, Gap), C + FVector2D(0, Gap + Len), Text, Thick);
			Line(Canvas, C - FVector2D(0, Gap), C - FVector2D(0, Gap + Len), Text, Thick);
			Box(Canvas, C - FVector2D(1.f, 1.f) * Scale, FVector2D(2.f, 2.f) * Scale, TextDim);
		}
	}

	if (State.bClickToLook && !ClickToLookHint.IsEmpty())
	{
		if (const UFont* Font = GEngine ? GEngine->GetMediumFont() : nullptr)
		{
			const float TextScale = Scale * 1.4f;
			const FVector2D HintSize = LabelSize(Canvas, Font, ClickToLookHint, TextScale);
			Label(Canvas, FVector2D((Size.X - HintSize.X) * 0.5f, Size.Y * 0.80f), ClickToLookHint, false, TextScale);
		}
	}

	if (!State.HoverStation.IsNone())
	{
		Label(Canvas, State.LabelScreen, State.HoverLabel, true, Scale * 1.4f);
	}
}
