#include "KillCam/VerseKillCam.h"

// ---------------------------------------------------------------------------------------------
// Buffer

void FVerseKillCamBuffer::Reset()
{
	Poses.Reset();
	Fires.Reset();
	Fractures.Reset();
}

void FVerseKillCamBuffer::AddPose(int32 PlayerId, double ServerTime, const FVector& Location, const FRotator& Rotation)
{
	TArray<FPoseSample>& Samples = Poses.FindOrAdd(PlayerId);
	if (Samples.Num() > 0 && ServerTime <= Samples.Last().Time)
	{
		// Same server time seen twice (client faster than the replicated clock): keep the newest.
		if (FMath::IsNearlyEqual(ServerTime, Samples.Last().Time))
		{
			Samples.Last().Location = Location;
			Samples.Last().Rotation = Rotation;
		}
		return;
	}
	Samples.Add({ServerTime, Location, Rotation});
}

void FVerseKillCamBuffer::AddFire(const FVerseFireEvent& Event, double ServerTime)
{
	Fires.Add({ServerTime, Event});
}

void FVerseKillCamBuffer::AddFracture(const FVerseFractureEvent& Event, double ServerTime)
{
	Fractures.Add({ServerTime, Event});
}

void FVerseKillCamBuffer::Trim(double ServerNow)
{
	const double Oldest = ServerNow - Window;
	for (TPair<int32, TArray<FPoseSample>>& Pair : Poses)
	{
		TArray<FPoseSample>& Samples = Pair.Value;
		// Keep one sample before the window so interpolation at its start still works.
		int32 Cut = 0;
		while (Cut + 1 < Samples.Num() && Samples[Cut + 1].Time < Oldest)
		{
			++Cut;
		}
		if (Cut > 0)
		{
			Samples.RemoveAt(0, Cut, EAllowShrinking::No);
		}
	}
	Fires.RemoveAll([Oldest](const FFireSample& S) { return S.Time < Oldest; });
	Fractures.RemoveAll([Oldest](const FFractureSample& S) { return S.Time < Oldest; });
}

bool FVerseKillCamBuffer::PoseAt(int32 PlayerId, double Time, FVector& OutLocation, FRotator& OutRotation) const
{
	const TArray<FPoseSample>* Samples = Poses.Find(PlayerId);
	if (!Samples || Samples->Num() == 0)
	{
		return false;
	}
	const TArray<FPoseSample>& S = *Samples;
	if (Time <= S[0].Time)
	{
		OutLocation = S[0].Location;
		OutRotation = S[0].Rotation;
		return Time >= S[0].Time - 0.1;
	}
	if (Time >= S.Last().Time)
	{
		OutLocation = S.Last().Location;
		OutRotation = S.Last().Rotation;
		return Time <= S.Last().Time + 0.25;
	}
	// Binary search for the segment.
	int32 Lo = 0;
	int32 Hi = S.Num() - 1;
	while (Hi - Lo > 1)
	{
		const int32 Mid = (Lo + Hi) / 2;
		if (S[Mid].Time <= Time)
		{
			Lo = Mid;
		}
		else
		{
			Hi = Mid;
		}
	}
	const double Span = S[Hi].Time - S[Lo].Time;
	const float Alpha = Span > 0.0 ? float((Time - S[Lo].Time) / Span) : 0.f;
	OutLocation = FMath::Lerp(S[Lo].Location, S[Hi].Location, Alpha);
	OutRotation = FQuat::Slerp(S[Lo].Rotation.Quaternion(), S[Hi].Rotation.Quaternion(), Alpha).Rotator();
	return true;
}

double FVerseKillCamBuffer::EarliestPose(int32 PlayerId) const
{
	const TArray<FPoseSample>* Samples = Poses.Find(PlayerId);
	return Samples && Samples->Num() > 0 ? (*Samples)[0].Time : TNumericLimits<double>::Max();
}

int32 FVerseKillCamBuffer::NumPoses(int32 PlayerId) const
{
	const TArray<FPoseSample>* Samples = Poses.Find(PlayerId);
	return Samples ? Samples->Num() : 0;
}

// ---------------------------------------------------------------------------------------------
// Player

