using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseUI : ModuleRules
{
	public VerseUI(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore", "VerseBridge", "VerseCombat", "VerseCrew", "VerseDecks" });
		// Engine modules only: Json and Slate for WP16's station overlay and command data; WP18's HUD,
		// menus, key bindings, JSON data and render-target captures. Engine re-exports their
		// headers but not their import libraries.
		PrivateDependencyModuleNames.AddRange(new string[] { "InputCore", "Json", "Slate", "SlateCore", "RenderCore", "RHI", "ImageCore" });
	}
}
