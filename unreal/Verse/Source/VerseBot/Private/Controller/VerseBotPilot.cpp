#include "Controller/VerseBotPilot.h"

#include "Brain/VerseBotBrainCore.h"
#include "Controller/VerseBotArenaData.h"
#include "Controller/VerseBotEngineQueries.h"
#include "Engine/World.h"
#include "GameFramework/Controller.h"
#include "GameFramework/PlayerState.h"
#include "Learning/VerseBotMatchMemory.h"

FVerseBotPilot::FVerseBotPilot(AController& InOwner)
	: Owner(&InOwner)
{
}

FVerseBotPilot::~FVerseBotPilot() = default;

void FVerseBotPilot::Reset(const UVerseBotTier& Tier, uint64 Seed, bool bLearning)
{
	AController* C = Owner.Get();
	if (!C)
	{
		return;
	}
	Memory = MakeUnique<FVerseBotMatchMemory>();
	Queries = MakeUnique<FVerseBotEngineQueries>(*C);
	Brain = MakeUnique<FVerseBotBrainCore>();
	Brain->UseMemory(*Memory);
	FVerseBotBrainCore::FConfig Config;
	Config.Seed = Seed;
	Config.SelfId = C->PlayerState ? C->PlayerState->GetPlayerId() : 0;
	Config.bLearning = bLearning;
	Brain->Init(Tier, Config);
	bArena = false;
	LastThinkMs = 0;
}

FVerseInputFrame FVerseBotPilot::Think(const FVersePerceptFrame& InFrame)
{
	AController* C = Owner.Get();
	if (!Brain || !C)
	{
		return FVerseInputFrame();
	}
	if (!bArena)
	{
		if (UWorld* World = C->GetWorld())
		{
			bArena = FVerseBotArenaData::AttachTo(*World, *Brain, *Queries, *Queries,
				C->PlayerState ? C->PlayerState->GetPlayerId() : INDEX_NONE) != nullptr;
		}
	}
	// One monotonic clock for the brain, as the bot controller keeps it.
	FVersePerceptFrame Frame = InFrame;
	Frame.ServerTimeMs = FMath::Max(Frame.ServerTimeMs, LastThinkMs);
	LastThinkMs = Frame.ServerTimeMs;
	return Brain->Think(Frame, *Queries);
}
