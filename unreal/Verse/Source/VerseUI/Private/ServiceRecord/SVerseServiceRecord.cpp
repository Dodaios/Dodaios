#include "ServiceRecord/SVerseServiceRecord.h"

#include "Styling/CoreStyle.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SUniformGridPanel.h"
#include "Widgets/Notifications/SProgressBar.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/Text/STextBlock.h"

#define LOCTEXT_NAMESPACE "VerseServiceRecord"

namespace
{
	const FLinearColor ColPanel(0.018f, 0.018f, 0.022f, 0.94f);
	const FLinearColor ColRaised(0.045f, 0.045f, 0.052f, 1.f);
	const FLinearColor ColText(0.92f, 0.91f, 0.88f, 1.f);
	const FLinearColor ColMuted(0.55f, 0.54f, 0.52f, 1.f);
	const FLinearColor ColGold(0.86f, 0.66f, 0.30f, 1.f);

	FSlateFontInfo RecordFont(int32 Size, bool bBold = false)
	{
		return FCoreStyle::GetDefaultFontStyle(bBold ? "Bold" : "Regular", Size);
	}

	FText Figure(int64 Value)
	{
		return FText::AsNumber(Value);
	}

	FText TierName(FName Tier)
	{
		if (Tier == TEXT("deck")) return LOCTEXT("tier.deck", "Deck ratings");
		if (Tier == TEXT("line")) return LOCTEXT("tier.line", "Line officers");
		if (Tier == TEXT("command")) return LOCTEXT("tier.command", "Command");
		return LOCTEXT("tier.flag", "Flag officers");
	}

	TSharedRef<SWidget> MakeFact(const FText& Caption, const TAttribute<FText>& Value)
	{
		return SNew(SBorder)
			.BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush"))
			.BorderBackgroundColor(ColRaised)
			.Padding(FMargin(10.f, 8.f))
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock).Text(Caption).Font(RecordFont(8)).ColorAndOpacity(ColMuted)
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock).Text(Value).Font(RecordFont(14)).ColorAndOpacity(ColText)
				]
			];
	}
}

FText VerseRankName(FName RankId)
{
	static const TMap<FName, FText> Names = {
		{FName(TEXT("recruit")), LOCTEXT("rank.recruit", "Recruit")},
		{FName(TEXT("deckhand")), LOCTEXT("rank.deckhand", "Deckhand")},
		{FName(TEXT("technician")), LOCTEXT("rank.technician", "Technician")},
		{FName(TEXT("senior_technician")), LOCTEXT("rank.senior_technician", "Senior Technician")},
		{FName(TEXT("ensign")), LOCTEXT("rank.ensign", "Ensign")},
		{FName(TEXT("lieutenant")), LOCTEXT("rank.lieutenant", "Lieutenant")},
		{FName(TEXT("senior_lieutenant")), LOCTEXT("rank.senior_lieutenant", "Senior Lieutenant")},
		{FName(TEXT("commander")), LOCTEXT("rank.commander", "Commander")},
		{FName(TEXT("captain")), LOCTEXT("rank.captain", "Captain")},
		{FName(TEXT("line_captain")), LOCTEXT("rank.line_captain", "Line Captain")},
		{FName(TEXT("commodore")), LOCTEXT("rank.commodore", "Commodore")},
		{FName(TEXT("rear_admiral")), LOCTEXT("rank.rear_admiral", "Rear Admiral")},
		{FName(TEXT("vice_admiral")), LOCTEXT("rank.vice_admiral", "Vice Admiral")},
		{FName(TEXT("admiral")), LOCTEXT("rank.admiral", "Admiral")},
		{FName(TEXT("fleet_admiral")), LOCTEXT("rank.fleet_admiral", "Fleet Admiral")},
	};
	const FText* Found = Names.Find(RankId);
	return Found ? *Found : FText::FromName(RankId);
}

