#include "Rules/VerseRuleset_Deathmatch.h"

#include "Damage/VerseCombatStateComponent.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Pawn.h"
#include "Misc/Guid.h"
#include "Net/Core/PushModel/PushModel.h"
#include "Rules/VersePlayerState.h"
#include "Rules/VerseSpawnPoint.h"
#include "VerseLog.h"

const FName UVerseRuleset_Deathmatch::RulesetId(TEXT("endless/1"));

namespace
{
	const FName BulwarkId(TEXT("bulwark"));
	const FName BreachChargeId(TEXT("breach_charge"));
	constexpr float GadgetBlockRadiusCm = 300.f;
}

void UVerseRuleset_Deathmatch::Init(AVerseGameMode* InMode, const UVerseRulesetConfig* InConfig)
{
	Super::Init(InMode, InConfig);
	Subscribe();
}

void UVerseRuleset_Deathmatch::BeginDestroy()
{
	Unsubscribe();
	Super::BeginDestroy();
}

void UVerseRuleset_Deathmatch::Subscribe()
{
	Unsubscribe();
	UVerseEventHub* Hub = UVerseEventHub::Get(this);
	if (!Hub)
	{
		return;
	}
	BoundHub = Hub;
	Handles.Add(Hub->OnFire.AddUObject(this, &UVerseRuleset_Deathmatch::HandleFire));
	Handles.Add(Hub->OnHit.AddUObject(this, &UVerseRuleset_Deathmatch::HandleHit));
	Handles.Add(Hub->OnGadget.AddUObject(this, &UVerseRuleset_Deathmatch::HandleGadget));
	Handles.Add(Hub->OnFracture.AddUObject(this, &UVerseRuleset_Deathmatch::HandleFracture));
	Handles.Add(Hub->OnArenaSwitch.AddUObject(this, &UVerseRuleset_Deathmatch::HandleArenaSwitch));
}

void UVerseRuleset_Deathmatch::Unsubscribe()
{
	if (UVerseEventHub* Hub = BoundHub.Get())
	{
		Hub->OnFire.Remove(Handles.IsValidIndex(0) ? Handles[0] : FDelegateHandle());
		Hub->OnHit.Remove(Handles.IsValidIndex(1) ? Handles[1] : FDelegateHandle());
		Hub->OnGadget.Remove(Handles.IsValidIndex(2) ? Handles[2] : FDelegateHandle());
		Hub->OnFracture.Remove(Handles.IsValidIndex(3) ? Handles[3] : FDelegateHandle());
		Hub->OnArenaSwitch.Remove(Handles.IsValidIndex(4) ? Handles[4] : FDelegateHandle());
	}
	Handles.Reset();
	BoundHub.Reset();
}

UVerseRuleset_Deathmatch::FPlayerRecord& UVerseRuleset_Deathmatch::Record(const AVersePlayerState* P)
{
	const TWeakObjectPtr<const AVersePlayerState> Key(P);
	if (FPlayerRecord* Found = Records.Find(Key))
	{
		return *Found;
	}
	// A player first seen mid-set (a bot spawned by a later OnArenaSwitch listener) gets its
	// identity now, so the set summary never reports player 0.
	FPlayerRecord& Added = Records.Add(Key);
	if (P)
	{
		Added.Line.PlayerId = P->GetPlayerId();
		Added.Line.bIsBot = P->IsBotPlayer();
	}
	return Added;
}

const UVerseRuleset_Deathmatch::FPlayerRecord* UVerseRuleset_Deathmatch::FindRecord(const AVersePlayerState* P) const
{
	return Records.Find(TWeakObjectPtr<const AVersePlayerState>(P));
}

bool UVerseRuleset_Deathmatch::IsSpawnProtected(const AVersePlayerState* P) const
{
	const FPlayerRecord* R = FindRecord(P);
	return R && R->bAlive && R->bProtected;
}

bool UVerseRuleset_Deathmatch::IsAlive(const AVersePlayerState* P) const
{
	const FPlayerRecord* R = FindRecord(P);
	return R && R->bAlive;
}

