#include "Melee/VerseMeleeImport.h"

#include "Combat/VerseMeleeDefinition.h"
#include "Finisher/VerseFinisherTimeline.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Melee/VerseMeleeJson.h"
#include "VerseCoords.h"

namespace
{
	using EType = FVerseMeleeJson::EType;

	struct FReader
	{
		FString& Error;

		const FVerseMeleeJson* Section(const FVerseMeleeJson& Root, const TCHAR* Name)
		{
			const FVerseMeleeJson* Out = Root.Field(Name, EType::Object);
			if (!Out)
			{
				Error = FString::Printf(TEXT("missing object '%s'"), Name);
			}
			return Out;
		}

		/** A number in (Min, Max]; Min itself is allowed when bMinInclusive. */
		bool Number(const FVerseMeleeJson& Obj, const TCHAR* Section, const TCHAR* Name, double Min,
			double Max, bool bMinInclusive, double& Out)
		{
			if (!Error.IsEmpty())
			{
				return false;
			}
			const FVerseMeleeJson* Field = Obj.Field(Name, EType::Number);
			if (!Field)
			{
				Error = FString::Printf(TEXT("missing number '%s.%s'"), Section, Name);
				return false;
			}
			Out = Field->Number;
			const bool bAboveMin = bMinInclusive ? Out >= Min : Out > Min;
			if (!bAboveMin || Out > Max || !FMath::IsFinite(Out))
			{
				Error = FString::Printf(TEXT("'%s.%s' = %g is outside %s%g, %g]"), Section, Name, Out,
					bMinInclusive ? TEXT("[") : TEXT("("), Min, Max);
				return false;
			}
			return true;
		}
	};
}

FString FVerseMeleeImport::DefaultPath()
{
	return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data/melee/hookbill.json"));
}

