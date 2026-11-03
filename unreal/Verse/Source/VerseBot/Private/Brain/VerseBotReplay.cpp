#include "Brain/VerseBotReplay.h"

#include <type_traits>

namespace
{
	enum class ECall : uint8
	{
		TestSight = 1,
		TraceBolt,
		FindPath,
		GetCoverPoints,
		GetPieces,
		GetSpawnPoints,
		GetZoneId,
		GetOwnWeapon,
		CanActivateFinisher
	};

	template <typename T>
	void Put(TArray<uint8>& Out, const T& Value)
	{
		static_assert(std::is_trivially_copyable_v<T>, "plain values only");
		const int32 At = Out.AddUninitialized(sizeof(T));
		FMemory::Memcpy(Out.GetData() + At, &Value, sizeof(T));
	}

	void PutVector(TArray<uint8>& Out, const FVector& V)
	{
		Put(Out, V.X);
		Put(Out, V.Y);
		Put(Out, V.Z);
	}

	uint32 HashVector(uint32 H, const FVector& V)
	{
		H = HashCombineFast(H, GetTypeHash(V.X));
		H = HashCombineFast(H, GetTypeHash(V.Y));
		return HashCombineFast(H, GetTypeHash(V.Z));
	}

	uint32 HashWeapon(uint32 H, const FVerseBotWeaponInfo& W)
	{
		H = HashCombineFast(H, GetTypeHash(W.Damage));
		H = HashCombineFast(H, GetTypeHash(W.PenetrationPower));
		H = HashCombineFast(H, GetTypeHash(W.MagazineSize));
		return HashCombineFast(H, GetTypeHash(W.HoleRadiusMm));
	}

	void Begin(TArray<uint8>& Tape, ECall Call, uint32 ArgHash)
	{
		Put(Tape, uint8(Call));
		Put(Tape, ArgHash);
	}

	void PutCover(TArray<uint8>& Out, const FVerseBotCoverPoint& C)
	{
		Put(Out, C.Id);
		PutVector(Out, C.Location);
		Put(Out, uint8(C.bHigh));
		Put(Out, uint8(C.bBulwarkSpot));
		Put(Out, C.EdgeId);
		PutVector(Out, C.Facing);
		Put(Out, C.MaterialProtection);
		Put(Out, int32(C.DependsOnPieces.Num()));
		for (uint16 P : C.DependsOnPieces)
		{
			Put(Out, P);
		}
	}

	void PutPiece(TArray<uint8>& Out, const FVerseBotPieceInfo& P)
	{
		Put(Out, P.PieceIndex);
		PutVector(Out, P.Center);
		PutVector(Out, P.Normal);
		Put(Out, uint8(P.bBreachable));
		Put(Out, uint8(P.bPenetrable));
	}
}

void FVerseBotTape::AppendOutput(TArray<uint8>& Out, const FVerseInputFrame& Frame)
{
	Put(Out, Frame.Move.X);
	Put(Out, Frame.Move.Y);
	Put(Out, Frame.LookDeltaDeg.X);
	Put(Out, Frame.LookDeltaDeg.Y);
	Put(Out, Frame.Buttons);
	Put(Out, Frame.Pressed);
	Put(Out, Frame.ServerTimeMs);
}

// Recording

bool FVerseBotRecordingQueries::TestSight(const FVector& Eye, const FVector& Target)
{
	const bool R = Inner.TestSight(Eye, Target);
	Begin(Tape, ECall::TestSight, HashVector(HashVector(0, Eye), Target));
	Put(Tape, uint8(R));
	return R;
}

FVerseBotBoltTrace FVerseBotRecordingQueries::TraceBolt(const FVector& Origin, const FVector& Target, const FVerseBotWeaponInfo& Weapon)
{
	const FVerseBotBoltTrace R = Inner.TraceBolt(Origin, Target, Weapon);
	Begin(Tape, ECall::TraceBolt, HashWeapon(HashVector(HashVector(0, Origin), Target), Weapon));
	Put(Tape, R.DamageFrac);
	Put(Tape, R.Pieces);
	return R;
}

