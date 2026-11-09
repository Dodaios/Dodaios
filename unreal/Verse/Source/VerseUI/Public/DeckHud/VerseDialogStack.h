#pragma once

#include "CoreMinimal.h"

enum class EVerseDialogNav : uint8
{
	Next,
	Previous,
	Up,
	Down,
	Left,
	Right,
};

/**
 * The dialogs on screen, newest on top (parity H-12, H-13). While one is open it is modal:
 * keyboard and gamepad navigation stay inside it, Escape or a click on the scrim closes it,
 * the focus goes back to the widget that opened it, the mouse cursor is shown and mouse look
 * stops. Widgets are named by FName; the Slate frame maps the names to widgets.
 */
class VERSEUI_API FVerseDialogStack
{
public:
	struct FDialog
	{
		FName Id;
		/** The widget that had the focus when the dialog opened; gets it back on close. */
		FName Opener;
		/** Focusable widgets inside, in navigation order. */
		TArray<FName> Focusables;
		FName Focused;
	};

	/** Opens a dialog; focus moves to InitialFocus (the first focusable when empty). */
	void Open(FName Id, FName Opener, const TArray<FName>& Focusables, FName InitialFocus = NAME_None);
	/** Closes the dialog and everything above it; returns the widget that gets the focus back. */
	FName Close(FName Id);
	/** Escape: closes the top dialog. True when one was open (the key is used). */
	bool HandleEscape(FName* OutFocusReturn = nullptr);
	/** A click on the scrim behind the top dialog. */
	bool HandleScrimClick(FName* OutFocusReturn = nullptr);
	/** Moves the focus inside the top dialog, wrapping at the ends. False with no dialog open. */
	bool HandleNavigate(EVerseDialogNav Direction);
	/** Focus follows a click or hover inside the dialog. */
	void SetFocused(FName Widget);

	bool IsModal() const { return Stack.Num() > 0; }
	int32 Num() const { return Stack.Num(); }
	const FDialog* Top() const { return Stack.Num() > 0 ? &Stack.Last() : nullptr; }
	/** The widget that has the focus now: inside the top dialog, or the one restored after the last close. */
	FName GetFocused() const;
	bool IsOpen(FName Id) const;

	/** Whether the cursor is shown (any dialog open). */
	bool ShouldShowCursor() const { return IsModal(); }
	/** Whether mouse look and the camera input stop (any dialog open). */
	bool BlocksLookInput() const { return IsModal(); }
	/** True when Widget lies outside the top dialog, so input to it must be ignored. */
	bool IsBlocked(FName Widget) const;

	/** The index after a navigation step inside a ring of Count focusables, wrapping at both ends. */
	static int32 StepIndex(int32 Index, int32 Count, EVerseDialogNav Direction);

	/** Where the focus sits when no dialog is open (set by the stage). */
	void SetBaseFocus(FName Widget) { BaseFocus = Widget; }

private:
	FName PopTop();

	TArray<FDialog> Stack;
	FName BaseFocus;
};
