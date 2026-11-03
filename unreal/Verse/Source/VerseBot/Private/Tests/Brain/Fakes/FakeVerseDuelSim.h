#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "Bot/VersePerceptTypes.h"
#include "Brain/VerseBotBrainCore.h"
#include "Brain/VerseBotReplay.h"
#include "CoreMinimal.h"
#include "Tests/Brain/Fakes/FakeVerseBotWorld.h"
#include "VerseGameplayTags.h"
#include "VerseRng.h"

/**
 * A world-free 1v1 at 60 Hz for WP08's tests (the WP07 perception, WP09 aim, WP01/WP02 pawn and
 * WP10 harness fakes in one): it moves the bot's fake pawn from the input frame, scripts the
 * opponent, and builds the bot's percept frames with the fair rules of bot.md 3 (55 deg cone and
 * line of sight for sight, audibility ranges and error for hearing, hurt percepts, HUD events).
 * The brain never sees the opponent's state except through those frames.
 */
class FFakeVerseDuelSim
{
public:
	enum class EModel : uint8
	{
		/** Walks a loop of waypoints, runs (audible), fights on sight. */
		Patrol,
		/** Avoids every fight: hides at a far spot, crouch-walks, never fires (BG12 hider). */
		Hider,
		/** Silent and still at a fixed spot (F3). */
		Still
	};

	struct FConfig
	{
		uint64 Seed = 1;
		EModel Model = EModel::Patrol;
		FVector StillSpot = FVector(0.f, 1000.f, 0.f);
		float BotHitChance = 0.3f;
		float OpponentHitChance = 0.22f;
	};

	FFakeVerseBotWorldQueries World;
	FVerseBotBrainCore Brain;
	FConfig Config;
	UVerseBotTier* Tier = nullptr;

	// Truth (sim only; the brain never reads it).
	FVector BotPos, BotVel = FVector::ZeroVector;
	FRotator BotView = FRotator::ZeroRotator;
	float BotHealth = 100.f;
	int32 BotMag = 30, BotReserve = 90;
	float BotDeadUntil = -1.f;
	FVector OppPos, OppVel = FVector::ZeroVector;
	float OppYaw = 0.f;
	float OppHealth = 100.f;
	float OppDeadUntil = -1.f;
	float OppSawBotAt = -1.f;
	float OppNextShot = 0.f;
	float BotNextShot = 0.f;
	int32 OppWaypoint = 0;
	uint32 TimeMs = 0;
	uint32 NextPerceptId = 1;
	float NextFootstepS = 0.f;
	FVerseRng Rng;

	// Results
	int32 BotKills = 0, OppKills = 0;
	int32 Ticks = 0;
	int32 VisibleTicks = 0;
	int32 FireTicks = 0;
	float LifeStartS = 0.f;
	bool bContactThisLife = false;
	TArray<float> TimeToContactS;
	TArray<double> ThinkUs;
	bool bMeasure = false;
	TArray<FVersePerceptFrame> RecordedFrames;
	bool bRecordFrames = false;
	TArray<uint8> Outputs;
	bool bRecordOutputs = false;

	/** F4 evidence at the shot event: every round the bot's weapon fired, and every percept the
	 * sim delivered (id -> kind, time), so a test can re-check each audit record on its own. */
	enum class EDelivered : uint8 { Sight, Heard };
	struct FDelivered
	{
		EDelivered Kind = EDelivered::Sight;
		uint32 TimeMs = 0;
	};
	struct FShot
	{
		uint32 TimeMs = 0;
		/** The fair sight rule held at the shot tick (truth, sim only). */
		bool bBotSawOpponent = false;
	};
	bool bRecordShots = false;
	TArray<FShot> Shots;
	TMap<uint32, FDelivered> Delivered;

	static constexpr int32 BotId = 1;
	static constexpr int32 OppId = 2;

	FFakeVerseDuelSim(FName TierId, const FConfig& InConfig)
		: Config(InConfig)
		, Rng(InConfig.Seed, 7, EVerseRngSalt::Harness)
	{
		FFakeVerseBotWorldQueries::BuildStandardArena(World);
		Tier = NewObject<UVerseBotTier>();
		Tier->AddToRoot();
		UVerseBotTier::ApplyStartValues(TierId, *Tier);
		FVerseBotBrainCore::FConfig BC;
		BC.Seed = InConfig.Seed;
		BC.SelfId = BotId;
		Brain.Init(*Tier, BC);
		BotPos = World.Spawns[0];
		OppPos = Config.Model == EModel::Still ? Config.StillSpot : World.Spawns[1];
		BotView = (OppPos - BotPos).Rotation();
		BotView.Pitch = 0.f;
		BotView.Yaw += 90.f;
	}

