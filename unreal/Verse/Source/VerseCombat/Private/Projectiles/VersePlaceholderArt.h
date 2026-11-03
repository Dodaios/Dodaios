#pragma once

#include "CoreMinimal.h"

class UMaterialInterface;
class UStaticMesh;

/**
 * WP02 placeholder look until WP14 (bolts, impacts, Bulwark slab, breach charge, test floor).
 * The shapes are built in code at first use (transient meshes, own geometry, no imported or
 * engine sample content); the material is the WP02 test material with a "Color" vector
 * parameter. Unit sizes: box 100 cm, cylinder 100 cm across and 100 cm tall along Z, sphere
 * 100 cm across, plane 100 x 100 cm facing +Z; all centred on the origin.
 */
namespace VersePlaceholderArt
{
	enum class EShape : uint8
	{
		Box,
		Cylinder,
		Sphere,
		Plane,
	};

	/** The shared transient mesh of a shape; null when the world cannot render. */
	UStaticMesh* Mesh(EShape Shape);

	/** /Game/Verse/Test/WP02/M_WP02_Placeholder (vector parameter "Color"). */
	UMaterialInterface* Material();
}
