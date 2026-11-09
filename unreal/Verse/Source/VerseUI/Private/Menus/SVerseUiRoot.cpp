#include "Menus/SVerseUiRoot.h"

#include "Brushes/SlateColorBrush.h"
#include "Core/VerseUiSubsystem.h"
#include "Core/VerseUiTheme.h"
#include "Settings/VerseGameSettings.h"
#include "Scalability.h"
#include "Styling/CoreStyle.h"
#include "Styling/SlateTypes.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SSpacer.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SNullWidget.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

namespace
{
	const FSlateBrush* ColourBrush(const FLinearColor& Colour)
	{
		// Brushes live as long as the module: one per distinct colour.
		static TMap<uint32, TUniquePtr<FSlateColorBrush>> Brushes;
		const uint32 Key = Colour.ToFColor(false).ToPackedARGB();
		TUniquePtr<FSlateColorBrush>& Brush = Brushes.FindOrAdd(Key);
		if (!Brush)
		{
			Brush = MakeUnique<FSlateColorBrush>(Colour);
		}
		return Brush.Get();
	}

	const FButtonStyle& ButtonStyle(bool bPrimary)
	{
		auto Make = [](bool bIsPrimary)
		{
			FButtonStyle Style = FCoreStyle::Get().GetWidgetStyle<FButtonStyle>("Button");
			const FLinearColor Base = bIsPrimary ? FLinearColor(0.32f, 0.16f, 0.02f, 1.f) : VerseUiTheme::SteelLight;
			Style.SetNormal(*ColourBrush(Base));
			Style.SetHovered(*ColourBrush(bIsPrimary ? FLinearColor(0.48f, 0.25f, 0.03f, 1.f) : VerseUiTheme::Edge));
			Style.SetPressed(*ColourBrush(VerseUiTheme::Amber * FLinearColor(0.6f, 0.6f, 0.6f, 1.f)));
			Style.SetDisabled(*ColourBrush(FLinearColor(0.02f, 0.02f, 0.02f, 0.6f)));
			Style.SetNormalPadding(FMargin(16.f, 8.f));
			Style.SetPressedPadding(FMargin(16.f, 9.f, 16.f, 7.f));
			return Style;
		};
		static const FButtonStyle Normal = Make(false);
		static const FButtonStyle Primary = Make(true);
		return bPrimary ? Primary : Normal;
	}
}

void SVerseUiRoot::Construct(const FArguments& InArgs, UVerseUiSubsystem* InOwner)
{
	Owner = InOwner;
	ChildSlot
	[
		SNew(SOverlay)
		+ SOverlay::Slot()
		.HAlign(HAlign_Center)
		.VAlign(VAlign_Top)
		.Padding(FMargin(0.f, 12.f, 0.f, 0.f))
		[
			SAssignNew(BarSlot, SBox)
		]
		+ SOverlay::Slot()
		.HAlign(HAlign_Center)
		.VAlign(VAlign_Center)
		[
			SAssignNew(ScreenSlot, SBox)
		]
	];
	Refresh();
}

FText SVerseUiRoot::S(const FString& Key) const
{
	return Owner.IsValid() ? Owner->GetStrings().Get(Key) : FText::AsCultureInvariant(Key);
}

void SVerseUiRoot::Refresh()
{
	if (!Owner.IsValid())
	{
		return;
	}
	BarSlot->SetContent(BuildBar());
	ScreenSlot->SetContent(BuildScreen());
}

void SVerseUiRoot::SetSettingsPage(int32 Page)
{
	SettingsPage = FMath::Clamp(Page, 0, NumSettingsPages() - 1);
	if (PageSlot.IsValid())
	{
		PageSlot->SetContent(BuildSettingsPage());
	}
}

