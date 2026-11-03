#include "Penetration/VersePenetrationPhysicalMaterial.h"

namespace VersePenetration
{
	EVersePenetrationMaterial WorldSurfaceMaterial(EVerseWorldSurface Surface)
	{
		switch (Surface)
		{
		case EVerseWorldSurface::StructuralBeam:
			return EVersePenetrationMaterial::ArmorSteel;
		case EVerseWorldSurface::HallFloor:
		case EVerseWorldSurface::StructuralWall:
		default:
			return EVersePenetrationMaterial::Concrete;
		}
	}

	FString PhysicalMaterialName(EVerseWorldSurface Surface)
	{
		switch (Surface)
		{
		case EVerseWorldSurface::HallFloor:
			return TEXT("PM_Verse_HallFloor");
		case EVerseWorldSurface::StructuralBeam:
			return TEXT("PM_Verse_StructuralBeam");
		case EVerseWorldSurface::StructuralWall:
		default:
			return TEXT("PM_Verse_StructuralWall");
		}
	}

	bool SurfaceFromPhysicalMaterialName(const FString& Name, EVerseWorldSurface& OutSurface)
	{
		const EVerseWorldSurface Surfaces[] = {EVerseWorldSurface::HallFloor, EVerseWorldSurface::StructuralWall, EVerseWorldSurface::StructuralBeam};
		for (const EVerseWorldSurface Surface : Surfaces)
		{
			const FString Base = PhysicalMaterialName(Surface);
			if (Name.Equals(Base, ESearchCase::IgnoreCase)
				|| (Name.StartsWith(Base + TEXT("_"), ESearchCase::IgnoreCase)))
			{
				OutSurface = Surface;
				return true;
			}
		}
		return false;
	}

	EVersePenetrationMaterial ResolveWorldMaterial(const UObject* PhysicalMaterial)
	{
		EVerseWorldSurface Surface = EVerseWorldSurface::StructuralWall;
		if (PhysicalMaterial && SurfaceFromPhysicalMaterialName(PhysicalMaterial->GetName(), Surface))
		{
			return WorldSurfaceMaterial(Surface);
		}
		return EVersePenetrationMaterial::Concrete;
	}
}
