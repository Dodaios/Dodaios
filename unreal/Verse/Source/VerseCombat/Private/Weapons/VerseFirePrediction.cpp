#include "Weapons/VerseFirePrediction.h"

FVerseShotReconcile FVerseFirePredictor::Confirm(uint16 Counter, EVerseShotResult Result)
{
	FVerseShotReconcile Out;
	const int32 Index = Pending.IndexOfByPredicate([Counter](const FVersePredictedShot& S) { return S.Counter == Counter; });
	if (Index == INDEX_NONE)
	{
		return Out;
	}
	Out.bKnown = true;
	if (Result == EVerseShotResult::Rejected)
	{
		Out.bRemoveBolt = true;
		Out.RefundRounds = 1;
	}
	Pending.RemoveAt(Index);
	return Out;
}

TArray<uint16> FVerseFirePredictor::Expire(float Now)
{
	TArray<uint16> Expired;
	Pending.RemoveAll([Now, &Expired](const FVersePredictedShot& S)
	{
		if (Now - S.Time > TimeoutS)
		{
			Expired.Add(S.Counter);
			return true;
		}
		return false;
	});
	return Expired;
}

const FVersePredictedShot* FVerseFirePredictor::Find(uint16 Counter) const
{
	return Pending.FindByPredicate([Counter](const FVersePredictedShot& S) { return S.Counter == Counter; });
}
