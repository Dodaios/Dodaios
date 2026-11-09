#pragma once

#include "CoreMinimal.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SCompoundWidget.h"

class SBox;
class UVerseDeckHudSubsystem;

/**
 * The deck's fixed HUD: the title top left (number, name, aboard / working / waiting counts,
 * the lift switch) with the rank card and the one-line notice under it, the tool rail top
 * right, and the click-to-look hint at the bottom. It reads the subsystem's models each frame;
 * Refresh rebuilds the tool rail when the set of tools changes.
 */
class SVerseDeckHud : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SVerseDeckHud) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs, UVerseDeckHudSubsystem* InOwner);
	void Refresh();

private:
	TSharedRef<SWidget> BuildRail();
	TSharedRef<SWidget> BuildTitle();

	TWeakObjectPtr<UVerseDeckHudSubsystem> Owner;
	TSharedPtr<SBox> RailSlot;
};
