#pragma once

#include "CoreMinimal.h"

/**
 * Colours and shapes of the Verse UI (README "Look": Military-Industrial Noir). Accents are
 * sparse amber, red and gold on black steel; never cyan or violet. Every state that carries a
 * colour also carries a shape (WP18.10), so nothing depends on colour alone.
 */
namespace VerseUiTheme
{
	/** Panels and plates. */
	inline const FLinearColor Steel(0.010f, 0.010f, 0.011f, 0.86f);
	inline const FLinearColor SteelLight(0.035f, 0.033f, 0.030f, 0.92f);
	inline const FLinearColor Edge(0.20f, 0.17f, 0.12f, 1.f);
	/** Body text: warm off-white. */
	inline const FLinearColor Text(0.86f, 0.82f, 0.74f, 1.f);
	inline const FLinearColor TextDim(0.48f, 0.45f, 0.40f, 1.f);
	/** Own side: amber (own bolts are amber, README). */
	inline const FLinearColor Amber(1.00f, 0.55f, 0.08f, 1.f);
	/** Opponent and danger: red (the opponent's bolts are red). */
	inline const FLinearColor Red(0.90f, 0.08f, 0.04f, 1.f);
	/** Headshots, wins, rank: gold. */
	inline const FLinearColor Gold(0.95f, 0.72f, 0.22f, 1.f);
	/** Blocked (spawn protection): neutral grey-white. */
	inline const FLinearColor Blocked(0.80f, 0.80f, 0.78f, 1.f);
	/** Text shadow under the HUD. */
	inline const FLinearColor Shadow(0.f, 0.f, 0.f, 0.75f);

	/** True when a colour is in the forbidden cyan or violet band (hue 170-300 deg, saturated). */
	VERSEUI_API bool IsForbiddenAccent(const FLinearColor& Colour);

	/** Every accent this file defines, for the palette test. */
	VERSEUI_API TArray<FLinearColor> AllColours();
}
