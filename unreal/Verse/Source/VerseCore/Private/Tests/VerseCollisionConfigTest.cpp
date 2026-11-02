#include "Misc/AutomationTest.h"
#include "Engine/CollisionProfile.h"
#include "VerseCollision.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Core.Collision: the project collision config matches VerseCollision.h and
// the response tables of contracts/art-pipeline.md 5 and contracts/destruction.md.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCollisionConfigTest, "Verse.Core.Collision",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace
{
	ECollisionResponse ResponseOf(const FCollisionResponseTemplate& Template, ECollisionChannel Channel)
	{
		return Template.ResponseToChannels.GetResponse(Channel);
	}
}

bool FVerseCollisionConfigTest::RunTest(const FString& Parameters)
{
	UCollisionProfile* Profiles = UCollisionProfile::Get();
	if (!TestNotNull(TEXT("collision profile settings"), Profiles))
	{
		return false;
	}

	const TPair<ECollisionChannel, FName> Channels[] = {
		{ VerseCollision::Bolt, VerseCollision::BoltName },
		{ VerseCollision::Sight, VerseCollision::SightName },
		{ VerseCollision::HitBody, VerseCollision::HitBodyName },
		{ VerseCollision::Debris, VerseCollision::DebrisName },
	};
	for (const TPair<ECollisionChannel, FName>& Channel : Channels)
	{
		TestEqual(FString::Printf(TEXT("channel slot of %s"), *Channel.Value.ToString()),
			Profiles->ReturnChannelNameFromContainerIndex(Channel.Key), Channel.Value);
	}

	const FName ProfileNames[] = {
		VerseCollision::Profile::Architecture, VerseCollision::Profile::Destructible,
		VerseCollision::Profile::Glass, VerseCollision::Profile::Prop,
		VerseCollision::Profile::PropSmall, VerseCollision::Profile::Debris,
		VerseCollision::Profile::ProxyOnly, VerseCollision::Profile::NoCollision,
	};
	for (const FName& Name : ProfileNames)
	{
		FCollisionResponseTemplate Template;
		TestTrue(FString::Printf(TEXT("profile %s exists"), *Name.ToString()), Profiles->GetProfileTemplate(Name, Template));
	}

	// Rows of the contract tables (Pawn and weapon trace columns, the debris and hit body rules).
	struct FExpect { FName Profile; ECollisionChannel Channel; ECollisionResponse Response; };
	const FExpect Expectations[] = {
		{ VerseCollision::Profile::Architecture, ECC_Pawn, ECR_Block },
		{ VerseCollision::Profile::Architecture, VerseCollision::Bolt, ECR_Block },
		{ VerseCollision::Profile::Architecture, VerseCollision::Sight, ECR_Block },
		{ VerseCollision::Profile::Architecture, VerseCollision::HitBody, ECR_Ignore },
		{ VerseCollision::Profile::Destructible, VerseCollision::Bolt, ECR_Block },
		{ VerseCollision::Profile::Destructible, VerseCollision::HitBody, ECR_Ignore },
		{ VerseCollision::Profile::Glass, ECC_Pawn, ECR_Block },
		{ VerseCollision::Profile::Glass, VerseCollision::Bolt, ECR_Block },
		{ VerseCollision::Profile::Glass, VerseCollision::Sight, ECR_Overlap },
		{ VerseCollision::Profile::Prop, ECC_Pawn, ECR_Block },
		{ VerseCollision::Profile::PropSmall, ECC_Pawn, ECR_Ignore },
		{ VerseCollision::Profile::PropSmall, VerseCollision::Bolt, ECR_Block },
		{ VerseCollision::Profile::Debris, ECC_Pawn, ECR_Ignore },
		{ VerseCollision::Profile::Debris, VerseCollision::Bolt, ECR_Ignore },
		{ VerseCollision::Profile::Debris, VerseCollision::Sight, ECR_Ignore },
		{ VerseCollision::Profile::Debris, VerseCollision::HitBody, ECR_Ignore },
		{ VerseCollision::Profile::Debris, ECC_WorldStatic, ECR_Block },
		{ VerseCollision::Profile::NoCollision, VerseCollision::Bolt, ECR_Ignore },
		{ FName(TEXT("Pawn")), VerseCollision::Bolt, ECR_Ignore },
		{ FName(TEXT("Pawn")), VerseCollision::HitBody, ECR_Ignore },
		{ FName(TEXT("Pawn")), VerseCollision::Debris, ECR_Ignore },
		{ FName(TEXT("CharacterMesh")), VerseCollision::HitBody, ECR_Block },
		{ FName(TEXT("CharacterMesh")), VerseCollision::Bolt, ECR_Ignore },
	};
	for (const FExpect& Expect : Expectations)
	{
		FCollisionResponseTemplate Template;
		if (Profiles->GetProfileTemplate(Expect.Profile, Template))
		{
			TestEqual(FString::Printf(TEXT("%s response to %s"), *Expect.Profile.ToString(),
				*Profiles->ReturnChannelNameFromContainerIndex(Expect.Channel).ToString()),
				int32(ResponseOf(Template, Expect.Channel)), int32(Expect.Response));
		}
	}

	FCollisionResponseTemplate DebrisTemplate;
	if (Profiles->GetProfileTemplate(VerseCollision::Profile::Debris, DebrisTemplate))
	{
		TestEqual(TEXT("Verse_Debris object type"), int32(DebrisTemplate.ObjectType), int32(VerseCollision::Debris));
	}
	FCollisionResponseTemplate NoneTemplate;
	if (Profiles->GetProfileTemplate(VerseCollision::Profile::NoCollision, NoneTemplate))
	{
		TestEqual(TEXT("Verse_NoCollision is off"), int32(NoneTemplate.CollisionEnabled.GetValue()), int32(ECollisionEnabled::NoCollision));
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