TSharedRef<SWidget> SVerseUiRoot::BuildScreen()
{
	switch (Owner->GetScreen())
	{
	case EVerseUiScreen::EscMenu: return BuildEscMenu();
	case EVerseUiScreen::Settings: return BuildSettings();
	case EVerseUiScreen::Armoury: return BuildArmoury();
	case EVerseUiScreen::EndOfSet: return BuildEndOfSet();
	case EVerseUiScreen::SessionSummary: return BuildSessionSummary();
	case EVerseUiScreen::None: break;
	}
	return SNullWidget::NullWidget;
}

TSharedRef<SWidget> SVerseUiRoot::Label(TAttribute<FText> Text, float Size, bool bBold, const FLinearColor& Colour)
{
	const float Scale = Owner.IsValid() ? FMath::Clamp(float(Owner->GetGameNumber(TEXT("access.text_scale"))), 0.8f, 1.6f) : 1.f;
	return SNew(STextBlock)
		.Text(Text)
		.Font(FCoreStyle::GetDefaultFontStyle(bBold ? "Bold" : "Regular", FMath::RoundToInt(Size * Scale)))
		.ColorAndOpacity(FSlateColor(Colour))
		.ShadowColorAndOpacity(VerseUiTheme::Shadow)
		.ShadowOffset(FVector2D(1.0, 1.0));
}

TSharedRef<SWidget> SVerseUiRoot::Button(TAttribute<FText> Text, FSimpleDelegate OnClick, bool bPrimary, TAttribute<bool> bSelected)
{
	return SNew(SHorizontalBox)
		+ SHorizontalBox::Slot()
		.AutoWidth()
		[
			// Selection is a bar beside the button (a shape), not only a colour.
			SNew(SBox)
			.WidthOverride(5.f)
			[
				SNew(SBorder)
				.BorderImage(ColourBrush(VerseUiTheme::Amber))
				.Visibility_Lambda([bSelected] { return bSelected.Get() ? EVisibility::Visible : EVisibility::Hidden; })
			]
		]
		+ SHorizontalBox::Slot()
		.FillWidth(1.f)
		[
			SNew(SButton)
			.ButtonStyle(&ButtonStyle(bPrimary))
			.HAlign(HAlign_Center)
			.OnClicked_Lambda([OnClick] { OnClick.ExecuteIfBound(); return FReply::Handled(); })
			[
				Label(Text, 15.f, true, VerseUiTheme::Text)
			]
		];
}

TSharedRef<SWidget> SVerseUiRoot::Panel(const FString& TitleKey, TSharedRef<SWidget> Body, float Width)
{
	return SNew(SBox)
		.WidthOverride(Width)
		[
			SNew(SBorder)
			.BorderImage(ColourBrush(VerseUiTheme::Steel))
			.Padding(FMargin(0.f))
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot()
				.AutoWidth()
				[
					SNew(SBox)
					.WidthOverride(4.f)
					[
						SNew(SBorder).BorderImage(ColourBrush(VerseUiTheme::Amber))
					]
				]
				+ SHorizontalBox::Slot()
				.FillWidth(1.f)
				.Padding(FMargin(28.f, 22.f))
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot()
					.AutoHeight()
					.Padding(FMargin(0.f, 0.f, 0.f, 16.f))
					[
						Label(S(TitleKey), 26.f, true, VerseUiTheme::Text)
					]
					+ SVerticalBox::Slot()
					.AutoHeight()
					[
						Body
					]
				]
			]
		];
}

