#pragma once

#include "CoreMinimal.h"

#include "VerseBotFireAudit.generated.h"

class UVerseBotTier;
struct FVerseBotBeliefSummary;

/** How a bot shot is justified (bot.md 8.4, F4). Unclassified is a contract violation. */
UENUM(BlueprintType)
enum class EVerseBotFireMode : uint8
{
	Unclassified,
	Visible,
	Suppression,
	Prefire,
	WallShot
};

/** One logged bot shot (bot.md frozen interface). */
USTRUCT(BlueprintType)
struct VERSEBOT_API FVerseBotFireAudit
{
	GENERATED_BODY()

	UPROPERTY()
	uint32 ServerTimeMs = 0;

	UPROPERTY()
	EVerseBotFireMode Mode = EVerseBotFireMode::Unclassified;

	UPROPERTY()
	bool bTargetVisible = false;

	/** The percepts that back the shot (sighting, heard). */
	UPROPERTY()
	TArray<uint32> PerceptIds;

	/** Belief mass within 1.5 m of the aim point. */
	UPROPERTY()
	float BeliefMassAtAim = 0.f;

	UPROPERTY()
	float SupportAgeS = 0.f;

	/** One log line: "VerseBotFire t=<ms> mode=<mode> visible=<0|1> percepts=<id,id> mass=<f> age=<f>". */
	FString ToLogLine() const;
};

/** Everything the classifier needs about one shot. World cm. */
struct VERSEBOT_API FVerseBotFireEvidence
{
	uint32 ServerTimeMs = 0;
	FVector AimPoint = FVector::ZeroVector;
	/** A sighting this frame of a target that is not spawn-protected, and the aim is on it. */
	bool bTargetVisible = false;
	uint32 SightPerceptId = 0;
	/** Seconds since sight of the target was lost; large when never seen. */
	float SinceSightLostS = 1.0e6f;
	FVector LastSeenLocation = FVector::ZeroVector;
	/** Newest heard percept: age, location, sd, id. */
	float HeardAgeS = 1.0e6f;
	FVector HeardLocation = FVector::ZeroVector;
	float HeardSdCm = 0.f;
	uint32 HeardPerceptId = 0;
	/** The aim point is a peek edge (cover edge of arena data) near which the heard percept lies. */
	bool bAimAtPeekEdge = false;
	/** A prefire roll (PrefireChance) passed for this approach. */
	bool bPrefireRolled = false;
	/** Believed bolt trace from the eye to the aim point. */
	float TraceDamageFrac = 0.f;
	int32 TracePieces = 0;
	/** Belief values (4.3, 4.5). */
	float MassAtAim = 0.f;
	float SupportedMassAtAim = 0.f;
	float SupportAgeS = 1.0e6f;
	bool bPriorOnly = true;
	bool bAimInTopCluster = false;
	/** The target is visibly spawn-protected (5.2: hold fire). */
	bool bTargetSpawnProtected = false;
};

/** The F4 classifier and the wall-shot authority of bot.md 4.5. */
struct VERSEBOT_API FVerseBotFireClassifier
{
	/** Suppression window after losing sight (8.4). */
	static constexpr float SuppressionS = 0.35f;
	/** Suppression radius around the last seen position (8.4). */
	static constexpr float SuppressionRadiusCm = 200.f;
	/** Prefire: heard within 2 s within 6 m of a peek edge (8.4). */
	static constexpr float PrefireHeardMaxAgeS = 2.f;
	static constexpr float PrefireEdgeRadiusCm = 600.f;
	/** Mass is measured within 1.5 m of the aim point (4.5). */
	static constexpr float MassRadiusCm = 150.f;
	/** Contract cap on penetrated pieces (destruction 2). */
	static constexpr int32 MaxPieces = 3;

	/** Effective tier values after the contract floors and caps (4.5). */
	static float MinBelief(const UVerseBotTier& Tier);
	static float MaxSourceAgeS(const UVerseBotTier& Tier);

	/** Wall-shot authority (4.5): all four conditions; learned or prior-only mass never authorises. */
	static bool HasWallShotAuthority(const FVerseBotFireEvidence& E, const UVerseBotTier& Tier);

	/** The mode of a shot, Unclassified when none of 8.4 applies. Order: Visible, Suppression, Prefire, WallShot. */
	static EVerseBotFireMode Classify(const FVerseBotFireEvidence& E, const UVerseBotTier& Tier);

	/** The audit record of a classified shot. */
	static FVerseBotFireAudit MakeAudit(const FVerseBotFireEvidence& E, EVerseBotFireMode Mode);
	/** The same, written into an existing record (keeps its PerceptIds allocation). */
	static void MakeAuditInto(const FVerseBotFireEvidence& E, EVerseBotFireMode Mode, FVerseBotFireAudit& Out);
};

/**
 * The per-bot audit log (F4). Counts every record per mode for the whole match and keeps the
 * newest records in a fixed ring (no growth, no per-tick allocation once warm); the harness sets
 * capture-all to keep every record of a bout and writes them next to its report. Fire intents the
 * gate blocked because no mode of 8.4 applied are counted apart: they never reach the trigger.
 */
class VERSEBOT_API FVerseBotFireAuditLog
{
public:
	/** Records kept outside capture-all. */
	static constexpr int32 RingCapacity = 1024;

	FVerseBotFireAuditLog();
	void Add(const FVerseBotFireAudit& Audit);
	/** Classify-and-log in place: the record is built in its ring slot. */
	void Add(const FVerseBotFireEvidence& E, EVerseBotFireMode Mode);
	/** A fire intent the gate dropped as unclassified (never a trigger press). */
	void AddBlocked() { ++Blocked; }
	void Reset();
	/** Keep every record (harness bouts and tests) instead of the newest RingCapacity. */
	void SetCaptureAll(bool bInCaptureAll) { bCaptureAll = bInCaptureAll; }
	/** The kept records, oldest first. */
	TArray<FVerseBotFireAudit> GetEntries() const;
	/** Records of a mode over the whole match (not only the kept ones). */
	int32 Count(EVerseBotFireMode Mode) const { return ByMode[int32(Mode)]; }
	/** All records over the whole match. */
	int32 Num() const { return Total; }
	int32 NumKept() const { return Entries.Num(); }
	int32 BlockedCount() const { return Blocked; }
	/** The kept lines joined with '\n'. */
	FString ToText() const;

private:
	FVerseBotFireAudit& NextSlot();

	TArray<FVerseBotFireAudit> Entries;
	int32 Head = 0;
	int32 Total = 0;
	int32 Blocked = 0;
	int32 ByMode[5] = {};
	bool bCaptureAll = false;
};

namespace VerseBot
{
	VERSEBOT_API const TCHAR* FireModeName(EVerseBotFireMode Mode);
}
