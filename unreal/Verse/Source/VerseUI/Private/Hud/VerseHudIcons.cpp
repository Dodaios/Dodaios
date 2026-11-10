#include "Hud/VerseHudIcons.h"

namespace
{
	using FIconPoly = TArray<FVector2D>;
	using FIconShape = TArray<FIconPoly>;

	FIconPoly R(double X0, double Y0, double X1, double Y1)
	{
		return {FVector2D(X0, Y0), FVector2D(X1, Y0), FVector2D(X1, Y1), FVector2D(X0, Y1)};
	}

	FIconPoly P(std::initializer_list<FVector2D> Points)
	{
		return FIconPoly(Points);
	}

	// Graveline: assault rifle with a fixed stock and a curved magazine.
	FIconShape Rifle()
	{
		return {
			P({{0, 5.5}, {12, 5}, {12, 11}, {1, 14.5}}),           // stock
			R(12, 5, 36, 11),                                      // receiver
			R(16, 3.4, 34, 5),                                     // top rail
			R(36, 6, 50, 10),                                      // handguard
			R(47, 4, 49, 6),                                       // front sight
			R(50, 7, 60, 8.8),                                     // barrel
			P({{26, 11}, {31.5, 11}, {34, 18}, {28.5, 19}}),       // magazine
			P({{16.5, 11}, {21, 11}, {19, 17.5}, {14.5, 17}}),     // grip
		};
	}

	// Skitter: compact SMG, folded stock, straight magazine.
	FIconShape Smg()
	{
		return {
			P({{0, 5.5}, {10, 5.5}, {10, 9.5}, {1, 11.5}}),        // folded stock
			R(10, 4, 34, 11),                                      // receiver
			R(14, 2.6, 28, 4),                                     // top rail
			R(34, 6.2, 44, 9.4),                                   // suppressor
			R(20, 11, 24.5, 19.5),                                 // magazine
			P({{12, 11}, {16, 11}, {15, 17}, {11, 17}}),           // grip
		};
	}

	// Longsight: marksman rifle with a scope and a long barrel.
	FIconShape Dmr()
	{
		return {
			P({{0, 6}, {12, 6}, {12, 12}, {1, 15}}),               // stock
			R(12, 6, 34, 11.5),                                    // receiver
			R(34, 7, 46, 10.5),                                    // handguard
			R(46, 7.8, 62, 9.4),                                   // barrel
			R(17, 1.6, 31, 4.2),                                   // scope tube
			P({{31, 1.6}, {35, 0.6}, {35, 5.2}, {31, 4.2}}),       // objective bell
			R(19.5, 4.2, 21.5, 6),                                 // scope ring
			R(27, 4.2, 29, 6),                                     // scope ring
			R(22, 11.5, 26.5, 16.5),                               // magazine
			P({{14, 11.5}, {18, 11.5}, {16.5, 17.5}, {12.5, 17.5}}), // grip
		};
	}

	// Tallow: pistol.
	FIconShape Pistol()
	{
		return {
			R(0, 3, 27, 8.2),                                      // slide
			R(3, 8.2, 25, 10.4),                                   // frame
			P({{3, 10.4}, {10.5, 10.4}, {8.5, 19}, {1.5, 19}}),    // grip
			P({{10.5, 10.4}, {15, 10.4}, {14, 12.4}, {10.5, 12.4}}), // trigger guard
		};
	}

	// Hookbill: knife with a hooked tip.
	FIconShape Knife()
	{
		return {
			R(0, 8, 13, 12),                                       // handle
			R(13, 6, 15, 14),                                      // guard
			P({{15, 7.6}, {36, 7.6}, {43, 9.2}, {15, 12}}),        // blade
			P({{36, 7.6}, {40.5, 4.8}, {43, 9.2}}),                // hook
		};
	}

	// Bulwark: deployable shield.
	FIconShape Shield()
	{
		return {
			R(0, 0, 16, 10),
			P({{0, 10}, {16, 10}, {8, 18}}),
		};
	}

	// Breach charge: a block with a detonator.
	FIconShape Charge()
	{
		return {
			R(0, 5, 18, 16),
			R(7, 1.5, 11, 5),
			R(13, 2.5, 15, 5),
		};
	}
}

namespace VerseHudIcons
{
	const TArray<TArray<FVector2D>>& Shape(FName ItemId)
	{
		static const TMap<FName, FIconShape> Shapes = {
			{TEXT("graveline"), Rifle()},
			{TEXT("skitter"), Smg()},
			{TEXT("longsight"), Dmr()},
			{TEXT("tallow"), Pistol()},
			{TEXT("hookbill"), Knife()},
			{TEXT("knife"), Knife()},
			{TEXT("bulwark"), Shield()},
			{TEXT("breach_charge"), Charge()},
		};
		static const FIconShape Empty;
		const FIconShape* Found = Shapes.Find(ItemId);
		return Found ? *Found : Empty;
	}

	FBox2D Bounds(const TArray<TArray<FVector2D>>& Shape)
	{
		FBox2D Box(ForceInit);
		for (const FIconPoly& Poly : Shape)
		{
			for (const FVector2D& Point : Poly)
			{
				Box += Point;
			}
		}
		return Box;
	}

	bool Triangulate(FName ItemId, const FBox2D& Box, int32 Align, TFunctionRef<void(const FVector2D&, const FVector2D&, const FVector2D&)> Emit)
	{
		const FIconShape& S = Shape(ItemId);
		if (S.Num() == 0)
		{
			return false;
		}
		const FBox2D Src = Bounds(S);
		const FVector2D SrcSize = Src.GetSize();
		const FVector2D DstSize = Box.GetSize();
		if (SrcSize.X <= 0.0 || SrcSize.Y <= 0.0)
		{
			return false;
		}
		const double Scale = FMath::Min(DstSize.X / SrcSize.X, DstSize.Y / SrcSize.Y);
		const FVector2D Size = SrcSize * Scale;
		const double X = Align < 0 ? Box.Min.X : Align > 0 ? Box.Max.X - Size.X : Box.Min.X + (DstSize.X - Size.X) * 0.5;
		const FVector2D Origin(X, Box.Min.Y + (DstSize.Y - Size.Y) * 0.5);
		auto Map = [&](const FVector2D& Point) { return Origin + (Point - Src.Min) * Scale; };
		for (const FIconPoly& Poly : S)
		{
			// Every polygon is convex: a fan from its first point covers it.
			for (int32 I = 1; I + 1 < Poly.Num(); ++I)
			{
				Emit(Map(Poly[0]), Map(Poly[I]), Map(Poly[I + 1]));
			}
		}
		return true;
	}
}
