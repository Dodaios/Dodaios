#pragma once

#include "CoreMinimal.h"

/**
 * The Sovereign's cloak (parity Z-02, reference `actors/cloak.ts`): secondary
 * motion on the six cloak bones `Cloak_{R,C,L}{1,2}` (children of the chest,
 * never animated by the shared clips).
 *
 * Each of the three columns (right, centre, left) is a damped spring on two
 * angles in the body's own frame: `Lift` (the hem rises backwards as the
 * body walks forward) and `Swing` (it swings sideways against a strafe or a
 * turn; positive = the hem toward the body's right). The lower segment
 * follows the upper with more lag, so the hem whips a little after a stop. A
 * light flutter rides on top while moving.
 *
 * The constants are the reference's, in its units (m/s, rad); inputs are
 * Unreal's (cm, degrees, Z up, yaw positive turning right).
 */
namespace VerseCloak
{
	/** Spring stiffness (1/s^2) and damping (1/s) of the upper and the lower segment. */
	inline constexpr float K1 = 55.f;
	inline constexpr float C1 = 10.f;
	inline constexpr float K2 = 30.f;
	inline constexpr float C2 = 6.5f;

	/** Columns right, centre, left; `Side` -1, 0, +1 as in the reference. */
	inline constexpr int32 Columns = 3;

	/** `Cloak_<R|C|L><1|2>`: `Column` 0..2 (right, centre, left), `Segment` 0 upper, 1 lower. */
	VERSEABILITIES_API FName BoneName(int32 Column, int32 Segment);

	/** Where a column wants to hang, radians. */
	struct FAngles
	{
		float Lift = 0.f;
		float Swing = 0.f;
	};

	/**
	 * The target of a column for a body moving `Forward` / `Right` m/s and turning
	 * `YawRate` rad/s (Unreal: positive turning right). Pure.
	 */
	VERSEABILITIES_API FAngles Target(float Forward, float Right, float YawRate, int32 Side);

	struct FColumn
	{
		int32 Side = 0;
		float Phase = 0.f;
		/** Upper and lower segment angles and their rates. */
		FAngles Upper;
		FAngles Lower;
		FAngles UpperRate;
		FAngles LowerRate;
	};

	/** The cloak's springs for one body. */
	class VERSEABILITIES_API FSim
	{
	public:
		FSim();

		/** Forget the motion (the body was placed somewhere new). */
		void Reset();

		/**
		 * Step the springs for a body standing at `Location` (cm) facing `YawDeg`.
		 * `bStill` drops the flutter.
		 */
		void Update(float Dt, const FVector& Location, float YawDeg, bool bStill = false);

		const FColumn& Column(int32 Index) const { return Cols[Index]; }

		/** Smoothed body speed in its own frame, m/s, and turn rate, rad/s. */
		float GetForward() const { return Forward; }
		float GetRight() const { return Right; }

	private:
		FColumn Cols[Columns];
		FVector Last = FVector::ZeroVector;
		float LastYaw = 0.f;
		bool bPrimed = false;
		float Forward = 0.f;
		float Right = 0.f;
		float Turn = 0.f;
		float Time = 0.f;
	};
}
