#include "Stations/SVerseStationPanel.h"

#include "HAL/PlatformTime.h"
#include "Stations/VerseStationUISubsystem.h"
#include "Styling/CoreStyle.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

namespace
{
	// Military-Industrial Noir: black steel ground, amber accent (README Look).
	const FLinearColor Ground(0.010f, 0.010f, 0.012f, 0.92f);
	const FLinearColor Ink(0.86f, 0.84f, 0.80f, 1.f);
	const FLinearColor Amber(1.00f, 0.55f, 0.10f, 1.f);

	FSlateFontInfo Font(int32 Size)
	{
		return FCoreStyle::GetDefaultFontStyle("Regular", Size);
	}
}

void SVerseStationPanel::Construct(const FArguments& InArgs)
{
	Owner = InArgs._Owner;
	TWeakObjectPtr<UVerseStationUISubsystem> W = Owner;
	auto Ctl = [W]() -> FVerseStationController* { return W.IsValid() ? &W->Controller() : nullptr; };
	auto PanelIs = [Ctl](EVerseStationPanel P)
	{
		return TAttribute<EVisibility>::CreateLambda([Ctl, P]()
		{
			const FVerseStationController* C = Ctl();
			return C && C->Panel() == P ? EVisibility::Visible : EVisibility::Collapsed;
		});
	};
	auto Button = [](const FText& Label, TFunction<void()> OnClick)
	{
		return SNew(SButton)
			.OnClicked_Lambda([OnClick]() { OnClick(); return FReply::Handled(); })
			[
				SNew(STextBlock).Text(Label).Font(Font(14)).ColorAndOpacity(Ink)
			];
	};
	auto Option = [Ctl](bool bWorkspace)
	{
		return TAttribute<FText>::CreateLambda([Ctl, bWorkspace]()
		{
			const FVerseStationController* C = Ctl();
			if (!C)
			{
				return FText::GetEmpty();
			}
			const FVerseLauncherState& S = C->Launcher();
			const TArray<FVerseLauncherOption>& List = bWorkspace ? S.Workspaces : S.Agents;
			const int32 I = bWorkspace ? S.Workspace : S.Agent;
			return List.IsValidIndex(I) ? FText::FromString(List[I].Name) : FText::FromString(TEXT("-"));
		});
	};
	auto Cycle = [Ctl](bool bWorkspace)
	{
		return [Ctl, bWorkspace]()
		{
			FVerseStationController* C = Ctl();
			if (!C)
			{
				return;
			}
			const FVerseLauncherState& S = C->Launcher();
			const int32 N = bWorkspace ? S.Workspaces.Num() : S.Agents.Num();
			for (int32 Step = 1; Step <= N; ++Step)
			{
				const int32 Next = ((bWorkspace ? S.Workspace : S.Agent) + Step) % FMath::Max(1, N);
				if (bWorkspace)
				{
					C->LauncherSelectWorkspace(Next);
					return;
				}
				if (S.Agents[Next].bFlag)
				{
					C->LauncherSelectAgent(Next);
					return;
				}
			}
		};
	};

	auto Label = [W](const TCHAR* Key, const TCHAR* Fallback)
	{
		const FVerseStationController* C = W.IsValid() ? &W->Controller() : nullptr;
		return FText::FromString(C && C->Localize ? C->Localize(Key, Fallback) : FString(Fallback));
	};

	TSharedRef<SVerticalBox> Programmes = SNew(SVerticalBox);
	for (const FVerseProgramme& P : FVerseStationController::Programmes())
	{
		const FString Id = P.Id;
		Programmes->AddSlot().AutoHeight().Padding(2.f)[Button(FText::FromString(P.Title), [Ctl, Id]() { if (FVerseStationController* C = Ctl()) { C->OpenProgramme(Id); } })];
	}

	ChildSlot
	[
		SNew(SOverlay)
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Top).Padding(0.f, 48.f)
		[
			SNew(STextBlock).Font(Font(16)).ColorAndOpacity(Amber)
				.Text_Lambda([W]() { return W.IsValid() ? FText::FromString(W->Notice(FPlatformTime::Seconds())) : FText::GetEmpty(); })
		]
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center).Padding(0.f, 140.f, 0.f, 0.f)
		[
			SNew(STextBlock).Font(Font(15)).ColorAndOpacity(Ink)
				.Visibility_Lambda([W]() { return W.IsValid() && W->Prompt().IsValid() && W->Controller().Panel() == EVerseStationPanel::None ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
				.Text_Lambda([W]()
				{
					if (!W.IsValid())
					{
						return FText::GetEmpty();
					}
					const FVerseStationPrompt& P = W->Prompt();
					return FText::FromString(FString::Printf(TEXT("[%s]  %s  ·  %s"), *P.Key, *P.Label, *P.Action));
				})
		]
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center)
		[
			SNew(SBorder).BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush")).BorderBackgroundColor(Ground).Padding(18.f)
				.Visibility_Lambda([Ctl]() { const FVerseStationController* C = Ctl(); return C && C->Panel() != EVerseStationPanel::None ? EVisibility::Visible : EVisibility::Collapsed; })
			[
				SNew(SBox).WidthOverride(560.f)
				[
					SNew(SVerticalBox)
					// Launcher (parity X-03 to X-06).
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(SVerticalBox).Visibility(PanelIs(EVerseStationPanel::Launcher))
						+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 10.f)
						[
							SNew(STextBlock).Font(Font(20)).ColorAndOpacity(Amber)
								.Text_Lambda([W]() { return FText::FromString(W.IsValid() && W->Controller().Localize ? W->Controller().Localize(TEXT("verse.launcher.title"), TEXT("Master systems console")) : FString()); })
						]
						+ SVerticalBox::Slot().AutoHeight().Padding(2.f)
						[
							SNew(SHorizontalBox)
							+ SHorizontalBox::Slot().FillWidth(1.f)[SNew(STextBlock).Font(Font(14)).ColorAndOpacity(Ink).Text(Option(true))]
							+ SHorizontalBox::Slot().AutoWidth()[Button(FText::FromString(TEXT(">")), Cycle(true))]
						]
						+ SVerticalBox::Slot().AutoHeight().Padding(2.f)
						[
							SNew(SHorizontalBox)
							+ SHorizontalBox::Slot().FillWidth(1.f)[SNew(STextBlock).Font(Font(14)).ColorAndOpacity(Ink).Text(Option(false))]
							+ SHorizontalBox::Slot().AutoWidth()[Button(FText::FromString(TEXT(">")), Cycle(false))]
						]
						+ SVerticalBox::Slot().AutoHeight().Padding(2.f)
						[
							SNew(SHorizontalBox)
							+ SHorizontalBox::Slot().AutoWidth()[Button(FText::FromString(TEXT("-")), [Ctl]() { if (FVerseStationController* C = Ctl()) { C->LauncherSetCount(C->Launcher().Count - 1); } })]
							+ SHorizontalBox::Slot().AutoWidth().Padding(12.f, 0.f).VAlign(VAlign_Center)
							[
								SNew(STextBlock).Font(Font(14)).ColorAndOpacity(Ink)
									.Text_Lambda([Ctl]() { const FVerseStationController* C = Ctl(); return FText::AsNumber(C ? C->Launcher().Count : 1); })
							]
							+ SHorizontalBox::Slot().AutoWidth()[Button(FText::FromString(TEXT("+")), [Ctl]() { if (FVerseStationController* C = Ctl()) { C->LauncherSetCount(C->Launcher().Count + 1); } })]
						]
						+ SVerticalBox::Slot().AutoHeight().Padding(2.f)
						[
							SNew(SEditableTextBox)
								.OnTextChanged_Lambda([Ctl](const FText& T) { if (FVerseStationController* C = Ctl()) { C->LauncherSetBrief(T.ToString()); } })
						]
						+ SVerticalBox::Slot().AutoHeight().Padding(2.f, 8.f)
						[
							SNew(SHorizontalBox)
							+ SHorizontalBox::Slot().AutoWidth()[Button(Label(TEXT("verse.launcher.start"), TEXT("Start")), [Ctl]() { if (FVerseStationController* C = Ctl()) { C->LauncherStart(); } })]
							+ SHorizontalBox::Slot().AutoWidth().Padding(8.f, 0.f)[Button(Label(TEXT("verse.launcher.open_ide"), TEXT("Open the IDE")), [Ctl]() { if (FVerseStationController* C = Ctl()) { C->LauncherOpenIde(); } })]
						]
						+ SVerticalBox::Slot().AutoHeight().Padding(2.f)
						[
							SNew(STextBlock).Font(Font(13)).ColorAndOpacity(Amber)
								.Text_Lambda([Ctl]() { const FVerseStationController* C = Ctl(); return FText::FromString(C ? C->Launcher().Line : FString()); })
						]
					]
					// Simulator (parity S-07).
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(SBox).Visibility(PanelIs(EVerseStationPanel::Simulator))[Programmes]
					]
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Right).Padding(0.f, 10.f, 0.f, 0.f)
					[
						Button(Label(TEXT("verse.station.close"), TEXT("Close")), [Ctl]() { if (FVerseStationController* C = Ctl()) { C->ClosePanel(); } })
					]
				]
			]
		]
	];
}
