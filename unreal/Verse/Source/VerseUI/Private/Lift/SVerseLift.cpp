#include "Lift/SVerseLift.h"

#include "DeckHud/SVerseDialogFrame.h"
#include "DeckHud/VerseDeckHudSubsystem.h"
#include "DeckHud/VerseSlateKit.h"
#include "Rendering/DrawElements.h"

void SVerseLiftPanel::Construct(const FArguments&, UVerseDeckHudSubsystem* InOwner)
{
	TWeakObjectPtr<UVerseDeckHudSubsystem> Weak = InOwner;
	TSharedRef<SVerticalBox> Rows = SNew(SVerticalBox);
	int32 CurrentIndex = 0;
	int32 Index = 0;
	for (const FVerseLiftRow& Row : InOwner->GetLift().Rows())
	{
		const FName Deck = Row.Deck;
		const FString NameKey = Row.NameKey;
		const FString AboutKey = Row.AboutKey;
		const bool bCurrent = Row.bCurrent;
		CurrentIndex = bCurrent ? Index : CurrentIndex;
		++Index;
		Rows->AddSlot().AutoHeight().Padding(0.f, 3.f)
		[
			SNew(SButton)
			.ButtonStyle(&VerseSlateKit::ButtonStyle(bCurrent))
			.OnClicked_Lambda([Weak, Deck]()
			{
				if (Weak.IsValid())
				{
					Weak->ChooseDeck(Deck);
				}
				return FReply::Handled();
			})
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 14.f, 0.f)
				[
					VerseSlateKit::Text(FText::AsCultureInvariant(Row.Number), 26, true, bCurrent ? VerseUiTheme::Gold : VerseUiTheme::TextDim)
				]
				+ SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()
					[
						VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Weak, NameKey]() { return Weak.IsValid() ? Weak->S(NameKey) : FText::GetEmpty(); }), 16, true, VerseUiTheme::Text)
					]
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(SBox).MaxDesiredWidth(380.f)
						[
							SNew(STextBlock)
							.Text_Lambda([Weak, AboutKey]() { return Weak.IsValid() ? Weak->S(AboutKey) : FText::GetEmpty(); })
							.Font(VerseSlateKit::Font(11))
							.ColorAndOpacity(FSlateColor(VerseUiTheme::TextDim))
							.AutoWrapText(true)
						]
					]
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(14.f, 0.f, 0.f, 0.f)
				[
					SNew(SBox)
					.Visibility(bCurrent ? EVisibility::Visible : EVisibility::Collapsed)
					[
						VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Weak]() { return Weak.IsValid() ? Weak->S(TEXT("verse.lift.here")) : FText::GetEmpty(); }), 11, true, VerseUiTheme::Amber)
					]
				]
			]
		];
	}
	ChildSlot
	[
		SNew(SVerseDialogFrame)
		.InitialFocusIndex(CurrentIndex)
		.OnClose_Lambda([Weak]() { if (Weak.IsValid()) { Weak->CloseLift(); } })
		[
			SNew(SBox).WidthOverride(560.f)
			[
				SNew(SBorder)
				.BorderImage(VerseSlateKit::Colour(VerseUiTheme::Steel))
				.Padding(FMargin(26.f, 20.f))
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 12.f)
					[
						VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Weak]() { return Weak.IsValid() ? Weak->S(TEXT("verse.lift.title")) : FText::GetEmpty(); }), 22, true, VerseUiTheme::Text)
					]
					+ SVerticalBox::Slot().AutoHeight()
					[
						Rows
					]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 10.f, 0.f, 0.f).HAlign(HAlign_Right)
					[
						SNew(SButton)
						.ButtonStyle(&VerseSlateKit::ButtonStyle(false))
						.OnClicked_Lambda([Weak]()
						{
							if (Weak.IsValid())
							{
								Weak->CloseLift();
							}
							return FReply::Handled();
						})
						[
							VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Weak]() { return Weak.IsValid() ? Weak->S(TEXT("verse.card.close")) : FText::GetEmpty(); }), 12, true, VerseUiTheme::Text)
						]
					]
				]
			]
		]
	];
}

void SVerseLiftDoors::Construct(const FArguments&, UVerseDeckHudSubsystem* InOwner)
{
	Owner = InOwner;
	// Painted every frame while the doors move.
	ForceVolatile(true);
}

int32 SVerseLiftDoors::OnPaint(const FPaintArgs&, const FGeometry& Geometry, const FSlateRect&, FSlateWindowElementList& Out, int32 LayerId, const FWidgetStyle&, bool) const
{
	const UVerseDeckHudSubsystem* Hud = Owner.Get();
	if (!Hud)
	{
		return LayerId;
	}
	const float Shut = Hud->GetLift().DoorFraction(Hud->Now());
	if (Shut <= 0.f)
	{
		return LayerId;
	}
	const FVector2D Size = Geometry.GetLocalSize();
	const float Leaf = Size.X * 0.5f * Shut;
	const FSlateBrush* White = VerseSlateKit::Colour(FLinearColor::White);
	const FLinearColor Steel(0.07f, 0.072f, 0.078f, 1.f);
	const FLinearColor Seam(0.95f, 0.72f, 0.22f, 1.f);
	auto Box = [&](float X, float Width, const FLinearColor& Tint)
	{
		FSlateDrawElement::MakeBox(Out, LayerId, Geometry.ToPaintGeometry(FVector2f(Width, Size.Y), FSlateLayoutTransform(FVector2f(X, 0.f))), White, ESlateDrawEffect::None, Tint);
	};
	Box(0.f, Leaf, Steel);
	Box(Size.X - Leaf, Leaf, Steel);
	// A gold line on each leaf's leading edge: the doors read as doors, not as a fade.
	Box(Leaf - 3.f, 3.f, Seam);
	Box(Size.X - Leaf, 3.f, Seam);
	return LayerId + 1;
}