TSharedRef<SWidget> SVerseUiRoot::Stepper(const FString& LabelKey, TAttribute<FText> Value, TFunction<void(int32)> Step)
{
	return SNew(SHorizontalBox)
		+ SHorizontalBox::Slot()
		.FillWidth(1.f)
		.VAlign(VAlign_Center)
		[
			Label(S(LabelKey), 15.f, false, VerseUiTheme::Text)
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		[
			SNew(SBox)
			.WidthOverride(52.f)
			[
				Button(S(TEXT("verse.ui.previous")), FSimpleDelegate::CreateLambda([Step] { Step(-1); }))
			]
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.VAlign(VAlign_Center)
		[
			SNew(SBox)
			.WidthOverride(200.f)
			.HAlign(HAlign_Center)
			[
				Label(Value, 15.f, true, VerseUiTheme::Amber)
			]
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		[
			SNew(SBox)
			.WidthOverride(52.f)
			[
				Button(S(TEXT("verse.ui.next")), FSimpleDelegate::CreateLambda([Step] { Step(1); }))
			]
		];
}

TSharedRef<SWidget> SVerseUiRoot::BuildBar()
{
	TWeakObjectPtr<UVerseUiSubsystem> Ui = Owner;
	const bool bDuel = Owner->GetGamePort().IsDuelRunning();
	const bool bShow = !bDuel || Owner->IsBarOpen() || Owner->GetScreen() != EVerseUiScreen::None;
	if (!bShow)
	{
		return SNullWidget::NullWidget;
	}
	TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);
	for (const FVerseBarEntry& Entry : FVerseBarModel::Build(Owner->GetDecks(), Owner->GetGamePort().GetCurrentDeck(), bDuel))
	{
		FSimpleDelegate Click;
		switch (Entry.Kind)
		{
		case EVerseBarEntryKind::QuickStartDuel:
			Click = FSimpleDelegate::CreateLambda([Ui, bDuel] { if (Ui.IsValid()) { bDuel ? Ui->LeaveDuel() : Ui->QuickStartDuel(); } });
			break;
		case EVerseBarEntryKind::Deck:
		{
			const FName Deck = Entry.Id;
			Click = FSimpleDelegate::CreateLambda([Ui, Deck] { if (Ui.IsValid()) { Ui->TravelToDeck(Deck); } });
			break;
		}
		case EVerseBarEntryKind::ReturnToApp:
			Click = FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->ReturnToApp(TEXT("esc_menu")); } });
			break;
		}
		const bool bActive = Entry.bActive;
		TSharedRef<SWidget> Item = Button(S(Entry.LabelKey), Click, Entry.Kind == EVerseBarEntryKind::QuickStartDuel, bActive);
		Item->SetEnabled(Entry.bEnabled);
		Row->AddSlot().AutoWidth().Padding(FMargin(3.f, 0.f))[Item];
	}
	return SNew(SBorder)
		.BorderImage(ColourBrush(VerseUiTheme::Steel))
		.Padding(FMargin(8.f, 6.f))
		[
			Row
		];
}

TSharedRef<SWidget> SVerseUiRoot::BuildEscMenu()
{
	TWeakObjectPtr<UVerseUiSubsystem> Ui = Owner;
	TSharedRef<SVerticalBox> Body = SNew(SVerticalBox);
	auto Add = [&Body](TSharedRef<SWidget> W) { Body->AddSlot().AutoHeight().Padding(FMargin(0.f, 4.f))[W]; };
	Add(Button(S(TEXT("verse.menu.resume")), FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->ShowScreen(EVerseUiScreen::None); } }), true));
	Add(Button(S(TEXT("verse.menu.settings")), FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->ShowScreen(EVerseUiScreen::Settings); } })));
	if (Owner->GetGamePort().IsDuelRunning())
	{
		Add(Button(S(TEXT("verse.menu.leave_duel")), FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->LeaveDuel(); } })));
	}
	Add(Button(S(TEXT("verse.menu.return")), FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->ReturnToApp(TEXT("esc_menu")); } })));
	return Panel(TEXT("verse.menu.title"), Body, 460.f);
}