FVerseBotPath FVerseBotRecordingQueries::FindPath(const FVector& From, const FVector& To, bool bCrouch)
{
	const FVerseBotPath R = Inner.FindPath(From, To, bCrouch);
	Begin(Tape, ECall::FindPath, HashCombineFast(HashVector(HashVector(0, From), To), uint32(bCrouch)));
	Put(Tape, uint8(R.bValid));
	Put(Tape, R.LengthCm);
	Put(Tape, int32(R.Waypoints.Num()));
	for (const FVector& W : R.Waypoints)
	{
		PutVector(Tape, W);
	}
	return R;
}

void FVerseBotRecordingQueries::GetCoverPoints(const FVector& Center, float RadiusCm, TArray<FVerseBotCoverPoint>& Out)
{
	Inner.GetCoverPoints(Center, RadiusCm, Out);
	Begin(Tape, ECall::GetCoverPoints, HashCombineFast(HashVector(0, Center), GetTypeHash(RadiusCm)));
	Put(Tape, int32(Out.Num()));
	for (const FVerseBotCoverPoint& C : Out)
	{
		PutCover(Tape, C);
	}
}

void FVerseBotRecordingQueries::GetPieces(const FVector& Center, float RadiusCm, TArray<FVerseBotPieceInfo>& Out)
{
	Inner.GetPieces(Center, RadiusCm, Out);
	Begin(Tape, ECall::GetPieces, HashCombineFast(HashVector(0, Center), GetTypeHash(RadiusCm)));
	Put(Tape, int32(Out.Num()));
	for (const FVerseBotPieceInfo& P : Out)
	{
		PutPiece(Tape, P);
	}
}

void FVerseBotRecordingQueries::GetSpawnPoints(TArray<FVector>& Out)
{
	Inner.GetSpawnPoints(Out);
	Begin(Tape, ECall::GetSpawnPoints, 0);
	Put(Tape, int32(Out.Num()));
	for (const FVector& S : Out)
	{
		PutVector(Tape, S);
	}
}

int32 FVerseBotRecordingQueries::GetZoneId(const FVector& Location)
{
	const int32 R = Inner.GetZoneId(Location);
	Begin(Tape, ECall::GetZoneId, HashVector(0, Location));
	Put(Tape, R);
	return R;
}

FVerseBotWeaponInfo FVerseBotRecordingQueries::GetOwnWeapon()
{
	const FVerseBotWeaponInfo R = Inner.GetOwnWeapon();
	Begin(Tape, ECall::GetOwnWeapon, 0);
	Put(Tape, R.Damage);
	Put(Tape, R.PenetrationPower);
	Put(Tape, R.MagazineSize);
	Put(Tape, R.HoleRadiusMm);
	return R;
}

bool FVerseBotRecordingQueries::CanActivateFinisher()
{
	const bool R = Inner.CanActivateFinisher();
	Begin(Tape, ECall::CanActivateFinisher, 0);
	Put(Tape, uint8(R));
	return R;
}

// Replay

template <typename T>
T FVerseBotReplayQueries::Read()
{
	T Value{};
	if (bDiverged || Offset + int32(sizeof(T)) > Tape.Num())
	{
		bDiverged = true;
		return Value;
	}
	FMemory::Memcpy(&Value, Tape.GetData() + Offset, sizeof(T));
	Offset += sizeof(T);
	return Value;
}

bool FVerseBotReplayQueries::Begin(uint8 CallId, uint32 ArgHash)
{
	if (bDiverged)
	{
		return false;
	}
	const uint8 Id = Read<uint8>();
	const uint32 Hash = Read<uint32>();
	if (bDiverged || Id != CallId || Hash != ArgHash)
	{
		bDiverged = true;
		return false;
	}
	++Calls;
	return true;
}

bool FVerseBotReplayQueries::TestSight(const FVector& Eye, const FVector& Target)
{
	if (!Begin(uint8(ECall::TestSight), HashVector(HashVector(0, Eye), Target)))
	{
		return false;
	}
	return Read<uint8>() != 0;
}

FVerseBotBoltTrace FVerseBotReplayQueries::TraceBolt(const FVector& Origin, const FVector& Target, const FVerseBotWeaponInfo& Weapon)
{
	FVerseBotBoltTrace R;
	if (!Begin(uint8(ECall::TraceBolt), HashWeapon(HashVector(HashVector(0, Origin), Target), Weapon)))
	{
		return R;
	}
	R.DamageFrac = Read<float>();
	R.Pieces = Read<int32>();
	return R;
}

