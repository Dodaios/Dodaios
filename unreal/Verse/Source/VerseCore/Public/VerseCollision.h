#pragma once

#include "CoreMinimal.h"
#include "Engine/EngineTypes.h"

// Verse collision channels and profiles (G0.8).
// Channel names are frozen in docs/verse/unreal/contracts/destruction.md, profile
// names in contracts/art-pipeline.md section 5. The channel slots match
// Config/DefaultEngine.ini [/Script/Engine.CollisionProfile]; Verse.Core.Collision
// fails when the two drift apart. Code never spells ECC_GameTraceChannelN itself.
namespace VerseCollision
{
	// Trace: bolts against piece proxies, world, Bulwark and drones.
	inline constexpr ECollisionChannel Bolt = ECC_GameTraceChannel1;
	// Trace: sight lines (TestSight applies the glass, grating and hole rules).
	inline constexpr ECollisionChannel Sight = ECC_GameTraceChannel2;
	// Trace: per-bone hit bodies only; pieces, world and debris ignore it.
	inline constexpr ECollisionChannel HitBody = ECC_GameTraceChannel3;
	// Object: debris chunks; ignores pawns, bolts, sight and hit bodies.
	inline constexpr ECollisionChannel Debris = ECC_GameTraceChannel4;

	inline const FName BoltName(TEXT("VerseBolt"));
	inline const FName SightName(TEXT("VerseSight"));
	inline const FName HitBodyName(TEXT("VerseHitBody"));
	inline const FName DebrisName(TEXT("VerseDebris"));

	namespace Profile
	{
		inline const FName Architecture(TEXT("Verse_Architecture"));
		inline const FName Destructible(TEXT("Verse_Destructible"));
		inline const FName Glass(TEXT("Verse_Glass"));
		inline const FName Prop(TEXT("Verse_Prop"));
		inline const FName PropSmall(TEXT("Verse_PropSmall"));
		inline const FName Debris(TEXT("Verse_Debris"));
		inline const FName ProxyOnly(TEXT("Verse_ProxyOnly"));
		inline const FName NoCollision(TEXT("Verse_NoCollision"));
	}
}
