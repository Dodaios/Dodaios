from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "installer-smoke.yml"


def test_forced_installer_smoke_avoids_full_history_checkout() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["changes"]["steps"]

    checkout = next(step for step in steps if step.get("name", "").startswith("Checkout"))
    assert checkout["with"]["fetch-depth"] == 1

    path_gate = next(step for step in steps if step.get("id") == "paths")
    script = path_gate["run"]
    force_short_circuit = script.index('if [ "${{ inputs.force }}" = "true" ]; then')
    history_fetch = script.index("git fetch --no-tags origin main:refs/remotes/origin/main")

    assert force_short_circuit < history_fetch
    assert "exit 0" in script[force_short_circuit:history_fetch]