// ---------------------------------------------------------------------------
// Match and sets
// ---------------------------------------------------------------------------

void UVerseRuleset_Deathmatch::OnMatchStart()
{
	if (bRunning)
	{
		EndMatch();
	}
	bRunning = true;
	SessionId = FGuid::NewGuid().ToString(EGuidFormats::DigitsWithHyphensLower);
	SetIndex = 0;
	DeathCount = 0;
	ActiveGadgets.Reset();
	Records.Reset();
	for (AVersePlayerState* P : GetPlayers())
	{
		P->Kills = P->Deaths = P->Headshots = P->Finishers = 0;
		P->SetKills = P->SetsWon = 0;
		P->RespawnAt = 0.f;
		P->MarkScoreDirty();
		Record(P);
	}
	StartSet();
	// Spawn both: the second spawn already sees the first player as its opponent.
	for (AVersePlayerState* P : GetPlayers())
	{
		SpawnPlayer(P);
	}
	UE_LOG(LogVerseCombat, Log, TEXT("Deathmatch: match %s started with %d players"), *SessionId, Records.Num());
}

void UVerseRuleset_Deathmatch::StartSet()
{
	++SetIndex;
	SetStartTime = Now();
	SetStartUnix = Host.UnixNow ? Host.UnixNow() : double(FDateTime::UtcNow().ToUnixTimestamp());
	for (auto& Pair : Records)
	{
		const int32 Id = Pair.Value.Line.PlayerId;
		const bool bBot = Pair.Value.Line.bIsBot;
		Pair.Value.Line = FVerseSetLine();
		Pair.Value.Line.PlayerId = Id;
		Pair.Value.Line.bIsBot = bBot;
		Pair.Value.Streak = 0;
	}
	for (AVersePlayerState* P : GetPlayers())
	{
		FPlayerRecord& R = Record(P);
		R.Line.PlayerId = P->GetPlayerId();
		R.Line.bIsBot = P->IsBotPlayer();
		P->SetKills = 0;
		P->MarkScoreDirty();
	}
}

void UVerseRuleset_Deathmatch::EndMatch()
{
	if (!bRunning)
	{
		return;
	}
	FVerseSetSummary Summary;
	BuildSummary(Summary, nullptr);
	bRunning = false;
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnSetEnded.Broadcast(Summary);
	}
	UE_LOG(LogVerseCombat, Log, TEXT("Deathmatch: match %s ended mid-set %d (unfinished)"), *SessionId, SetIndex);
}

bool UVerseRuleset_Deathmatch::IsSetOver(AVersePlayerState*& OutWinner) const
{
	const int32 Target = Config ? Config->KillsPerSet : 10;
	for (AVersePlayerState* P : GetPlayers())
	{
		if (P->SetKills >= Target)
		{
			OutWinner = P;
			return true;
		}
	}
	return false;
}

void UVerseRuleset_Deathmatch::FinishSet(AVersePlayerState* Winner)
{
	FVerseSetSummary Summary;
	BuildSummary(Summary, Winner);
	Winner->SetsWon += 1;
	Winner->MarkScoreDirty();
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnSetEnded.Broadcast(Summary);
	}
	StartSet();
}

void UVerseRuleset_Deathmatch::BuildSetSummary(FVerseSetSummary& Out) const
{
	AVersePlayerState* Winner = nullptr;
	BuildSummary(Out, IsSetOver(Winner) ? Winner : nullptr);
}

