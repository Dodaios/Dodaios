#include "ServiceRecord/SVerseServiceRecord.h"

#include "Core/VerseUiStrings.h"
#include "DeckHud/SVerseDialogFrame.h"
#include "DeckHud/VerseSlateKit.h"
#include "ServiceRecord/VerseRankPlate.h"
#include "ServiceRecord/VerseRecordPages.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SUniformGridPanel.h"
#include "Widgets/Notifications/SProgressBar.h"

#define LOCTEXT_NAMESPACE "VerseServiceRecord"

namespace
{
	const FLinearColor ColText = VerseUiTheme::Text;
	const FLinearColor ColMuted = VerseUiTheme::TextDim;
	const FLinearColor ColGold = VerseUiTheme::Gold;
	const FLinearColor ColRaised(0.045f, 0.045f, 0.052f, 1.f);

	using FPages = FVerseRecordPages;

	// The record's figures are culture-invariant, like the web record: thousands grouped with a
	// space, no decimals. Both records show the same characters.
	FText Figure(int64 Value)
	{
		return FText::AsCultureInvariant(SVerseServiceRecord::FormatFigure(Value));
	}

	FText TierName(FName Tier)
	{
		if (Tier == TEXT("deck")) return LOCTEXT("tier.deck", "Deck ratings");
		if (Tier == TEXT("line")) return LOCTEXT("tier.line", "Line officers");
		if (Tier == TEXT("command")) return LOCTEXT("tier.command", "Command");
		return LOCTEXT("tier.flag", "Flag officers");
	}

	/** The catalogue in English, for a record built with no strings getter. */
	const FVerseUiStrings& FallbackStrings()
	{
		static const FVerseUiStrings Loaded = []
		{
			FVerseUiStrings Strings;
			Strings.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir());
			return Strings;
		}();
		return Loaded;
	}

	TSharedRef<SWidget> Caps(const FText& Value, const FLinearColor& Tint = ColMuted)
	{
		return VerseSlateKit::Text(Value, 10, true, Tint);
	}

	TSharedRef<SWidget> Hint(const FText& Value)
	{
		return SNew(STextBlock).Text(Value).Font(VerseSlateKit::Font(11)).ColorAndOpacity(FSlateColor(ColMuted)).AutoWrapText(true);
	}

	TSharedRef<SWidget> Fact(const FText& Caption, const FText& Value, const FText& Note = FText::GetEmpty())
	{
		TSharedRef<SVerticalBox> Box = SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()[Caps(Caption)]
			+ SVerticalBox::Slot().AutoHeight()[VerseSlateKit::Text(Value, 15, true, ColText)];
		if (!Note.IsEmpty())
		{
			Box->AddSlot().AutoHeight()[Caps(Note)];
		}
		return SNew(SBorder).BorderImage(VerseSlateKit::Colour(ColRaised)).Padding(FMargin(10.f, 8.f))[Box];
	}

	TSharedRef<SWidget> Section(const FText& Title, TSharedRef<SWidget> Body)
	{
		return SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 14.f, 0.f, 6.f)[Caps(Title)]
			+ SVerticalBox::Slot().AutoHeight()[Body];
	}

	TSharedRef<SWidget> Row(TSharedRef<SWidget> Left, TSharedRef<SWidget> Middle, TSharedRef<SWidget> Right)
	{
		return SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)[Left]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(12.f, 0.f)[Middle]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[Right];
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

FText VerseRankName(const FVerseUiStrings& Strings, FName RankId)
{
	return Strings.Get(FString::Printf(TEXT("verse.ranks.rank.%s"), *RankId.ToString()));
}

// ------------------------------------------------------------------ the record

const FVerseUiStrings& SVerseServiceRecord::Strings() const
{
	return GetStrings ? GetStrings() : FallbackStrings();
}

