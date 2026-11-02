using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseScreens : ModuleRules
{
	public VerseScreens(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore", "VerseBridge", "VerseDecks" });
		// Json: verse.bridge/1 cells.json/1 frames and command data (WP16, request to the integration owner).
		PrivateDependencyModuleNames.AddRange(new string[] { "Json" });
	}
}
