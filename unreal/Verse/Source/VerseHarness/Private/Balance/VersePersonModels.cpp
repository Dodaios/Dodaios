#include "Balance/VersePersonModels.h"

#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "VerseHarnessJson.h"

namespace VersePersonModelsPrivate
{
	struct FTrickName
	{
		EVerseTrick Trick;
		const TCHAR* Name;
	};

	// The frozen trick ids of bot.md 11.2.
	const FTrickName TrickNames[] = {
		{EVerseTrick::Spray, TEXT("spray")},
		{EVerseTrick::Camper, TEXT("camper")},
		{EVerseTrick::Rusher, TEXT("rusher")},
		{EVerseTrick::Slider, TEXT("slider")},
		{EVerseTrick::JumpPeek, TEXT("jumppeek")},
		{EVerseTrick::LeanSpam, TEXT("leanspam")},
		{EVerseTrick::Prone, TEXT("prone")},
		{EVerseTrick::WallSpam, TEXT("wallspam")},
		{EVerseTrick::Turtle, TEXT("turtle")},
		{EVerseTrick::Breacher, TEXT("breacher")},
		{EVerseTrick::Knife, TEXT("knife")},
		{EVerseTrick::Finisher, TEXT("finisher")},
		{EVerseTrick::Kiter, TEXT("kiter")},
		{EVerseTrick::Watcher, TEXT("watcher")},
		{EVerseTrick::Silent, TEXT("silent")},
		{EVerseTrick::Repeek, TEXT("repeek")},
		{EVerseTrick::Hider, TEXT("hider")},
	};
	static_assert(UE_ARRAY_COUNT(TrickNames) == VerseTrickCount, "one name per trick");

	float Num(const FVerseJson* Obj, const TCHAR* Field, float Default)
	{
		double Value = Default;
		return Obj && Obj->TryNumber(Field, Value) ? float(Value) : Default;
	}

	bool Flag(const FVerseJson* Obj, const TCHAR* Field)
	{
		bool Value = false;
		return Obj && Obj->TryBool(Field, Value) && Value;
	}
}

bool VerseTrickFromName(FName Name, EVerseTrick& OutTrick)
{
	for (const VersePersonModelsPrivate::FTrickName& Entry : VersePersonModelsPrivate::TrickNames)
	{
		if (Name == FName(Entry.Name))
		{
			OutTrick = Entry.Trick;
			return true;
		}
	}
	OutTrick = EVerseTrick::None;
	return Name.IsNone();
}

FName VerseTrickName(EVerseTrick Trick)
{
	for (const VersePersonModelsPrivate::FTrickName& Entry : VersePersonModelsPrivate::TrickNames)
	{
		if (Entry.Trick == Trick)
		{
			return FName(Entry.Name);
		}
	}
	return NAME_None;
}

FString FVersePersonModelSet::DefaultPath()
{
	return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data"), TEXT("bot"), TEXT("person_models.json"));
}

bool FVersePersonModelSet::LoadDefault(FVersePersonModelSet& Out, FString& OutError)
{
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *DefaultPath()))
	{
		OutError = FString::Printf(TEXT("cannot read %s"), *DefaultPath());
		return false;
	}
	return Parse(Text, Out, OutError);
}

