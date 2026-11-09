#include "Notices/VerseQuietStack.h"

void FVerseQuietStack::Add(int64 Id, const FText& Text, FName RankId, double Now)
{
	if (Contains(Id))
	{
		return;
	}
	FVerseQuietEntry Entry;
	Entry.Id = Id;
	Entry.Text = Text;
	Entry.RankId = RankId;
	Entry.Until = Now + Seconds;
	Lines.Add(Entry);
	while (Lines.Num() > MaxVisible)
	{
		Lines.RemoveAt(0);
	}
	++Version;
}

bool FVerseQuietStack::Dismiss(int64 Id)
{
	const int32 Index = Lines.IndexOfByPredicate([Id](const FVerseQuietEntry& E) { return E.Id == Id; });
	if (Index == INDEX_NONE)
	{
		return false;
	}
	Lines.RemoveAt(Index);
	++Version;
	return true;
}

bool FVerseQuietStack::Tick(double Now)
{
	const int32 Before = Lines.Num();
	Lines.RemoveAll([Now](const FVerseQuietEntry& E) { return Now >= E.Until; });
	if (Lines.Num() != Before)
	{
		++Version;
		return true;
	}
	return false;
}

void FVerseQuietStack::Clear()
{
	if (Lines.Num() > 0)
	{
		Lines.Reset();
		++Version;
	}
}

bool FVerseQuietStack::Contains(int64 Id) const
{
	return Lines.ContainsByPredicate([Id](const FVerseQuietEntry& E) { return E.Id == Id; });
}
