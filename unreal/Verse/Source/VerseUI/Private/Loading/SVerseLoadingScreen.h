#pragma once

#include "Brushes/SlateImageBrush.h"
#include "CoreMinimal.h"
#include "UObject/StrongObjectPtr.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SCompoundWidget.h"

class UTexture2D;
class UVerseDeckHudSubsystem;

/**
 * The loading screen (parity A-07): key art, a title, a tip and a progress bar over the whole
 * screen. The subsystem sets its render opacity while it fades out.
 */
class SVerseLoadingScreen : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SVerseLoadingScreen) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs, UVerseDeckHudSubsystem* InOwner);

	/** <project>/Data/ui/loading.jpg */
	static FString KeyArtPath();

private:
	TStrongObjectPtr<UTexture2D> Art;
	FSlateBrush ArtBrush;
};
