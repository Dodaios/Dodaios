#pragma once

#include "CoreMinimal.h"
#include "Misc/Build.h"

#if WITH_DEV_AUTOMATION_TESTS

/** CIEDE2000 for the A16.3 colour tests (headless and rendered). */
namespace VerseColourDifference
{
	/** sRGB 8-bit to CIELAB (D65). */
	inline FVector3d ToLab(const FColor& C)
	{
		auto Lin = [](double V)
		{
			V /= 255.0;
			return V <= 0.04045 ? V / 12.92 : FMath::Pow((V + 0.055) / 1.055, 2.4);
		};
		const double R = Lin(C.R), G = Lin(C.G), B = Lin(C.B);
		const double X = (0.4124564 * R + 0.3575761 * G + 0.1804375 * B) / 0.95047;
		const double Y = (0.2126729 * R + 0.7151522 * G + 0.0721750 * B) / 1.0;
		const double Z = (0.0193339 * R + 0.1191920 * G + 0.9503041 * B) / 1.08883;
		auto F = [](double T) { return T > 216.0 / 24389.0 ? FMath::Pow(T, 1.0 / 3.0) : (24389.0 / 27.0 * T + 16.0) / 116.0; };
		const double Fx = F(X), Fy = F(Y), Fz = F(Z);
		return FVector3d(116.0 * Fy - 16.0, 500.0 * (Fx - Fy), 200.0 * (Fy - Fz));
	}

	/** CIEDE2000 colour difference (Sharma, Wu, Dalal 2005). */
	inline double DeltaE2000(const FColor& A, const FColor& B)
	{
		const FVector3d L1 = ToLab(A), L2 = ToLab(B);
		const double C1 = FMath::Sqrt(L1.Y * L1.Y + L1.Z * L1.Z), C2 = FMath::Sqrt(L2.Y * L2.Y + L2.Z * L2.Z);
		const double Cm = 0.5 * (C1 + C2);
		const double G = 0.5 * (1.0 - FMath::Sqrt(FMath::Pow(Cm, 7.0) / (FMath::Pow(Cm, 7.0) + FMath::Pow(25.0, 7.0))));
		const double A1 = (1.0 + G) * L1.Y, A2 = (1.0 + G) * L2.Y;
		const double Cp1 = FMath::Sqrt(A1 * A1 + L1.Z * L1.Z), Cp2 = FMath::Sqrt(A2 * A2 + L2.Z * L2.Z);
		auto Hue = [](double Bv, double Av) { if (Av == 0.0 && Bv == 0.0) { return 0.0; } double H = FMath::RadiansToDegrees(FMath::Atan2(Bv, Av)); return H < 0.0 ? H + 360.0 : H; };
		const double H1 = Hue(L1.Z, A1), H2 = Hue(L2.Z, A2);
		const double DL = L2.X - L1.X, DC = Cp2 - Cp1;
		double Dh = 0.0;
		if (Cp1 * Cp2 != 0.0)
		{
			Dh = H2 - H1;
			if (Dh > 180.0) { Dh -= 360.0; }
			else if (Dh < -180.0) { Dh += 360.0; }
		}
		const double DH = 2.0 * FMath::Sqrt(Cp1 * Cp2) * FMath::Sin(FMath::DegreesToRadians(Dh / 2.0));
		const double Lm = 0.5 * (L1.X + L2.X), Cpm = 0.5 * (Cp1 + Cp2);
		double Hm = H1 + H2;
		if (Cp1 * Cp2 != 0.0)
		{
			if (FMath::Abs(H1 - H2) <= 180.0) { Hm = 0.5 * (H1 + H2); }
			else { Hm = (H1 + H2 < 360.0) ? 0.5 * (H1 + H2 + 360.0) : 0.5 * (H1 + H2 - 360.0); }
		}
		const double T = 1.0 - 0.17 * FMath::Cos(FMath::DegreesToRadians(Hm - 30.0)) + 0.24 * FMath::Cos(FMath::DegreesToRadians(2.0 * Hm))
			+ 0.32 * FMath::Cos(FMath::DegreesToRadians(3.0 * Hm + 6.0)) - 0.20 * FMath::Cos(FMath::DegreesToRadians(4.0 * Hm - 63.0));
		const double DTheta = 30.0 * FMath::Exp(-FMath::Square((Hm - 275.0) / 25.0));
		const double Rc = 2.0 * FMath::Sqrt(FMath::Pow(Cpm, 7.0) / (FMath::Pow(Cpm, 7.0) + FMath::Pow(25.0, 7.0)));
		const double Sl = 1.0 + (0.015 * FMath::Square(Lm - 50.0)) / FMath::Sqrt(20.0 + FMath::Square(Lm - 50.0));
		const double Sc = 1.0 + 0.045 * Cpm, Sh = 1.0 + 0.015 * Cpm * T;
		const double Rt = -FMath::Sin(FMath::DegreesToRadians(2.0 * DTheta)) * Rc;
		return FMath::Sqrt(FMath::Square(DL / Sl) + FMath::Square(DC / Sc) + FMath::Square(DH / Sh) + Rt * (DC / Sc) * (DH / Sh));
	}
}

#endif // WITH_DEV_AUTOMATION_TESTS