TSharedRef<SWidget> SVerseUiRoot::BuildSettings()
{
	// The tabs of the app's Game settings page (game_settings.py TABS), same order, same strings.
	TSharedRef<SHorizontalBox> Tabs = SNew(SHorizontalBox);
	const TArray<FString>& TabIds = FVerseGameSettingsCatalogue::Get().GetTabs();
	TWeakPtr<SVerseUiRoot> Self = SharedThis(this);
	for (int32 I = 0; I < TabIds.Num(); ++I)
	{
		Tabs->AddSlot().FillWidth(1.f).Padding(FMargin(2.f, 0.f))
		[
			Button(S(TEXT("verse_settings.tabs.") + TabIds[I]), FSimpleDelegate::CreateLambda([Self, I] { if (TSharedPtr<SVerseUiRoot> P = Self.Pin()) { P->SetSettingsPage(I); } }), false,
				TAttribute<bool>::CreateLambda([Self, I] { TSharedPtr<SVerseUiRoot> P = Self.Pin(); return P.IsValid() && P->SettingsPage == I; }))
		];
	}
	TWeakObjectPtr<UVerseUiSubsystem> Ui = Owner;
	TSharedRef<SVerticalBox> Body = SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 0.f, 0.f, 12.f))[Tabs]
		+ SVerticalBox::Slot().AutoHeight()
		[
			SNew(SBox)
			.HeightOverride(560.f)
			[
				SAssignNew(PageSlot, SBox)
			]
		]
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Right).Padding(FMargin(0.f, 12.f, 0.f, 0.f))
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().Padding(FMargin(0.f, 0.f, 8.f, 0.f))
			[
				SNew(SBox).WidthOverride(240.f)
				[
					// parity T-01: reset restores the view defaults.
					Button(S(TEXT("verse.settings.reset")), FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->ResetSettings(); } }))
				]
			]
			+ SHorizontalBox::Slot().AutoWidth()
			[
				SNew(SBox).WidthOverride(240.f)
				[
					Button(S(TEXT("verse.ui.back")), FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->ShowScreen(EVerseUiScreen::EscMenu); } }))
				]
			]
		];
	PageSlot->SetContent(BuildSettingsPage());
	return Panel(TEXT("verse.settings.title"), Body, 1240.f);
}

int32 SVerseUiRoot::NumSettingsPages()
{
	return FMath::Max(1, FVerseGameSettingsCatalogue::Get().GetTabs().Num());
}

FText SVerseUiRoot::SettingValueText(const UVerseUiSubsystem& Ui, const FVerseGameSettingDef& Def)
{
	const FVerseUiStrings& Strings = Ui.GetStrings();
	const TSharedPtr<FJsonValue> Value = Ui.GetGameSetting(Def.Id);
	if (!Value.IsValid())
	{
		return FText::GetEmpty();
	}
	switch (Def.Kind)
	{
	case EVerseGameSettingKind::Toggle:
		return Strings.Get(Value->AsBool() ? TEXT("verse.ui.on") : TEXT("verse.ui.off"));
	case EVerseGameSettingKind::Choice:
	{
		// Resolutions and frame rates are numbers; every other option has a word.
		const FString Option = Value->AsString();
		return !Option.IsEmpty() && FChar::IsDigit(Option[0]) ? FText::AsCultureInvariant(Option) : Strings.Get(TEXT("verse_settings.o.") + Option);
	}
	case EVerseGameSettingKind::Range:
	{
		const double N = Value->AsNumber();
		if (Def.Unit == TEXT("%"))
		{
			return Strings.Percent(Def.Max <= 2.0 ? N : N / 100.0);
		}
		if (Def.Unit == TEXT("x"))
		{
			return Strings.Number(N, 2);
		}
		return Strings.Number(N, Def.Step < 1.0 ? 2 : 0);
	}
	case EVerseGameSettingKind::Key:
		return FKey(*Value->AsString()).GetDisplayName();
	}
	return FText::GetEmpty();
}

