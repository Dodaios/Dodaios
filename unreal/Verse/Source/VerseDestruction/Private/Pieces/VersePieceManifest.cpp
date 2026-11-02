#include "Pieces/VersePieceManifest.h"

#include "Algo/BinarySearch.h"
#include "EngineUtils.h"
#include "Pieces/VerseDestructible.h"

void UVersePieceManifest::SortGuids(TArray<FGuid>& Guids)
{
	Guids.Sort([](const FGuid& A, const FGuid& B) { return A < B; });
}

uint32 UVersePieceManifest::ComputeHash(TConstArrayView<FGuid> Guids)
{
	uint32 Crc = 0;
	for (const FGuid& Guid : Guids)
	{
		const uint32 Words[4] = {Guid.A, Guid.B, Guid.C, Guid.D};
		Crc = FCrc::MemCrc32(Words, sizeof(Words), Crc);
	}
	return Crc ^ uint32(Guids.Num());
}

bool UVersePieceManifest::Build(TArray<FGuid> Guids, FString* OutError)
{
	for (const FGuid& Guid : Guids)
	{
		if (!Guid.IsValid())
		{
			if (OutError)
			{
				*OutError = TEXT("a destructible has no valid GUID");
			}
			return false;
		}
	}
	SortGuids(Guids);
	const int32 Before = Guids.Num();
	for (int32 Index = Guids.Num() - 1; Index > 0; --Index)
	{
		if (Guids[Index] == Guids[Index - 1])
		{
			Guids.RemoveAt(Index);
		}
	}
	if (Guids.Num() != Before && OutError)
	{
		*OutError = FString::Printf(TEXT("%d duplicate GUIDs dropped"), Before - Guids.Num());
	}
	if (Guids.Num() > MaxPieces)
	{
		if (OutError)
		{
			*OutError = FString::Printf(TEXT("%d pieces, the limit is %d per deck"), Guids.Num(), MaxPieces);
		}
		return false;
	}
	PieceGuids = MoveTemp(Guids);
	Hash = ComputeHash(PieceGuids);
	return true;
}

int32 UVersePieceManifest::IndexOf(const FGuid& Guid) const
{
	const int32 Index = Algo::LowerBound(PieceGuids, Guid, [](const FGuid& A, const FGuid& B) { return A < B; });
	return (PieceGuids.IsValidIndex(Index) && PieceGuids[Index] == Guid) ? Index : INDEX_NONE;
}

bool UVersePieceManifest::IsConsistent() const
{
	for (int32 Index = 1; Index < PieceGuids.Num(); ++Index)
	{
		if (!(PieceGuids[Index - 1] < PieceGuids[Index]))
		{
			return false;
		}
	}
	return PieceGuids.Num() <= MaxPieces && Hash == ComputeHash(PieceGuids);
}

#if WITH_EDITOR
TArray<FGuid> UVersePieceManifest::CollectFromWorld(const UWorld& World)
{
	TArray<FGuid> Out;
	for (TActorIterator<AVerseDestructible> It(&World); It; ++It)
	{
		Out.Add(It->GetPieceGuid());
	}
	return Out;
}
#endif
