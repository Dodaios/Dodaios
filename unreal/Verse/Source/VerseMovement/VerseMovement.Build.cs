using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseMovement : ModuleRules
{
	public VerseMovement(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "GameplayTags" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore" });
		// WP01: Enhanced Input for the person's input path, NetCore for push-model replication,
		// Json for DA_MovementTuning's source file, PhysicsCore for footstep surfaces.
		PublicDependencyModuleNames.AddRange(new string[] { "EnhancedInput", "InputCore", "NetCore" });
		PrivateDependencyModuleNames.AddRange(new string[] { "Json", "PhysicsCore" });
	}
}