void SVerseUiRoot::StepSetting(UVerseUiSubsystem& Ui, const FVerseGameSettingDef& Def, int32 Direction)
{
	const TSharedPtr<FJsonValue> Value = Ui.GetGameSetting(Def.Id);
	if (!Value.IsValid())
	{
		return;
	}
	switch (Def.Kind)
	{
	case EVerseGameSettingKind::Toggle:
		Ui.SetGameSetting(Def.Id, MakeShared<FJsonValueBoolean>(!Value->AsBool()));
		break;
	case EVerseGameSettingKind::Choice:
	{
		const int32 Count = Def.Options.Num();
		if (Count > 0)
		{
			const int32 Index = FMath::Max(0, Def.OptionIndex(Value->AsString()));
			Ui.SetGameSetting(Def.Id, MakeShared<FJsonValueString>(Def.Options[((Index + Direction) % Count + Count) % Count]));
		}
		break;
	}
	case EVerseGameSettingKind::Range:
	{
		// At most about 40 presses end to end: the catalogue step times 1, 2, 5, 10, 20 or 50.
		const double Steps = (Def.Max - Def.Min) / FMath::Max(Def.Step, 1e-6);
		double Stride = Def.Step;
		for (const int32 K : {1, 2, 5, 10, 20, 50})
		{
			Stride = Def.Step * K;
			if (Steps / K <= 40.0)
			{
				break;
			}
		}
		const double Next = FMath::Clamp(FMath::RoundToDouble((Value->AsNumber() + Stride * Direction) / Def.Step) * Def.Step, Def.Min, Def.Max);
		if (Def.Id == TEXT("access.text_scale"))
		{
			Ui.SetTextScale(float(Next)); // rebuilds the menus at the new size
		}
		else
		{
			Ui.SetGameSetting(Def.Id, MakeShared<FJsonValueNumber>(Next));
		}
		break;
	}
	case EVerseGameSettingKind::Key:
		break; // keys rebind on the keybinds page
	}
}

TSharedRef<SWidget> SVerseUiRoot::BuildSettingsPage()
{
	TWeakObjectPtr<UVerseUiSubsystem> Ui = Owner;
	TSharedRef<SScrollBox> Box = SNew(SScrollBox);
	auto Add = [&Box](TSharedRef<SWidget> W, float Top = 4.f) { Box->AddSlot().Padding(FMargin(0.f, Top, 12.f, 4.f))[W]; };
	const FVerseGameSettingsCatalogue& Catalogue = FVerseGameSettingsCatalogue::Get();
	const FString Tab = Catalogue.GetTabs().IsValidIndex(SettingsPage) ? Catalogue.GetTabs()[SettingsPage] : FString();

	if (Tab == TEXT("keybinds"))
	{
		// Rebinding writes settings.game keybinds.* (and return_key) through the app settings.
		TWeakPtr<SVerseUiRoot> Self = SharedThis(this);
		for (const FVerseKeyMap::FAction& Action : Owner->GetKeyMap().GetActions())
		{
			const FName Name = Action.Action;
			Add(SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
				[
					Label(S(Action.LabelKey), 15.f, false, VerseUiTheme::Text)
				]
				+ SHorizontalBox::Slot().AutoWidth()
				[
					SNew(SBox).WidthOverride(240.f)
					[
						Button(TAttribute<FText>::CreateLambda([Self, Ui, Name]
							{
								TSharedPtr<SVerseUiRoot> P = Self.Pin();
								if (P.IsValid() && P->ListeningAction == Name && Ui.IsValid())
								{
									return Ui->GetStrings().Get(TEXT("verse.settings.press_key"));
								}
								return Ui.IsValid() ? Ui->GetKeyMap().GetKey(Name).GetDisplayName() : FText();
							}),
							FSimpleDelegate::CreateLambda([Self, Name] { if (TSharedPtr<SVerseUiRoot> P = Self.Pin()) { P->ListeningAction = Name; } }), false,
							TAttribute<bool>::CreateLambda([Self, Name] { TSharedPtr<SVerseUiRoot> P = Self.Pin(); return P.IsValid() && P->ListeningAction == Name; }))
					]
				]);
		}
		return Box;
	}

	FString Section;
	bool bFirst = true;
	for (const FVerseGameSettingDef& Def : Catalogue.GetSettings())
	{
		if (Def.Tab != Tab || Def.Kind == EVerseGameSettingKind::Key)
		{
			continue;
		}
		if (Def.Section != Section)
		{
			Section = Def.Section;
			Add(Label(S(TEXT("verse_settings.sections.") + Section), 13.f, true, VerseUiTheme::Amber), bFirst ? 0.f : 14.f);
			bFirst = false;
		}
		const FVerseGameSettingDef Entry = Def;
		Add(Stepper(TEXT("verse_settings.s.") + Def.Id + TEXT(".label"),
			TAttribute<FText>::CreateLambda([Ui, Entry] { return Ui.IsValid() ? SettingValueText(*Ui, Entry) : FText(); }),
			[Ui, Entry](int32 D) { if (Ui.IsValid()) { StepSetting(*Ui, Entry, D); } }));
		if (Def.bRestart)
		{
			Add(Label(S(TEXT("verse_settings.restart")), 12.f, false, VerseUiTheme::TextDim), 0.f);
		}
	}
	if (Tab == TEXT("graphics"))
	{
		// T-02: the tier in effect, also while the choice is Auto.
		Add(Label(TAttribute<FText>::CreateLambda([Ui]
			{
				if (!Ui.IsValid())
				{
					return FText();
				}
				const int32 Level = FVerseRenderTier::Resolve(Ui->GetUserSettings()->Scalability, Scalability::GetQualityLevels().GetSingleQualityLevel());
				FFormatNamedArguments Args;
				Args.Add(TEXT("tier"), Ui->GetStrings().Get(FVerseRenderTier::KeyFor(Level)));
				return Ui->GetStrings().Format(TEXT("verse.settings.render_tier"), Args);
			}), 13.f, false, VerseUiTheme::TextDim), 14.f);
	}
	if (Tab == TEXT("accessibility"))
	{
		Add(Label(S(TEXT("verse.settings.markers_note")), 13.f, false, VerseUiTheme::TextDim), 14.f);
	}
	return Box;
}

