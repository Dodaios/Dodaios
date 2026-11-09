#pragma once

#include "CoreMinimal.h"
#include "DeckHud/VerseDialogStack.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SCompoundWidget.h"

/**
 * The modal frame every Verse dialog sits in (parity H-12): a scrim behind, keyboard and
 * gamepad navigation trapped inside, Escape (and the gamepad's back button) or a click on the
 * scrim close it, and the focus goes back to the widget that opened it. The lift, the service
 * record and the menus use it.
 */
class SVerseDialogFrame : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SVerseDialogFrame)
		: _bScrim(true)
		, _bHandleEscape(true)
		, _bTakeFocus(true)
		, _InitialFocusIndex(0)
	{
	}
	/** Dim the game behind and close on a click there. */
	SLATE_ARGUMENT(bool, bScrim)
	/** Escape closes (a menu that routes Escape itself leaves this off). */
	SLATE_ARGUMENT(bool, bHandleEscape)
	/** Move the focus into the dialog when it opens, and give it back when it closes. */
	SLATE_ARGUMENT(bool, bTakeFocus)
	/** Which focusable (tree order) gets the focus first. */
	SLATE_ARGUMENT(int32, InitialFocusIndex)
	SLATE_EVENT(FSimpleDelegate, OnClose)
	SLATE_DEFAULT_SLOT(FArguments, Content)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);
	virtual ~SVerseDialogFrame() override;

	virtual FReply OnPreviewKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent) override;
	virtual bool SupportsKeyboardFocus() const override { return false; }

	/** The widgets keyboard and gamepad navigation can reach inside, in tree order. */
	TArray<TSharedRef<SWidget>> CollectFocusables() const;
	/** The navigation a key means, if any. */
	static bool NavigationOfKey(const FKey& Key, bool bShift, EVerseDialogNav& Out);

private:
	EActiveTimerReturnType TakeFocus(double InCurrentTime, float InDeltaTime);
	void CollectFrom(const TSharedRef<SWidget>& Widget, TArray<TSharedRef<SWidget>>& Out) const;

	FSimpleDelegate OnClose;
	bool bHandleEscape = true;
	bool bTakeFocus = true;
	int32 InitialFocusIndex = 0;
	TWeakPtr<SWidget> Opener;
};
