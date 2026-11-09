#include "Loading/SVerseLoadingScreen.h"

#include "DeckHud/VerseDeckHudSubsystem.h"
#include "DeckHud/VerseSlateKit.h"
#include "Engine/Texture2D.h"
#include "HAL/FileManager.h"
#include "ImageUtils.h"
#include "Misc/Paths.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Layout/SScaleBox.h"
#include "Widgets/Notifications/SProgressBar.h"
#include "Widgets/SOverlay.h"

FString SVerseLoadingScreen::KeyArtPath()
{
	return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data/ui/loading.jpg"));
}

void SVerseLoadingScreen::Construct(const FArguments&, UVerseDeckHudSubsystem* InOwner)
{
	TWeakObjectPtr<UVerseDeckHudSubsystem> Weak = InOwner;
	const FString Path = KeyArtPath();
	if (IFileManager::Get().FileExists(*Path))
	{
		Art.Reset(FImageUtils::ImportFileAsTexture2D(Path));
		if (Art.IsValid())
		{
			ArtBrush.SetResourceObject(Art.Get());
			ArtBrush.ImageSize = FVector2D(Art->GetSizeX(), Art->GetSizeY());
			ArtBrush.DrawAs = ESlateBrushDrawType::Image;
		}
	}

	TSharedRef<SOverlay> Layers = SNew(SOverlay)
		+ SOverlay::Slot()
		[
			SNew(SBorder).BorderImage(VerseSlateKit::Colour(FLinearColor(0.012f, 0.012f, 0.014f, 1.f)))
		];
	if (Art.IsValid())
	{
		Layers->AddSlot()
		[
			SNew(SScaleBox)
			.Stretch(EStretch::ScaleToFill)
			[
				SNew(SImage).Image(&ArtBrush)
			]
		];
	}
	// A shade under the words so they read on any art.
	Layers->AddSlot().VAlign(VAlign_Bottom)
	[
		SNew(SBox).HeightOverride(340.f)
		[
			SNew(SBorder).BorderImage(VerseSlateKit::Colour(FLinearColor(0.f, 0.f, 0.f, 0.62f)))
		]
	];
	Layers->AddSlot().HAlign(HAlign_Center).VAlign(VAlign_Bottom).Padding(FMargin(0.f, 0.f, 0.f, 72.f))
	[
		SNew(SBox).WidthOverride(520.f)
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
			[
				VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Weak]() { return Weak.IsValid() ? Weak->S(TEXT("verse.loading.title")) : FText::GetEmpty(); }), 52, true, VerseUiTheme::Gold)
			]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 2.f, 0.f, 18.f)
			[
				VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Weak]() { return Weak.IsValid() ? Weak->S(TEXT("verse.loading.subtitle")) : FText::GetEmpty(); }), 14, false, VerseUiTheme::TextDim)
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 16.f)
			[
				SNew(STextBlock)
				.Text_Lambda([Weak]()
				{
					return Weak.IsValid() ? Weak->S(FString::Printf(TEXT("verse.loading.tip_%d"), Weak->GetLoading().GetTip())) : FText::GetEmpty();
				})
				.Font(VerseSlateKit::Font(14))
				.ColorAndOpacity(FSlateColor(VerseUiTheme::Text))
				.Justification(ETextJustify::Center)
				.AutoWrapText(true)
			]
			+ SVerticalBox::Slot().AutoHeight()
			[
				SNew(SBox).HeightOverride(4.f)
				[
					SNew(SProgressBar)
					.FillColorAndOpacity(VerseUiTheme::Gold)
					.Percent_Lambda([Weak]() -> TOptional<float>
					{
						return Weak.IsValid() ? Weak->GetLoading().Progress(Weak->Now()) : 0.f;
					})
				]
			]
		]
	];
	ChildSlot[Layers];
}
