#pragma once

#include "Containers/Ticker.h"
#include "CoreMinimal.h"
#include "ServiceRecord/VerseServiceRecordModel.h"
#include "Subsystems/GameInstanceSubsystem.h"

#include "VerseServiceRecordSubsystem.generated.h"

class SWidget;

/**
 * Shows the oldest unseen promotion for a while, then tells the model it was shown (which sends
 * `progression.told`). Show and Hide put the notice on screen; with no screen it waits.
 */
class VERSEUI_API FVersePromotionPresenter
{
public:
	/** How long a notice stays up. */
	static constexpr float NoticeSeconds = 3.0f;

	FVersePromotionPresenter(TSharedRef<FVerseServiceRecordModel> InModel,
		TFunction<bool(const FVersePromotion&)> InShow, TFunction<void()> InHide);

	/** Advance by DeltaSeconds: start the next notice, or end the one on screen. */
	void Tick(float DeltaSeconds);

	bool IsShowing() const { return bShowing; }

private:
	TSharedRef<FVerseServiceRecordModel> Model;
	TFunction<bool(const FVersePromotion&)> Show;
	TFunction<void()> Hide;
	bool bShowing = false;
	int64 ShowingSeq = 0;
	float Elapsed = 0.f;
};

/**
 * The service record of the game instance (WP21.7): the model the bridge's progression topic
 * feeds, the record panel and the promotion notice on the game viewport. The bridge client
 * (WP17) calls HandleBridgeMessage for `progression.snapshot` / `progression.awarded` and gives
 * SetToldSender its `progression.told` sender. Console: `Verse.UI.ServiceRecord` toggles the panel.
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

	void OpenRecord();
	void CloseRecord();
	void ToggleRecord();
	bool IsRecordOpen() const { return RecordWidget.IsValid(); }

private:
	bool Tick(float DeltaSeconds);
	bool ShowNotice(const FVersePromotion& Promotion);
	void HideNotice();

	TSharedPtr<FVerseServiceRecordModel> Model;
	TUniquePtr<FVersePromotionPresenter> Presenter;
	TSharedPtr<SWidget> RecordWidget;
	TSharedPtr<SWidget> NoticeWidget;
	FTSTicker::FDelegateHandle TickHandle;
};
