using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseDestruction : ModuleRules
{
	public VerseDestruction(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore" });
		// Engine modules (not Verse edges): FFastArraySerializer and push model of the piece state
		// (destruction.md 3.3), the debris geometry collections and their real chunk counts (10),
		// navmesh build feedback for the dirty-tile queue (6.1).
		PublicDependencyModuleNames.AddRange(new string[] { "NetCore", "Chaos", "GeometryCollectionEngine", "NavigationSystem" });
		// The validator reads the source geometry of a mesh in the editor (destruction.md 9).
		PrivateDependencyModuleNames.AddRange(new string[] { "MeshDescription" });
		// PhysicsCore: a UPhysicalMaterial subclass may carry the world surface role (change request #1134).
		PrivateDependencyModuleNames.AddRange(new string[] { "PhysicsCore" });
	}
}
