using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseCore : ModuleRules
{
	public VerseCore(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "GameplayTags" });
		// Json: the coordinate golden file test (contracts/coordinates.md 5, test 13).
		PrivateDependencyModuleNames.AddRange(new string[] { "Json" });
	}
}
