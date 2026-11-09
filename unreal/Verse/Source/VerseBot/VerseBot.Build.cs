using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseBot : ModuleRules
{
	public VerseBot(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore", "VerseMovement", "VerseCombat", "VerseDestruction" });
		// The AAIController, EQS, the belief nav query filter and the StateTree tactics of bot.md 5 and 6
		// (WP08, change request #1162). Engine modules only, no Verse edge.
		PrivateDependencyModuleNames.AddRange(new string[] { "AIModule", "NavigationSystem", "StateTreeModule", "GameplayStateTreeModule" });
	}
}