void SVerseServiceRecord::Construct(const FArguments& InArgs, TSharedRef<FVerseServiceRecordModel> InModel, FVerseStringsGetter InStrings, EVerseRecordTab InTab)
{
	Model = InModel;
	GetStrings = MoveTemp(InStrings);
	OnClose = InArgs._OnClose;
	CurrentTab = InTab;
	TWeakPtr<SVerseServiceRecord> Weak = SharedThis(this);

	ChildSlot
	[
		SNew(SVerseDialogFrame)
		.OnClose_Lambda([Weak]()
		{
			if (const TSharedPtr<SVerseServiceRecord> Self = Weak.Pin())
			{
				Self->OnClose.ExecuteIfBound();
			}
		})
		[
			SNew(SBox)
			.WidthOverride(780.f)
			.MaxDesiredHeight(760.f)
			[
				SNew(SBorder)
				.BorderImage(VerseSlateKit::Colour(VerseUiTheme::Steel))
				.Padding(FMargin(22.f, 18.f))
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(SHorizontalBox)
						+ SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
						[
							VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Weak]() { const TSharedPtr<SVerseServiceRecord> S = Weak.Pin(); return S.IsValid() ? S->Strings().Get(TEXT("verse.ranks.record.title")) : FText::GetEmpty(); }), 22, true, ColText)
						]
						+ SHorizontalBox::Slot().AutoWidth()
						[
							SNew(SButton)
							.ButtonStyle(&VerseSlateKit::ButtonStyle(false))
							.OnClicked_Lambda([Weak]()
							{
								if (const TSharedPtr<SVerseServiceRecord> S = Weak.Pin())
								{
									S->OnClose.ExecuteIfBound();
								}
								return FReply::Handled();
							})
							[
								VerseSlateKit::Text(TAttribute<FText>::CreateLambda([Weak]() { const TSharedPtr<SVerseServiceRecord> S = Weak.Pin(); return S.IsValid() ? S->Strings().Get(TEXT("verse.ranks.record.close")) : FText::GetEmpty(); }), 12, true, ColText)
							]
						]
					]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 12.f, 0.f, 8.f)
					[
						SAssignNew(TabsSlot, SBox)
					]
					+ SVerticalBox::Slot().FillHeight(1.f)
					[
						SNew(SScrollBox)
						+ SScrollBox::Slot()
						[
							SAssignNew(PageSlot, SBox)
						]
					]
				]
			]
		]
	];
	ChangedHandle = Model->OnChanged.AddSP(this, &SVerseServiceRecord::Rebuild);
	Rebuild();
}

SVerseServiceRecord::~SVerseServiceRecord()
{
	if (Model.IsValid())
	{
		Model->OnChanged.Remove(ChangedHandle);
	}
}

void SVerseServiceRecord::SetTab(EVerseRecordTab Tab)
{
	CurrentTab = Tab;
	Rebuild();
}

void SVerseServiceRecord::Rebuild()
{
	if (!TabsSlot.IsValid() || !PageSlot.IsValid())
	{
		return;
	}
	TabsSlot->SetContent(BuildTabs());
	switch (CurrentTab)
	{
	case EVerseRecordTab::Ladder: PageSlot->SetContent(BuildLadderPage()); break;
	case EVerseRecordTab::Rewards: PageSlot->SetContent(BuildRewardsPage()); break;
	case EVerseRecordTab::Earn: PageSlot->SetContent(BuildEarnPage()); break;
	case EVerseRecordTab::Crew: PageSlot->SetContent(BuildCrewPage()); break;
	default: PageSlot->SetContent(BuildRecordPage()); break;
	}
}