TSharedRef<SWidget> SVerseUiRoot::BuildArmoury()
{
	TWeakObjectPtr<UVerseUiSubsystem> Ui = Owner;
	FVerseArmouryModel& Armoury = Owner->GetArmoury();
	TSharedRef<SVerticalBox> Loadout = SNew(SVerticalBox);
	for (const FVerseArmouryItem& Item : Armoury.GetLoadout())
	{
		const FString Id = Item.ItemId.ToString().ToLower();
		const FString SlotKey = FString::Printf(TEXT("verse.armoury.slot.%s"), *StaticEnum<EVerseLoadoutSlot>()->GetNameStringByValue(int64(Item.Slot)).ToLower());
		Loadout->AddSlot().AutoHeight().Padding(FMargin(0.f, 3.f))
		[
			SNew(SBorder)
			.BorderImage(ColourBrush(VerseUiTheme::SteelLight))
			.Padding(FMargin(12.f, 8.f))
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
				[
					SNew(SBox).WidthOverride(170.f)
					[
						Label(S(SlotKey), 12.f, true, VerseUiTheme::TextDim)
					]
				]
				+ SHorizontalBox::Slot().FillWidth(1.f)
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()[Label(S(FString::Printf(TEXT("verse.item.%s.name"), *Id)), 17.f, true, VerseUiTheme::Text)]
					+ SVerticalBox::Slot().AutoHeight()[Label(S(FString::Printf(TEXT("verse.item.%s.role"), *Id)), 13.f, false, VerseUiTheme::TextDim)]
				]
			]
		];
	}

	TSharedRef<SHorizontalBox> Tiers = SNew(SHorizontalBox);
	for (const FName& Tier : Armoury.GetTiers())
	{
		Tiers->AddSlot().FillWidth(1.f).Padding(FMargin(2.f, 0.f))
		[
			Button(S(FString::Printf(TEXT("verse.tier.%s"), *Tier.ToString())),
				FSimpleDelegate::CreateLambda([Ui, Tier] { if (Ui.IsValid()) { Ui->GetArmoury().SelectTier(Tier); } }), false,
				TAttribute<bool>::CreateLambda([Ui, Tier] { return Ui.IsValid() && Ui->GetArmoury().GetSelectedTier() == Tier; }))
		];
	}

	TSharedRef<SVerticalBox> Body = SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 0.f, 0.f, 6.f))[Label(S(TEXT("verse.armoury.loadout")), 13.f, true, VerseUiTheme::Amber)]
		+ SVerticalBox::Slot().AutoHeight()[Loadout]
		+ SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 18.f, 0.f, 6.f))[Label(S(TEXT("verse.armoury.tier")), 13.f, true, VerseUiTheme::Amber)]
		+ SVerticalBox::Slot().AutoHeight()[Tiers]
		+ SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 8.f, 0.f, 0.f))
		[
			Label(TAttribute<FText>::CreateLambda([Ui]
				{
					return Ui.IsValid() ? Ui->GetStrings().Get(FString::Printf(TEXT("verse.tier.%s.desc"), *Ui->GetArmoury().GetSelectedTier().ToString())) : FText();
				}), 13.f, false, VerseUiTheme::Text)
		]
		+ SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 22.f, 0.f, 0.f))
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().FillWidth(1.f).Padding(FMargin(0.f, 0.f, 6.f, 0.f))
			[
				Button(S(TEXT("verse.ui.back")), FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->ShowScreen(EVerseUiScreen::None); } }))
			]
			+ SHorizontalBox::Slot().FillWidth(2.f)
			[
				Button(S(TEXT("verse.armoury.start")), FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->StartDuelFromArmoury(); } }), true)
			]
		];
	return Panel(TEXT("verse.armoury.title"), Body, 860.f);
}

