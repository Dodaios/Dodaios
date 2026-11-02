#pragma once

#include "CoreMinimal.h"
#include "ServiceRecord/VerseServiceRecordModel.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SCompoundWidget.h"

/** The words of a rank id (`verse.ranks.rank.<id>` on the web). */
VERSEUI_API FText VerseRankName(FName RankId);

/**
 * The service record panel: the commander's rank, level and XP, the next rank, and the duel
 * record (sets, won / lost, K/D, headshots, finishers, best streak). Reads the model live.
 */
class VERSEUI_API SVerseServiceRecord : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SVerseServiceRecord) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs, TSharedRef<FVerseServiceRecordModel> InModel);

	/** The texts the panel shows, keyed by fact (`rank`, `level`, `xp`, `next`, `sets`, ...). */
	static TMap<FString, FText> DescribeFacts(const FVerseServiceRecordModel& RecordModel);

private:
	TSharedPtr<FVerseServiceRecordModel> Model;
};

/** The promotion notice: the new rank (or level) of the oldest promotion not shown yet. */
class VERSEUI_API SVersePromotionNotice : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SVersePromotionNotice) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs, const FVersePromotion& InPromotion);

	FText Headline() const;
	FText Detail() const;

private:
	FVersePromotion Promotion;
};
