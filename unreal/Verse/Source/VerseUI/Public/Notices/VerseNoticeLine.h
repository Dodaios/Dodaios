#pragma once

#include "CoreMinimal.h"

/**
 * The one line of text under the deck title (parity H-07): a notice lives 4.2 s, help text
 * 15 s. A new line replaces the one on screen. Time is the caller's clock (real seconds), so a
 * test pins it.
 */
class VERSEUI_API FVerseNoticeLine
{
public:
	/** A notice (a view switch, a crew call): 4.2 s. */
	static constexpr double NoticeSeconds = 4.2;
	/** Help text: 15 s. */
	static constexpr double HelpSeconds = 15.0;

	enum class EKind : uint8
	{
		Notice,
		Help,
	};

	void PostNotice(const FText& InText, double Now) { Post(InText, Now, EKind::Notice, NoticeSeconds); }
	void PostHelp(const FText& InText, double Now) { Post(InText, Now, EKind::Help, HelpSeconds); }
	void Post(const FText& InText, double Now, EKind InKind, double Seconds);
	void Clear();

	bool IsVisible(double Now) const;
	/** The line on screen, empty once it expired. */
	FText GetText(double Now) const;
	EKind GetKind() const { return Kind; }
	double Remaining(double Now) const;
	double GetPostedAt() const { return PostedAt; }
	double GetLifetime() const { return Lifetime; }

private:
	FText Text;
	EKind Kind = EKind::Notice;
	double PostedAt = 0.0;
	double Lifetime = 0.0;
	bool bHas = false;
};
