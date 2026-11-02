#include "Penetration/VersePenetrationPhysicalMaterial.h"

EVersePenetrationMaterial UVersePenetrationPhysicalMaterial::GetPenetrationMaterial() const
{
	return VersePenetration::WorldSurfaceMaterial(Surface);
}

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

	EVersePenetrationMaterial ResolveWorldMaterial(const UPhysicalMaterial* PhysicalMaterial)
	{
		if (const UVersePenetrationPhysicalMaterial* Verse = Cast<UVersePenetrationPhysicalMaterial>(PhysicalMaterial))
		{
			return Verse->GetPenetrationMaterial();
		}
		return EVersePenetrationMaterial::Concrete;
	}
}
