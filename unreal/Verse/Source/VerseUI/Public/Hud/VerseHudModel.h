#pragma once

#include "Combat/VerseCombatTypes.h"
#include "Core/VerseUiPorts.h"
#include "CoreMinimal.h"

/** Hit marker kinds (WP18.2). Each has its own shape (VerseHudPainter), never colour alone. */
enum class EVerseHitMarkerKind : uint8
{
	Hit,
	Headshot,
	Kill,
	Blocked,
};

struct VERSEUI_API FVerseHitMarker
{
	EVerseHitMarkerKind Kind = EVerseHitMarkerKind::Hit;
	double StartTime = 0.0;
	float Duration = 0.f;
};

/** Damage direction: where the bolt came from, in world space, so it turns with the view. */
struct VERSEUI_API FVerseDamageIndicator
{
	/** Unit vector from the person toward the source. */
	FVector FromDirection = FVector::ForwardVector;
	double StartTime = 0.0;
	float Duration = 0.f;
	/** 0..1, from the damage. */
	float Strength = 1.f;
};

enum class EVerseFeedKind : uint8
{
	Kill,
	Respawn,
	SetEnd,
};

struct VERSEUI_API FVerseKillFeedEntry
{
	EVerseFeedKind Kind = EVerseFeedKind::Kill;
	int32 KillerId = INDEX_NONE;
	int32 VictimId = INDEX_NONE;
	EVerseDamageSource Cause = EVerseDamageSource::Bolt;
	FName WeaponId;
	bool bHeadshot = false;
	/** The killing bolt went through at least one piece. */
	bool bWallShot = false;
	EVerseSetOutcome Outcome = EVerseSetOutcome::Unfinished;
	double Time = 0.0;
};

/** Tuning of the HUD model (unreal/Verse/Data/ui/hud.json "timing"). */
struct VERSEUI_API FVerseHudTiming
{
	float HitMarker = 0.30f;
	float HeadshotMarker = 0.40f;
	float KillMarker = 0.70f;
	float BlockedMarker = 0.40f;
	float DamageIndicator = 1.6f;
	float FeedEntry = 6.f;
	int32 FeedMax = 5;
	int32 SetTarget = 10;
};

/**
 * The HUD's view of the fight, fed by hub events and the HUD source (WP18.2-18.4). Pure C++:
 * no world, no widgets, so every rule here is unit tested. "Now" is local real time in
 * seconds; server times only drive the respawn countdown.
 */
class VERSEUI_API FVerseHudModel
{
public:
	FVerseHudTiming Timing;

	void Reset();
	void SetLocalPlayerId(int32 Id) { LocalId = Id; }
	int32 GetLocalPlayerId() const { return LocalId; }

	void OnHit(const FVerseHitEvent& Event, double Now);
	void OnDeath(const FVerseDeathEvent& Event, double Now);
	void OnSetEnded(const FVerseSetSummary& Summary, double Now);
	/** A finished set from the other side's view never arrives; this is the person's summary. */

	/** Expires markers and feed lines; raises the respawn line when a dead player's RespawnAt passes. */
	void Tick(double Now, double ServerTime);

	const TArray<FVerseHitMarker>& GetHitMarkers() const { return HitMarkers; }
	const TArray<FVerseDamageIndicator>& GetDamageIndicators() const { return DamageIndicators; }
	/** Oldest first. */
	const TArray<FVerseKillFeedEntry>& GetKillFeed() const { return Feed; }

	int32 GetScoreSelf() const { return ScoreSelf; }
	int32 GetScoreOpponent() const { return ScoreOpponent; }
	int32 GetSetIndex() const { return SetIndex; }

	bool IsLocalDead() const { return bLocalDead; }
	/** Seconds until the person respawns (server clock), 0 when alive. */
	float GetRespawnRemaining(double ServerTime) const;
	/** Server time of the person's respawn. */
	double GetLocalRespawnAt() const { return LocalRespawnAt; }

	/** The last summary, for the end-of-set screen. */
	const TOptional<FVerseSetSummary>& GetLastSummary() const { return LastSummary; }

	static float MarkerAlpha(const FVerseHitMarker& Marker, double Now);

private:
	void PushFeed(const FVerseKillFeedEntry& Entry);

	int32 LocalId = INDEX_NONE;
	TArray<FVerseHitMarker> HitMarkers;
	TArray<FVerseDamageIndicator> DamageIndicators;
	TArray<FVerseKillFeedEntry> Feed;
	/** Victim id -> the last hit on them (wall shot and headshot of the kill). */
	TMap<int32, FVerseHitEvent> LastHitOn;
	/** Dead player id -> RespawnAt (server time). */
	TMap<int32, double> PendingRespawn;
	int32 ScoreSelf = 0;
	int32 ScoreOpponent = 0;
	int32 SetIndex = 1;
	bool bLocalDead = false;
	double LocalRespawnAt = 0.0;
	TOptional<FVerseSetSummary> LastSummary;
};