FVerseBotPath FVerseBotReplayQueries::FindPath(const FVector& From, const FVector& To, bool bCrouch)
{
	FVerseBotPath R;
	if (!Begin(uint8(ECall::FindPath), HashCombineFast(HashVector(HashVector(0, From), To), uint32(bCrouch))))
	{
		return R;
	}
	R.bValid = Read<uint8>() != 0;
	R.LengthCm = Read<float>();
	const int32 N = Read<int32>();
	for (int32 i = 0; i < N && !bDiverged; ++i)
	{
		const double X = Read<double>(), Y = Read<double>(), Z = Read<double>();
		R.Waypoints.Add(FVector(X, Y, Z));
	}
	return R;
}

void FVerseBotReplayQueries::GetCoverPoints(const FVector& Center, float RadiusCm, TArray<FVerseBotCoverPoint>& Out)
{
	Out.Reset();
	if (!Begin(uint8(ECall::GetCoverPoints), HashCombineFast(HashVector(0, Center), GetTypeHash(RadiusCm))))
	{
		return;
	}
	const int32 N = Read<int32>();
	for (int32 i = 0; i < N && !bDiverged; ++i)
	{
		FVerseBotCoverPoint C;
		C.Id = Read<int32>();
		{
			const double X = Read<double>(), Y = Read<double>(), Z = Read<double>();
			C.Location = FVector(X, Y, Z);
		}
		C.bHigh = Read<uint8>() != 0;
		C.bBulwarkSpot = Read<uint8>() != 0;
		C.EdgeId = Read<int32>();
		{
			const double X = Read<double>(), Y = Read<double>(), Z = Read<double>();
			C.Facing = FVector(X, Y, Z);
		}
		C.MaterialProtection = Read<float>();
		const int32 D = Read<int32>();
		for (int32 j = 0; j < D && !bDiverged; ++j)
		{
			C.DependsOnPieces.Add(Read<uint16>());
		}
		Out.Add(C);
	}
}

void FVerseBotReplayQueries::GetPieces(const FVector& Center, float RadiusCm, TArray<FVerseBotPieceInfo>& Out)
{
	Out.Reset();
	if (!Begin(uint8(ECall::GetPieces), HashCombineFast(HashVector(0, Center), GetTypeHash(RadiusCm))))
	{
		return;
	}
	const int32 N = Read<int32>();
	for (int32 i = 0; i < N && !bDiverged; ++i)
	{
		FVerseBotPieceInfo P;
		P.PieceIndex = Read<uint16>();
		{
			const double X = Read<double>(), Y = Read<double>(), Z = Read<double>();
			P.Center = FVector(X, Y, Z);
		}
		{
			const double X = Read<double>(), Y = Read<double>(), Z = Read<double>();
			P.Normal = FVector(X, Y, Z);
		}
		P.bBreachable = Read<uint8>() != 0;
		P.bPenetrable = Read<uint8>() != 0;
		Out.Add(P);
	}
}

void FVerseBotReplayQueries::GetSpawnPoints(TArray<FVector>& Out)
{
	Out.Reset();
	if (!Begin(uint8(ECall::GetSpawnPoints), 0))
	{
		return;
	}
	const int32 N = Read<int32>();
	for (int32 i = 0; i < N && !bDiverged; ++i)
	{
		const double X = Read<double>(), Y = Read<double>(), Z = Read<double>();
		Out.Add(FVector(X, Y, Z));
	}
}

int32 FVerseBotReplayQueries::GetZoneId(const FVector& Location)
{
	if (!Begin(uint8(ECall::GetZoneId), HashVector(0, Location)))
	{
		return INDEX_NONE;
	}
	return Read<int32>();
}

FVerseBotWeaponInfo FVerseBotReplayQueries::GetOwnWeapon()
{
	FVerseBotWeaponInfo R;
	if (!Begin(uint8(ECall::GetOwnWeapon), 0))
	{
		return R;
	}
	R.Damage = Read<float>();
	R.PenetrationPower = Read<float>();
	R.MagazineSize = Read<int32>();
	R.HoleRadiusMm = Read<uint8>();
	return R;
}

bool FVerseBotReplayQueries::CanActivateFinisher()
{
	if (!Begin(uint8(ECall::CanActivateFinisher), 0))
	{
		return false;
	}
	return Read<uint8>() != 0;
}
