#pragma once

#include "Bot/VersePerceptTypes.h"
#include "Brain/VerseBotWorldQueries.h"
#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

// Record and replay harness of BR1 (bot.md 10): a recorded percept stream plus the recorded
// world-query answers plus the seed, fed to FVerseBotBrainCore twice, must give identical outputs.
// The tape is an in-memory byte stream; it is never written to disk by the game (L1).

/** A recorded run: frames, query answers, and the brain's outputs. */
struct VERSEBOT_API FVerseBotTape
{
	uint64 Seed = 0;
	FName TierId;
	TArray<FVersePerceptFrame> Frames;
	/** Serialised query calls and answers, in call order. */
	TArray<uint8> Queries;
	/** Serialised FVerseInputFrame outputs, one per frame. */
	TArray<uint8> Outputs;

	/** Bytes of one input frame as the tape stores it. */
	static void AppendOutput(TArray<uint8>& Out, const FVerseInputFrame& Frame);
};

/** Wraps a live world: forwards every call and appends call id, arguments and answer to a tape. */
class VERSEBOT_API FVerseBotRecordingQueries final : public IVerseBotWorldQueries
{
public:
	FVerseBotRecordingQueries(IVerseBotWorldQueries& InInner, TArray<uint8>& InTape) : Inner(InInner), Tape(InTape) {}

	virtual bool TestSight(const FVector& Eye, const FVector& Target) override;
	virtual FVerseBotBoltTrace TraceBolt(const FVector& Origin, const FVector& Target, const FVerseBotWeaponInfo& Weapon) override;
	virtual FVerseBotPath FindPath(const FVector& From, const FVector& To, bool bCrouch) override;
	virtual void GetCoverPoints(const FVector& Center, float RadiusCm, TArray<FVerseBotCoverPoint>& Out) override;
	virtual void GetPieces(const FVector& Center, float RadiusCm, TArray<FVerseBotPieceInfo>& Out) override;
	virtual void GetSpawnPoints(TArray<FVector>& Out) override;
	virtual int32 GetZoneId(const FVector& Location) override;
	virtual FVerseBotWeaponInfo GetOwnWeapon() override;
	virtual bool CanActivateFinisher() override;

private:
	IVerseBotWorldQueries& Inner;
	TArray<uint8>& Tape;
};

/**
 * Answers from a tape. Every call checks its call id and arguments against the recording; the
 * first mismatch sets Diverged and the call answers a neutral default from then on.
 */
class VERSEBOT_API FVerseBotReplayQueries final : public IVerseBotWorldQueries
{
public:
	explicit FVerseBotReplayQueries(const TArray<uint8>& InTape) : Tape(InTape) {}

	virtual bool TestSight(const FVector& Eye, const FVector& Target) override;
	virtual FVerseBotBoltTrace TraceBolt(const FVector& Origin, const FVector& Target, const FVerseBotWeaponInfo& Weapon) override;
	virtual FVerseBotPath FindPath(const FVector& From, const FVector& To, bool bCrouch) override;
	virtual void GetCoverPoints(const FVector& Center, float RadiusCm, TArray<FVerseBotCoverPoint>& Out) override;
	virtual void GetPieces(const FVector& Center, float RadiusCm, TArray<FVerseBotPieceInfo>& Out) override;
	virtual void GetSpawnPoints(TArray<FVector>& Out) override;
	virtual int32 GetZoneId(const FVector& Location) override;
	virtual FVerseBotWeaponInfo GetOwnWeapon() override;
	virtual bool CanActivateFinisher() override;

	bool HasDiverged() const { return bDiverged; }
	/** All recorded calls were consumed. */
	bool IsAtEnd() const { return Offset == Tape.Num(); }
	int32 GetCallCount() const { return Calls; }

private:
	bool Begin(uint8 CallId, uint32 ArgHash);
	template <typename T> T Read();

	const TArray<uint8>& Tape;
	int32 Offset = 0;
	int32 Calls = 0;
	bool bDiverged = false;
};
