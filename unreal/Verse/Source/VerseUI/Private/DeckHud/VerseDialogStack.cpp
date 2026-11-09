#include "DeckHud/VerseDialogStack.h"

void FVerseDialogStack::Open(FName Id, FName Opener, const TArray<FName>& Focusables, FName InitialFocus)
{
	Close(Id);
	FDialog Dialog;
	Dialog.Id = Id;
	// A dialog opened from another dialog returns to the widget focused there.
	Dialog.Opener = Opener.IsNone() ? GetFocused() : Opener;
	Dialog.Focusables = Focusables;
	Dialog.Focused = Focusables.Contains(InitialFocus) ? InitialFocus : (Focusables.Num() > 0 ? Focusables[0] : NAME_None);
	Stack.Add(MoveTemp(Dialog));
}

FName FVerseDialogStack::PopTop()
{
	if (Stack.Num() == 0)
	{
		return NAME_None;
	}
	const FName Opener = Stack.Last().Opener;
	Stack.Pop();
	if (Stack.Num() == 0)
	{
		BaseFocus = Opener;
	}
	else
	{
		Stack.Last().Focused = Opener;
	}
	return Opener;
}

FName FVerseDialogStack::Close(FName Id)
{
	const int32 Index = Stack.IndexOfByPredicate([Id](const FDialog& D) { return D.Id == Id; });
	if (Index == INDEX_NONE)
	{
		return NAME_None;
	}
	FName Returned = NAME_None;
	while (Stack.Num() > Index)
	{
		Returned = PopTop();
	}
	return Returned;
}

bool FVerseDialogStack::HandleEscape(FName* OutFocusReturn)
{
	if (Stack.Num() == 0)
	{
		return false;
	}
	const FName Returned = PopTop();
	if (OutFocusReturn)
	{
		*OutFocusReturn = Returned;
	}
	return true;
}

bool FVerseDialogStack::HandleScrimClick(FName* OutFocusReturn)
{
	return HandleEscape(OutFocusReturn);
}

bool FVerseDialogStack::HandleNavigate(EVerseDialogNav Direction)
{
	if (Stack.Num() == 0)
	{
		return false;
	}
	FDialog& Dialog = Stack.Last();
	const int32 Count = Dialog.Focusables.Num();
	if (Count == 0)
	{
		return true;  // nothing to focus, but the key stays inside
	}
	const int32 Next = StepIndex(Dialog.Focusables.IndexOfByKey(Dialog.Focused), Count, Direction);
	Dialog.Focused = Dialog.Focusables[Next];
	return true;
}

void FVerseDialogStack::SetFocused(FName Widget)
{
	if (Stack.Num() > 0 && Stack.Last().Focusables.Contains(Widget))
	{
		Stack.Last().Focused = Widget;
	}
}

FName FVerseDialogStack::GetFocused() const
{
	return Stack.Num() > 0 ? Stack.Last().Focused : BaseFocus;
}

bool FVerseDialogStack::IsOpen(FName Id) const
{
	return Stack.ContainsByPredicate([Id](const FDialog& D) { return D.Id == Id; });
}

bool FVerseDialogStack::IsBlocked(FName Widget) const
{
	return Stack.Num() > 0 && !Stack.Last().Focusables.Contains(Widget);
}

int32 FVerseDialogStack::StepIndex(int32 Index, int32 Count, EVerseDialogNav Direction)
{
	if (Count <= 0)
	{
		return INDEX_NONE;
	}
	const int32 Step = (Direction == EVerseDialogNav::Previous || Direction == EVerseDialogNav::Up || Direction == EVerseDialogNav::Left) ? -1 : 1;
	return Index == INDEX_NONE ? (Step > 0 ? 0 : Count - 1) : ((Index + Step) % Count + Count) % Count;
}
