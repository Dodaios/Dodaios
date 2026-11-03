#include "Hud/VerseHudModel.h"

#include "Hud/VerseCrosshair.h"

// ---------------------------------------------------------------------------------------------
// HUD model

void FVerseHudModel::Reset()
{
	HitMarkers.Reset();
	DamageIndicators.Reset();
	Feed.Reset();
	LastHitOn.Reset();
	PendingRespawn.Reset();
	ScoreSelf = 0;
	ScoreOpponent = 0;
	SetIndex = 1;
	bLocalDead = false;
	LocalRespawnAt = 0.0;
	LastSummary.Reset();
}

void FVerseHudModel::OnHit(const FVerseHitEvent& Event, double Now)
{
	LastHitOn.Add(Event.VictimId, Event);

	if (LocalId != INDEX_NONE && Event.InstigatorId == LocalId && Event.VictimId != LocalId)
	{
		FVerseHitMarker Marker;
		Marker.StartTime = Now;
		if (Event.bBlockedBySpawnProtection)
		{
			Marker.Kind = EVerseHitMarkerKind::Blocked;
			Marker.Duration = Timing.BlockedMarker;
		}
		else if (Event.bKillingBlow)
		{
			Marker.Kind = EVerseHitMarkerKind::Kill;
			Marker.Duration = Timing.KillMarker;
		}
		else if (Event.bHeadshot)
		{
			Marker.Kind = EVerseHitMarkerKind::Headshot;
			Marker.Duration = Timing.HeadshotMarker;
		}
		else
		{
			Marker.Kind = EVerseHitMarkerKind::Hit;
			Marker.Duration = Timing.HitMarker;
		}
		// One marker of each kind at a time: a new hit restarts it (rapid fire stays readable).
		HitMarkers.RemoveAll([&Marker](const FVerseHitMarker& M) { return M.Kind == Marker.Kind; });
		HitMarkers.Add(Marker);
	}

	if (LocalId != INDEX_NONE && Event.VictimId == LocalId && Event.InstigatorId != LocalId && !Event.bBlockedBySpawnProtection)
	{
		FVerseDamageIndicator Indicator;
		// Direction is the bolt's travel (shooter -> victim); the indicator points back at the source.
		const FVector Travel = FVector(Event.Direction);
		Indicator.FromDirection = Travel.IsNearlyZero() ? FVector::ForwardVector : -Travel.GetSafeNormal();
		Indicator.StartTime = Now;
		Indicator.Duration = Timing.DamageIndicator;
		Indicator.Strength = FMath::Clamp(Event.Damage / 50.f, 0.35f, 1.f);
		DamageIndicators.Add(Indicator);
		if (DamageIndicators.Num() > 8)
		{
			DamageIndicators.RemoveAt(0);
		}
	}
}

void FVerseHudModel::OnDeath(const FVerseDeathEvent& Event, double Now)
{
	FVerseKillFeedEntry Entry;
	Entry.Kind = EVerseFeedKind::Kill;
	Entry.KillerId = Event.KillerId;
	Entry.VictimId = Event.VictimId;
	Entry.Cause = Event.Cause;
	Entry.WeaponId = Event.WeaponId;
	Entry.bHeadshot = Event.LastZone == EVerseHitZone::Head;
	Entry.Time = Now;
	if (const FVerseHitEvent* Last = LastHitOn.Find(Event.VictimId))
	{
		if (Last->InstigatorId == Event.KillerId)
		{
			Entry.bWallShot = Last->PenetrationCount > 0;
			Entry.bHeadshot = Entry.bHeadshot || Last->bHeadshot;
		}
	}
	PushFeed(Entry);
	LastHitOn.Remove(Event.VictimId);

	// Ids below 0 are the world (combat-state 11.1 uses -1); a world kill or a suicide scores nobody.
	const bool bSuicide = Event.KillerId == Event.VictimId || Event.KillerId < 0;
	if (LocalId != INDEX_NONE)
	{
		if (Event.VictimId == LocalId)
		{
			bLocalDead = true;
			LocalRespawnAt = Event.RespawnAt;
			if (!bSuicide)
			{
				++ScoreOpponent;
			}
		}
		else if (Event.KillerId == LocalId)
		{
			++ScoreSelf;
		}
		else
		{
			// A kill by the world counts for nobody; a kill by the opponent of a third player does
			// not exist in 1v1.
		}
	}
	PendingRespawn.Add(Event.VictimId, Event.RespawnAt);
}

void FVerseHudModel::OnSetEnded(const FVerseSetSummary& Summary, double Now)
{
	LastSummary = Summary;
	FVerseKillFeedEntry Entry;
	Entry.Kind = EVerseFeedKind::SetEnd;
	Entry.Outcome = Summary.Outcome;
	Entry.Time = Now;
	PushFeed(Entry);
	// Score resets with every set (combat-state 9.1); the match itself never ends.
	ScoreSelf = 0;
	ScoreOpponent = 0;
	SetIndex = Summary.SetIndex + 1;
}

