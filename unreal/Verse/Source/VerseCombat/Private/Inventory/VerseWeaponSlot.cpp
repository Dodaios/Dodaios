#include "Inventory/VerseWeaponSlot.h"

#include "Combat/VerseWeaponDefinition.h"

FVerseWeaponSlotState* FVerseWeaponSlotArray::Find(EVerseLoadoutSlot Slot)
{
	return Items.FindByPredicate([Slot](const FVerseWeaponSlotState& S) { return S.Slot == Slot; });
}

const FVerseWeaponSlotState* FVerseWeaponSlotArray::Find(EVerseLoadoutSlot Slot) const
{
	return Items.FindByPredicate([Slot](const FVerseWeaponSlotState& S) { return S.Slot == Slot; });
}

void FVerseMagazine::InitFull(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W)
{
	const int32 Size = FMath::Clamp(W.MagazineSize, 0, 255);
	if (W.bClosedBolt && Size > 0)
	{
		S.bChambered = true;
		S.Magazine = uint8(Size - 1);
	}
	else
	{
		S.bChambered = false;
		S.Magazine = uint8(Size);
	}
	S.Reserve = uint16(FMath::Clamp(W.ReserveRounds, 0, 65535));
	S.Reload = EVerseReloadPhase::None;
	S.ReloadEndsAt = 0.f;
	S.ReloadStartedAt = 0.f;
	S.bReloadCommitted = false;
}

int32 FVerseMagazine::RoundsReady(const FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W)
{
	return int32(S.Magazine) + ((W.bClosedBolt && S.bChambered) ? 1 : 0);
}

bool FVerseMagazine::WouldBeTactical(const FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W)
{
	return W.bClosedBolt ? S.bChambered : S.Magazine > 0;
}

bool FVerseMagazine::CanFire(const FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W)
{
	return !IsReloading(S) && RoundsReady(S, W) > 0;
}

bool FVerseMagazine::ConsumeRound(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W)
{
	if (!CanFire(S, W))
	{
		return false;
	}
	if (W.bClosedBolt)
	{
		// The chambered round goes; the next one is fed from the magazine.
		S.bChambered = S.Magazine > 0;
		if (S.Magazine > 0)
		{
			--S.Magazine;
		}
	}
	else
	{
		--S.Magazine;
	}
	return true;
}

void FVerseMagazine::RefundRound(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W)
{
	if (W.bClosedBolt)
	{
		if (S.bChambered)
		{
			S.Magazine = uint8(FMath::Min(255, int32(S.Magazine) + 1));
		}
		else
		{
			S.bChambered = true;
		}
	}
	else
	{
		S.Magazine = uint8(FMath::Min(255, int32(S.Magazine) + 1));
	}
}

bool FVerseMagazine::CanReload(const FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W)
{
	return !IsReloading(S) && S.Reserve > 0 && int32(S.Magazine) < W.MagazineSize;
}

bool FVerseMagazine::StartReload(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W, float Now)
{
	if (!CanReload(S, W))
	{
		return false;
	}
	const bool bTactical = WouldBeTactical(S, W);
	S.Reload = bTactical ? EVerseReloadPhase::Tactical : EVerseReloadPhase::Empty;
	S.ReloadStartedAt = Now;
	S.ReloadEndsAt = Now + (bTactical ? W.ReloadTactical : W.ReloadEmpty);
	S.bReloadCommitted = false;
	return true;
}

float FVerseMagazine::CommitTime(const FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W)
{
	const float Fraction = FMath::Clamp(W.ReloadCommitFraction, 0.f, 1.f);
	return S.ReloadStartedAt + (S.ReloadEndsAt - S.ReloadStartedAt) * Fraction;
}

void FVerseMagazine::Commit(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W)
{
	const int32 Size = FMath::Clamp(W.MagazineSize, 0, 255);
	// The rounds left in the old magazine go back to the reserve; a full magazine is taken from it.
	int32 Pool = int32(S.Reserve) + int32(S.Magazine);
	const int32 Take = FMath::Min(Size, Pool);
	Pool -= Take;
	if (W.bClosedBolt && !S.bChambered)
	{
		// Empty reload: chambering takes one round from the new magazine.
		S.bChambered = Take > 0;
		S.Magazine = uint8(FMath::Max(0, Take - 1));
	}
	else
	{
		// Tactical: the chambered round stays, so the weapon holds magazine + 1.
		S.Magazine = uint8(Take);
	}
	S.Reserve = uint16(FMath::Clamp(Pool, 0, 65535));
	S.bReloadCommitted = true;
}

EVerseMagazineChange FVerseMagazine::Tick(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W, float Now)
{
	if (!IsReloading(S))
	{
		return EVerseMagazineChange::None;
	}
	EVerseMagazineChange Change = EVerseMagazineChange::None;
	if (!S.bReloadCommitted && Now >= CommitTime(S, W))
	{
		Commit(S, W);
		Change = EVerseMagazineChange::ReloadCommitted;
	}
	if (Now >= S.ReloadEndsAt)
	{
		if (!S.bReloadCommitted)
		{
			Commit(S, W);
		}
		S.Reload = EVerseReloadPhase::None;
		S.bReloadCommitted = false;
		Change = EVerseMagazineChange::ReloadFinished;
	}
	return Change;
}

EVerseMagazineChange FVerseMagazine::Cancel(FVerseWeaponSlotState& S)
{
	if (!IsReloading(S))
	{
		return EVerseMagazineChange::None;
	}
	S.Reload = EVerseReloadPhase::None;
	S.bReloadCommitted = false;
	return EVerseMagazineChange::ReloadCancelled;
}
