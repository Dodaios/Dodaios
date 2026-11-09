#pragma once

#include "CoreMinimal.h"
#include "DeckHud/VerseDeckHudModel.h"
#include "ServiceRecord/VerseServiceRecordModel.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SCompoundWidget.h"

/**
 * The rank card (parity H-02): the commander's plate, rank, level and the XP to the next rank.
 * Beside the deck title in full size; the compact variant sits in a panel. A click opens the
 * service record on its Record page.
 */
class SVerseRankCard : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SVerseRankCard)
		: _bCompact(false)
	{
	}
	SLATE_ARGUMENT(bool, bCompact)
	SLATE_EVENT(FSimpleDelegate, OnOpen)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs, TSharedPtr<FVerseServiceRecordModel> InModel, FVerseStringsGetter InStrings);

	/** What a click does: opens the service record on its Record page. */
	void Activate() const { OnOpen.ExecuteIfBound(); }

	/** The lines the card prints: rank, level, to-go text. Tests read these. */
	struct FFacts
	{
		FName RankId;
		FText Rank;
		FText Level;
		FText ToGo;
		float Fraction = 0.f;
	};
	static FFacts Describe(const FVerseServiceRecordModel& Model, const FVerseUiStrings& Strings);

private:
	TSharedPtr<FVerseServiceRecordModel> Model;
	FVerseStringsGetter GetStrings;
	FSimpleDelegate OnOpen;
};
