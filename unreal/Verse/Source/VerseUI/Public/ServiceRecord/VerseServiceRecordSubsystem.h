#pragma once

#include "Containers/Ticker.h"
#include "CoreMinimal.h"
#include "DeckHud/VerseDeckHudModel.h"
#include "Notices/VerseQuietStack.h"
#include "ServiceRecord/VerseServiceRecordModel.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "Templates/Function.h"

#include "VerseServiceRecordSubsystem.generated.h"

class FVerseUiStrings;
class SVerseQuietLines;
class SVersePromotionNotice;
class SWidget;

/**
 * Shows the oldest unseen promotion for a while, then tells the model it was shown (which sends
 * `progression.told`). Show and Hide put the notice on screen; with no screen, or while the
 * Verse is not visible, it waits and nothing is told (parity R-13).
 */
class VERSEUI_API FVersePromotionPresenter
{
public:
	/** How long the full notice of a new rank stays up (parity R-10). */
	static constexpr float NoticeSeconds = 7.0f;
	/** How long a quiet level-up line stays (parity R-11). */
	static constexpr float QuietSeconds = 5.0f;

	/** The time on screen of a promotion: the notice for a new rank, the quiet line otherwise. */
	static float SecondsFor(const FVersePromotion& Promotion) { return Promotion.IsFullNotice() ? NoticeSeconds : QuietSeconds; }

	/**
	 * @param InIsOn  Optional: false when the person closed the notice (Acknowledge, Escape, a
	 *                click on the line) before its time ran out; it then counts as shown at once.
	 */
	FVersePromotionPresenter(TSharedRef<FVerseServiceRecordModel> InModel,
		TFunction<bool(const FVersePromotion&)> InShow, TFunction<void()> InHide, TFunction<bool()> InIsOn = nullptr);

	/** Advance by DeltaSeconds: start the next notice, or end the one on screen. */
	void Tick(float DeltaSeconds);

	bool IsShowing() const { return bShowing; }

private:
	TSharedRef<FVerseServiceRecordModel> Model;
	TFunction<bool(const FVersePromotion&)> Show;
	TFunction<void()> Hide;
	TFunction<bool()> IsOn;
	bool bShowing = false;
	int64 ShowingSeq = 0;
	float Elapsed = 0.f;
	float Duration = NoticeSeconds;
};

/**
 * The service record of the game instance (WP21.7): the model the bridge progression topic
 * feeds, the five-page record dialog, the promotion notice and the quiet level-up lines on the
 * game viewport. The bridge client (WP17) calls HandleBridgeMessage for `progression.snapshot` /
 * `progression.awarded` and gives SetToldSender its `progression.told` sender. Console:
 * `Verse.UI.ServiceRecord` toggles the dialog.
 */
UCLASS()
class VERSEUI_API UVerseServiceRecordSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	TSharedRef<FVerseServiceRecordModel> GetModel() const { return Model.ToSharedRef(); }

	/** One frame of the progression topic; false when the type is not one it reads. */
	bool HandleBridgeMessage(const FString& Type, const FJsonObject& Data);

	void SetToldSender(TFunction<void(int64 Seq)> Sender);

	/** The strings of the moment (the world UI's language); the catalogue in English when unset. */
	void SetStringsProvider(TFunction<const FVerseUiStrings*()> Provider);
	const FVerseUiStrings& Strings() const;
	FVerseStringsGetter StringsGetter() const;

	/**
	 * Whether the Verse is on screen (parity R-13): awards that come in while it is not stay
	 * queued and show on the next time it is. Default: always.
	 */
	void SetOverlayVisible(TFunction<bool()> Visible);
	bool IsOverlayVisible() const { return !OverlayVisible || OverlayVisible(); }

	/** Opens the record on a page; a second call with the dialog open switches the page. */
	void OpenRecord(EVerseRecordTab Tab = EVerseRecordTab::Record);
	EVerseRecordTab GetRecordTab() const { return RecordTab; }
	void CloseRecord();
	void ToggleRecord();
	bool IsRecordOpen() const { return RecordWidget.IsValid(); }

	/** Acknowledge or Escape on the promotion notice. True when a notice was up. */
	bool DismissNotice();
	bool IsNoticeUp() const { return NoticeWidget.IsValid(); }
	const FVerseQuietStack& GetQuietLines() const { return Quiet; }

	/** Drives the notices by hand (tests); the game ticks this on its own unless told not to. */
	void TickNotices(float DeltaSeconds);
	void SetManualTick(bool bManual) { bTickingByHand = bManual; }

	/** Local clock of the notices; tests may pin it. */
	TFunction<double()> Clock;

private:
	bool Tick(float DeltaSeconds);
	bool ShowNotice(const FVersePromotion& Promotion);
	void HideNotice();
	void LayoutQuietLines();
	double Now() const;
	FText QuietText(FName RankId, int32 Level, bool bPromoted, const FString& Who) const;

	TSharedPtr<FVerseServiceRecordModel> Model;
	TUniquePtr<FVersePromotionPresenter> Presenter;
	EVerseRecordTab RecordTab = EVerseRecordTab::Record;
	TSharedPtr<SWidget> RecordWidget;
	TSharedPtr<SWidget> NoticeWidget;
	TSharedPtr<SVerseQuietLines> QuietWidget;
	TSharedPtr<SWidget> QuietHolder;
	FVerseQuietStack Quiet;
	uint32 QuietLaidOut = 0;
	bool bNoticeAcknowledged = false;
	/** The seq of the quiet line standing in for a promotion, or 0. */
	int64 QuietPromotionSeq = 0;
	bool IsPresentationOn() const;
	TFunction<const FVerseUiStrings*()> StringsProvider;
	TFunction<bool()> OverlayVisible;
	FTSTicker::FDelegateHandle TickHandle;
	bool bTickingByHand = false;
};
