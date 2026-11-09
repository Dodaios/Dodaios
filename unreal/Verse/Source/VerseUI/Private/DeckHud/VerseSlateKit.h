#pragma once

#include "Brushes/SlateColorBrush.h"
#include "Core/VerseUiTheme.h"
#include "CoreMinimal.h"
#include "Styling/CoreStyle.h"
#include "Styling/SlateTypes.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/Text/STextBlock.h"

/** Small Slate helpers shared by the deck HUD, the lift, the loading screen and the service record. */
namespace VerseSlateKit
{
	inline const FSlateBrush* Colour(const FLinearColor& InColour)
	{
		// One brush per distinct colour, alive as long as the module.
		static TMap<uint32, TUniquePtr<FSlateColorBrush>> Brushes;
		const uint32 Key = InColour.ToFColor(false).ToPackedARGB();
		TUniquePtr<FSlateColorBrush>& Brush = Brushes.FindOrAdd(Key);
		if (!Brush)
		{
			Brush = MakeUnique<FSlateColorBrush>(InColour);
		}
		return Brush.Get();
	}

	inline FSlateFontInfo Font(int32 Size, bool bBold = false)
	{
		return FCoreStyle::GetDefaultFontStyle(bBold ? "Bold" : "Regular", Size);
	}

	inline const FButtonStyle& ButtonStyle(bool bPrimary)
	{
		auto Make = [](bool bIsPrimary)
		{
			FButtonStyle Style = FCoreStyle::Get().GetWidgetStyle<FButtonStyle>("Button");
			const FLinearColor Base = bIsPrimary ? FLinearColor(0.32f, 0.16f, 0.02f, 1.f) : VerseUiTheme::SteelLight;
			Style.SetNormal(*Colour(Base));
			Style.SetHovered(*Colour(bIsPrimary ? FLinearColor(0.48f, 0.25f, 0.03f, 1.f) : VerseUiTheme::Edge));
			Style.SetPressed(*Colour(VerseUiTheme::Amber * FLinearColor(0.6f, 0.6f, 0.6f, 1.f)));
			Style.SetDisabled(*Colour(FLinearColor(0.02f, 0.02f, 0.02f, 0.6f)));
			Style.SetNormalPadding(FMargin(10.f, 6.f));
			Style.SetPressedPadding(FMargin(10.f, 7.f, 10.f, 5.f));
			return Style;
		};
		static const FButtonStyle Normal = Make(false);
		static const FButtonStyle Primary = Make(true);
		return bPrimary ? Primary : Normal;
	}

	inline TSharedRef<SWidget> Text(TAttribute<FText> Value, int32 Size, bool bBold, const FLinearColor& Tint)
	{
		return SNew(STextBlock)
			.Text(Value)
			.Font(Font(Size, bBold))
			.ColorAndOpacity(FSlateColor(Tint))
			.ShadowColorAndOpacity(VerseUiTheme::Shadow)
			.ShadowOffset(FVector2D(1.0, 1.0));
	}
}