TSharedRef<SWidget> SVerseServiceRecord::BuildTabs()
{
	TSharedRef<SHorizontalBox> Tabs = SNew(SHorizontalBox);
	TWeakPtr<SVerseServiceRecord> Weak = SharedThis(this);
	for (const FPages::FTab& Tab : FPages::Tabs())
	{
		const EVerseRecordTab Which = Tab.Tab;
		Tabs->AddSlot().FillWidth(1.f).Padding(2.f, 0.f)
		[
			SNew(SButton)
			.ButtonStyle(&VerseSlateKit::ButtonStyle(Tab.Tab == CurrentTab))
			.HAlign(HAlign_Center)
			.OnClicked_Lambda([Weak, Which]()
			{
				if (const TSharedPtr<SVerseServiceRecord> S = Weak.Pin())
				{
					S->SetTab(Which);
				}
				return FReply::Handled();
			})
			[
				VerseSlateKit::Text(Strings().Get(Tab.LabelKey), 12, true, Tab.Tab == CurrentTab ? ColGold : ColText)
			]
		];
	}
	return Tabs;
}

TSharedRef<SWidget> SVerseServiceRecord::BuildRecordPage()
{
	const FPages::FRecordPage Page = FPages::Record(*Model, Strings());
	const FVerseUiStrings& S = Strings();
	TSharedRef<SVerticalBox> Body = SNew(SVerticalBox);
	Body->AddSlot().AutoHeight()
	[
		SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 14.f, 0.f)
		[
			SNew(SVerseRankPlate).Rank(Page.RankId).Width(72.f)
		]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()[Caps(FText::AsCultureInvariant(S.Get(TEXT("verse.ranks.record.rank")).ToString() + TEXT(" · ") + Page.Tier.ToString()))]
			+ SVerticalBox::Slot().AutoHeight()[VerseSlateKit::Text(Page.Rank, 24, true, ColText)]
		]
	];
	Body->AddSlot().AutoHeight().Padding(0.f, 12.f, 0.f, 0.f)
	[
		SNew(SUniformGridPanel).SlotPadding(FMargin(2.f))
		+ SUniformGridPanel::Slot(0, 0)[Fact(S.Get(TEXT("verse.ranks.record.level")), Page.Level)]
		+ SUniformGridPanel::Slot(1, 0)[Fact(S.Get(TEXT("verse.ranks.record.total_xp")), Page.TotalXp)]
		+ SUniformGridPanel::Slot(2, 0)[Fact(S.Get(TEXT("verse.ranks.record.this_level")), Page.ThisLevel)]
		+ SUniformGridPanel::Slot(3, 0)[Fact(S.Get(TEXT("verse.ranks.record.next_rank")), Page.NextRankXp.IsEmpty() ? FText::AsCultureInvariant(TEXT("-")) : Page.NextRankXp, Page.NextRank)]
	];
	Body->AddSlot().AutoHeight().Padding(0.f, 8.f, 0.f, 0.f)
	[
		SNew(SBox).HeightOverride(4.f)
		[
			SNew(SProgressBar).FillColorAndOpacity(ColGold).Percent(Page.Fraction)
		]
	];

	// Duels
	TSharedRef<SVerticalBox> Duels = SNew(SVerticalBox);
	if (!Page.bHasDuels)
	{
		Duels->AddSlot().AutoHeight()[Hint(S.Get(TEXT("verse.ranks.record.duel.empty")))];
	}
	else
	{
		Duels->AddSlot().AutoHeight()
		[
			SNew(SUniformGridPanel).SlotPadding(FMargin(2.f))
			+ SUniformGridPanel::Slot(0, 0)[Fact(S.Get(TEXT("verse.ranks.record.duel.sets")), Page.Sets)]
			+ SUniformGridPanel::Slot(1, 0)[Fact(S.Get(TEXT("verse.ranks.record.duel.record")), Page.WonLost, Page.Unfinished)]
			+ SUniformGridPanel::Slot(2, 0)[Fact(S.Get(TEXT("verse.ranks.record.duel.kd")), Page.KillDeath)]
			+ SUniformGridPanel::Slot(0, 1)[Fact(S.Get(TEXT("verse.ranks.record.duel.headshots")), Page.Headshots)]
			+ SUniformGridPanel::Slot(1, 1)[Fact(S.Get(TEXT("verse.ranks.record.duel.finishers")), Page.Finishers)]
			+ SUniformGridPanel::Slot(2, 1)[Fact(S.Get(TEXT("verse.ranks.record.duel.best_streak")), Page.BestStreak)]
		];
	}
	Body->AddSlot().AutoHeight()[Section(S.Get(TEXT("verse.ranks.record.duel.title")), Duels)];

	// Ribbons
	TSharedRef<SHorizontalBox> Ribbons = SNew(SHorizontalBox);
	if (Page.Ribbons.Num() == 0)
	{
		Ribbons->AddSlot().AutoWidth()[Hint(Page.NoRibbons)];
	}
	for (const FText& Ribbon : Page.Ribbons)
	{
		Ribbons->AddSlot().AutoWidth().Padding(0.f, 0.f, 10.f, 0.f)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 5.f, 0.f)
			[
				SNew(SBox).WidthOverride(22.f).HeightOverride(10.f)[SNew(SBorder).BorderImage(VerseSlateKit::Colour(ColGold))]
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[VerseSlateKit::Text(Ribbon, 11, false, ColText)]
		];
	}
	Body->AddSlot().AutoHeight()[Section(S.Get(TEXT("verse.ranks.record.ribbons")), Ribbons)];

	// Log
	TSharedRef<SVerticalBox> Log = SNew(SVerticalBox);
	if (Page.Log.Num() == 0)
	{
		Log->AddSlot().AutoHeight()[Hint(Page.NoLog)];
	}
	for (const FPages::FLogRow& Entry : Page.Log)
	{
		Log->AddSlot().AutoHeight().Padding(0.f, 2.f)
		[
			Row(VerseSlateKit::Text(Entry.Source, 12, false, ColText), VerseSlateKit::Text(Entry.When, 11, false, ColMuted), VerseSlateKit::Text(Entry.Xp, 12, true, ColGold))
		];
	}
	Body->AddSlot().AutoHeight()[Section(S.Get(TEXT("verse.ranks.record.log")), Log)];

	// The bell
	TWeakPtr<FVerseServiceRecordModel> WeakModel = Model;
	Body->AddSlot().AutoHeight().Padding(0.f, 14.f, 0.f, 0.f)
	[
		SNew(SCheckBox)
		.IsChecked_Lambda([WeakModel]() { const TSharedPtr<FVerseServiceRecordModel> M = WeakModel.Pin(); return M.IsValid() && M->IsBellOn() ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
		.OnCheckStateChanged_Lambda([WeakModel](ECheckBoxState State)
		{
			if (const TSharedPtr<FVerseServiceRecordModel> M = WeakModel.Pin())
			{
				M->SetBellOn(State == ECheckBoxState::Checked);
			}
		})
		[
			VerseSlateKit::Text(S.Get(TEXT("verse.ranks.record.sound")), 12, false, ColText)
		]
	];
	return Body;
}

TSharedRef<SWidget> SVerseServiceRecord::BuildLadderPage()
{
	TSharedRef<SVerticalBox> Body = SNew(SVerticalBox);
	for (const FPages::FTierBlock& Block : FPages::Ladder(*Model, Strings()))
	{
		TSharedRef<SVerticalBox> Steps = SNew(SVerticalBox);
		for (const FPages::FStep& Step : Block.Steps)
		{
			const bool bAhead = Step.State == FPages::EStepState::Ahead;
			const bool bCurrent = Step.State == FPages::EStepState::Current;
			// Held plain, the current rank marked in red (a bar as well as a colour), the ones ahead dimmed.
			const FLinearColor Tint = bCurrent ? VerseUiTheme::Red : (bAhead ? ColMuted * FLinearColor(1.f, 1.f, 1.f, 0.7f) : ColText);
			Steps->AddSlot().AutoHeight().Padding(0.f, 2.f)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().Padding(0.f, 0.f, 8.f, 0.f)
				[
					SNew(SBox).WidthOverride(3.f)[SNew(SBorder).BorderImage(VerseSlateKit::Colour(bCurrent ? VerseUiTheme::Red : FLinearColor(0.f, 0.f, 0.f, 0.f)))]
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 10.f, 0.f)
				[
					SNew(SVerseRankPlate).Rank(Step.RankId).Width(30.f)
				]
				+ SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth()[VerseSlateKit::Text(Step.Name, 13, bCurrent, Tint)]
					+ SHorizontalBox::Slot().AutoWidth().Padding(10.f, 0.f, 0.f, 0.f)[Caps(Step.StateText)]
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[VerseSlateKit::Text(Step.Right, 12, false, Tint)]
			];
		}
		Body->AddSlot().AutoHeight()
		[
			Section(FText::AsCultureInvariant(Block.Name.ToString() + TEXT("  ·  ") + Block.FromLevel.ToString()), Steps)
		];
	}
	return Body;
}