TSharedRef<SWidget> SVerseUiRoot::BuildStatsTable(const FVerseEndScreen& End)
{
	TSharedRef<SVerticalBox> Table = SNew(SVerticalBox);
	Table->AddSlot().AutoHeight().Padding(FMargin(0.f, 2.f))
	[
		SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().FillWidth(2.f)[SNew(SSpacer)]
		+ SHorizontalBox::Slot().FillWidth(1.f).HAlign(HAlign_Right)[Label(S(TEXT("verse.end.you")), 13.f, true, VerseUiTheme::Amber)]
		+ SHorizontalBox::Slot().FillWidth(1.f).HAlign(HAlign_Right)[Label(S(TEXT("verse.end.opponent")), 13.f, true, VerseUiTheme::Red)]
	];
	for (const FVerseEndScreenRow& Row : End.Rows)
	{
		Table->AddSlot().AutoHeight().Padding(FMargin(0.f, 2.f))
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().FillWidth(2.f)[Label(S(Row.LabelKey), 15.f, false, VerseUiTheme::Text)]
			+ SHorizontalBox::Slot().FillWidth(1.f).HAlign(HAlign_Right)[Label(Row.Person, 15.f, true, VerseUiTheme::Text)]
			+ SHorizontalBox::Slot().FillWidth(1.f).HAlign(HAlign_Right)[Label(Row.Opponent, 15.f, true, VerseUiTheme::Text)]
		];
	}
	return Table;
}

