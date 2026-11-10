#include "Hud/VerseHudIcons.h"

#include "Engine/Texture2D.h"
#include "ImageUtils.h"
#include "Misc/Paths.h"

namespace
{
	struct FIconInfo
	{
		const TCHAR* Stem;
		/** Width over height of the trimmed icon (hud_icons.py output). */
		float Aspect;
	};

	/** Stored heights, ascending (hud_icons.py HEIGHTS). */
	constexpr int32 Heights[] = {32, 64, 128};

	const FIconInfo* Find(FName ItemId)
	{
		static const TMap<FName, FIconInfo> Icons = {
			{TEXT("graveline"), {TEXT("graveline"), 3.891f}},
			{TEXT("skitter"), {TEXT("skitter"), 2.195f}},
			{TEXT("longsight"), {TEXT("longsight"), 4.211f}},
			{TEXT("tallow"), {TEXT("tallow"), 1.195f}},
			{TEXT("hookbill"), {TEXT("hookbill"), 6.297f}},
			// The melee slot reports "knife" when it has no definition id.
			{TEXT("knife"), {TEXT("hookbill"), 6.297f}},
			{TEXT("bulwark"), {TEXT("bulwark"), 0.836f}},
			{TEXT("breach_charge"), {TEXT("breach_charge"), 1.133f}},
		};
		return Icons.Find(ItemId);
	}
}

namespace VerseHudIcons
{
	bool Has(FName ItemId)
	{
		return Find(ItemId) != nullptr;
	}

	float Aspect(FName ItemId)
	{
		const FIconInfo* Info = Find(ItemId);
		return Info ? Info->Aspect : 0.f;
	}

	FString Directory()
	{
		return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data"), TEXT("ui"), TEXT("icons"));
	}

	UTexture2D* Texture(FName ItemId, float DrawHeightPx)
	{
		const FIconInfo* Info = Find(ItemId);
		if (!Info)
		{
			return nullptr;
		}
		int32 Height = Heights[UE_ARRAY_COUNT(Heights) - 1];
		for (int32 H : Heights)
		{
			if (H >= DrawHeightPx)
			{
				Height = H;
				break;
			}
		}
		const FString Key = FString::Printf(TEXT("%s_%d"), Info->Stem, Height);
		// Rooted for the whole session (static smart pointers would outlive the object system);
		// a missing file is remembered as null so it is read once.
		static TMap<FString, UTexture2D*> Cache;
		if (UTexture2D* const* Found = Cache.Find(Key))
		{
			return *Found;
		}
		UTexture2D* Loaded = nullptr;
		const FString Path = FPaths::Combine(Directory(), Key + TEXT(".png"));
		if (FPaths::FileExists(Path))
		{
			Loaded = FImageUtils::ImportFileAsTexture2D(Path);
			if (Loaded)
			{
				Loaded->Filter = TF_Bilinear;
				Loaded->SRGB = true;
				Loaded->LODGroup = TEXTUREGROUP_UI;
				Loaded->UpdateResource();
				Loaded->AddToRoot();
			}
		}
		Cache.Add(Key, Loaded);
		return Loaded;
	}
}