TSharedRef<SWidget> SVerseServiceRecord::BuildRewardsPage()
{
	const FPages::FQuartermasterPage Page = FPages::Quartermaster(*Model, Strings());
	const FVerseUiStrings& S = Strings();
	TWeakPtr<FVerseServiceRecordModel> WeakModel = Model;
	TSharedRef<SVerticalBox> Uniforms = SNew(SVerticalBox);
	Uniforms->AddSlot().AutoHeight()[Hint(S.Get(TEXT("verse.ranks.record.uniforms_hint")))];
	for (const FPages::FUniformOption& Option : Page.Uniforms)
	{
		const FName Id = Option.Id;
		Uniforms->AddSlot().AutoHeight().Padding(0.f, 3.f)
		[
			SNew(SButton)
			.ButtonStyle(&VerseSlateKit::ButtonStyle(Option.bChosen))
			.IsEnabled(Option.bOpen)
			.OnClicked_Lambda([WeakModel, Id]()
			{
				if (const TSharedPtr<FVerseServiceRecordModel> M = WeakModel.Pin())
				{
					M->ChooseUniform(Id);
				}
				return FReply::Handled();
			})
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 12.f, 0.f)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth()[SNew(SBox).WidthOverride(16.f).HeightOverride(24.f)[SNew(SBorder).BorderImage(VerseSlateKit::Colour(FVerseRankPlate::UniformColour(Option.SwatchTier)))]]
					+ SHorizontalBox::Slot().AutoWidth()[SNew(SBox).WidthOverride(16.f).HeightOverride(24.f)[SNew(SBorder).BorderImage(VerseSlateKit::Colour(FVerseRankPlate::TierColour(Option.SwatchTier)))]]
				]
				+ SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()[VerseSlateKit::Text(Option.Name, 13, true, ColText)]
					+ SVerticalBox::Slot().AutoHeight()[Hint(Option.Note)]
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[Caps(Option.StateText, Option.bChosen ? ColGold : ColMuted)]
			]
		];
	}
	TSharedRef<SVerticalBox> Ribbons = SNew(SVerticalBox);
	Ribbons->AddSlot().AutoHeight()[Hint(S.Get(TEXT("verse.ranks.record.ribbons_hint")))];
	for (const FPages::FRibbonRow& Ribbon : Page.Ribbons)
	{
		Ribbons->AddSlot().AutoHeight().Padding(0.f, 4.f)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 10.f, 0.f)
			[
				SNew(SBox).WidthOverride(26.f).HeightOverride(10.f)[SNew(SBorder).BorderImage(VerseSlateKit::Colour(Ribbon.bOpen ? ColGold : FLinearColor(0.2f, 0.2f, 0.2f, 1.f)))]
			]
			+ SHorizontalBox::Slot().FillWidth(1.f)
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()[VerseSlateKit::Text(Ribbon.Name, 13, true, Ribbon.bOpen ? ColText : ColMuted)]
				+ SVerticalBox::Slot().AutoHeight()[Hint(Ribbon.Note)]
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()[Caps(Ribbon.ForYou)]
				+ SVerticalBox::Slot().AutoHeight()[Caps(Ribbon.ForCrew)]
			]
		];
	}
	return SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight()[Section(S.Get(TEXT("verse.ranks.record.uniforms")), Uniforms)]
		+ SVerticalBox::Slot().AutoHeight()[Section(S.Get(TEXT("verse.ranks.record.ribbons")), Ribbons)];
}

