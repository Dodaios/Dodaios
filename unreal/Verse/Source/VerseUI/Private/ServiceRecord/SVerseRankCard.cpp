#include "ServiceRecord/SVerseRankCard.h"

#include "Core/VerseUiStrings.h"
#include "DeckHud/VerseSlateKit.h"
#include "ServiceRecord/SVerseServiceRecord.h"
#include "ServiceRecord/VerseRankPlate.h"
#include "Widgets/Notifications/SProgressBar.h"

SVerseRankCard::FFacts SVerseRankCard::Describe(const FVerseServiceRecordModel& Model, const FVerseUiStrings& Strings)
{
	FFacts Facts;
	const FVerseCommanderRecord& C = Model.Commander();
	const FVerseRankRow& Rank = FVerseServiceRecordModel::RankFor(C.Level);
	Facts.RankId = Rank.Id;
	Facts.Rank = VerseRankName(Strings, Rank.Id);
	Facts.Level = FText::AsCultureInvariant(Strings.Get(TEXT("verse.ranks.card.level")).ToString() + TEXT(" ") + SVerseServiceRecord::FormatFigure(C.Level));
	if (const FVerseRankRow* Next = FVerseServiceRecordModel::NextRank(C.Level))
	{
		FFormatNamedArguments Args;
		Args.Add(TEXT("xp"), FText::AsCultureInvariant(SVerseServiceRecord::FormatFigure(FMath::Max<int64>(0, FVerseServiceRecordModel::TotalXpForLevel(Next->Level) - C.TotalXp))));
		Args.Add(TEXT("rank"), VerseRankName(Strings, Next->Id));
		Facts.ToGo = Strings.Format(TEXT("verse.ranks.card.to_go"), Args);
	}
	else
	{
		Facts.ToGo = Strings.Get(TEXT("verse.ranks.card.top"));
	}
	Facts.Fraction = C.ForNext > 0 ? float(double(C.IntoLevel) / double(C.ForNext)) : 1.f;
	return Facts;
}

void SVerseRankCard::Construct(const FArguments& InArgs, TSharedPtr<FVerseServiceRecordModel> InModel, FVerseStringsGetter InStrings)
{
	Model = InModel;
	GetStrings = MoveTemp(InStrings);
	OnOpen = InArgs._OnOpen;
	const bool bCompact = InArgs._bCompact;
	auto Facts = [this]() { return Model.IsValid() ? Describe(*Model, GetStrings()) : FFacts(); };
	const float PlateWidth = bCompact ? 40.f : 54.f;

	ChildSlot
	[
		SNew(SButton)
		.ButtonStyle(&VerseSlateKit::ButtonStyle(false))
		.ToolTipText_Lambda([this]() { return GetStrings().Get(TEXT("verse.ranks.card.open")); })
		.OnClicked_Lambda([this]()
		{
			Activate();
			return FReply::Handled();
		})
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 10.f, 0.f)
			[
				SNew(SVerseRankPlate)
				.Width(PlateWidth)
				.Rank_Lambda([Facts]() { return Facts().RankId; })
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Facts]() { return Facts().Rank; }), bCompact ? 13 : 15, true, VerseUiTheme::Gold)
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Facts]() { return Facts().Level; }), 11, false, VerseUiTheme::Text)
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f, 0.f, 0.f)
				[
					SNew(SBox).HeightOverride(3.f)
					[
						SNew(SProgressBar)
						.FillColorAndOpacity(VerseUiTheme::Gold)
						.Percent_Lambda([Facts]() -> TOptional<float> { return Facts().Fraction; })
					]
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 2.f, 0.f, 0.f)
				[
					VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Facts]() { return Facts().ToGo; }), 10, false, VerseUiTheme::TextDim)
				]
			]
		]
	];
}
