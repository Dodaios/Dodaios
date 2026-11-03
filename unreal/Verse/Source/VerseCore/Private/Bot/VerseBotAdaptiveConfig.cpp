#include "Bot/VerseBotAdaptiveConfig.h"

#include "Bot/VerseBotTier.h"
#include "UObject/UnrealType.h"

float UVerseBotAdaptiveConfig::NextSkill(float CurrentSkill, float PersonShare, int32 KillsSoFar) const
{
	const float S = FMath::Clamp(CurrentSkill, 0.f, 1.f);
	if (KillsSoFar < WarmupKills || FMath::Abs(PersonShare - TargetPersonShare) <= Deadband)
	{
		return S;
	}
	const float Step = FMath::Clamp(Gain * (PersonShare - TargetPersonShare), -MaxStepPerKill, MaxStepPerKill);
	return FMath::Clamp(S + Step, 0.f, 1.f);
}

void UVerseBotAdaptiveConfig::InterpolateTier(const UVerseBotTier& Normal, const UVerseBotTier& Hard, const UVerseBotTier& Elite,
	float S, UVerseBotTier& Out)
{
	const float Clamped = FMath::Clamp(S, 0.f, 1.f);
	const bool bLowerHalf = Clamped <= 0.5f;
	const UVerseBotTier& From = bLowerHalf ? Normal : Hard;
	const UVerseBotTier& To = bLowerHalf ? Hard : Elite;
	const float T = bLowerHalf ? Clamped * 2.f : (Clamped - 0.5f) * 2.f;

	for (TFieldIterator<FProperty> It(UVerseBotTier::StaticClass()); It; ++It)
	{
		const FProperty* Prop = *It;
		if (Prop->GetOwnerClass() != UVerseBotTier::StaticClass())
		{
			continue;
		}
		if (const FFloatProperty* FloatProp = CastField<FFloatProperty>(Prop))
		{
			const float A = FloatProp->GetPropertyValue_InContainer(&From);
			const float B = FloatProp->GetPropertyValue_InContainer(&To);
			FloatProp->SetPropertyValue_InContainer(&Out, FMath::Lerp(A, B, T));
		}
		else if (const FIntProperty* IntProp = CastField<FIntProperty>(Prop))
		{
			const int32 A = IntProp->GetPropertyValue_InContainer(&From);
			const int32 B = IntProp->GetPropertyValue_InContainer(&To);
			IntProp->SetPropertyValue_InContainer(&Out, FMath::RoundToInt(FMath::Lerp(float(A), float(B), T)));
		}
		else if (const FStructProperty* StructProp = CastField<FStructProperty>(Prop))
		{
			if (StructProp->Struct && StructProp->Struct->GetFName() == FName(TEXT("Vector2f")))
			{
				const FVector2f& A = *StructProp->ContainerPtrToValuePtr<FVector2f>(&From);
				const FVector2f& B = *StructProp->ContainerPtrToValuePtr<FVector2f>(&To);
				*StructProp->ContainerPtrToValuePtr<FVector2f>(&Out) = FMath::Lerp(A, B, T);
			}
		}
	}
	Out.TierId = TEXT("adaptive");
}