TSharedRef<SWidget> SVerseServiceRecord::BuildEarnPage()
{
	const FPages::FEarnPage Page = FPages::Earn(*Model, Strings());
	TSharedRef<SVerticalBox> Body = SNew(SVerticalBox);
	Body->AddSlot().AutoHeight()[Hint(Page.Hint)];
	for (const FPages::FEarnGroup& Group : Page.Groups)
	{
		TSharedRef<SVerticalBox> Rules = SNew(SVerticalBox);
		for (const FPages::FRuleRow& Rule : Group.Rules)
		{
			Rules->AddSlot().AutoHeight().Padding(0.f, 3.f)
			[
				Row(
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()[VerseSlateKit::Text(Rule.Text, 12, false, ColText)]
					+ SVerticalBox::Slot().AutoHeight()[Rule.Limits.IsEmpty() ? SNullWidget::NullWidget : Hint(Rule.Limits)],
					SNullWidget::NullWidget,
					VerseSlateKit::Text(Rule.Xp, 13, true, ColGold))
			];
		}
		Body->AddSlot().AutoHeight()[Section(Group.Title, Rules)];
	}
	return Body;
}

TSharedRef<SWidget> SVerseServiceRecord::BuildCrewPage()
{
	const FPages::FCrewPage Page = FPages::Crew(*Model, Strings());
	const FVerseUiStrings& S = Strings();
	TSharedRef<SVerticalBox> Body = SNew(SVerticalBox);
	Body->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 4.f)
	[
		SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().FillWidth(1.f)[Caps(S.Get(TEXT("verse.ranks.kind.agent")))]
		+ SHorizontalBox::Slot().AutoWidth()[SNew(SBox).WidthOverride(190.f)[Caps(S.Get(TEXT("verse.ranks.record.rank")))]]
		+ SHorizontalBox::Slot().AutoWidth()[SNew(SBox).WidthOverride(60.f).HAlign(HAlign_Right)[Caps(S.Get(TEXT("verse.ranks.record.level")))]]
		+ SHorizontalBox::Slot().AutoWidth()[SNew(SBox).WidthOverride(90.f).HAlign(HAlign_Right)[Caps(S.Get(TEXT("verse.ranks.card.xp")))]]
	];
	if (Page.bNoOfficers)
	{
		Body->AddSlot().AutoHeight()[Hint(Page.Empty)];
	}
	for (const FPages::FCrewRow& Crew : Page.Rows)
	{
		Body->AddSlot().AutoHeight().Padding(0.f, 3.f)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().Padding(0.f, 0.f, 8.f, 0.f)[SNew(SVerseRankPlate).Rank(Crew.RankId).Width(24.f)]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[VerseSlateKit::Text(Crew.Name, 12, Crew.bCompanion, ColText)]
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[SNew(SBox).WidthOverride(190.f)[VerseSlateKit::Text(Crew.Rank, 12, false, ColText)]]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[SNew(SBox).WidthOverride(60.f).HAlign(HAlign_Right)[VerseSlateKit::Text(Figure(Crew.Level), 12, false, ColText)]]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[SNew(SBox).WidthOverride(90.f).HAlign(HAlign_Right)[VerseSlateKit::Text(Figure(Crew.Xp), 12, false, ColText)]]
		];
	}
	return Body;
}

