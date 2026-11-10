#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"

class UVerseStationUISubsystem;

/**
 * The plain Slate overlay of the station views: prompt below the view centre (parity S-13),
 * notice line, launcher and simulator panels. Stands in for WP18's UI root.
 */
class SVerseStationPanel : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SVerseStationPanel) {}
		SLATE_ARGUMENT(TWeakObjectPtr<UVerseStationUISubsystem>, Owner)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

private:
	TWeakObjectPtr<UVerseStationUISubsystem> Owner;
};
