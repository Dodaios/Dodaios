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
		// Json: crew life reads verse.bridge/1 frames and its tuning files (WP15; CCR in the WP15 PR).
		PrivateDependencyModuleNames.AddRange(new string[] { "Json" });
	}
}