// ------------------------------------------------------------------ facts (the older record panel, kept for the model tests)

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
	Facts.Add(TEXT("kd"), FText::FromString(SVerseServiceRecord::FormatRatio(D.KillDeathRatio())));
	Facts.Add(TEXT("headshots"), Figure(D.Headshots));
	Facts.Add(TEXT("finishers"), Figure(D.Finishers));
	Facts.Add(TEXT("best_streak"), Figure(D.BestStreak));
	return Facts;
}

FString SVerseServiceRecord::FormatFigure(int64 Value)
{
	const bool bNegative = Value < 0;
	const FString Digits = FString::Printf(TEXT("%lld"), bNegative ? -Value : Value);
	FString Out;
	for (int32 i = 0; i < Digits.Len(); ++i)
	{
		if (i > 0 && (Digits.Len() - i) % 3 == 0)
		{
			Out.AppendChar(TEXT(' '));
		}
		Out.AppendChar(Digits[i]);
	}
	return bNegative ? TEXT("-") + Out : Out;
}

FString SVerseServiceRecord::FormatRatio(float Value)
{
	// Two decimals with a point, as the web's toFixed(2); Printf ignores the running culture.
	return FString::Printf(TEXT("%.2f"), Value);
}

// ------------------------------------------------------------------ the promotion notice

