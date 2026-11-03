#pragma once

#include "CoreMinimal.h"

class UVerseMeleeDefinition;

/**
 * Presentation values that live next to the melee definition in
 * unreal/Verse/Data/melee/hookbill.json but are not gameplay fields of UVerseMeleeDefinition:
 * knife swing timing, the paired finisher pose and the finisher camera. Units as in the
 * JSON are converted once here (seconds stay seconds, metres become cm through VerseCoords).
 */
struct VERSECOMBAT_API FVerseMeleePresentationTuning
{
	FName WeaponId = FName(TEXT("hookbill"));
	/** Knife draw when another slot is active; capped at the strike hit delay so contact lands on time. */
	double EquipS = 0.12;
	/** Swing follow-through after the contact frame. */
	double SwingRecoverS = 0.3;
	/** Attacker stands this far behind the victim in the paired pose (the Warp_Finisher target). */
	double PairedOffsetCm = 70.0;
	/** Victim correction to the paired pose on a client (4.6). */
	double VictimSnapS = 0.1;
	double CameraDistanceCm = 260.0;
	double CameraHeightCm = 120.0;
	double CameraBlendS = 0.15;
};

/** Importer for the verse.melee/1 text surface (WP04.1). Strict: every field must be present and valid. */
struct VERSECOMBAT_API FVerseMeleeImport
{
	static constexpr const TCHAR* Schema = TEXT("verse.melee/1");

	/** <Project>/Data/melee/hookbill.json */
	static FString DefaultPath();

	static bool FromJsonString(const FString& Text, UVerseMeleeDefinition& OutDef,
		FVerseMeleePresentationTuning& OutTuning, FString& OutError);

	static bool FromFile(const FString& Path, UVerseMeleeDefinition& OutDef,
		FVerseMeleePresentationTuning& OutTuning, FString& OutError);
};