void UVerseRuleset_Deathmatch::BuildSummary(FVerseSetSummary& Out, const AVersePlayerState* Winner) const
{
	Out = FVerseSetSummary();
	Out.SessionId = SessionId;
	Out.SetIndex = SetIndex;
	Out.MatchId = FString::Printf(TEXT("%s/%d"), *SessionId, SetIndex);
	Out.RulesetId = RulesetId;
	Out.StartedAtUnix = SetStartUnix;
	Out.EndedAtUnix = Host.UnixNow ? Host.UnixNow() : double(FDateTime::UtcNow().ToUnixTimestamp());
	Out.MatchTimeS = FMath::Max(0.f, Now() - SetStartTime);

	// The person is the first player without a bot tier; the opponent is the other one.
	const AVersePlayerState* Person = nullptr;
	const AVersePlayerState* Opponent = nullptr;
	for (const AVersePlayerState* P : GetPlayers())
	{
		if (!Person && !P->IsBotPlayer())
		{
			Person = P;
		}
	}
	for (const AVersePlayerState* P : GetPlayers())
	{
		if (P != Person && !Opponent)
		{
			Opponent = P;
		}
	}
	if (!Person)
	{
		Person = Opponent;
		Opponent = nullptr;
		for (const AVersePlayerState* P : GetPlayers())
		{
			if (P != Person && !Opponent)
			{
				Opponent = P;
			}
		}
	}
	if (const FPlayerRecord* R = Person ? FindRecord(Person) : nullptr)
	{
		Out.Person = R->Line;
	}
	if (const FPlayerRecord* R = Opponent ? FindRecord(Opponent) : nullptr)
	{
		Out.Opponent = R->Line;
	}
	Out.BotTier = Opponent ? Opponent->BotTier : NAME_None;
	if (!Winner)
	{
		Out.Outcome = EVerseSetOutcome::Unfinished;
	}
	else
	{
		Out.Outcome = Winner == Person ? EVerseSetOutcome::Won : EVerseSetOutcome::Lost;
	}
}

// ---------------------------------------------------------------------------
// Kills, respawn, protection
// ---------------------------------------------------------------------------

void UVerseRuleset_Deathmatch::OnKill(const FVerseDeathEvent& E)
{
	if (!bRunning)
	{
		return;
	}
	AVersePlayerState* Victim = FindPlayer(E.VictimId);
	if (!Victim)
	{
		return;
	}
	FPlayerRecord& VR = Record(Victim);
	if (!VR.bAlive)
	{
		return;  // one death per life
	}
	++DeathCount;
	VR.bAlive = false;
	VR.bProtected = false;
	VR.Streak = 0;
	VR.Line.Deaths += 1;
	VR.RespawnAt = E.ServerTime + GetRespawnDelay(Victim);
	Victim->Deaths += 1;
	Victim->RespawnAt = VR.RespawnAt;
	Victim->MarkScoreDirty();
	WriteProtection(Victim, false, 0.f);

	AVersePlayerState* Killer = E.KillerId != E.VictimId ? FindPlayer(E.KillerId) : nullptr;
	if (Killer)
	{
		FPlayerRecord& KR = Record(Killer);
		const bool bHead = E.LastZone == EVerseHitZone::Head;
		const bool bFinisher = E.Cause == EVerseDamageSource::Finisher;
		KR.Line.Kills += 1;
		KR.Line.Headshots += bHead ? 1 : 0;
		KR.Line.Finishers += bFinisher ? 1 : 0;
		KR.Line.MeleeKills += E.Cause == EVerseDamageSource::Melee ? 1 : 0;
		KR.Streak += 1;
		KR.Line.BestStreak = FMath::Max(KR.Line.BestStreak, KR.Streak);
		if (!E.WeaponId.IsNone())
		{
			FIntVector4& W = KR.Line.PerWeapon.FindOrAdd(E.WeaponId);
			W.X += 1;
			W.Y += bHead ? 1 : 0;
		}
		Killer->Kills += 1;
		Killer->SetKills += 1;
		Killer->Headshots += bHead ? 1 : 0;
		Killer->Finishers += bFinisher ? 1 : 0;
		Killer->MarkScoreDirty();
	}

	AVersePlayerState* Winner = nullptr;
	if (IsSetOver(Winner) && Winner)
	{
		FinishSet(Winner);
	}
}

