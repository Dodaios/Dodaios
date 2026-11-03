#include "Damage/VerseHealthSet.h"

#include "Damage/VerseDamageMath.h"
#include "GameplayEffectExtension.h"
#include "Net/UnrealNetwork.h"

const FName UVerseDamageEffect::DamageName(TEXT("Verse.Damage"));

UVerseHealthSet::UVerseHealthSet()
{
	InitHealth(StartHealth);
	InitMaxHealth(StartHealth);
	InitArmor(0.f);
	InitMaxArmor(0.f);
	InitIncomingDamage(0.f);
}

void UVerseHealthSet::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	DOREPLIFETIME_CONDITION_NOTIFY(UVerseHealthSet, Health, COND_OwnerOnly, REPNOTIFY_Always);
	DOREPLIFETIME_CONDITION_NOTIFY(UVerseHealthSet, MaxHealth, COND_OwnerOnly, REPNOTIFY_Always);
	DOREPLIFETIME_CONDITION_NOTIFY(UVerseHealthSet, Armor, COND_OwnerOnly, REPNOTIFY_Always);
	DOREPLIFETIME_CONDITION_NOTIFY(UVerseHealthSet, MaxArmor, COND_OwnerOnly, REPNOTIFY_Always);
}

void UVerseHealthSet::PreAttributeChange(const FGameplayAttribute& Attribute, float& NewValue)
{
	Super::PreAttributeChange(Attribute, NewValue);
	if (Attribute == GetHealthAttribute())
	{
		NewValue = FMath::Clamp(NewValue, 0.f, GetMaxHealth());
	}
	else if (Attribute == GetArmorAttribute())
	{
		NewValue = FMath::Clamp(NewValue, 0.f, GetMaxArmor());
	}
}

void UVerseHealthSet::PostGameplayEffectExecute(const FGameplayEffectModCallbackData& Data)
{
	Super::PostGameplayEffectExecute(Data);
	if (Data.EvaluatedData.Attribute != GetIncomingDamageAttribute())
	{
		return;
	}
	const float Damage = GetIncomingDamage();
	SetIncomingDamage(0.f);
	const FVerseDamageSplit Split = FVerseDamageMath::Split(Damage, GetHealth(), GetArmor(), GetMaxArmor());
	LastToArmor = Split.ToArmor;
	LastToHealth = Split.ToHealth;
	SetArmor(Split.ArmorAfter);
	SetHealth(Split.HealthAfter);
}

void UVerseHealthSet::OnRep_Health(const FGameplayAttributeData& Old)
{
	GAMEPLAYATTRIBUTE_REPNOTIFY(UVerseHealthSet, Health, Old);
}

void UVerseHealthSet::OnRep_MaxHealth(const FGameplayAttributeData& Old)
{
	GAMEPLAYATTRIBUTE_REPNOTIFY(UVerseHealthSet, MaxHealth, Old);
}

void UVerseHealthSet::OnRep_Armor(const FGameplayAttributeData& Old)
{
	GAMEPLAYATTRIBUTE_REPNOTIFY(UVerseHealthSet, Armor, Old);
}

void UVerseHealthSet::OnRep_MaxArmor(const FGameplayAttributeData& Old)
{
	GAMEPLAYATTRIBUTE_REPNOTIFY(UVerseHealthSet, MaxArmor, Old);
}

UVerseDamageEffect::UVerseDamageEffect()
{
	DurationPolicy = EGameplayEffectDurationType::Instant;

	FSetByCallerFloat SetByCaller;
	SetByCaller.DataName = DamageName;

	FGameplayModifierInfo Modifier;
	Modifier.Attribute = UVerseHealthSet::GetIncomingDamageAttribute();
	Modifier.ModifierOp = EGameplayModOp::AddBase;
	Modifier.ModifierMagnitude = FGameplayEffectModifierMagnitude(SetByCaller);
	Modifiers.Add(Modifier);
}