bool FVersePersonModelSet::Parse(const FString& JsonText, FVersePersonModelSet& Out, FString& OutError)
{
	using namespace VersePersonModelsPrivate;

	const TSharedPtr<FVerseJson> Root = FVerseJson::Parse(JsonText, OutError);
	if (!Root.IsValid() || !Root->IsObject())
	{
		OutError = TEXT("person_models.json is not a JSON object: ") + OutError;
		return false;
	}
	if (Root->StringOr(TEXT("schema")) != TEXT("verse.person_models/1"))
	{
		OutError = TEXT("schema is not verse.person_models/1");
		return false;
	}
	Out = FVersePersonModelSet();
	const FVerseJson* Models = Root->ObjectField(TEXT("models"));
	const FVerseJson* Tricks = Root->ObjectField(TEXT("tricks"));
	if (!Models || !Tricks)
	{
		OutError = TEXT("models and tricks are required");
		return false;
	}
	for (const TPair<FString, TSharedPtr<FVerseJson>>& Pair : Models->Object)
	{
		const FVerseJson* M = Pair.Value.Get();
		FVersePersonModel Model;
		Model.Name = FName(*Pair.Key);
		Model.ReactionMeanMs = Num(M, TEXT("reactionMeanMs"), Model.ReactionMeanMs);
		Model.ReactionSdMs = Num(M, TEXT("reactionSdMs"), Model.ReactionSdMs);
		Model.TurnRateDegS = Num(M, TEXT("turnRateDegS"), Model.TurnRateDegS);
		Model.RecoilPatternComp = Num(M, TEXT("recoilPatternComp"), Model.RecoilPatternComp);
		Model.HeadAimChance = Num(M, TEXT("headAimChance"), Model.HeadAimChance);
		Model.AimWanderSdDeg = Num(M, TEXT("aimWanderSdDeg"), Model.AimWanderSdDeg);
		Model.AimWanderTheta = Num(M, TEXT("aimWanderTheta"), Model.AimWanderTheta);
		Model.LearnWeight = Num(M, TEXT("learnWeight"), Model.LearnWeight);
		Model.bLearning = !M || !M->Find(TEXT("learning")) || Flag(M, TEXT("learning"));
		Out.Models.Add(Model.Name, Model);
	}
	for (const TPair<FString, TSharedPtr<FVerseJson>>& Pair : Tricks->Object)
	{
		FVerseTrickConfig Config;
		if (!VerseTrickFromName(FName(*Pair.Key), Config.Trick) || Config.Trick == EVerseTrick::None)
		{
			OutError = FString::Printf(TEXT("unknown trick id '%s'"), *Pair.Key);
			return false;
		}
		const FVerseJson* T = Pair.Value.Get();
		const FVerseJson* Input = T ? T->ObjectField(TEXT("input")) : nullptr;
		const FVerseJson* Intent = T ? T->ObjectField(TEXT("intent")) : nullptr;
		Config.LeanFlipMinMs = Num(Input, TEXT("leanFlipMinMs"), Config.LeanFlipMinMs);
		Config.LeanFlipMaxMs = Num(Input, TEXT("leanFlipMaxMs"), Config.LeanFlipMaxMs);
		Config.ProneBeyondM = Num(Input, TEXT("proneBeyondM"), Config.ProneBeyondM);
		Config.MeleeRangeM = Num(Input, TEXT("meleeRangeM"), Config.MeleeRangeM);
		Config.BackOffInsideM = Num(Input, TEXT("backOffInsideM"), Config.BackOffInsideM);
		Config.SlideCooldownS = Num(Input, TEXT("slideCooldownS"), Config.SlideCooldownS);
		FVerseTrickIntent& I = Config.Intent;
		I.HoldSpawnCoverRadiusM = Num(Intent, TEXT("holdSpawnCoverRadiusM"), 0.f);
		I.bRushBelief = Flag(Intent, TEXT("rushBelief"));
		I.PreferRangeM = Num(Intent, TEXT("preferRangeM"), 0.f);
		I.bWallShotAuthorityOff = Flag(Intent, TEXT("wallShotAuthorityOff"));
		I.bFireThroughPenetrable = Flag(Intent, TEXT("fireThroughPenetrable"));
		I.bStayBehindBulwark = Flag(Intent, TEXT("stayBehindBulwark"));
		I.bBreachEveryRoutePiece = Flag(Intent, TEXT("breachEveryRoutePiece"));
		I.bStalkForFinisher = Flag(Intent, TEXT("stalkForFinisher"));
		I.bWatchOpponentSpawn = Flag(Intent, TEXT("watchOpponentSpawn"));
		I.RepeekSameAngleWithinS = Num(Intent, TEXT("repeekSameAngleWithinS"), 0.f);
		I.bAvoidFights = Flag(Intent, TEXT("avoidFights"));
		Out.Tricks.Add(FName(*Pair.Key), Config);
	}
	if (Out.Tricks.Num() != VerseTrickCount)
	{
		OutError = FString::Printf(TEXT("person_models.json lists %d tricks, bot.md 11.2 has %d"), Out.Tricks.Num(),
			VerseTrickCount);
		return false;
	}
	return true;
}