void UVerseRuleset_Deathmatch::Advance(float ServerTime)
{
	if (!bRunning)
	{
		return;
	}
	for (AVersePlayerState* P : GetPlayers())
	{
		FPlayerRecord& R = Record(P);
		if (!R.bAlive && ServerTime >= R.RespawnAt)
		{
			SpawnPlayer(P);
		}
		else if (R.bAlive && R.bProtected && ServerTime >= R.ProtectedUntil)
		{
			EndProtection(P);
		}
	}
}

void UVerseRuleset_Deathmatch::SpawnPlayer(AVersePlayerState* P)
{
	AVerseSpawnPoint* Spawn = ChooseSpawn(P);
	if (Host.Respawn)
	{
		Host.Respawn(P, Spawn);
	}
	FPlayerRecord& R = Record(P);
	R.bAlive = true;
	R.bProtected = true;
	R.ProtectedUntil = Now() + GetSpawnProtection(P);
	WriteProtection(P, true, R.ProtectedUntil);
}

void UVerseRuleset_Deathmatch::EndProtection(AVersePlayerState* P)
{
	FPlayerRecord& R = Record(P);
	if (!R.bProtected)
	{
		return;
	}
	R.bProtected = false;
	WriteProtection(P, false, R.ProtectedUntil);
}

void UVerseRuleset_Deathmatch::WriteProtection(const AVersePlayerState* P, bool bOn, float Until) const
{
	UVerseCombatStateComponent* Combat = Host.CombatState ? Host.CombatState(P) : nullptr;
	if (!Combat)
	{
		return;
	}
	Combat->bSpawnProtected = bOn;
	Combat->SpawnProtectedUntil = Until;
	MARK_PROPERTY_DIRTY_FROM_NAME(UVerseCombatStateComponent, bSpawnProtected, Combat);
	MARK_PROPERTY_DIRTY_FROM_NAME(UVerseCombatStateComponent, SpawnProtectedUntil, Combat);
}

bool UVerseRuleset_Deathmatch::CanDamage(const FVerseDamageContext& Ctx) const
{
	const AVersePlayerState* Victim = Ctx.Victim ? Ctx.Victim->GetPlayerState<AVersePlayerState>() : nullptr;
	if (!Victim)
	{
		return true;  // not a duel player (a test dummy, a drone): the ruleset has no say
	}
	return CanDamagePlayer(Victim, Ctx.Source);
}

bool UVerseRuleset_Deathmatch::CanDamagePlayer(const AVersePlayerState* Victim, EVerseDamageSource Source) const
{
	if (IsSpawnProtected(Victim))
	{
		return false;
	}
	if (const UVerseCombatStateComponent* Combat = Host.CombatState ? Host.CombatState(Victim) : nullptr)
	{
		if (Combat->Phase == EVerseCombatPhase::FinisherVictim && Source != EVerseDamageSource::Finisher)
		{
			return false;
		}
	}
	return true;
}

void UVerseRuleset_Deathmatch::OnPlayerAction(AVersePlayerState* P, EVersePlayerAction Action)
{
	if (!P)
	{
		return;
	}
	switch (Action)
	{
	case EVersePlayerAction::Fire:
	case EVersePlayerAction::Melee:
	case EVersePlayerAction::Gadget:
		EndProtection(P);
		break;
	default:
		break;  // reload, ADS, movement and slot switches keep protection (9.3)
	}
}

// ---------------------------------------------------------------------------
// Spawn selection (9.2)
// ---------------------------------------------------------------------------

bool UVerseRuleset_Deathmatch::IsSpawnBlocked(const FVector& Floor, const AVersePlayerState* Respawning) const
{
	if (Host.PawnNear && Host.PawnNear(Floor, VerseSpawnSelection::BlockRadiusCm, Respawning))
	{
		return true;
	}
	for (const FVerseGadgetEvent& G : ActiveGadgets)
	{
		if (FVector::Dist(FVector(G.Location), Floor) <= GadgetBlockRadiusCm)
		{
			return true;
		}
	}
	return false;
}

