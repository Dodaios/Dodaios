using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseCrew : ModuleRules
{
	public VerseCrew(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore", "VerseBridge", "VerseDecks" });
		// Json: bridge frames, crew tuning and presentation files; NavigationSystem: typed and async
		// Recast path queries for crew walks (WP15, change request #1167).
		PrivateDependencyModuleNames.AddRange(new string[] { "Json", "NavigationSystem" });
	}
}
