#include "Audit/VerseBotFireAudit.h"

#include "Bot/VerseBotTier.h"

namespace VerseBot
{
	const TCHAR* FireModeName(EVerseBotFireMode Mode)
	{
		switch (Mode)
		{
		case EVerseBotFireMode::Unclassified: return TEXT("unclassified");
		case EVerseBotFireMode::Visible: return TEXT("visible");
		case EVerseBotFireMode::Suppression: return TEXT("suppression");
		case EVerseBotFireMode::Prefire: return TEXT("prefire");
		case EVerseBotFireMode::WallShot: return TEXT("wall_shot");
		}
		return TEXT("unclassified");
	}
}

FString FVerseBotFireAudit::ToLogLine() const
{
	FString Ids;
	for (int32 i = 0; i < PerceptIds.Num(); ++i)
	{
		if (i > 0)
		{
			Ids += TEXT(",");
		}
		Ids += FString::Printf(TEXT("%u"), PerceptIds[i]);
	}
	return FString::Printf(TEXT("VerseBotFire t=%u mode=%s visible=%d percepts=%s mass=%.3f age=%.2f"), ServerTimeMs,
		VerseBot::FireModeName(Mode), bTargetVisible ? 1 : 0, *Ids, BeliefMassAtAim, SupportAgeS);
}

float FVerseBotFireClassifier::MinBelief(const UVerseBotTier& Tier)
{
	return FMath::Max(Tier.WallbangMinBelief, float(UVerseBotTier::WallbangMinBeliefFloor));
}

float FVerseBotFireClassifier::MaxSourceAgeS(const UVerseBotTier& Tier)
{
	return FMath::Min(Tier.WallbangMaxSourceAgeS, float(UVerseBotTier::WallbangMaxSourceAgeCapS));
}

bool FVerseBotFireClassifier::HasWallShotAuthority(const FVerseBotFireEvidence& E, const UVerseBotTier& Tier)
{
	const float MaxAge = MaxSourceAgeS(Tier);
	// Aim point: inside TopCluster, or within 2 sd of a heard percept younger than the age cap.
	const bool bNearHeard = E.HeardAgeS <= MaxAge && E.HeardSdCm > 0.f
		&& FVector::Dist(E.AimPoint, E.HeardLocation) <= 2.f * E.HeardSdCm;
	if (!E.bAimInTopCluster && !bNearHeard)
	{
		return false;
	}
	// Belief: supported mass only; prior-only (and learned) mass never authorises.
	if (E.bPriorOnly || E.SupportedMassAtAim < MinBelief(Tier))
	{
		return false;
	}
	if (E.SupportAgeS > MaxAge)
	{
		return false;
	}
	// Path: enough damage left through at most 3 believed pieces.
	return E.TracePieces <= MaxPieces && E.TraceDamageFrac >= Tier.WallbangMinDamageFrac;
}

EVerseBotFireMode FVerseBotFireClassifier::Classify(const FVerseBotFireEvidence& E, const UVerseBotTier& Tier)
{
	if (E.bTargetSpawnProtected)
	{
		return EVerseBotFireMode::Unclassified;
	}
	if (E.bTargetVisible)
	{
		return EVerseBotFireMode::Visible;
	}
	if (E.SinceSightLostS <= SuppressionS && FVector::Dist(E.AimPoint, E.LastSeenLocation) <= SuppressionRadiusCm)
	{
		return EVerseBotFireMode::Suppression;
	}
	if (E.bPrefireRolled && E.bAimAtPeekEdge && E.HeardAgeS <= PrefireHeardMaxAgeS
		&& FVector::Dist(E.HeardLocation, E.AimPoint) <= PrefireEdgeRadiusCm
		&& E.SupportedMassAtAim >= MinBelief(Tier))
	{
		return EVerseBotFireMode::Prefire;
	}
	if (HasWallShotAuthority(E, Tier))
	{
		return EVerseBotFireMode::WallShot;
	}
	return EVerseBotFireMode::Unclassified;
}

FVerseBotFireAudit FVerseBotFireClassifier::MakeAudit(const FVerseBotFireEvidence& E, EVerseBotFireMode Mode)
{
	FVerseBotFireAudit A;
	A.ServerTimeMs = E.ServerTimeMs;
	A.Mode = Mode;
	A.bTargetVisible = E.bTargetVisible;
	if (E.SightPerceptId != 0 && (Mode == EVerseBotFireMode::Visible || Mode == EVerseBotFireMode::Suppression))
	{
		A.PerceptIds.Add(E.SightPerceptId);
	}
	if (Mode == EVerseBotFireMode::Prefire || Mode == EVerseBotFireMode::WallShot)
	{
		// The percepts behind the belief at the aim point: the newest heard and the last sighting.
		if (E.HeardPerceptId != 0)
		{
			A.PerceptIds.Add(E.HeardPerceptId);
		}
		if (E.SightPerceptId != 0)
		{
			A.PerceptIds.Add(E.SightPerceptId);
		}
	}
	A.BeliefMassAtAim = E.MassAtAim;
	A.SupportAgeS = E.SupportAgeS;
	return A;
}

void FVerseBotFireAuditLog::Add(const FVerseBotFireAudit& Audit)
{
	Entries.Add(Audit);
}

int32 FVerseBotFireAuditLog::Count(EVerseBotFireMode Mode) const
{
	int32 N = 0;
	for (const FVerseBotFireAudit& A : Entries)
	{
		N += A.Mode == Mode ? 1 : 0;
	}
	return N;
}

FString FVerseBotFireAuditLog::ToText() const
{
	FString Out;
	for (const FVerseBotFireAudit& A : Entries)
	{
		Out += A.ToLogLine();
		Out += TEXT("\n");
	}
	return Out;
}