bool FVerseMeleeImport::FromJsonString(const FString& Text, UVerseMeleeDefinition& OutDef,
	FVerseMeleePresentationTuning& OutTuning, FString& OutError)
{
	OutError.Reset();
	FString ParseError;
	const TSharedPtr<FVerseMeleeJson> Root = FVerseMeleeJson::Parse(Text, ParseError);
	if (!Root.IsValid() || Root->Type != EType::Object)
	{
		OutError = FString::Printf(TEXT("not a JSON object (%s)"), *ParseError);
		return false;
	}
	const FVerseMeleeJson* SchemaValue = Root->Field(TEXT("schema"), EType::String);
	if (!SchemaValue || SchemaValue->String != Schema)
	{
		OutError = FString::Printf(TEXT("schema must be '%s'"), Schema);
		return false;
	}
	const FVerseMeleeJson* IdValue = Root->Field(TEXT("id"), EType::String);
	if (!IdValue || IdValue->String.IsEmpty())
	{
		OutError = TEXT("missing string 'id'");
		return false;
	}
	const FString Id = IdValue->String;

	FReader R{OutError};
	const FVerseMeleeJson* Strike = R.Section(*Root, TEXT("strike"));
	if (!Strike)
	{
		return false;
	}
	const FVerseMeleeJson* Finisher = R.Section(*Root, TEXT("finisher"));
	if (!Finisher)
	{
		return false;
	}
	const FVerseMeleeJson* Presentation = R.Section(*Root, TEXT("presentation"));
	if (!Presentation)
	{
		return false;
	}

	double Damage = 0, HitDelay = 0, Cooldown = 0, Range = 0, Cone = 0;
	double FRange = 0, FHeight = 0, FFront = 0, FFacing = 0, FDuration = 0, FKill = 0;
	double Equip = 0, Recover = 0, Offset = 0, Snap = 0, CamDist = 0, CamHeight = 0, CamBlend = 0;
	R.Number(*Strike, TEXT("strike"), TEXT("damage"), 0.0, 1000.0, false, Damage);
	R.Number(*Strike, TEXT("strike"), TEXT("hit_delay_s"), 0.0, 1.0, true, HitDelay);
	R.Number(*Strike, TEXT("strike"), TEXT("cooldown_s"), 0.0, 5.0, false, Cooldown);
	R.Number(*Strike, TEXT("strike"), TEXT("range_m"), 0.0, 5.0, false, Range);
	R.Number(*Strike, TEXT("strike"), TEXT("cone_half_angle_deg"), 0.0, 90.0, false, Cone);
	R.Number(*Finisher, TEXT("finisher"), TEXT("range_m"), 0.0, 5.0, false, FRange);
	R.Number(*Finisher, TEXT("finisher"), TEXT("max_height_delta_m"), 0.0, 2.0, true, FHeight);
	R.Number(*Finisher, TEXT("finisher"), TEXT("front_half_angle_deg"), 0.0, 180.0, true, FFront);
	R.Number(*Finisher, TEXT("finisher"), TEXT("attacker_facing_max_deg"), 0.0, 180.0, true, FFacing);
	R.Number(*Finisher, TEXT("finisher"), TEXT("duration_s"), 0.0, 10.0, false, FDuration);
	R.Number(*Finisher, TEXT("finisher"), TEXT("kill_time_s"), 0.0, 10.0, false, FKill);
	R.Number(*Presentation, TEXT("presentation"), TEXT("equip_s"), 0.0, 2.0, true, Equip);
	R.Number(*Presentation, TEXT("presentation"), TEXT("swing_recover_s"), 0.0, 2.0, true, Recover);
	R.Number(*Presentation, TEXT("presentation"), TEXT("paired_offset_m"), 0.0, 3.0, false, Offset);
	R.Number(*Presentation, TEXT("presentation"), TEXT("victim_snap_s"), 0.0, 1.0, true, Snap);
	R.Number(*Presentation, TEXT("presentation"), TEXT("camera_distance_m"), 0.0, 10.0, false, CamDist);
	R.Number(*Presentation, TEXT("presentation"), TEXT("camera_height_m"), -5.0, 10.0, true, CamHeight);
	R.Number(*Presentation, TEXT("presentation"), TEXT("camera_blend_s"), 0.0, 2.0, true, CamBlend);
	if (!OutError.IsEmpty())
	{
		return false;
	}
	// The phase offsets are frozen (combat-state.md 7.4); the two fields must agree with them.
	if (!FMath::IsNearlyEqual(FDuration, VerseFinisher::EndAt, 1e-6) || !FMath::IsNearlyEqual(FKill, VerseFinisher::RecoverAt, 1e-6))
	{
		OutError = FString::Printf(TEXT("finisher duration_s/kill_time_s must be %g/%g (frozen phase offsets)"),
			VerseFinisher::EndAt, VerseFinisher::RecoverAt);
		return false;
	}
	if (Offset > FRange)
	{
		OutError = TEXT("presentation.paired_offset_m must not exceed finisher.range_m");
		return false;
	}

	OutDef.StrikeDamage = float(Damage);
	OutDef.StrikeHitDelay = float(HitDelay);
	OutDef.StrikeCooldown = float(Cooldown);
	OutDef.StrikeRange = float(Range);
	OutDef.StrikeConeHalfAngle = float(Cone);
	OutDef.FinisherRange = float(FRange);
	OutDef.FinisherMaxHeightDelta = float(FHeight);
	OutDef.FrontHalfAngle = float(FFront);
	OutDef.AttackerFacingMax = float(FFacing);
	OutDef.FinisherDuration = float(FDuration);
	OutDef.FinisherKillTime = float(FKill);

	using namespace Verse::Coords;
	OutTuning.WeaponId = FName(*Id);
	OutTuning.EquipS = FMath::Min(Equip, HitDelay);
	OutTuning.SwingRecoverS = Recover;
	OutTuning.PairedOffsetCm = MetresToCm(Offset);
	OutTuning.VictimSnapS = Snap;
	OutTuning.CameraDistanceCm = MetresToCm(CamDist);
	OutTuning.CameraHeightCm = MetresToCm(CamHeight);
	OutTuning.CameraBlendS = CamBlend;
	return true;
}

bool FVerseMeleeImport::FromFile(const FString& Path, UVerseMeleeDefinition& OutDef,
	FVerseMeleePresentationTuning& OutTuning, FString& OutError)
{
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		OutError = FString::Printf(TEXT("cannot read %s"), *Path);
		return false;
	}
	return FromJsonString(Text, OutDef, OutTuning, OutError);
}
