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
		// Json: cells.json/1 frames, screen command data and golden fixtures (WP16, change request #1142).
		PrivateDependencyModuleNames.AddRange(new string[] { "Json" });
	}
}
