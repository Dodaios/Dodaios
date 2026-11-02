#include "Crew/VerseCrewTypes.h"

#include "Crew/VerseCrewCollate.h"

bool VerseCrewServiceOrderLess(const FVerseCrewMember& A, const FVerseCrewMember& B)
{
	if (A.bLead != B.bLead)
	{
		return A.bLead;
	}
	if (A.ArrivalOrder != B.ArrivalOrder)
	{
		return A.ArrivalOrder < B.ArrivalOrder;
	}
	return VerseCrew::LocaleCompare(A.Id, B.Id) < 0;
}

namespace VerseCrew
{
	uint32 Hash32(const FString& Text)
	{
		const FTCHARToUTF16 Utf16(*Text, Text.Len());
		const UTF16CHAR* Units = reinterpret_cast<const UTF16CHAR*>(Utf16.Get());
		uint32 H = 0x811c9dc5u;
		for (int32 Index = 0; Index < Utf16.Length(); ++Index)
		{
			H ^= static_cast<uint32>(Units[Index]);
			H *= 0x01000193u;
		}
		return H;
	}

	// Duty values are exact lower-case enum strings (bridge 4.2); FString == ignores case, so compare case-sensitively.
	bool TryParseDuty(const FString& Value, EVerseCrewDuty& Out)
	{
		if (Value.Equals(TEXT("working"), ESearchCase::CaseSensitive)) { Out = EVerseCrewDuty::Working; return true; }
		if (Value.Equals(TEXT("waiting"), ESearchCase::CaseSensitive)) { Out = EVerseCrewDuty::Waiting; return true; }
		if (Value.Equals(TEXT("idle"), ESearchCase::CaseSensitive)) { Out = EVerseCrewDuty::Idle; return true; }
		if (Value.Equals(TEXT("paused"), ESearchCase::CaseSensitive)) { Out = EVerseCrewDuty::Paused; return true; }
		if (Value.Equals(TEXT("error"), ESearchCase::CaseSensitive)) { Out = EVerseCrewDuty::Error; return true; }
		return false;
	}

	EVerseCrewDuty ParseDuty(const FString& Value)
	{
		EVerseCrewDuty Duty = EVerseCrewDuty::Idle;
		return TryParseDuty(Value, Duty) ? Duty : EVerseCrewDuty::Idle;
	}

	const TCHAR* DutyName(EVerseCrewDuty Duty)
	{
		switch (Duty)
		{
		case EVerseCrewDuty::Working: return TEXT("working");
		case EVerseCrewDuty::Waiting: return TEXT("waiting");
		case EVerseCrewDuty::Paused: return TEXT("paused");
		case EVerseCrewDuty::Error: return TEXT("error");
		default: return TEXT("idle");
		}
	}

	const TCHAR* VenueName(EVerseCrewVenue Venue)
	{
		switch (Venue)
		{
		case EVerseCrewVenue::Console: return TEXT("console");
		case EVerseCrewVenue::Terminal: return TEXT("terminal");
		case EVerseCrewVenue::Briefing: return TEXT("briefing");
		case EVerseCrewVenue::Mess: return TEXT("mess");
		case EVerseCrewVenue::Corridor: return TEXT("corridor");
		case EVerseCrewVenue::Viewport: return TEXT("viewport");
		case EVerseCrewVenue::Bunk: return TEXT("bunk");
		default: return TEXT("workshop");
		}
	}

	const TCHAR* ActivityName(EVerseCrewActivity Activity)
	{
		switch (Activity)
		{
		case EVerseCrewActivity::SitType: return TEXT("sit_type");
		case EVerseCrewActivity::StandWait: return TEXT("stand_wait");
		case EVerseCrewActivity::StandAlert: return TEXT("stand_alert");
		case EVerseCrewActivity::SitRest: return TEXT("sit_rest");
		case EVerseCrewActivity::StandRest: return TEXT("stand_rest");
		case EVerseCrewActivity::Sleep: return TEXT("sleep");
		case EVerseCrewActivity::Talk: return TEXT("talk");
		case EVerseCrewActivity::Listen: return TEXT("listen");
		case EVerseCrewActivity::StandGuard: return TEXT("stand_guard");
		default: return TEXT("walk");
		}
	}

	float WalkPaceCmPerSecond(const FString& Id)
	{
		const uint32 H = Hash32(Id + TEXT(":pace"));
		return 100.f * (1.2f + static_cast<float>(H % 26u) / 100.f);
	}
}
