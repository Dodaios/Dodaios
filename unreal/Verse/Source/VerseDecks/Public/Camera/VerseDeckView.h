#pragma once

#include "CoreMinimal.h"

/**
 * Deck cameras as pure state and maths (WP12.10), ported from the three.js stage
 * (`engine/realtime/viewMode.ts`, `shoulderRig.ts`, `mouseLook.ts`) into Unreal space:
 * centimetres, Z up, yaw in degrees growing clockwise seen from above, pitch positive looking up
 * (contracts/coordinates.md 2.2). The camera actor (`AVerseDeckCamera`) feeds it the commander's
 * pose and a collision test once per frame; input calls Look, Zoom, Pan and the view switch.
 */

/** The three ways to see a deck (parity V-01). */
enum class EVerseDeckView : uint8
{
	Overview,
	Third,
	First,
};

/** The person of the eye-level views. */
enum class EVerseDeckPerson : uint8
{
	Third,
	First,
};

/** First hit along the segment From -> To as a fraction 0..1 of its length, or unset when clear. */
using FVerseSegmentTest = TFunction<TOptional<double>(const FVector& From, const FVector& To)>;

namespace Verse::DeckView
{
	/** Order of the view switch and of V's cycle. */
	VERSEDECKS_API TConstArrayView<EVerseDeckView> Order();
	VERSEDECKS_API const TCHAR* Name(EVerseDeckView View);
	VERSEDECKS_API TOptional<EVerseDeckView> FromName(const FString& Name);
	/** The view a key picks directly (1/2/3, top row and keypad), by FKey name ("One", "NumPadOne"). */
	VERSEDECKS_API TOptional<EVerseDeckView> ForKey(FName KeyName);
	/** First person needs the eye-level scene; without it third person is shown. */
	VERSEDECKS_API EVerseDeckView Resolve(EVerseDeckView Wanted, bool bEyeCapable);
	/** The view after V: the next in Order() that can be shown (parity V-02). */
	VERSEDECKS_API EVerseDeckView Cycle(EVerseDeckView Current, bool bEyeCapable);
	/** Anything stored as a view; third person when unknown (parity V-21 default). */
	VERSEDECKS_API EVerseDeckView Normalize(const FString& Stored);
}

/** The wheel's state between third and first person (`viewMode.ts` zoomStep). */
struct VERSEDECKS_API FVerseZoomState
{
	EVerseDeckPerson Person = EVerseDeckPerson::Third;
	/** Wanted third-person distance, cm. */
	double DistanceCm = 0.0;
	/** Log of the zoom pushed past a hand-over point (in negative, out positive). */
	double Push = 0.0;
};

/** One wheel step: Factor < 1 moves in. Pushing past the closest distance hands over to first person. */
VERSEDECKS_API FVerseZoomState VerseZoomStep(const FVerseZoomState& State, double Factor, double MinCm, double MaxCm, double Handover);

/** Tuning of the eye-level camera (`SHOULDER` in `shoulderRig.ts`), lengths in cm. */
struct VERSEDECKS_API FVerseShoulderTuning
{
	double HfovThirdDeg = 70.0;
	double HfovFirstDeg = 85.0;
	double MinHfovDeg = 55.0;
	double MaxHfovDeg = 110.0;
	double DistanceCm;
	double MinDistanceCm;
	double MaxDistanceCm;
	double ZoomS = 0.09;
	double Handover = 0.1;
	double PivotHeightCm;
	double EyeHeightCm;
	double EyeForwardCm;
	/** Sideways pivot offset along the camera's right; negative keeps the commander right of centre. */
	double SideCm;
	/** Default pitch, degrees, positive up (today 7 degrees down). */
	double PitchDeg = -7.0;
	double ThirdMinPitchDeg = -60.0;
	double ThirdMaxPitchDeg = 35.0;
	double FirstMinPitchDeg = -80.0;
	double FirstMaxPitchDeg = 80.0;
	/** Degrees per pixel of drag and of captured mouse movement. */
	double DragDegPerPx;
	double LockDegPerPx;
	double FollowS = 0.07;
	double FollowZS = 0.16;
	double PersonS = 0.07;
	double ClearanceCm;
	double EyeClearanceCm;
	double RegainCmPerS;
	double MinSensitivity = 0.25;
	double MaxSensitivity = 3.0;

