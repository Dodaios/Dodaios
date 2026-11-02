#include "Belief/VerseOpponentEstimate.h"

#include "VerseGameplayTags.h"

void FVerseOpponentEstimate::OnSighting(const FVerseSightPercept& Sight, float NowS)
{
	bDead = false;
	LastSeenYawDeg = Sight.FacingYawDeg;
	LastSeenYawAtS = NowS;
	LastSeenLocation = Sight.PelvisLocation;
	LastSeenVelocity = Sight.Velocity;
	if (Sight.bReloading)
	{
		// The reload animation is visible: the magazine is refilled.
		ShotsSinceReload = 0;
		bHeardReload = true;
		HeardReloadAtS = NowS;
	}
	else
	{
		bHeardReload = false;
	}
	if (Sight.HeldWeaponId != LastSeenWeapon)
	{
		LastSeenWeapon = Sight.HeldWeaponId;
		ShotsSinceReload = 0;
	}
}

void FVerseOpponentEstimate::OnHeard(const FVerseHeardPercept& Heard, float NowS)
{
	if (Heard.Noise == VerseTags::Noise_Shot)
	{
		++ShotsSinceReload;
	}
	else if (Heard.Noise == VerseTags::Noise_Reload)
	{
		ShotsSinceReload = 0;
		bHeardReload = true;
		HeardReloadAtS = NowS;
	}
}

void FVerseOpponentEstimate::OnOwnHit(float Damage, float NowS)
{
	DamageSinceFull = FMath::Clamp(DamageSinceFull + FMath::Max(0.f, Damage), 0.f, MaxHealth);
	LastOwnHitAtS = NowS;
}

void FVerseOpponentEstimate::OnOpponentDead()
{
	bDead = true;
}

void FVerseOpponentEstimate::OnOpponentRespawned()
{
	bDead = false;
	DamageSinceFull = 0.f;
	ShotsSinceReload = 0;
	bHeardReload = false;
	LastSeenYawAtS = -1.f;
	LastOwnHitAtS = -1.f;
}

float FVerseOpponentEstimate::EstimatedHealth(float NowS) const
{
	if (bDead)
	{
		return 0.f;
	}
	float Damage = DamageSinceFull;
	if (RegenPerS > 0.f && LastOwnHitAtS >= 0.f)
	{
		const float Regen = FMath::Max(0.f, NowS - LastOwnHitAtS - RegenDelayS) * RegenPerS;
		Damage = FMath::Max(0.f, Damage - Regen);
	}
	return FMath::Max(0.f, MaxHealth - Damage);
}

int32 FVerseOpponentEstimate::EstimatedAmmo() const
{
	return FMath::Max(0, MagazineSize - ShotsSinceReload);
}

float FVerseOpponentEstimate::FacingAgeS(float NowS) const
{
	return LastSeenYawAtS < 0.f ? TNumericLimits<float>::Max() : FMath::Max(0.f, NowS - LastSeenYawAtS);
}
