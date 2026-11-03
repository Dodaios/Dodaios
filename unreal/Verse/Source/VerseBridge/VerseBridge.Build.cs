using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseBridge : ModuleRules
{
	public VerseBridge(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore" });
		// Json: the duel.result codec and its pending store (WP21.6, bridge-protocol.md 10).
		PrivateDependencyModuleNames.AddRange(new string[] { "Json" });
	}
}
