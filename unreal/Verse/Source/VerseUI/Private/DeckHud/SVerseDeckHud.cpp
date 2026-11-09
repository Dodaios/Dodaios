#include "DeckHud/SVerseDeckHud.h"

#include "Core/VerseUiStrings.h"
#include "DeckHud/VerseDeckHudSubsystem.h"
#include "DeckHud/VerseSlateKit.h"
#include "ServiceRecord/SVerseRankCard.h"
#include "Widgets/SOverlay.h"

void SVerseDeckHud::Construct(const FArguments&, UVerseDeckHudSubsystem* InOwner)
{
	Owner = InOwner;
	TWeakObjectPtr<UVerseDeckHudSubsystem> Weak = InOwner;
	ChildSlot
	[
		SNew(SOverlay)
		// Top left: the title, the rank card, the notice line.
		+ SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Top).Padding(FMargin(28.f, 24.f))
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()
			[
				BuildTitle()
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 10.f, 0.f, 0.f)
			[
				SNew(SBox).Visibility_Lambda([Weak]() { return Weak.IsValid() && Weak->GetRecordModel().IsValid() ? EVisibility::Visible : EVisibility::Collapsed; })
				[
					SNew(SVerseRankCard, InOwner->GetRecordModel(), [Weak]() -> const FVerseUiStrings& { return Weak->Strings(); })
					.OnOpen_Lambda([Weak]() { if (Weak.IsValid()) { Weak->OpenServiceRecord(0); } })
				]
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 10.f, 0.f, 0.f)
			[
				SNew(SBox).MaxDesiredWidth(560.f)
				[
					SNew(STextBlock)
					.Text_Lambda([Weak]() { return Weak.IsValid() ? Weak->GetNoticeText() : FText::GetEmpty(); })
					.Font(VerseSlateKit::Font(13))
					.ColorAndOpacity(FSlateColor(VerseUiTheme::Text))
					.ShadowColorAndOpacity(VerseUiTheme::Shadow)
					.ShadowOffset(FVector2D(1.0, 1.0))
					.AutoWrapText(true)
				]
			]
		]
		// Top right: the tool rail.
		+ SOverlay::Slot().HAlign(HAlign_Right).VAlign(VAlign_Top).Padding(FMargin(28.f, 24.f))
		[
			SAssignNew(RailSlot, SBox)
		]
		// Bottom: the click-to-look hint.
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Bottom).Padding(FMargin(0.f, 0.f, 0.f, 96.f))
		[
			SNew(SBorder)
			.BorderImage(VerseSlateKit::Colour(VerseUiTheme::Steel))
			.Padding(FMargin(14.f, 6.f))
			.Visibility_Lambda([Weak]() { return Weak.IsValid() && Weak->ShowsClickToLook() ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
			[
				VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Weak]() { return Weak.IsValid() ? Weak->S(TEXT("verse.tools.click_to_look")) : FText::GetEmpty(); }), 14, true, VerseUiTheme::Text)
			]
		]
	];
	Refresh();
}

void SVerseDeckHud::Refresh()
{
	if (RailSlot.IsValid())
	{
		RailSlot->SetContent(BuildRail());
	}
}

TSharedRef<SWidget> SVerseDeckHud::BuildTitle()
{
	TWeakObjectPtr<UVerseDeckHudSubsystem> Weak = Owner;
	auto Title = [Weak]() { return Weak.IsValid() ? Weak->GetTitle() : FVerseDeckTitle(); };
	auto Counted = [Title](FText FVerseDeckTitle::*Member)
	{
		return TAttribute<FText>::CreateLambda([Title, Member]() { return Title().*Member; });
	};
	return SNew(SBorder)
		.BorderImage(VerseSlateKit::Colour(VerseUiTheme::Steel))
		.Padding(FMargin(14.f, 10.f))
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 14.f, 0.f)
			[
				VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Title]() { return FText::AsCultureInvariant(Title().Number); }), 40, true, VerseUiTheme::Gold)
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					VerseSlateKit::Text(Counted(&FVerseDeckTitle::Label), 11, false, VerseUiTheme::TextDim)
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					VerseSlateKit::Text(Counted(&FVerseDeckTitle::Name), 22, true, VerseUiTheme::Text)
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 4.f, 0.f, 0.f)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth().Padding(0.f, 0.f, 14.f, 0.f)
					[
						VerseSlateKit::Text(Counted(&FVerseDeckTitle::AboardText), 12, false, VerseUiTheme::Text)
					]
					+ SHorizontalBox::Slot().AutoWidth().Padding(0.f, 0.f, 14.f, 0.f)
					[
						VerseSlateKit::Text(Counted(&FVerseDeckTitle::WorkingText), 12, false, VerseUiTheme::Amber)
					]
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(SBox)
						.Visibility_Lambda([Title]() { return Title().bShowWaiting ? EVisibility::Visible : EVisibility::Collapsed; })
						[
							VerseSlateKit::Text(Counted(&FVerseDeckTitle::WaitingText), 12, true, VerseUiTheme::Red)
						]
					]
				]
			]
			// The deck switch sits right on the title: it is where people look for the other decks.
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(18.f, 0.f, 0.f, 0.f)
			[
				SNew(SButton)
				.ButtonStyle(&VerseSlateKit::ButtonStyle(false))
				.OnClicked_Lambda([Weak]()
				{
					if (Weak.IsValid())
					{
						Weak->OpenLift(EVerseLiftSource::TitleSwitch);
					}
					return FReply::Handled();
				})
				[
					VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Weak]() { return Weak.IsValid() ? Weak->S(TEXT("verse.lift.switch")) : FText::GetEmpty(); }), 12, true, VerseUiTheme::Text)
				]
			]
		];
}

TSharedRef<SWidget> SVerseDeckHud::BuildRail()
{
	TWeakObjectPtr<UVerseDeckHudSubsystem> Weak = Owner;
	TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);
	if (!Weak.IsValid())
	{
		return Row;
	}
	for (const FVerseToolEntry& Entry : Weak->GetTools())
	{
		const EVerseTool Tool = Entry.Tool;
		const FString LabelKey = Entry.LabelKey;
		const FString KeyHint = Entry.KeyHint;
		TSharedRef<SHorizontalBox> Content = SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Weak, LabelKey]() { return Weak.IsValid() ? Weak->S(LabelKey) : FText::GetEmpty(); }), 12, true, VerseUiTheme::Text)
			];
		if (!KeyHint.IsEmpty())
		{
			Content->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(8.f, 0.f, 0.f, 0.f)
			[
				SNew(SBorder)
				.BorderImage(VerseSlateKit::Colour(VerseUiTheme::Edge))
				.Padding(FMargin(5.f, 1.f))
				[
					VerseSlateKit::Text(FText::AsCultureInvariant(KeyHint), 10, true, VerseUiTheme::TextDim)
				]
			];
		}
		TSharedRef<SButton> Button = SNew(SButton)
			.ButtonStyle(&VerseSlateKit::ButtonStyle(Entry.bPressed))
			.IsEnabled(Entry.bEnabled)
			.OnClicked_Lambda([Weak, Tool]()
			{
				if (Weak.IsValid())
				{
					Weak->ActivateTool(Tool);
				}
				return FReply::Handled();
			})
			[
				Content
			];
		Row->AddSlot().AutoWidth().Padding(2.f, 0.f)
		[
			SNew(SBorder)
			.BorderImage(VerseSlateKit::Colour(VerseUiTheme::Steel))
			.Padding(FMargin(0.f))
			[
				Button
			]
		];
	}
	return Row;
}
