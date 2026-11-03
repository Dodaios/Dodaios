#include "Rules/VerseRuleset.h"

#include "Engine/DataAsset.h"
#include "Engine/World.h"
#include "Rules/VersePlayerState.h"

void UVerseRuleset::Init(AVerseGameMode* InMode, const UVerseRulesetConfig* InConfig)
{
	Mode = InMode;
	Config = InConfig;
}

void UVerseRuleset::GetLoadout(const AVersePlayerState* P, TMap<EVerseLoadoutSlot, const UPrimaryDataAsset*>& Out) const
{
	Out.Reset();
	if (!Config)
	{
		return;
	}
	for (const TPair<EVerseLoadoutSlot, TSoftObjectPtr<UPrimaryDataAsset>>& Pair : Config->Loadout)
	{
		if (const UPrimaryDataAsset* Asset = Pair.Value.LoadSynchronous())
		{
			Out.Add(Pair.Key, Asset);
		}
	}
}

float UVerseRuleset::GetRespawnDelay(const AVersePlayerState* P) const
{
	return Config ? Config->RespawnDelay : 3.f;
}

float UVerseRuleset::GetSpawnProtection(const AVersePlayerState* P) const
{
	return Config ? Config->SpawnProtectionMax : 2.f;
}

float UVerseRuleset::Now() const
{
	if (Host.ServerTime)
	{
		return Host.ServerTime();
	}
	const UWorld* World = GetWorld();
	return World ? World->GetTimeSeconds() : 0.f;
}

TArray<AVersePlayerState*> UVerseRuleset::GetPlayers() const
{
	TArray<AVersePlayerState*> Out = Host.Players ? Host.Players() : TArray<AVersePlayerState*>();
	Out.RemoveAll([](const AVersePlayerState* P) { return P == nullptr; });
	return Out;
}

AVersePlayerState* UVerseRuleset::FindPlayer(int32 PlayerId) const
{
	for (AVersePlayerState* P : GetPlayers())
	{
		if (P->GetPlayerId() == PlayerId)
		{
			return P;
		}
	}
	return nullptr;
}