const FVerseUiStrings& SVersePromotionNotice::Strings() const
{
	return GetStrings ? GetStrings() : FallbackStrings();
}

double SVersePromotionNotice::NowSeconds() const
{
	return Clock ? Clock() : FPlatformTime::Seconds();
}

int32 SVersePromotionNotice::TilesAt(double Elapsed, int32 NumLit, bool bReducedMotion)
{
	if (bReducedMotion)
	{
		return NumLit;
	}
	return FMath::Clamp(int32(FMath::FloorToInt(Elapsed / TileStepSeconds)), 0, NumLit);
}

int32 SVersePromotionNotice::RevealedTiles() const
{
	return TilesAt(NowSeconds() - CreatedAt, FVerseRankPlate::For(Promotion.RankId).NumLit(), bReduced);
}

FText SVersePromotionNotice::Headline() const
{
	return Strings().Get(Promotion.Kind == EVerseSubjectKind::Pet ? TEXT("verse.ranks.promo.eyebrow_drone") : TEXT("verse.ranks.promo.eyebrow"));
}

FText SVersePromotionNotice::Detail() const
{
	return VerseRankName(Strings(), Promotion.RankId);
}

TArray<FString> SVersePromotionNotice::IssuedNames() const
{
	TArray<FString> Names;
	for (const FString& Id : Promotion.Unlocked)
	{
		// Only what the rulebook knows can be named: uniform_<tier> and ribbon_<id>.
		FString Key;
		if (Id.StartsWith(TEXT("uniform_")))
		{
			Key = FString::Printf(TEXT("verse.ranks.uniform.%s"), *Id.RightChop(8));
		}
		else if (Id.StartsWith(TEXT("ribbon_")))
		{
			Key = FString::Printf(TEXT("verse.ranks.ribbon.%s"), *Id);
		}
		if (!Key.IsEmpty() && !Strings().GetIn(Key, TEXT("en")).IsEmpty())
		{
			Names.Add(Strings().Get(Key).ToString());
		}
	}
	return Names;
}

