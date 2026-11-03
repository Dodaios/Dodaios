#include "Stations/VerseStationTypes.h"

namespace VerseStations
{
	namespace
	{
		struct FKindRow
		{
			const TCHAR* Name;
			const TCHAR* FallbackName;
			const TCHAR* FallbackAction;
		};

		// English strings of the ship locale (frontend i18n/locales/ship/verse.en.json); the app sends
		// the person's language in welcome.locale.strings, these only cover a link without one.
		const FKindRow Rows[KindCount] = {
			{TEXT("agents_list"), TEXT("Command station"), TEXT("Open the crew list")},
			{TEXT("team"), TEXT("Briefing table"), TEXT("Open the team")},
			{TEXT("service_record"), TEXT("Records hall"), TEXT("Open your service record")},
			{TEXT("mess_call"), TEXT("Mess hall"), TEXT("Call the off-duty crew to the mess")},
			{TEXT("games"), TEXT("Simulator room"), TEXT("Start a simulation")},
			{TEXT("quartermaster"), TEXT("Quartermaster"), TEXT("Choose your uniform")},
			{TEXT("coding_launcher"), TEXT("Master systems console"), TEXT("Start coding agents")},
			{TEXT("create_agent"), TEXT("Arrivals desk"), TEXT("Bring a new officer aboard")},
			{TEXT("lift"), TEXT("Lift"), TEXT("Ride to another deck")},
			{TEXT("armoury"), TEXT("Armoury"), TEXT("Open the duel")},
		};

		const FKindRow& Row(EVerseStationKind Kind) { return Rows[FMath::Clamp(int32(Kind), 0, KindCount - 1)]; }
	}

	FName KindName(EVerseStationKind Kind) { return FName(Row(Kind).Name); }

	bool KindFromName(FName Name, EVerseStationKind& OutKind)
	{
		for (int32 I = 0; I < KindCount; ++I)
		{
			if (Name == FName(Rows[I].Name))
			{
				OutKind = EVerseStationKind(I);
				return true;
			}
		}
		return false;
	}

	FString NameKey(EVerseStationKind Kind) { return FString::Printf(TEXT("verse.station.%s.name"), Row(Kind).Name); }
	FString ActionKey(EVerseStationKind Kind) { return FString::Printf(TEXT("verse.station.%s.action"), Row(Kind).Name); }
	FString FallbackName(EVerseStationKind Kind) { return Row(Kind).FallbackName; }
	FString FallbackAction(EVerseStationKind Kind) { return Row(Kind).FallbackAction; }
}