	FVerseShoulderTuning();
};

/** The commander's pose the rig follows. */
struct VERSEDECKS_API FVerseRigBody
{
	/** Feet, deck-local or world cm. */
	FVector FeetCm = FVector::ZeroVector;
	/** Gameplay heading, degrees. */
	double HeadingDeg = 0.0;
};

/** Over-the-shoulder and first-person camera (`ShoulderRig`), parity V-04 to V-10. */
class VERSEDECKS_API FVerseShoulderRig
{
public:
	FVerseShoulderTuning Tuning;

	double YawDeg = 0.0;
	double PitchDeg = -7.0;
	double DistanceCm = 0.0;
	EVerseDeckPerson Person = EVerseDeckPerson::Third;
	double Sensitivity = 1.0;
	bool bInvertY = false;
	double FovThirdDeg = 70.0;
	double FovFirstDeg = 85.0;

	/** Valid after Update. */
	FVector Location = FVector::ZeroVector;
	FRotator Rotation = FRotator::ZeroRotator;
	/** Third-person distance in use after easing and collisions, cm. */
	double ActualCm = 0.0;
	/** 0 third .. 1 first, eased. */
	double FirstShare = 0.0;

	FVerseShoulderRig();

	void PitchLimits(double& OutMin, double& OutMax) const;
	/** Turns the view by a pointer movement in pixels; `bCaptured` for captured mouse deltas. */
	void Look(double Dx, double Dy, bool bCaptured);
	/** Zoom by Factor (> 1 out). Returns the new person when it changed. */
	TOptional<EVerseDeckPerson> Zoom(double Factor);
	void SetPerson(EVerseDeckPerson NewPerson);
	/** Horizontal field of view to render now (blended), degrees. */
	double Hfov() const;
	/** Straight behind a body facing `HeadingDeg`, at the default pitch. */
	void SnapBehind(double HeadingDeg);
	/** Turn toward a floor point (the crew card's "show"). */
	void FaceToward(const FVector& FromCm, const FVector& ToCm);
	/** Follow the body; `Test` checks segments against the deck (may be unset). */
	void Update(double DtS, const FVerseRigBody& Body, const FVerseSegmentTest& Test);

private:
	FVector Pivot = FVector::ZeroVector;
	double Zoomed = 0.0;
	double Push = 0.0;
	double Blend = 0.0;
	bool bPrimed = false;
};

/** The bird's-eye view (parity V-14, V-17): pan, zoom about the centre, drag turns; focus and return. */
class VERSEDECKS_API FVerseOverviewCamera
{
public:
	/** Plate camera pitch of today's decks: 60 degrees down. */
	double PitchDeg = -60.0;
	double YawDeg = 90.0;
	FVector CentreCm = FVector::ZeroVector;
	double DistanceCm;
	double MinDistanceCm;
	double MaxDistanceCm;
	/** Pan speed as a share of the distance per second. */
	double PanShare = 0.9;

	FVector Location = FVector::ZeroVector;
	FRotator Rotation = FRotator::ZeroRotator;

	FVerseOverviewCamera();

	/** Held keys on the screen plane: X right, Y up (W). */
	void Pan(const FVector2D& Input, double DtS);
	void Zoom(double Factor);
	void Look(double DxDeg);
	/** Centre on a point and remember the framing for Return (the commander button). */
	void Focus(const FVector& PointCm);
	/** Back to the framing before the last Focus (the return key). False when there is none. */
	bool Return();
	bool HasReturn() const { return bHasSaved; }
	void Update();

private:
	FVector SavedCentre = FVector::ZeroVector;
	double SavedDistance = 0.0;
	double SavedYaw = 0.0;
	bool bHasSaved = false;
};
