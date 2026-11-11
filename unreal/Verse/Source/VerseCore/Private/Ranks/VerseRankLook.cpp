#include "Ranks/VerseRankLook.h"

#include "Components/MeshComponent.h"
#include "Materials/MaterialInstanceDynamic.h"

namespace VerseRanks
{
	TConstArrayView<FRank> Ladder()
	{
		// RANKS-BEGIN (progression/ranks.ts RANKS)
		static const FRank Table[] = {
			{ TEXT("recruit"), 1, TEXT("deck"), TEXT("000|010") },
			{ TEXT("deckhand"), 3, TEXT("deck"), TEXT("000|101") },
			{ TEXT("technician"), 5, TEXT("deck"), TEXT("000|111") },
			{ TEXT("senior_technician"), 8, TEXT("deck"), TEXT("010|111") },
			{ TEXT("ensign"), 11, TEXT("line"), TEXT("010|000") },
			{ TEXT("lieutenant"), 14, TEXT("line"), TEXT("101|000") },
			{ TEXT("senior_lieutenant"), 17, TEXT("line"), TEXT("111|000") },
			{ TEXT("commander"), 21, TEXT("line"), TEXT("111|010") },
			{ TEXT("captain"), 25, TEXT("line"), TEXT("111|101") },
			{ TEXT("line_captain"), 29, TEXT("command"), TEXT("010|010") },
			{ TEXT("commodore"), 33, TEXT("command"), TEXT("101|010") },
			{ TEXT("rear_admiral"), 37, TEXT("flag"), TEXT("010|101") },
			{ TEXT("vice_admiral"), 41, TEXT("flag"), TEXT("101|101") },
			{ TEXT("admiral"), 45, TEXT("flag"), TEXT("101|111") },
			{ TEXT("fleet_admiral"), 50, TEXT("flag"), TEXT("111|111") },
		};
		// RANKS-END
		return Table;
	}

	TConstArrayView<FTier> Tiers()
	{
		// TIERS-BEGIN (characters/build.py TIERS, tile = ranks.ts TIER_STYLE)
		static const FTier Table[] = {
			{ TEXT("deck"), TEXT("#3b3f47"), TEXT("#3b3f47"), TEXT("#5a5f68"), TEXT("#3b3f47"), TEXT("#a9adb2") },
			{ TEXT("line"), TEXT("#34404f"), TEXT("#2a3340"), TEXT("#262f3b"), TEXT("#34404f"), TEXT("#4d86d9") },
			{ TEXT("command"), TEXT("#24262b"), TEXT("#1b1c20"), TEXT("#a8873e"), TEXT("#24262b"), TEXT("#c27a3a") },
			{ TEXT("flag"), TEXT("#4a1d24"), TEXT("#1b1c20"), TEXT("#c8a24a"), TEXT("#4a1d24"), TEXT("#c8a24a") },
		};
		// TIERS-END
		return Table;
	}

	const FRank& ForLevel(int32 Level)
	{
		const TConstArrayView<FRank> All = Ladder();
		const FRank* Best = &All[0];
		for (const FRank& Rank : All)
		{
			if (Rank.Level <= Level)
			{
				Best = &Rank;
			}
		}
		return *Best;
	}

	const FTier* FindTier(FName Tier)
	{
		for (const FTier& Entry : Tiers())
		{
			if (Tier == FName(Entry.Id))
			{
				return &Entry;
			}
		}
		return nullptr;
	}

	TArray<int32> LitSlots(const FString& Plate)
	{
		TArray<int32> Out;
		const FString Bits = Plate.Replace(TEXT("|"), TEXT(""));
		for (int32 I = 0; I < Bits.Len() && I < 6; ++I)
		{
			if (Bits[I] == TEXT('1'))
			{
				Out.Add(I);
			}
		}
		return Out;
	}

	FLinearColor Linear(const TCHAR* Hex)
	{
		return FLinearColor::FromSRGBColor(FColor::FromHex(Hex));
	}

	FLinearColor TileUnlit()
	{
		return Linear(TEXT("#2a2d31"));
	}

	int32 ApplyLook(UMeshComponent* Body, FName Tier, const FString& Plate, const FLinearColor* Accent)
	{
		const FTier* Style = FindTier(Tier);
		if (Body == nullptr || Style == nullptr)
		{
			return 0;
		}
		int32 Set = 0;
		auto Paint = [Body, &Set](const TCHAR* Slot, const FLinearColor& Colour, const FLinearColor* Glow)
		{
			const int32 Index = Body->GetMaterialIndex(FName(Slot));
			if (Index == INDEX_NONE)
			{
				return;
			}
			if (UMaterialInstanceDynamic* Instance = Body->CreateDynamicMaterialInstance(Index))
			{
				Instance->SetVectorParameterValue(TEXT("BaseTint"), Colour);
				if (Glow)
				{
					Instance->SetVectorParameterValue(TEXT("EmissiveColor"), *Glow);
				}
				++Set;
			}
		};
		Paint(TEXT("M_Uniform"), Linear(Style->Uniform), nullptr);
		Paint(TEXT("M_Trousers"), Linear(Style->Trousers), nullptr);
		Paint(TEXT("M_Trim"), Linear(Style->Trim), nullptr);
		Paint(TEXT("M_Cap"), Linear(Style->Cap), nullptr);
		if (Accent)
		{
			Paint(TEXT("M_Accent"), *Accent, nullptr);
		}
		const TArray<int32> Lit = LitSlots(Plate);
		const FLinearColor Tile = Linear(Style->Tile);
		const FLinearColor Glow = Tile * (LitTileEmission * EmitToNits);
		const FLinearColor Dark = FLinearColor::Black;
		for (int32 Slot = 0; Slot < 6; ++Slot)
		{
			const FString Name = FString::Printf(TEXT("M_RankTile_%d"), Slot + 1);
			const bool bLit = Lit.Contains(Slot);
			Paint(*Name, bLit ? Tile : TileUnlit(), bLit ? &Glow : &Dark);
		}
		return Set;
	}

	int32 ApplyLevel(UMeshComponent* Body, int32 Level, const FLinearColor* Accent)
	{
		const FRank& Rank = ForLevel(Level);
		return ApplyLook(Body, FName(Rank.Tier), Rank.Plate, Accent);
	}
}
