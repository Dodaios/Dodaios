#pragma once

#include "CoreMinimal.h"

/** Called with the id of the line a click dismissed. */
DECLARE_DELEGATE_OneParam(FOnVerseQuietDismiss, int64);

struct VERSEUI_API FVerseQuietEntry
{
	int64 Id = 0;
	FText Text;
	/** The plate shown beside the line. */
	FName RankId;
	/** Local time the line goes. */
	double Until = 0.0;
};

/**
 * The quiet level-up lines in the corner (parity R-11): any level-up that is not the
 * commander's or the companion's new rank. Up to three lines, each five seconds or until a
 * click; a fourth pushes out the oldest.
 */
class VERSEUI_API FVerseQuietStack
{
public:
	static constexpr double Seconds = 5.0;
	static constexpr int32 MaxVisible = 3;

	void Add(int64 Id, const FText& Text, FName RankId, double Now);
	/** A click on a line. True when it was there. */
	bool Dismiss(int64 Id);
	/** Drops the lines whose time is up. True when something went. */
	bool Tick(double Now);
	void Clear();

	bool Contains(int64 Id) const;
	const TArray<FVerseQuietEntry>& Entries() const { return Lines; }
	/** Changes with every change of the lines, so a view knows when to lay them out again. */
	uint32 Revision() const { return Version; }

private:
	TArray<FVerseQuietEntry> Lines;
	uint32 Version = 0;
};
