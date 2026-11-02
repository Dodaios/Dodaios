#pragma once

#include "CoreMinimal.h"
#include "UObject/WeakObjectPtrTemplates.h"

class UVerseBotAdaptiveConfig;
class UVerseBotTier;

/** One kill as the adaptive controller saw it (the adaptiveTrace of bot.md 11.3). */
struct VERSEBOT_API FVerseBotAdaptiveTraceEntry
{
	int32 Kill = 0;
	bool bPersonKill = false;
	/** Person share of the kills in the window after this kill. */
	float WindowShare = 0.f;
	/** The target skill after this kill (applied at the next bot respawn). */
	float PendingSkill = 0.f;
	/** The skill the bot plays with right now. */
	float AppliedSkill = 0.f;
};

/**
 * The adaptive mode (bot.md 9.2). A continuous skill s in [0, 1] (0 normal, 0.5 hard, 1 elite) that
 * moves the person's share of the last WindowKills kills toward TargetPersonShare:
 *
 *   after each kill, once KillsSoFar >= WarmupKills and |share - target| > Deadband:
 *       s' = clamp(s + clamp(Gain x (share - target), -MaxStepPerKill, MaxStepPerKill), 0, 1)
 *
 * (UVerseBotAdaptiveConfig::NextSkill). The new value is pending until the bot respawns
 * (ApplyAt = bot_respawn), never during an engagement. Several kills before a respawn chain their
 * pending steps, but each respawn moves the applied value by at most MaxStepPerKill toward the
 * pending one; any remainder applies at later respawns.
 *
 * Kills come from the kill feed (HUD), so the controller reads nothing a person could not see.
 * Lives for one match (B8); Reset at match end.
 */
class VERSEBOT_API FVerseBotAdaptiveController
{
public:
	void Reset(const UVerseBotAdaptiveConfig& InConfig);

	/** A kill in the match: bPersonKill when the person killed the bot, false when the bot killed. */
	void OnKill(bool bPersonKill);

	/** The bot respawned: the applied skill steps toward the pending one (at most MaxStepPerKill). Returns true when it changed. */
	bool OnBotRespawn();

	/** The skill the bot plays with (AVersePlayerState::BotEffectiveSkill). */
	float GetAppliedSkill() const { return Applied; }
	float GetPendingSkill() const { return Pending; }
	int32 GetKillsSoFar() const { return KillsSoFar; }
	float GetWindowShare() const;

	const TArray<FVerseBotAdaptiveTraceEntry>& GetTrace() const { return Trace; }

	/** The tier the bot plays with at skill S: UVerseBotAdaptiveConfig::InterpolateTier, TierId "adaptive". */
	static void BuildTier(const UVerseBotTier& Normal, const UVerseBotTier& Hard, const UVerseBotTier& Elite, float S, UVerseBotTier& Out);

private:
	/** The config asset; the caller keeps it alive (tier assets are loaded for the match). */
	TWeakObjectPtr<const UVerseBotAdaptiveConfig> Config;
	/** Ring of the last WindowKills kills, true = person kill. */
	TArray<bool> Window;
	int32 KillsSoFar = 0;
	float Applied = 0.5f;
	float Pending = 0.5f;
	TArray<FVerseBotAdaptiveTraceEntry> Trace;
};