TSharedRef<SWidget> SVerseUiRoot::BuildEndOfSet()
{
	TWeakObjectPtr<UVerseUiSubsystem> Ui = Owner;
	const FVerseEndScreen& End = Owner->GetEndScreen();
	const FVerseUiStrings& Strings = Owner->GetStrings();

	FFormatNamedArguments SetArgs;
	SetArgs.Add(TEXT("set"), Strings.Number(End.SetIndex));
	FFormatNamedArguments ScoreArgs;
	ScoreArgs.Add(TEXT("person"), Strings.Number(End.PersonKills));
	ScoreArgs.Add(TEXT("opponent"), Strings.Number(End.OpponentKills));

	TSharedRef<SWidget> Table = BuildStatsTable(End);

	TSharedRef<SVerticalBox> Body = SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight()[Label(Strings.Format(TEXT("verse.end.set"), SetArgs), 14.f, false, VerseUiTheme::TextDim)]
		+ SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 4.f, 0.f, 14.f))
		[
			Label(Strings.Format(TEXT("verse.end.score"), ScoreArgs), 34.f, true, End.Outcome == EVerseSetOutcome::Won ? VerseUiTheme::Gold : VerseUiTheme::Text)
		]
		+ SVerticalBox::Slot().AutoHeight()[Owner->GetGameBool(TEXT("gameplay.show_duel_stats")) ? Table : SNullWidget::NullWidget];
	if (End.bShowSkill)
	{
		FFormatNamedArguments SkillArgs;
		SkillArgs.Add(TEXT("skill"), Strings.Number(End.Skill, 2));
		Body->AddSlot().AutoHeight().Padding(FMargin(0.f, 14.f, 0.f, 0.f))[Label(Strings.Format(TEXT("verse.end.adaptive"), SkillArgs), 14.f, true, VerseUiTheme::Amber)];
	}
	else if (!End.Tier.IsNone())
	{
		FFormatNamedArguments TierArgs;
		TierArgs.Add(TEXT("tier"), S(FString::Printf(TEXT("verse.tier.%s"), *End.Tier.ToString())));
		Body->AddSlot().AutoHeight().Padding(FMargin(0.f, 14.f, 0.f, 0.f))[Label(Strings.Format(TEXT("verse.end.tier"), TierArgs), 14.f, false, VerseUiTheme::TextDim)];
	}
	Body->AddSlot().AutoHeight().Padding(FMargin(0.f, 22.f, 0.f, 0.f))
	[
		SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().FillWidth(1.f).Padding(FMargin(0.f, 0.f, 6.f, 0.f))
		[
			Button(S(TEXT("verse.end.leave")), FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->LeaveDuel(); } }))
		]
		+ SHorizontalBox::Slot().FillWidth(2.f)
		[
			Button(S(TEXT("verse.end.next")), FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->ContinueAfterSet(); } }), true)
		]
	];
	return Panel(End.TitleKey, Body, 720.f);
}

TSharedRef<SWidget> SVerseUiRoot::BuildSessionSummary()
{
	// parity D-10: leave shows the session summary and "again"; a mid-set leave says so.
	TWeakObjectPtr<UVerseUiSubsystem> Ui = Owner;
	const FVerseEndScreen& Summary = Owner->GetSessionScreen();
	const FVerseUiStrings& Strings = Owner->GetStrings();
	TSharedRef<SVerticalBox> Body = SNew(SVerticalBox);
	if (Owner->GetSession().bLeftMidSet)
	{
		Body->AddSlot().AutoHeight().Padding(FMargin(0.f, 0.f, 0.f, 10.f))[Label(S(TEXT("verse.duel.notice.left")), 15.f, true, VerseUiTheme::Amber)];
	}
	FFormatNamedArguments SetsArgs;
	SetsArgs.Add(TEXT("won"), Strings.Number(Summary.PersonKills));
	SetsArgs.Add(TEXT("lost"), Strings.Number(Summary.OpponentKills));
	Body->AddSlot().AutoHeight().Padding(FMargin(0.f, 0.f, 0.f, 14.f))[Label(Strings.Format(TEXT("verse.end.sets"), SetsArgs), 26.f, true, VerseUiTheme::Text)];
	if (Summary.SetIndex > 0 && Owner->GetGameBool(TEXT("gameplay.show_duel_stats")))
	{
		Body->AddSlot().AutoHeight()[BuildStatsTable(Summary)];
	}
	Body->AddSlot().AutoHeight().Padding(FMargin(0.f, 22.f, 0.f, 0.f))
	[
		SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().FillWidth(1.f).Padding(FMargin(0.f, 0.f, 6.f, 0.f))
		[
			Button(S(TEXT("verse.duel.result.leave")), FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->ShowScreen(EVerseUiScreen::None); } }))
		]
		+ SHorizontalBox::Slot().FillWidth(2.f)
		[
			Button(S(TEXT("verse.duel.result.rematch")), FSimpleDelegate::CreateLambda([Ui] { if (Ui.IsValid()) { Ui->QuickStartDuel(); } }), true)
		]
	];
	return Panel(Summary.TitleKey, Body, 720.f);
}
