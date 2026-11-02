using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseCombat : ModuleRules
{
	public VerseCombat(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "NetCore" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore", "VerseMovement", "VerseDestruction" });
		// GAS for health, damage effects and the gadget abilities (architecture.md 2 rule 4, 3.2 "Abilities").
		PublicDependencyModuleNames.AddRange(new string[] { "GameplayTags", "GameplayAbilities", "GameplayTasks" });
		// Json: the weapon and gadget definition importer (WP02.1).
		PrivateDependencyModuleNames.AddRange(new string[] { "Json" });
	}
}