bool FVerseKillCamPlayer::Begin(const FVerseKillCamBuffer& Buffer, const FVerseDeathEvent& Death, int32 LocalPlayerId,
	double LocalNow, double ServerNow, bool bCutFinisher)
{
	Stop();
	if (Death.VictimId != LocalPlayerId || Death.KillerId == LocalPlayerId || Death.KillerId < 0)
	{
		return false;
	}
	if (Buffer.NumPoses(Death.KillerId) == 0)
	{
		return false;
	}
	// The replay may run until EndMargin before respawn; it shows the seconds up to the death.
	const double Available = Death.RespawnAt - ServerNow - Tuning.EndMarginS;
	double End = Death.ServerTime;
	if (bCutFinisher && Death.Cause == EVerseDamageSource::Finisher)
	{
		End -= Tuning.FinisherCutS;
	}
	const double Earliest = FMath::Max(Buffer.EarliestPose(Death.KillerId), Death.ServerTime - Buffer.Window);
	const double Length = FMath::Min(End - Earliest, Available);
	if (Length < Tuning.MinLengthS)
	{
		return false;
	}

	Clip = Buffer;
	KillerId = Death.KillerId;
	ClipEnd = End;
	ClipStart = End - Length;
	PlayStart = LocalNow;
	ReplayTime = ClipStart;
	NextFire = 0;
	NextFracture = 0;
	while (NextFire < Clip.GetFires().Num() && Clip.GetFires()[NextFire].Time < ClipStart)
	{
		++NextFire;
	}
	while (NextFracture < Clip.GetFractures().Num() && Clip.GetFractures()[NextFracture].Time < ClipStart)
	{
		++NextFracture;
	}
	State = EVerseKillCamState::Playing;
	return true;
}

void FVerseKillCamPlayer::Tick(double LocalNow)
{
	if (State != EVerseKillCamState::Playing)
	{
		return;
	}
	ReplayTime = FMath::Min(ClipEnd, ClipStart + (LocalNow - PlayStart));
	const TArray<FVerseKillCamBuffer::FFireSample>& Fires = Clip.GetFires();
	while (NextFire < Fires.Num() && Fires[NextFire].Time <= ReplayTime)
	{
		if (OnReplayFire)
		{
			OnReplayFire(Fires[NextFire].Event);
		}
		++NextFire;
	}
	const TArray<FVerseKillCamBuffer::FFractureSample>& Fractures = Clip.GetFractures();
	while (NextFracture < Fractures.Num() && Fractures[NextFracture].Time <= ReplayTime)
	{
		if (OnReplayFracture)
		{
			OnReplayFracture(Fractures[NextFracture].Event);
		}
		++NextFracture;
	}
	if (ReplayTime >= ClipEnd)
	{
		State = EVerseKillCamState::Finished;
		EndedAt = LocalNow;
	}
}

void FVerseKillCamPlayer::Skip(double LocalNow)
{
	if (State == EVerseKillCamState::Playing)
	{
		State = EVerseKillCamState::Skipped;
		EndedAt = LocalNow;
	}
}

void FVerseKillCamPlayer::Stop()
{
	State = EVerseKillCamState::Idle;
	Clip.Reset();
	KillerId = INDEX_NONE;
}

bool FVerseKillCamPlayer::GetKillerPose(FVector& OutLocation, FRotator& OutRotation) const
{
	return State == EVerseKillCamState::Playing && Clip.PoseAt(KillerId, ReplayTime, OutLocation, OutRotation);
}

bool FVerseKillCamPlayer::GetCamera(FVector& OutLocation, FRotator& OutRotation) const
{
	FVector Killer;
	FRotator View;
	if (!GetKillerPose(Killer, View))
	{
		return false;
	}
	// Over the killer's shoulder, looking where the killer looked (third person, README Camera).
	const FRotator Yaw(0.f, View.Yaw, 0.f);
	const FVector Forward = Yaw.Vector();
	const FVector Right = FRotationMatrix(Yaw).GetUnitAxis(EAxis::Y);
	OutLocation = Killer - Forward * Tuning.CameraBack + Right * Tuning.CameraRight + FVector::UpVector * Tuning.CameraUp;
	const FVector Target = Killer + View.Vector() * 1000.f;
	OutRotation = (Target - OutLocation).Rotation();
	return true;
}