void SVersePromotionNotice::Construct(const FArguments& InArgs, const FVersePromotion& InPromotion, FVerseStringsGetter InStrings)
{
	Promotion = InPromotion;
	GetStrings = MoveTemp(InStrings);
	bReduced = InArgs._bReducedMotion;
	CreatedAt = NowSeconds();
	const FVerseUiStrings& S = Strings();
	const FVerseRankRow& Rank = FVerseServiceRecordModel::RankFor(Promotion.Level);
	const bool bDrone = Promotion.Kind == EVerseSubjectKind::Pet;
	TWeakPtr<SVersePromotionNotice> Weak = SharedThis(this);

	TSharedRef<SVerticalBox> Body = SNew(SVerticalBox);
	Body->AddSlot().AutoHeight().HAlign(HAlign_Center)[Caps(Headline(), ColGold)];
	Body->AddSlot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 8.f)
	[
		// The new plate; its lit tiles are laid on one by one.
		SNew(SVerseRankPlate)
		.Rank(Promotion.RankId)
		.Width(120.f)
		.Revealed_Lambda([Weak]() { const TSharedPtr<SVersePromotionNotice> N = Weak.Pin(); return N.IsValid() ? N->RevealedTiles() : 6; })
	];
	Body->AddSlot().AutoHeight().HAlign(HAlign_Center)[VerseSlateKit::Text(Detail(), 24, true, ColText)];
	Body->AddSlot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 2.f, 0.f, 8.f)
	[
		Caps(FText::AsCultureInvariant(FPages::Fill(S, TEXT("verse.ranks.promo.level_up"), {{TEXT("level"), FString::FromInt(Promotion.Level)}}).ToString() + TEXT(" · ") + FPages::TierName(S, Rank.Tier).ToString()))
	];
	Body->AddSlot().AutoHeight().HAlign(HAlign_Center)
	[
		SNew(SBox).MaxDesiredWidth(380.f)
		[
			SNew(STextBlock)
			.Text(S.Get(bDrone ? TEXT("verse.ranks.promo.salute_drone") : FString::Printf(TEXT("verse.ranks.promo.salute.%s"), *Rank.Tier.ToString())))
			.Font(VerseSlateKit::Font(12))
			.ColorAndOpacity(FSlateColor(ColText))
			.Justification(ETextJustify::Center)
			.AutoWrapText(true)
		]
	];
	const TArray<FString> Issued = IssuedNames();
	if (Issued.Num() > 0)
	{
		Body->AddSlot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 6.f, 0.f, 0.f)
		[
			Hint(FPages::Fill(S, TEXT("verse.ranks.promo.issued"), {{TEXT("what"), FString::Join(Issued, TEXT(", "))}}))
		];
	}
	Body->AddSlot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 12.f, 0.f, 0.f)
	[
		// A click on it never takes the focus from the game.
		SNew(SButton)
		.ButtonStyle(&VerseSlateKit::ButtonStyle(true))
		.IsFocusable(false)
		.OnClicked_Lambda([Ack = InArgs._OnAcknowledge]()
		{
			Ack.ExecuteIfBound();
			return FReply::Handled();
		})
		[
			VerseSlateKit::Text(S.Get(TEXT("verse.ranks.promo.acknowledge")), 12, true, ColText)
		]
	];
	ChildSlot
	[
		SNew(SBorder)
		.BorderImage(VerseSlateKit::Colour(VerseUiTheme::Steel))
		.Padding(FMargin(28.f, 18.f))
		[
			Body
		]
	];
}

// ------------------------------------------------------------------ the quiet lines

void SVerseQuietLines::Construct(const FArguments& InArgs)
{
	OnDismiss = InArgs._OnDismiss;
	ChildSlot
	[
		SAssignNew(LinesBox, SBox)
	];
}

void SVerseQuietLines::Show(const TArray<FVerseQuietEntry>& Entries)
{
	TSharedRef<SVerticalBox> Lines = SNew(SVerticalBox);
	for (const FVerseQuietEntry& Entry : Entries)
	{
		const int64 Id = Entry.Id;
		Lines->AddSlot().AutoHeight().Padding(0.f, 2.f)
		[
			SNew(SButton)
			.ButtonStyle(&VerseSlateKit::ButtonStyle(false))
			.IsFocusable(false)
			.OnClicked_Lambda([this, Id]()
			{
				OnDismiss.ExecuteIfBound(Id);
				return FReply::Handled();
			})
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 8.f, 0.f)[SNew(SVerseRankPlate).Rank(Entry.RankId).Width(24.f)]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[VerseSlateKit::Text(Entry.Text, 12, false, ColText)]
			]
		];
	}
	LinesBox->SetContent(Lines);
}

#undef LOCTEXT_NAMESPACE
