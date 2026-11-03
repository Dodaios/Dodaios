#pragma once

#include "AbilitySystemComponent.h"
#include "AttributeSet.h"
#include "CoreMinimal.h"
#include "GameplayEffect.h"

#include "VerseHealthSet.generated.h"

/**
 * Health and armor (combat-state.md 2.1, 11.2). Health and armor replicate to the owner only:
 * the opponent's health is never shown. IncomingDamage is a server-only meta attribute that the
 * damage effect writes; PostGameplayEffectExecute spends it on armor first, then health.
 */
UCLASS()
class VERSECOMBAT_API UVerseHealthSet : public UAttributeSet
{
	GENERATED_BODY()

public:
	UVerseHealthSet();

	ATTRIBUTE_ACCESSORS_BASIC(UVerseHealthSet, Health)
	ATTRIBUTE_ACCESSORS_BASIC(UVerseHealthSet, MaxHealth)
	ATTRIBUTE_ACCESSORS_BASIC(UVerseHealthSet, Armor)
	ATTRIBUTE_ACCESSORS_BASIC(UVerseHealthSet, MaxArmor)
	ATTRIBUTE_ACCESSORS_BASIC(UVerseHealthSet, IncomingDamage)

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;
	virtual void PreAttributeChange(const FGameplayAttribute& Attribute, float& NewValue) override;
	virtual void PostGameplayEffectExecute(const FGameplayEffectModCallbackData& Data) override;

	/** Start: 100 (combat-state.md 2.1). */
	static constexpr float StartHealth = 100.f;

	/** Owner only. */
	UPROPERTY(ReplicatedUsing = OnRep_Health, BlueprintReadOnly, Category = "Verse|Health")
	FGameplayAttributeData Health;

	UPROPERTY(ReplicatedUsing = OnRep_MaxHealth, BlueprintReadOnly, Category = "Verse|Health")
	FGameplayAttributeData MaxHealth;

	/** 0 in deathmatch (MaxArmor 0 makes it inert). */
	UPROPERTY(ReplicatedUsing = OnRep_Armor, BlueprintReadOnly, Category = "Verse|Health")
	FGameplayAttributeData Armor;

	UPROPERTY(ReplicatedUsing = OnRep_MaxArmor, BlueprintReadOnly, Category = "Verse|Health")
	FGameplayAttributeData MaxArmor;

	/** Meta, server only. */
	UPROPERTY(BlueprintReadOnly, Category = "Verse|Health")
	FGameplayAttributeData IncomingDamage;

	/** Damage spent on armor and health by the last executed damage effect (server). */
	float LastToArmor = 0.f;
	float LastToHealth = 0.f;

protected:
	UFUNCTION()
	void OnRep_Health(const FGameplayAttributeData& Old);
	UFUNCTION()
	void OnRep_MaxHealth(const FGameplayAttributeData& Old);
	UFUNCTION()
	void OnRep_Armor(const FGameplayAttributeData& Old);
	UFUNCTION()
	void OnRep_MaxArmor(const FGameplayAttributeData& Old);
};

/**
 * The damage effect (combat-state.md 5): instant, adds the set-by-caller magnitude
 * `Verse.Damage` to IncomingDamage. The damage service builds one spec per hit.
 */
UCLASS()
class VERSECOMBAT_API UVerseDamageEffect : public UGameplayEffect
{
	GENERATED_BODY()

public:
	UVerseDamageEffect();

	/** Set-by-caller name of the damage magnitude. */
	static const FName DamageName;
};
