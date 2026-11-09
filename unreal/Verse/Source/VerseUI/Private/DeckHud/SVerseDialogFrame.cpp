#include "DeckHud/SVerseDialogFrame.h"

#include "DeckHud/VerseSlateKit.h"
#include "Framework/Application/SlateApplication.h"
#include "InputCoreTypes.h"
#include "Widgets/SOverlay.h"

void SVerseDialogFrame::Construct(const FArguments& InArgs)
{
	OnClose = InArgs._OnClose;
	bHandleEscape = InArgs._bHandleEscape;
	bTakeFocus = InArgs._bTakeFocus;
	InitialFocusIndex = InArgs._InitialFocusIndex;

	TSharedRef<SOverlay> Layers = SNew(SOverlay);
	if (InArgs._bScrim)
	{
		Layers->AddSlot()
		[
			SNew(SBorder)
			.BorderImage(VerseSlateKit::Colour(FLinearColor(0.f, 0.f, 0.f, 0.55f)))
			.OnMouseButtonDown_Lambda([this](const FGeometry&, const FPointerEvent&)
			{
				OnClose.ExecuteIfBound();
				return FReply::Handled();
			})
		];
	}
	Layers->AddSlot()
	.HAlign(HAlign_Center)
	.VAlign(VAlign_Center)
	[
		InArgs._Content.Widget
	];
	ChildSlot[Layers];

	if (bTakeFocus && FSlateApplication::IsInitialized())
	{
		Opener = FSlateApplication::Get().GetUserFocusedWidget(0);
		RegisterActiveTimer(0.f, FWidgetActiveTimerDelegate::CreateSP(this, &SVerseDialogFrame::TakeFocus));
	}
}

SVerseDialogFrame::~SVerseDialogFrame()
{
	if (bTakeFocus && FSlateApplication::IsInitialized())
	{
		if (const TSharedPtr<SWidget> Back = Opener.Pin())
		{
			FSlateApplication::Get().SetUserFocus(0, Back, EFocusCause::Navigation);
		}
	}
}

EActiveTimerReturnType SVerseDialogFrame::TakeFocus(double, float)
{
	const TArray<TSharedRef<SWidget>> List = CollectFocusables();
	if (List.Num() > 0 && FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().SetUserFocus(0, List[FMath::Clamp(InitialFocusIndex, 0, List.Num() - 1)], EFocusCause::Navigation);
	}
	return EActiveTimerReturnType::Stop;
}

void SVerseDialogFrame::CollectFrom(const TSharedRef<SWidget>& Widget, TArray<TSharedRef<SWidget>>& Out) const
{
	if (Widget->GetVisibility().IsVisible() && Widget->IsEnabled() && Widget->SupportsKeyboardFocus() && Widget != AsShared())
	{
		Out.Add(Widget);
	}
	FChildren* Children = Widget->GetChildren();
	for (int32 Index = 0; Children && Index < Children->Num(); ++Index)
	{
		CollectFrom(Children->GetChildAt(Index), Out);
	}
}

TArray<TSharedRef<SWidget>> SVerseDialogFrame::CollectFocusables() const
{
	TArray<TSharedRef<SWidget>> Out;
	FChildren* Children = const_cast<SVerseDialogFrame*>(this)->GetChildren();
	for (int32 Index = 0; Children && Index < Children->Num(); ++Index)
	{
		CollectFrom(Children->GetChildAt(Index), Out);
	}
	return Out;
}

bool SVerseDialogFrame::NavigationOfKey(const FKey& Key, bool bShift, EVerseDialogNav& Out)
{
	if (Key == EKeys::Tab)
	{
		Out = bShift ? EVerseDialogNav::Previous : EVerseDialogNav::Next;
	}
	else if (Key == EKeys::Up || Key == EKeys::Gamepad_DPad_Up || Key == EKeys::Gamepad_LeftStick_Up)
	{
		Out = EVerseDialogNav::Up;
	}
	else if (Key == EKeys::Down || Key == EKeys::Gamepad_DPad_Down || Key == EKeys::Gamepad_LeftStick_Down)
	{
		Out = EVerseDialogNav::Down;
	}
	else if (Key == EKeys::Left || Key == EKeys::Gamepad_DPad_Left || Key == EKeys::Gamepad_LeftStick_Left)
	{
		Out = EVerseDialogNav::Left;
	}
	else if (Key == EKeys::Right || Key == EKeys::Gamepad_DPad_Right || Key == EKeys::Gamepad_LeftStick_Right)
	{
		Out = EVerseDialogNav::Right;
	}
	else
	{
		return false;
	}
	return true;
}

FReply SVerseDialogFrame::OnPreviewKeyDown(const FGeometry&, const FKeyEvent& KeyEvent)
{
	const FKey Key = KeyEvent.GetKey();
	if (Key == EKeys::Escape || Key == EKeys::Gamepad_FaceButton_Right)
	{
		if (bHandleEscape)
		{
			OnClose.ExecuteIfBound();
		}
		return bHandleEscape ? FReply::Handled() : FReply::Unhandled();
	}
	EVerseDialogNav Nav;
	if (!NavigationOfKey(Key, KeyEvent.IsShiftDown(), Nav))
	{
		return FReply::Unhandled();
	}
	const TArray<TSharedRef<SWidget>> List = CollectFocusables();
	if (List.Num() == 0)
	{
		return FReply::Handled();  // nothing to reach, and nothing outside gets the key
	}
	const TSharedPtr<SWidget> Focused = FSlateApplication::Get().GetUserFocusedWidget(KeyEvent.GetUserIndex());
	int32 Index = INDEX_NONE;
	for (int32 I = 0; I < List.Num(); ++I)
	{
		if (Focused.IsValid() && List[I] == Focused.ToSharedRef())
		{
			Index = I;
			break;
		}
	}
	const int32 Next = FVerseDialogStack::StepIndex(Index, List.Num(), Nav);
	FSlateApplication::Get().SetUserFocus(KeyEvent.GetUserIndex(), List[Next], EFocusCause::Navigation);
	return FReply::Handled();
}
