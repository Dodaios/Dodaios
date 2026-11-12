"""The jarvis-shader-pet/1 pack: a fragment file with hard limits."""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.ui.pets.loader import load_pet_by_id, read_manifest
from dodaios.ui.pets.manifest import PetManifestError, parse_manifest
from dodaios.ui.pets.shader import MAX_SHADER_BYTES, check_shader_source
from dodaios.ui.pets.states import SHADER_PET_FORMAT
from dodaios.ui.pets.store import PetStore

USER_ID = "u0123456789abcdef"
SOURCE = """
void main() {
  float band = 0.5 + 0.5 * sin(uTime + vLocal.y * 6.0 + uState);
  vec3 color = mix(vec3(0.05, 0.08, 0.2), vec3(0.3, 0.75, 1.0), band);
  gl_FragColor = vec4(color, 0.9);
}
"""


def test_a_shader_manifest_has_no_sheet() -> None:
    manifest = parse_manifest(
        {
            "format": SHADER_PET_FORMAT,
            "id": USER_ID,
            "name": "Tide",
            "description": "Rings.",
            "shader": "shader.frag",
        },
        builtin=False,
    )
    assert manifest.kind == "shader"
    assert manifest.shader == "shader.frag"
    assert manifest.to_json()["format"] == SHADER_PET_FORMAT
    assert "sheet" not in manifest.to_json()


def test_shader_source_rules() -> None:
    check_shader_source(SOURCE)
    with pytest.raises(PetManifestError, match="while"):
        check_shader_source("void main() { while (true) { } }")
    with pytest.raises(PetManifestError, match="sampler"):
        check_shader_source("void main() { sampler2D tex; gl_FragColor = vec4(1.0); }")
    with pytest.raises(PetManifestError, match="for loop"):
        check_shader_source("void main() { for (int i = 0; i < n; i++) { } }")
    with pytest.raises(PetManifestError, match="32"):
        check_shader_source("void main() { for (int i = 0; i < 64; i++) { } }")
    with pytest.raises(PetManifestError, match="16 KB"):
        check_shader_source("void main() {}\n" + ("a" * (MAX_SHADER_BYTES + 1)))


def test_loop_counter_nesting_and_hidden_words() -> None:
    nested = "void main() { for (int i = 0; i < 32; i++) { for (int k = 0; k < 5; k++) { } } }"
    check_shader_source(nested)
    sequential = "void main() { for (int i = 0; i < 32; i++) { } for (int k = 0; k < 32; k++) { } }"
    check_shader_source(sequential)
    root = Path(__file__).resolve().parents[4] / "dodaios/ui/pets/builtin"
    check_shader_source((root / "wisp-swarm/shader.frag").read_text(encoding="utf-8"))
    check_shader_source((root / "mirror-fold/shader.frag").read_text(encoding="utf-8"))
    with pytest.raises(PetManifestError, match="for loop"):
        check_shader_source("void main() { for (int i = 0; j < 8; i++) { } }")
    with pytest.raises(PetManifestError, match="counter"):
        check_shader_source("void main() { for (int i = 0; i < 4; i++) { i = 0; } }")
    with pytest.raises(PetManifestError, match="counter"):
        check_shader_source("void main() { for (int i = 0; i < 4; i++) { i++; } }")
    with pytest.raises(PetManifestError, match="160"):
        check_shader_source(
            "void main() { for (int i = 0; i < 32; i++) { for (int k = 0; k < 32; k++) { } } }"
        )
    with pytest.raises(PetManifestError, match="while"):
        check_shader_source("void main() { wh\\\nile (true) { } }")
    with pytest.raises(PetManifestError, match="#undef"):
        check_shader_source("void main() { gl_FragColor = vec4(1.0); }\n#undef uState\n")


def test_store_round_trip_and_the_overlay_skips_it(tmp_path: Path) -> None:
    data = tmp_path / "data"
    store = PetStore(data / "pets")
    manifest = store.add_shader(source=SOURCE, name="Tide", description="Rings.")
    folder = data / "pets" / manifest.id
    loaded = read_manifest(folder, builtin=False)
    assert loaded.kind == "shader"
    assert (folder / "shader.frag").read_text(encoding="utf-8") == SOURCE.replace("\r\n", "\n")
    # The sprite loader has no frames for it, so it still falls back. The
    # desktop figure reads the fragment itself (ui.orb.shader_desktop).
    fallback = load_pet_by_id(manifest.id, data_dir=data)
    assert fallback is not None and fallback.manifest.id != manifest.id