void FVerseHudModel::Tick(double Now, double ServerTime)
{
	HitMarkers.RemoveAll([Now](const FVerseHitMarker& M) { return Now - M.StartTime >= M.Duration; });
	DamageIndicators.RemoveAll([Now](const FVerseDamageIndicator& D) { return Now - D.StartTime >= D.Duration; });
	Feed.RemoveAll([Now, this](const FVerseKillFeedEntry& E) { return Now - E.Time >= Timing.FeedEntry; });

	for (auto It = PendingRespawn.CreateIterator(); It; ++It)
	{
		if (ServerTime >= It.Value())
		{
			FVerseKillFeedEntry Entry;
			Entry.Kind = EVerseFeedKind::Respawn;
			Entry.VictimId = It.Key();
			Entry.Time = Now;
			if (It.Key() == LocalId)
			{
				bLocalDead = false;
				LocalRespawnAt = 0.0;
			}
			else
			{
				// bot.md 3.3: the kill feed says the opponent respawned; the person's own respawn
				// needs no line.
				PushFeed(Entry);
			}
			It.RemoveCurrent();
		}
	}
}

float FVerseHudModel::GetRespawnRemaining(double ServerTime) const
{
	return bLocalDead ? float(FMath::Max(0.0, LocalRespawnAt - ServerTime)) : 0.f;
}

float FVerseHudModel::MarkerAlpha(const FVerseHitMarker& Marker, double Now)
{
	if (Marker.Duration <= 0.f)
	{
		return 0.f;
	}
	const float T = float((Now - Marker.StartTime) / Marker.Duration);
	// Full for the first half, then a linear fade.
	return FMath::Clamp(T < 0.5f ? 1.f : 2.f * (1.f - T), 0.f, 1.f);
}

void FVerseHudModel::PushFeed(const FVerseKillFeedEntry& Entry)
{
	Feed.Add(Entry);
	while (Feed.Num() > FMath::Max(1, Timing.FeedMax))
	{
		Feed.RemoveAt(0);
	}
}

// ---------------------------------------------------------------------------------------------
// Crosshair

FMatrix FVerseCrosshair::ViewProjection(const FVerseHudView& View, const FVector2D& Viewport)
{
	// As ULocalPlayer::GetProjectionData with AspectRatio_MaintainXFOV: view rotation into
	// Unreal's camera space (X forward -> Z depth), then a reversed-Z perspective.
	const FMatrix ViewRotation = FInverseRotationMatrix(View.Rotation) *
		FMatrix(FPlane(0, 0, 1, 0), FPlane(1, 0, 0, 0), FPlane(0, 1, 0, 0), FPlane(0, 0, 0, 1));
	const float HalfFov = FMath::DegreesToRadians(FMath::Clamp(View.HorizontalFovDeg, 1.f, 170.f)) * 0.5f;
	const float Width = float(FMath::Max(1.0, Viewport.X));
	const float Height = float(FMath::Max(1.0, Viewport.Y));
	const float NearPlane = 10.f;
	const FMatrix Projection = FReversedZPerspectiveMatrix(HalfFov, HalfFov, 1.f, Width / Height, NearPlane, NearPlane);
	return ViewRotation * Projection;
}

bool FVerseCrosshair::ProjectDirection(const FVerseHudView& View, const FVector2D& Viewport, const FVector& Direction, FVector2D& OutPixel)
{
	const FVector Dir = Direction.GetSafeNormal();
	if (Dir.IsNearlyZero() || FVector::DotProduct(Dir, View.Rotation.Vector()) <= KINDA_SMALL_NUMBER)
	{
		return false;
	}
	const FMatrix ViewProj = ViewProjection(View, Viewport);
	// A point far along the direction, relative to the eye (translation cancels out).
	const FVector4 Clip = ViewProj.TransformFVector4(FVector4(Dir * 100000.0, 1.0));
	if (Clip.W <= 0.0)
	{
		return false;
	}
	const double NdcX = Clip.X / Clip.W;
	const double NdcY = Clip.Y / Clip.W;
	OutPixel.X = (NdcX * 0.5 + 0.5) * Viewport.X;
	OutPixel.Y = (0.5 - NdcY * 0.5) * Viewport.Y;
	return true;
}

float FVerseCrosshair::SpreadRadiusPx(const FVerseHudView& View, const FVector2D& Viewport, float HalfAngleDeg)
{
	const float HalfFov = FMath::DegreesToRadians(FMath::Clamp(View.HorizontalFovDeg, 1.f, 170.f)) * 0.5f;
	const float Spread = FMath::DegreesToRadians(FMath::Clamp(HalfAngleDeg, 0.f, 45.f));
	return float(FMath::Tan(Spread) / FMath::Tan(HalfFov) * Viewport.X * 0.5);
}
