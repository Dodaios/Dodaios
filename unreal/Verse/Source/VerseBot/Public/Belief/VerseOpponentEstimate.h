#pragma once

#include "Bot/VersePerceptTypes.h"
#include "CoreMinimal.h"

/**
 * What the bot estimates about the opponent beyond position (contracts/bot.md 3.3, 4.1): facing,
 * health from its own confirmed hits, ammo from heard shots. Never read from the opponent's pawn.
 */
struct VERSEBOT_API FVerseOpponentEstimate
{
	// ---- facing (bot.md 4.1) ----
	float LastSeenYawDeg = 0.f;
	/** Server time of the last sighting, seconds; negative when never seen. */
	float LastSeenYawAtS = -1.f;
	/** A reload was heard or seen and no shot since (cleared by a heard or seen shot, or a respawn). */
	bool bHeardReload = false;
	float HeardReloadAtS = -1.f;
	FVector LastSeenLocation = FVector::ZeroVector;
	FVector LastSeenVelocity = FVector::ZeroVector;
	FName LastSeenWeapon;

	// ---- health (public rules: max health, regeneration) ----
	float MaxHealth = 100.f;
	/** Health per second after RegenDelayS without own hits; 0 = the ruleset has none. */
	float RegenPerS = 0.f;
	float RegenDelayS = 0.f;
	float DamageSinceFull = 0.f;
	float LastOwnHitAtS = -1.f;

	// ---- ammo ----
	int32 MagazineSize = 30;
	int32 ShotsSinceReload = 0;

	bool bDead = false;

	void OnSighting(const FVerseSightPercept& Sight, float NowS);
	void OnHeard(const FVerseHeardPercept& Heard, float NowS);
	/** An opponent bolt was seen (a shot): the heard-reload flag no longer holds. */
	void OnSeenShot(float NowS);
	/** A hit marker on the opponent; Damage from the bot's own weapon (public rules). */
	void OnOwnHit(float Damage, float NowS);
	void OnOpponentDead();
	void OnOpponentRespawned();

	float EstimatedHealth(float NowS) const;
	int32 EstimatedAmmo() const;
	/** Seconds since the facing estimate was last refreshed; large when never. */
	float FacingAgeS(float NowS) const;
};
