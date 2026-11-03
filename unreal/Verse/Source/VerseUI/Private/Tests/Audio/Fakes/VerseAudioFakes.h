#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "Audio/VerseAudioSink.h"
#include "CoreMinimal.h"
#include "Destruction/VerseDestructionInterfaces.h"

/** Records every voice instead of playing it (work-packages.md 0.3 fake). */
class FFakeVerseAudioSink final : public IVerseAudioSink
{
public:
	struct FPlay
	{
		int32 Handle = 0;
		FVerseAudioPlayRequest Request;
		int64 Frame = 0;
	};

	TArray<FPlay> Plays;
	TArray<int32> Stops;
	/** The engine model of a voice's level: a multiplier fixed at the start times a fader. */
	TMap<int32, float> VoiceMultiplier;
	TMap<int32, float> VoiceFader;
	TMap<int32, float> VoiceLowpass;
	TArray<float> MasterHistory;
	float Master = 1.f;
	int32 Routed = 0;

	virtual bool Initialize(UWorld*, const FVerseAudioMixSettings&) override { return true; }
	virtual void Play(int32 Handle, const FVerseAudioPlayRequest& Request) override
	{
		Plays.Add({Handle, Request, int64(GFrameCounter)});
		VoiceMultiplier.Add(Handle, Request.Volume);
		VoiceFader.Add(Handle, Request.Fader);
		VoiceLowpass.Add(Handle, Request.LowpassHz);
	}
	virtual void Stop(int32 Handle, float) override
	{
		Stops.Add(Handle);
		VoiceMultiplier.Remove(Handle);
		VoiceFader.Remove(Handle);
	}
	virtual void SetVoiceLocation(int32, const FVector&) override {}
	virtual void SetVoiceOcclusion(int32 Handle, float Gain, float LowpassHz) override
	{
		VoiceFader.Add(Handle, Gain);
		VoiceLowpass.Add(Handle, LowpassHz);
	}
	/** What the voice is heard at now (multiplier x fader, as FActiveSound::GetVolume); -1 when not playing. */
	float EffectiveVolume(int32 Handle) const
	{
		const float* Mult = VoiceMultiplier.Find(Handle);
		const float* Fader = VoiceFader.Find(Handle);
		return Mult && Fader ? *Mult * *Fader : -1.f;
	}
	const FPlay* LastPlayOf(FName CueId) const
	{
		for (int32 I = Plays.Num() - 1; I >= 0; --I)
		{
			if (Plays[I].Request.CueId == CueId)
			{
				return &Plays[I];
			}
		}
		return nullptr;
	}
	virtual void SetMasterVolume(float Volume) override
	{
		Master = Volume;
		MasterHistory.Add(Volume);
	}
	virtual void Route(USoundBase*, EVerseAudioBus) override { ++Routed; }
	virtual void Shutdown() override {}

	int32 CountOf(FName CueId) const
	{
		int32 N = 0;
		for (const FPlay& P : Plays)
		{
			N += P.Request.CueId == CueId ? 1 : 0;
		}
		return N;
	}
};

/**
 * One wall piece (index 0) across the X axis at X = WallX: a bolt or sound trace that crosses it
 * enters the piece unless it is holed. Implements IVersePenetrationQuery and IVersePieceQuery
 * exactly, nothing more (work-packages.md 0.3).
 */
class FFakeVerseWall final : public IVersePenetrationQuery, public IVersePieceQuery
{
public:
	float WallX = 500.f;
	float ThicknessCm = 1.2f;
	EVersePenetrationMaterial Material = EVersePenetrationMaterial::SheetMetal;
	EVersePieceState State = EVersePieceState::Intact;

	virtual TArray<FVersePenetrationHit> TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist, float, float,
		uint8, int32 MaxPieces) const override
	{
		TArray<FVersePenetrationHit> Hits;
		const bool bOpen = State == EVersePieceState::Holed || State == EVersePieceState::Breached
			|| State == EVersePieceState::Destroyed;
		const FVector End = Origin + Dir * MaxDist;
		const bool bCrosses = (Origin.X - WallX) * (End.X - WallX) < 0.0;
		if (!bOpen && bCrosses && MaxPieces > 0)
		{
			const double T = (WallX - Origin.X) / Dir.X;
			FVersePenetrationHit Hit;
			Hit.PieceIndex = 0;
			Hit.MaterialWireId = uint8(Material);
			Hit.Entry = Origin + Dir * T;
			Hit.Exit = Hit.Entry + Dir * ThicknessCm;
			Hit.TracedThicknessCm = ThicknessCm;
			Hit.bPassed = true;
			Hits.Add(Hit);
		}
		return Hits;
	}

	virtual bool TestSight(const FVector& Eye, const FVector& Target) const override
	{
		return TraceBolt(Eye, (Target - Eye).GetSafeNormal(), float(FVector::Dist(Eye, Target)), 0.f, 0.f, 0, 1).Num() == 0;
	}

	virtual EVersePieceState GetPieceState(uint16) const override { return State; }
	virtual EVersePenetrationMaterial GetPieceMaterial(uint16) const override { return Material; }
	virtual FBox GetPieceBounds(uint16) const override
	{
		return FBox(FVector(WallX - 1.0, -200.0, 0.0), FVector(WallX + 1.0, 200.0, 300.0));
	}
	virtual TArray<uint16> GetPiecesInBox(const FBox& Box) const override
	{
		return Box.Intersect(GetPieceBounds(0)) ? TArray<uint16>{0} : TArray<uint16>{};
	}
};

#endif // WITH_DEV_AUTOMATION_TESTS