AVerseSpawnPoint* UVerseRuleset_Deathmatch::ChooseSpawn(const AVersePlayerState* P)
{
	TArray<AVerseSpawnPoint*> Points = Host.SpawnPoints ? Host.SpawnPoints() : TArray<AVerseSpawnPoint*>();
	Points.RemoveAll([](const AVerseSpawnPoint* S) { return S == nullptr; });
	// Actor iteration order is not stable across World Partition loads; the seeded tie break
	// indexes into this list, so order it by SpawnId, then by actor name.
	Points.Sort([](const AVerseSpawnPoint& A, const AVerseSpawnPoint& B) {
		if (A.SpawnId != B.SpawnId)
		{
			return A.SpawnId.LexicalLess(B.SpawnId);
		}
		return A.GetFName().LexicalLess(B.GetFName());
	});
	if (Points.IsEmpty())
	{
		UE_LOG(LogVerseCombat, Warning, TEXT("Deathmatch: no AVerseSpawnPoint in the arena"));
		LastChoice = FVerseSpawnChoice();
		return nullptr;
	}
	TArray<FVerseSpawnCandidate> Candidates;
	for (const AVerseSpawnPoint* S : Points)
	{
		FVerseSpawnCandidate& C = Candidates.AddDefaulted_GetRef();
		C.Floor = Host.SpawnFloor ? Host.SpawnFloor(S) : S->GetFloorLocation();
		C.ProbeHeightsM = S->ProbeHeightsM;
		C.bBlocked = IsSpawnBlocked(C.Floor, P);
	}
	// 1v1: the opponent is the only other player; with more, the nearest living enemy would be used.
	TOptional<FVector> OpponentEye;
	TOptional<FVector> OpponentFloor;
	for (const AVersePlayerState* Other : GetPlayers())
	{
		FVector Eye;
		if (Other != P && IsAlive(Other) && Host.EyePoint && Host.EyePoint(Other, Eye))
		{
			OpponentEye = Eye;
			FVector Floor;
			if (Host.FloorPoint && Host.FloorPoint(Other, Floor))
			{
				OpponentFloor = Floor;
			}
			break;
		}
	}
	auto LineClear = [this](const FVector& A, const FVector& B) { return Host.LineClear ? Host.LineClear(A, B) : true; };
	auto PathLength = [this](const FVector& A, const FVector& B) { return Host.PathLength ? Host.PathLength(A, B) : -1.f; };
	LastChoice = VerseSpawnSelection::Choose(Candidates, OpponentEye, LineClear, PathLength, MatchSeed, DeathCount, OpponentFloor);
	return Points.IsValidIndex(LastChoice.Index) ? Points[LastChoice.Index] : nullptr;
}

// ---------------------------------------------------------------------------
// Statistics from the hub
// ---------------------------------------------------------------------------

void UVerseRuleset_Deathmatch::HandleFire(const FVerseFireEvent& E)
{
	if (!bRunning)
	{
		return;
	}
	if (AVersePlayerState* P = FindPlayer(E.ShooterId))
	{
		FPlayerRecord& R = Record(P);
		R.Line.ShotsFired += 1;
		if (!E.WeaponId.IsNone())
		{
			R.Line.PerWeapon.FindOrAdd(E.WeaponId).Z += 1;
		}
		// The first own shot ends protection on the tick it is fired (D4), even when the
		// weapon code reports it only through the hub.
		OnPlayerAction(P, EVersePlayerAction::Fire);
	}
}

void UVerseRuleset_Deathmatch::HandleHit(const FVerseHitEvent& E)
{
	if (!bRunning || E.bBlockedBySpawnProtection)
	{
		return;
	}
	if (AVersePlayerState* Shooter = FindPlayer(E.InstigatorId))
	{
		FPlayerRecord& R = Record(Shooter);
		if (E.Source == EVerseDamageSource::Bolt)
		{
			R.Line.ShotsHit += 1;
			if (!E.WeaponId.IsNone())
			{
				R.Line.PerWeapon.FindOrAdd(E.WeaponId).W += 1;
			}
		}
		R.Line.DamageDealt += FMath::RoundToInt(E.Damage);
	}
	if (AVersePlayerState* Victim = FindPlayer(E.VictimId))
	{
		Record(Victim).Line.DamageTaken += FMath::RoundToInt(E.Damage);
	}
}

