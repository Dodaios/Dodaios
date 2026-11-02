#include "Crew/VerseCrewCollate.h"

namespace
{
	// Primary weight of one character: group (0 punctuation and space, 1 digits, 2 letters, 3 other),
	// then the case-folded value.
	uint32 PrimaryWeight(TCHAR C)
	{
		if (C >= TEXT('0') && C <= TEXT('9'))
		{
			return (1u << 16) | static_cast<uint32>(C);
		}
		if ((C >= TEXT('a') && C <= TEXT('z')) || (C >= TEXT('A') && C <= TEXT('Z')))
		{
			return (2u << 16) | static_cast<uint32>(FChar::ToLower(C));
		}
		if (C < 128)
		{
			return static_cast<uint32>(C);
		}
		return (3u << 16) | static_cast<uint32>(C);
	}

	int32 Sign(int64 Value)
	{
		return Value < 0 ? -1 : (Value > 0 ? 1 : 0);
	}
}

namespace VerseCrew
{
	int32 LocaleCompare(const FString& A, const FString& B)
	{
		const int32 N = FMath::Min(A.Len(), B.Len());
		for (int32 I = 0; I < N; ++I)
		{
			const uint32 WA = PrimaryWeight(A[I]);
			const uint32 WB = PrimaryWeight(B[I]);
			if (WA != WB)
			{
				return WA < WB ? -1 : 1;
			}
		}
		if (A.Len() != B.Len())
		{
			return A.Len() < B.Len() ? -1 : 1;
		}
		// Tertiary: lower case before upper case at the first difference.
		for (int32 I = 0; I < N; ++I)
		{
			if (A[I] != B[I])
			{
				const bool bLowerA = FChar::IsLower(A[I]);
				const bool bLowerB = FChar::IsLower(B[I]);
				if (bLowerA != bLowerB)
				{
					return bLowerA ? -1 : 1;
				}
				return Sign(static_cast<int64>(A[I]) - static_cast<int64>(B[I]));
			}
		}
		return 0;
	}
}