void SVerseServiceRecord::Construct(const FArguments& InArgs, TSharedRef<FVerseServiceRecordModel> InModel)
{
	Model = InModel;
	TWeakPtr<FVerseServiceRecordModel> Weak = InModel;
	auto Live = [this](const FString Key)
	{
		return TAttribute<FText>::CreateLambda([this, Key]()
		{
			const FText* Value = Model.IsValid() ? DescribeFacts(*Model).Find(Key) : nullptr;
			return Value ? *Value : FText::GetEmpty();
		});
	};

	ChildSlot
	[
		SNew(SBox)
		.WidthOverride(560.f)
		[
			SNew(SBorder)
			.BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush"))
			.BorderBackgroundColor(ColPanel)
			.Padding(FMargin(20.f))
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 12.f)
				[
					SNew(STextBlock).Text(LOCTEXT("title", "SERVICE RECORD")).Font(RecordFont(10, true)).ColorAndOpacity(ColGold)
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock).Text(Live(TEXT("tier"))).Font(RecordFont(8)).ColorAndOpacity(ColMuted)
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 2.f, 0.f, 12.f)
				[
					SNew(STextBlock).Text(Live(TEXT("rank"))).Font(RecordFont(22, true)).ColorAndOpacity(ColText)
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(SUniformGridPanel).SlotPadding(FMargin(1.f))
					+ SUniformGridPanel::Slot(0, 0)[MakeFact(LOCTEXT("level", "LEVEL"), Live(TEXT("level")))]
					+ SUniformGridPanel::Slot(1, 0)[MakeFact(LOCTEXT("total_xp", "TOTAL XP"), Live(TEXT("total_xp")))]
					+ SUniformGridPanel::Slot(2, 0)[MakeFact(LOCTEXT("this_level", "THIS LEVEL"), Live(TEXT("xp")))]
					+ SUniformGridPanel::Slot(3, 0)[MakeFact(LOCTEXT("next_rank", "NEXT RANK"), Live(TEXT("next")))]
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 6.f, 0.f, 16.f)
				[
					SNew(SBox).HeightOverride(4.f)
					[
						SNew(SProgressBar)
						.FillColorAndOpacity(ColGold)
						.Percent_Lambda([Weak]() -> TOptional<float>
						{
							const TSharedPtr<FVerseServiceRecordModel> M = Weak.Pin();
							if (!M.IsValid() || M->Commander().ForNext <= 0)
							{
								return 1.f;
							}
							return float(double(M->Commander().IntoLevel) / double(M->Commander().ForNext));
						})
					]
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 6.f)
				[
					SNew(STextBlock).Text(LOCTEXT("duels", "DUELS")).Font(RecordFont(8, true)).ColorAndOpacity(ColMuted)
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(SUniformGridPanel).SlotPadding(FMargin(1.f))
					+ SUniformGridPanel::Slot(0, 0)[MakeFact(LOCTEXT("sets", "SETS"), Live(TEXT("sets")))]
					+ SUniformGridPanel::Slot(1, 0)[MakeFact(LOCTEXT("won_lost", "WON / LOST"), Live(TEXT("won_lost")))]
					+ SUniformGridPanel::Slot(2, 0)[MakeFact(LOCTEXT("kd", "K/D"), Live(TEXT("kd")))]
					+ SUniformGridPanel::Slot(0, 1)[MakeFact(LOCTEXT("headshots", "HEADSHOTS"), Live(TEXT("headshots")))]
					+ SUniformGridPanel::Slot(1, 1)[MakeFact(LOCTEXT("finishers", "FINISHERS"), Live(TEXT("finishers")))]
					+ SUniformGridPanel::Slot(2, 1)[MakeFact(LOCTEXT("best_streak", "BEST STREAK"), Live(TEXT("best_streak")))]
				]
			]
		]
	];
}

TMap<FString, FText> SVerseServiceRecord::DescribeFacts(const FVerseServiceRecordModel& RecordModel)
{
	TMap<FString, FText> Facts;
	const FVerseCommanderRecord& C = RecordModel.Commander();
	const FVerseRankRow& Rank = FVerseServiceRecordModel::RankFor(C.Level);
	const FVerseRankRow* Next = FVerseServiceRecordModel::NextRank(C.Level);
	Facts.Add(TEXT("rank"), VerseRankName(Rank.Id));
	Facts.Add(TEXT("tier"), TierName(Rank.Tier));
	Facts.Add(TEXT("level"), Figure(C.Level));
	Facts.Add(TEXT("total_xp"), Figure(C.TotalXp));
	Facts.Add(TEXT("xp"), C.ForNext > 0
		? FText::Format(LOCTEXT("xp_of", "{0} / {1}"), Figure(C.IntoLevel), Figure(C.ForNext))
		: LOCTEXT("at_cap", "-"));
	Facts.Add(TEXT("next"), Next ? VerseRankName(Next->Id) : LOCTEXT("top_rank", "Highest rank"));

	const FVerseDuelTotals& D = RecordModel.Duels();
	Facts.Add(TEXT("sets"), Figure(D.Matches));
	Facts.Add(TEXT("won_lost"), FText::Format(LOCTEXT("won_lost_value", "{0} / {1}"), Figure(D.Wins), Figure(D.Losses)));
	FNumberFormattingOptions TwoDecimals;
	TwoDecimals.SetMinimumFractionalDigits(2).SetMaximumFractionalDigits(2);
	Facts.Add(TEXT("kd"), FText::AsNumber(D.KillDeathRatio(), &TwoDecimals));
	Facts.Add(TEXT("headshots"), Figure(D.Headshots));
	Facts.Add(TEXT("finishers"), Figure(D.Finishers));
	Facts.Add(TEXT("best_streak"), Figure(D.BestStreak));
	return Facts;
}

void SVersePromotionNotice::Construct(const FArguments& InArgs, const FVersePromotion& InPromotion)
{
	Promotion = InPromotion;
	ChildSlot
	[
		SNew(SBorder)
		.BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush"))
		.BorderBackgroundColor(ColPanel)
		.Padding(FMargin(24.f, 14.f))
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()
			[
				SNew(STextBlock).Text(Headline()).Font(RecordFont(9, true)).ColorAndOpacity(ColGold)
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 4.f, 0.f, 0.f)
			[
				SNew(STextBlock).Text(Detail()).Font(RecordFont(18, true)).ColorAndOpacity(ColText)
			]
		]
	];
}

FText SVersePromotionNotice::Headline() const
{
	return Promotion.IsNewRank() ? LOCTEXT("promoted", "PROMOTED") : LOCTEXT("level_up", "LEVEL UP");
}

FText SVersePromotionNotice::Detail() const
{
	return Promotion.IsNewRank()
		? FText::Format(LOCTEXT("promoted_detail", "{0}, level {1}"), VerseRankName(Promotion.RankId), FText::AsNumber(Promotion.Level))
		: FText::Format(LOCTEXT("level_detail", "Level {0}"), FText::AsNumber(Promotion.Level));
}

#undef LOCTEXT_NAMESPACE