void UVerseRuleset_Deathmatch::HandleGadget(const FVerseGadgetEvent& E)
{
	auto Remove = [this, &E](const FName Id) {
		// Destroyed, Expired and Detonate end the nearest active gadget of that owner and kind.
		int32 Best = INDEX_NONE;
		double BestD = TNumericLimits<double>::Max();
		for (int32 i = 0; i < ActiveGadgets.Num(); ++i)
		{
			const FVerseGadgetEvent& G = ActiveGadgets[i];
			const double D = FVector::DistSquared(FVector(G.Location), FVector(E.Location));
			if (G.GadgetId == Id && G.OwnerId == E.OwnerId && D < BestD)
			{
				Best = i;
				BestD = D;
			}
		}
		if (Best != INDEX_NONE)
		{
			ActiveGadgets.RemoveAt(Best);
		}
	};
	switch (E.Kind)
	{
	case EVerseGadgetEventKind::Deploy:
		// One active Bulwark per owner (2.3): a second deploy replaces the first.
		ActiveGadgets.RemoveAll([&E](const FVerseGadgetEvent& G) { return G.GadgetId == BulwarkId && G.OwnerId == E.OwnerId; });
		ActiveGadgets.Add(E);
		break;
	case EVerseGadgetEventKind::Plant:
		ActiveGadgets.Add(E);
		break;
	case EVerseGadgetEventKind::Destroyed:
	case EVerseGadgetEventKind::Expired:
		Remove(E.GadgetId.IsNone() ? BulwarkId : E.GadgetId);
		break;
	case EVerseGadgetEventKind::Detonate:
		Remove(E.GadgetId.IsNone() ? BreachChargeId : E.GadgetId);
		break;
	}
	if (!bRunning)
	{
		return;
	}
	if (AVersePlayerState* P = FindPlayer(E.OwnerId))
	{
		if (E.Kind == EVerseGadgetEventKind::Deploy && E.GadgetId == BulwarkId)
		{
			Record(P).Line.BulwarksPlaced += 1;
		}
		if (E.Kind == EVerseGadgetEventKind::Deploy || E.Kind == EVerseGadgetEventKind::Plant)
		{
			OnPlayerAction(P, EVersePlayerAction::Gadget);
		}
	}
}

void UVerseRuleset_Deathmatch::HandleFracture(const FVerseFractureEvent& E)
{
	if (!bRunning || E.Cause != EVerseFractureCause::Breach || E.ToState != EVersePieceState::Breached)
	{
		return;
	}
	// FVerseFractureEvent carries the instigator as the low byte of the player state id.
	for (AVersePlayerState* P : GetPlayers())
	{
		if (uint8(P->GetPlayerId() & 0xFF) == E.Instigator)
		{
			Record(P).Line.WallsBreached += 1;
			break;
		}
	}
}

void UVerseRuleset_Deathmatch::HandleArenaSwitch(const FVerseArenaSwitchEvent& E)
{
	// AVerseGameMode forwards "arena on" as OnMatchStart; closing the arena ends the match here.
	if (!E.bArenaOn)
	{
		EndMatch();
	}
}

// ---------------------------------------------------------------------------
// FTickableGameObject
// ---------------------------------------------------------------------------

void UVerseRuleset_Deathmatch::Tick(float DeltaTime)
{
	Advance(Now());
}

TStatId UVerseRuleset_Deathmatch::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseRuleset_Deathmatch, STATGROUP_Tickables);
}

bool UVerseRuleset_Deathmatch::IsTickable() const
{
	return bAutoTick && bRunning && !IsTemplate() && !HasAnyFlags(RF_BeginDestroyed);
}

UWorld* UVerseRuleset_Deathmatch::GetTickableGameObjectWorld() const
{
	return GetWorld();
}
