#include "Notices/VerseNoticeLine.h"

void FVerseNoticeLine::Post(const FText& InText, double Now, EKind InKind, double Seconds)
{
	if (InText.IsEmpty())
	{
		return;
	}
	Text = InText;
	Kind = InKind;
	PostedAt = Now;
	Lifetime = Seconds;
	bHas = true;
}

void FVerseNoticeLine::Clear()
{
	Text = FText::GetEmpty();
	bHas = false;
}

double FVerseNoticeLine::Remaining(double Now) const
{
	return bHas ? FMath::Max(0.0, PostedAt + Lifetime - Now) : 0.0;
}

bool FVerseNoticeLine::IsVisible(double Now) const
{
	return bHas && Now < PostedAt + Lifetime;
}

FText FVerseNoticeLine::GetText(double Now) const
{
	return IsVisible(Now) ? Text : FText::GetEmpty();
}