	~FFakeVerseDuelSim()
	{
		if (Tier)
		{
			Tier->RemoveFromRoot();
		}
	}

	FFakeVerseDuelSim(const FFakeVerseDuelSim&) = delete;
	FFakeVerseDuelSim& operator=(const FFakeVerseDuelSim&) = delete;

	float Now() const { return float(TimeMs) / 1000.f; }

	FVector BotEye() const { return BotPos + FVector(0, 0, 165.f); }
	FVector OppPelvis() const { return OppPos + FVector(0, 0, 95.f); }

	bool BotSeesOpp() const
	{
		if (OppDeadUntil > Now())
		{
			return false;
		}
		const FVector To = OppPelvis() + FVector(0, 0, 40.f) - BotEye();
		const float Angle = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(float(FVector::DotProduct(To.GetSafeNormal(), BotView.Vector())), -1.f, 1.f)));
		const bool bClose = To.Size2D() < 200.f;
		return (Angle <= 55.f || bClose) && !World.Blocked(BotEye(), OppPelvis() + FVector(0, 0, 40.f));
	}

	bool OppSeesBot() const
	{
		const FVector To = BotEye() - (OppPos + FVector(0, 0, 165.f));
		const FVector Facing = FRotator(0.f, OppYaw, 0.f).Vector();
		const float Angle = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(float(FVector::DotProduct(To.GetSafeNormal2D(), Facing)), -1.f, 1.f)));
		return Angle <= 55.f && !World.Blocked(OppPos + FVector(0, 0, 165.f), BotEye());
	}

	FVector FarthestSpawnFrom(const FVector& From)
	{
		FVector Best = World.Spawns[0];
		float BestD = -1.f;
		for (const FVector& S : World.Spawns)
		{
			const float D = float(FVector::Dist2D(S, From));
			if (D > BestD)
			{
				BestD = D;
				Best = S;
			}
		}
		return Best;
	}

	void MoveOpponent(float Dt)
	{
		if (Config.Model == EModel::Still)
		{
			OppVel = FVector::ZeroVector;
			return;
		}
		static const FVector Loop[6] = {FVector(-1800, -1000, 0), FVector(-500, 1200, 0), FVector(1500, 900, 0),
			FVector(1800, -1200, 0), FVector(300, -1500, 0), FVector(-1500, 300, 0)};
		FVector Target = Loop[OppWaypoint % 6];
		float Speed = 450.f;
		if (Config.Model == EModel::Hider)
		{
			// Hide behind the wall farthest from the bot and crouch-walk (silent, 2 m/s).
			Target = BotPos.X > 0.f ? FVector(-1900.f, -1500.f, 0.f) : FVector(1900.f, 1500.f, 0.f);
			Speed = 200.f;
		}
		const FVerseBotPath Path = World.FindPath(OppPos, Target, false);
		const FVector Way = Path.bValid && Path.Waypoints.Num() > 0 ? Path.Waypoints[0] : Target;
		const FVector Dir = (Way - OppPos).GetSafeNormal2D();
		if (FVector::Dist2D(OppPos, Target) < 80.f)
		{
			++OppWaypoint;
			OppVel = FVector::ZeroVector;
			return;
		}
		const FVector Next = OppPos + Dir * Speed * Dt;
		if (World.IsWalkable(Next))
		{
			OppPos = Next;
			OppVel = Dir * Speed;
			if (!(OppSawBotAt >= 0.f))
			{
				OppYaw = float(Dir.Rotation().Yaw);
			}
		}
		else
		{
			++OppWaypoint;
		}
	}

	/** One 60 Hz tick: percepts, brain, apply input, opponent, combat. */
	void Tick()
	{
		const float Dt = 1.f / 60.f;
		TimeMs += 17;
		const float T = Now();
		FVersePerceptFrame F;
		F.ServerTimeMs = TimeMs;
		F.Hud = MoveTemp(PendingHud);
		PendingHud.Reset();

		// Respawns.
		if (BotDeadUntil >= 0.f && T >= BotDeadUntil)
		{
			BotDeadUntil = -1.f;
			BotHealth = 100.f;
			BotMag = 30;
			BotReserve = 90;
			BotPos = FarthestSpawnFrom(OppPos);
			LifeStartS = T;
			bContactThisLife = false;
		}
		if (OppDeadUntil >= 0.f && T >= OppDeadUntil)
		{
			OppDeadUntil = -1.f;
			OppHealth = 100.f;
			OppPos = Config.Model == EModel::Still ? Config.StillSpot : FarthestSpawnFrom(BotPos);
			LifeStartS = T;
			bContactThisLife = false;
			FVerseHudEvent E;
			E.Kind = EVerseHudEventKind::OpponentRespawned;
			E.ServerTimeMs = TimeMs;
			F.Hud.Add(E);
		}
		const bool bBotAlive = BotDeadUntil < 0.f;
		const bool bOppAlive = OppDeadUntil < 0.f;

		// Own HUD.
		FVerseSelfPercept& S = F.Self;
		S.Health = BotHealth;
		S.MaxHealth = 100.f;
		S.Magazine = BotMag;
		S.bChambered = BotMag > 0;
		S.Reserve = BotReserve;
		S.GadgetCharges[0] = 1;
		S.GadgetCharges[1] = 2;
		S.Location = BotPos;
		S.Velocity = BotVel;
		S.EyeLocation = BotEye();
		S.ViewRotation = BotView;
		S.Phase = bBotAlive ? EVerseCombatPhase::Alive : EVerseCombatPhase::Dead;

		// Sight (3.1).
		const bool bSees = bBotAlive && bOppAlive && BotSeesOpp();
		if (bSees)
		{
			FVerseSightPercept P;
			P.PerceptId = NextPerceptId++;
			P.PelvisLocation = OppPelvis();
			P.Velocity = OppVel;
			P.FacingYawDeg = OppYaw;
			P.VisibleMask = 0xff;
			F.Sightings.Add(P);
			++VisibleTicks;
			if (!bContactThisLife)
			{
				bContactThisLife = true;
				TimeToContactS.Add(T - LifeStartS);
			}
		}
		// Hearing (3.2): run footsteps within 10 m every 0.4 s; error sd base + per-metre.
		if (bBotAlive && bOppAlive && OppVel.Size2D() > 300.f && T >= NextFootstepS)
		{
			NextFootstepS = T + 0.4f;
			const float D = float(FVector::Dist(OppPos, BotPos)) / 100.f;
			if (D <= 10.f)
			{
				FVerseHeardPercept H;
				H.PerceptId = NextPerceptId++;
				H.Noise = VerseTags::Noise_Footstep_Run;
				H.ErrorSdM = (Tier->HearingErrorBaseM + Tier->HearingErrorPerM * D) * 1.3f;
				const FVector2D Disk = Rng.UnitDisk();
				H.Location = OppPos + FVector(Disk.X, Disk.Y, 0.f) * H.ErrorSdM * 100.f;
				H.ServerTimeMs = TimeMs;
				F.Heard.Add(H);
			}
		}

		// Opponent shoots on sight after a 0.3 s reaction.
		if (bBotAlive && bOppAlive && Config.Model == EModel::Patrol && OppSeesBot())
		{
			if (OppSawBotAt < 0.f)
			{
				OppSawBotAt = T;
			}
			OppYaw = float((BotPos - OppPos).Rotation().Yaw);
			if (T - OppSawBotAt > 0.3f && T >= OppNextShot)
			{
				OppNextShot = T + 0.1f;
				const float D = float(FVector::Dist(OppPos, BotPos)) / 100.f;
				FVerseHeardPercept H;
				H.PerceptId = NextPerceptId++;
				H.Noise = VerseTags::Noise_Shot;
				H.ErrorSdM = Tier->HearingErrorBaseM + Tier->HearingErrorPerM * D;
				const FVector2D Disk = Rng.UnitDisk();
				H.Location = OppPos + FVector(Disk.X, Disk.Y, 0.f) * H.ErrorSdM * 100.f;
				H.ServerTimeMs = TimeMs;
				F.Heard.Add(H);
				if (Rng.Chance(Config.OpponentHitChance))
				{
					BotHealth -= 25.f;
					F.bHasHurt = true;
					F.Hurt.PerceptId = NextPerceptId++;
					F.Hurt.Damage = 25.f;
					F.Hurt.IncomingDirection = (OppPos - BotPos).GetSafeNormal().RotateAngleAxis(float(Rng.Range(-8.0, 8.0)), FVector::UpVector);
					F.Hurt.ServerTimeMs = TimeMs;
					if (BotHealth <= 0.f)
					{
						++OppKills;
						BotDeadUntil = T + 3.f;
						FVerseHudEvent E;
						E.Kind = EVerseHudEventKind::Kill;
						E.KillerId = OppId;
						E.VictimId = BotId;
						E.ServerTimeMs = TimeMs;
						F.Hud.Add(E);
					}
				}
			}
		}
		else
		{
			OppSawBotAt = -1.f;
		}

		// Brain.
		if (bRecordFrames)
		{
			RecordedFrames.Add(F);
		}
		if (bRecordShots)
		{
			for (const FVerseSightPercept& P : F.Sightings)
			{
				Delivered.Add(P.PerceptId, FDelivered{EDelivered::Sight, TimeMs});
			}
			for (const FVerseHeardPercept& H : F.Heard)
			{
				Delivered.Add(H.PerceptId, FDelivered{EDelivered::Heard, TimeMs});
			}
		}
		const double T0 = bMeasure ? FPlatformTime::Seconds() : 0.0;
		const FVerseInputFrame In = Brain.Think(F, World);
		if (bMeasure)
		{
			ThinkUs.Add((FPlatformTime::Seconds() - T0) * 1.0e6);
		}
		if (In.IsHeld(EVerseInputButton::Fire))
		{
			++FireTicks;
		}
		if (bRecordOutputs)
		{
			FVerseBotTape::AppendOutput(Outputs, In);
		}

		// Apply the bot's input to its fake pawn (the same path a person uses).
		if (BotDeadUntil < 0.f)
		{
			BotView.Pitch = FMath::Clamp(float(BotView.Pitch) + In.LookDeltaDeg.X, -89.f, 89.f);
			BotView.Yaw = FRotator::NormalizeAxis(float(BotView.Yaw) + In.LookDeltaDeg.Y);
			const FRotator Yaw(0.f, BotView.Yaw, 0.f);
			const float Speed = In.IsHeld(EVerseInputButton::Sprint) ? 650.f : In.IsHeld(EVerseInputButton::Crouch) ? 200.f : 450.f;
			const FVector Wish = Yaw.RotateVector(FVector(In.Move.X, In.Move.Y, 0.f)) * Speed;
			// Slide along walls like a character movement component: full step, else one axis.
			const FVector Steps[3] = {Wish * Dt, FVector(Wish.X, 0.f, 0.f) * Dt, FVector(0.f, Wish.Y, 0.f) * Dt};
			BotVel = FVector::ZeroVector;
			for (const FVector& Step : Steps)
			{
				if (!Step.IsNearlyZero() && World.IsWalkable(BotPos + Step))
				{
					BotPos += Step;
					BotVel = Step / Dt;
					break;
				}
			}
			if (In.WasPressed(EVerseInputButton::Reload) && BotMag < 30 && BotReserve > 0)
			{
				const int32 Need = FMath::Min(30 - BotMag, BotReserve);
				BotMag += Need;
				BotReserve -= Need;
			}
			if (In.IsHeld(EVerseInputButton::Fire) && BotMag > 0 && T >= BotNextShot)
			{
				BotNextShot = T + 0.1f;
				--BotMag;
				if (bRecordShots)
				{
					Shots.Add(FShot{TimeMs, bSees});
				}
				if (bSees && OppDeadUntil < 0.f && Rng.Chance(Config.BotHitChance))
				{
					OppHealth -= 25.f;
					FVerseHudEvent E;
					E.Kind = OppHealth <= 0.f ? EVerseHudEventKind::KillMarker : EVerseHudEventKind::HitMarker;
					E.ServerTimeMs = TimeMs;
					PendingHud.Add(E);
					if (OppHealth <= 0.f)
					{
						++BotKills;
						OppDeadUntil = T + 3.f;
						FVerseHudEvent K;
						K.Kind = EVerseHudEventKind::Kill;
						K.KillerId = BotId;
						K.VictimId = OppId;
						K.ServerTimeMs = TimeMs;
						PendingHud.Add(K);
					}
				}
			}
		}
		if (OppDeadUntil < 0.f)
		{
			MoveOpponent(Dt);
		}
		++Ticks;
	}

	/** HUD events raised by the bot's own shots reach it on the next frame. */
	TArray<FVerseHudEvent> PendingHud;

	void Run(int32 NumTicks)
	{
		for (int32 i = 0; i < NumTicks; ++i)
		{
			Tick();
		}
	}

	int32 Kills() const { return BotKills + OppKills; }
};

#endif // WITH_DEV_AUTOMATION_TESTS
