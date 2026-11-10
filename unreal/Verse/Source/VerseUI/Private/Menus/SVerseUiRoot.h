#pragma once

#include "CoreMinimal.h"
#include "Menus/VerseUiMenus.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SCompoundWidget.h"

class SBox;
class UVerseUiSubsystem;
struct FVerseGameSettingDef;

/**
 * Slate root of the Verse menus over the game viewport: the Verse bar (WP18.7) and one screen
 * at a time (Esc menu, settings, armoury, end of set; WP18.6, 18.8, 18.9). Every text is a
 * strings key (A18.4). Sizes are authored at 1080p; the viewport's DPI curve scales them.
 */
class SVerseUiRoot : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SVerseUiRoot) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs, UVerseUiSubsystem* InOwner);

	/** Rebuilds the screen layer for the owner's current screen. */
	void Refresh();

	/** Key rebinding: the next key goes to this action. */
	bool IsListening() const { return !ListeningAction.IsNone(); }
	FName GetListeningAction() const { return ListeningAction; }
	void StopListening() { ListeningAction = NAME_None; }

	/** Settings page index, one per catalogue tab (tests and captures pick a page). */
	void SetSettingsPage(int32 Page);
	int32 GetSettingsPage() const { return SettingsPage; }

	/** The tabs of the game settings catalogue (graphics, audio, controls, keybinds, gameplay, interface, accessibility). */
	static int32 NumSettingsPages();

	/** The value a settings row shows ("High", "On", "85%"). */
	static FText SettingValueText(const UVerseUiSubsystem& Ui, const FVerseGameSettingDef& Def);
	/** One press of a row's previous (-1) or next (+1) button. */
	static void StepSetting(UVerseUiSubsystem& Ui, const FVerseGameSettingDef& Def, int32 Direction);

private:
	TSharedRef<SWidget> BuildScreen();
	TSharedRef<SWidget> BuildBar();
	TSharedRef<SWidget> BuildEscMenu();
	TSharedRef<SWidget> BuildSettings();
	TSharedRef<SWidget> BuildSettingsPage();
	TSharedRef<SWidget> BuildArmoury();
	TSharedRef<SWidget> BuildEndOfSet();
	TSharedRef<SWidget> BuildSessionSummary();
	TSharedRef<SWidget> BuildStatsTable(const struct FVerseEndScreen& Screen);

	TSharedRef<SWidget> Panel(const FString& TitleKey, TSharedRef<SWidget> Body, float Width);
	TSharedRef<SWidget> Button(TAttribute<FText> Label, FSimpleDelegate OnClick, bool bPrimary = false, TAttribute<bool> bSelected = false);
	TSharedRef<SWidget> Stepper(const FString& LabelKey, TAttribute<FText> Value, TFunction<void(int32)> Step);
	TSharedRef<SWidget> Label(TAttribute<FText> Text, float Size, bool bBold, const FLinearColor& Colour);
	FText S(const FString& Key) const;

	TWeakObjectPtr<UVerseUiSubsystem> Owner;
	TSharedPtr<SBox> ScreenSlot;
	TSharedPtr<SBox> BarSlot;
	TSharedPtr<SBox> PageSlot;
	FName ListeningAction;
	int32 SettingsPage = 0;
};
