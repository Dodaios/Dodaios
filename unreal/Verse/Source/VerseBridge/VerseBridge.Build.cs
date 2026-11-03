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
		// Engine modules of the bridge client (WP17.11, 17.12): Json is in the public
		// feed and codec headers and also serves the duel.result codec (WP21.6);
		// Sockets carries the WebSocket client; Slate, SlateCore and InputCore move,
		// show and focus the window and catch the return key.
		PublicDependencyModuleNames.AddRange(new string[] { "Json" });
		PrivateDependencyModuleNames.AddRange(new string[] { "Slate", "SlateCore", "InputCore", "Sockets" });
	}
}
