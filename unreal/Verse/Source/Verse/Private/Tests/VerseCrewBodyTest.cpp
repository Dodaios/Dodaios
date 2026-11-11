#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Anim/VerseAnimInstance.h"
#include "Components/SkeletalMeshComponent.h"
#include "Crew/VerseCrewPawn.h"
#include "Crew/VerseCrewTypes.h"
#include "Engine/Engine.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "GameFramework/WorldSettings.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Ranks/VerseRankLook.h"
#include "VerseCrewBody.h"

// Verse.Crew.Body: a crew pawn wears the body three.js gives it (officer uniform or coverall, F or M
// by hash32 of the id), its rank (tier colours, lit plate tiles; technicians in the deck tier),
// the activity's crew clip, the walk clip while moving, and a promotion repaints it.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewBodyTest, "Verse.Crew.Body", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseCrewBodyTest::RunTest(const FString&)
{
	TestEqual(TEXT("sit_type"), UVerseCrewBody::ClipFor(EVerseCrewActivity::SitType), FName(TEXT("A_Crew_Sit_Type")));
	TestEqual(TEXT("sleep"), UVerseCrewBody::ClipFor(EVerseCrewActivity::Sleep), FName(TEXT("A_Crew_Bunk")));
	TestEqual(TEXT("guard falls back to the stand"), UVerseCrewBody::ClipFor(EVerseCrewActivity::StandGuard), FName(TEXT("A_Crew_Stand")));

	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, MakeUniqueObjectName(GetTransientPackage(), UWorld::StaticClass(), TEXT("VerseCrewBodyTest")));
	FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
	Context.SetCurrentWorld(World);
	World->InitializeActorsForPlay(FURL());
	World->BeginPlay();
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	auto Spawn = [World, &Params](const TCHAR* Id, EVerseCrewRole Role, const TCHAR* Rank)
	{
		AVerseCrewPawn* Pawn = World->SpawnActor<AVerseCrewPawn>(AVerseCrewPawn::StaticClass(), FVector(0.0, 0.0, 90.0), FRotator::ZeroRotator, Params);
		Pawn->MemberId = Id;
		Pawn->CrewRole = Role;
		Pawn->RankId = Rank;
		Pawn->Activity = EVerseCrewActivity::SitType;
		return Pawn;
	};
	auto Tint = [](USkeletalMeshComponent* Body, const TCHAR* Slot, const TCHAR* Param)
	{
		FLinearColor Out = FLinearColor::Transparent;
		if (const UMaterialInstanceDynamic* Mid = Cast<UMaterialInstanceDynamic>(Body->GetMaterial(Body->GetMaterialIndex(FName(Slot)))))
		{
			Mid->GetVectorParameterValue(FHashedMaterialParameterInfo(Param), Out);
		}
		return Out;
	};

	AVerseCrewPawn* Officer = Spawn(TEXT("agent-7"), EVerseCrewRole::Officer, TEXT("commodore"));
	UVerseCrewBody* Body = UVerseCrewBody::Dress(Officer);
	if (TestNotNull(TEXT("the officer is dressed"), Body))
	{
		const FString Mesh = Officer->Body->GetSkeletalMeshAsset() ? Officer->Body->GetSkeletalMeshAsset()->GetName() : FString();
		TestTrue(TEXT("officer uniform"), Mesh.StartsWith(TEXT("SK_Commander_")));
		TestEqual(TEXT("dressing twice keeps one body"), UVerseCrewBody::Dress(Officer), Body);
		const VerseRanks::FTier* Command = VerseRanks::FindTier(TEXT("command"));
		TestTrue(TEXT("command uniform"), Tint(Officer->Body, TEXT("M_Uniform"), TEXT("BaseTint")).Equals(VerseRanks::Linear(Command->Uniform), 1e-3f));
		TestTrue(TEXT("commodore plate: tile 1 glows"), Tint(Officer->Body, TEXT("M_RankTile_1"), TEXT("EmissiveColor")).GetLuminance() > 0.5f);
		Officer->Body->InitAnim(true);
		Body->Animate(1.f / 30.f);
		TestEqual(TEXT("seated at the desk"), Body->GetClip(), FName(TEXT("A_Crew_Sit_Type")));
		TestEqual(TEXT("the root stays on the floor (the clip holds the seat)"), Officer->Body->GetRelativeLocation().Z, -90.0);
		Officer->SetActorLocation(Officer->GetActorLocation() + FVector(5.0, 0.0, 0.0));
		Body->Animate(1.f / 30.f);
		TestEqual(TEXT("walking while it moves"), Body->GetClip(), FName(TEXT("A_Crew_Walk")));
		Officer->RankId = TEXT("fleet_admiral");
		Body->Animate(1.f / 30.f);
		TestTrue(TEXT("a promotion repaints the uniform"), Tint(Officer->Body, TEXT("M_Uniform"), TEXT("BaseTint")).Equals(VerseRanks::Linear(VerseRanks::FindTier(TEXT("flag"))->Uniform), 1e-3f));
	}

	AVerseCrewPawn* Technician = Spawn(TEXT("pane-3"), EVerseCrewRole::Technician, TEXT("captain"));
	if (TestNotNull(TEXT("the technician is dressed"), UVerseCrewBody::Dress(Technician)))
	{
		const FString Mesh = Technician->Body->GetSkeletalMeshAsset() ? Technician->Body->GetSkeletalMeshAsset()->GetName() : FString();
		TestTrue(TEXT("coverall"), Mesh.StartsWith(TEXT("SK_Crew_")));
		TestTrue(TEXT("technicians wear the deck tier"), Tint(Technician->Body, TEXT("M_Uniform"), TEXT("BaseTint")).Equals(VerseRanks::Linear(VerseRanks::FindTier(TEXT("deck"))->Uniform), 1e-3f));
	}
	World->EndPlay(EEndPlayReason::Quit);
	GEngine->DestroyWorldContext(World);
	World->DestroyWorld(false);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
