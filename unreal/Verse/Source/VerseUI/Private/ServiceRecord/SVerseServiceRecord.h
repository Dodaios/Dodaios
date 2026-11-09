#pragma once

#include "CoreMinimal.h"
#include "DeckHud/VerseDeckHudModel.h"
#include "Notices/VerseQuietStack.h"
#include "ServiceRecord/VerseServiceRecordModel.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SCompoundWidget.h"

class SBox;

/** The words of a rank id (`verse.ranks.rank.<id>` on the web). */
VERSEUI_API FText VerseRankName(FName RankId);
/** The same words from the strings catalogue, in the language of the Verse UI. */
VERSEUI_API FText VerseRankName(const class FVerseUiStrings& Strings, FName RankId);

/**
 * The service record (parity R-04 to R-09): a dialog with five pages, Record, Ladder,
 * Quartermaster, How to earn and Crew. It reads the model live and rebuilds the open page when
 * the model changes. Escape, the scrim and the close button end it through OnClose.
 */
class VERSEUI_API SVerseServiceRecord : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SVerseServiceRecord) {}
	SLATE_EVENT(FSimpleDelegate, OnClose)
	SLATE_END_ARGS()

	/** Strings default to the catalogue in English; the subsystem passes the language of the Verse UI. */
	void Construct(const FArguments& InArgs, TSharedRef<FVerseServiceRecordModel> InModel, FVerseStringsGetter InStrings = nullptr, EVerseRecordTab InTab = EVerseRecordTab::Record);
	virtual ~SVerseServiceRecord() override;

	/** Opens a page (openRecord(tab)). */
	void SetTab(EVerseRecordTab Tab);
	EVerseRecordTab GetTab() const { return CurrentTab; }

	/** The texts the panel shows, keyed by fact (`rank`, `level`, `xp`, `next`, `sets`, ...). */
	static TMap<FString, FText> DescribeFacts(const FVerseServiceRecordModel& RecordModel);
	/** A whole number as both records print it: thousands grouped with a space ("12 340"). */
	static FString FormatFigure(int64 Value);
	/** A ratio as both records print it: two decimals with a point ("1.19"), in every culture. */
	static FString FormatRatio(float Value);

private:
	const class FVerseUiStrings& Strings() const;
	void Rebuild();
	TSharedRef<SWidget> BuildTabs();
	TSharedRef<SWidget> BuildRecordPage();
	TSharedRef<SWidget> BuildLadderPage();
	TSharedRef<SWidget> BuildRewardsPage();
	TSharedRef<SWidget> BuildEarnPage();
	TSharedRef<SWidget> BuildCrewPage();

	TSharedPtr<FVerseServiceRecordModel> Model;
	FVerseStringsGetter GetStrings;
	FSimpleDelegate OnClose;
	EVerseRecordTab CurrentTab = EVerseRecordTab::Record;
	TSharedPtr<SBox> TabsSlot;
	TSharedPtr<SBox> PageSlot;
	FDelegateHandle ChangedHandle;
};

/**
 * The promotion notice (parity R-10): the new plate with its tiles laid on one by one, the
 * rank, the level, one line of salute and what the quartermaster issued. It never takes the
 * input focus; Acknowledge, Escape or seven seconds close it.
 */
class VERSEUI_API SVersePromotionNotice : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SVersePromotionNotice)
		: _bReducedMotion(false)
	{
	}
	SLATE_ARGUMENT(bool, bReducedMotion)
	SLATE_EVENT(FSimpleDelegate, OnAcknowledge)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs, const FVersePromotion& InPromotion, FVerseStringsGetter InStrings = nullptr);

	/** "Promotion" for the commander, "Companion drone promoted" for the drone. */
	FText Headline() const;
	/** The rank and level: "Commander", "Level 21 . Line officers". */
	FText Detail() const;

	/** Pins the clock the tile animation reads (tests). */
	TFunction<double()> Clock;
	/** Tiles shown at the moment (a lit tile counts once laid on). */
	int32 RevealedTiles() const;
	/** The tiles laid on after Elapsed seconds; all of them with reduced motion. */
	static int32 TilesAt(double Elapsed, int32 NumLit, bool bReducedMotion);
	static constexpr double TileStepSeconds = 0.14;

	/** The notice never takes focus: no focusable child, no focus on itself. */
	virtual bool SupportsKeyboardFocus() const override { return false; }
	TArray<FString> IssuedNames() const;

private:
	const class FVerseUiStrings& Strings() const;
	double NowSeconds() const;

	FVersePromotion Promotion;
	FVerseStringsGetter GetStrings;
	bool bReduced = false;
	double CreatedAt = 0.0;
};

/** The quiet corner lines (parity R-11): up to three, five seconds or a click. */
class VERSEUI_API SVerseQuietLines : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SVerseQuietLines) {}
	SLATE_EVENT(FOnVerseQuietDismiss, OnDismiss)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);
	/** Lays out the stack's lines (call when they change). */
	void Show(const TArray<FVerseQuietEntry>& Entries);

private:
	FOnVerseQuietDismiss OnDismiss;
	TSharedPtr<SBox> LinesBox;
};
