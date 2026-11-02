"""Texture import from `verse.import/1` texture records (art-pipeline 6.4).

Called by `import_assets` for records of kind `texture`. The record's
`texture` block sets sRGB, compression, group and maximum size; green is
flipped on import for normal maps. A record whose `texture.channels.lut`
names a lattice size is a colour lookup table: no mips, clamped, no
filtering beyond bilinear, never streamed (`T_Verse_Grade_LUT_M`, WP14.2).
"""

from __future__ import annotations

from pathlib import Path

from .records import split_object_path

COMPRESSION = {
    "Default": "TC_DEFAULT",
    "Normalmap": "TC_NORMALMAP",
    "Masks": "TC_MASKS",
    "BC7": "TC_BC7",
    "Grayscale": "TC_GRAYSCALE",
    "HDR": "TC_HDR",
}
GROUPS = {
    "World": "TEXTUREGROUP_WORLD",
    "WorldNormalMap": "TEXTUREGROUP_WORLD_NORMAL_MAP",
    "Character": "TEXTUREGROUP_CHARACTER",
    "CharacterNormalMap": "TEXTUREGROUP_CHARACTER_NORMAL_MAP",
    "Weapon": "TEXTUREGROUP_WEAPON",
    "UI": "TEXTUREGROUP_UI",
}


def import_texture(record: dict, png: Path, *, save: bool = True):
    import unreal

    folder, name = split_object_path(record["asset_path"])
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", str(png))
    task.set_editor_property("destination_path", folder)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", False)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    texture = unreal.load_asset(record["asset_path"])
    if texture is None:
        raise RuntimeError(f"import of {png.name} produced no {record['asset_path']}")
    spec = record["texture"]
    texture.set_editor_property("srgb", bool(spec["srgb"]))
    compression = getattr(unreal.TextureCompressionSettings, COMPRESSION[spec["compression"]])
    texture.set_editor_property("compression_settings", compression)
    texture.set_editor_property("flip_green_channel", bool(spec["flip_green"]))
    texture.set_editor_property("max_texture_size", int(spec["max_size"]))
    channels = spec.get("channels") or {}
    if "lut" in channels:
        texture.set_editor_property(
            "lod_group", unreal.TextureGroup.TEXTUREGROUP_COLOR_LOOKUP_TABLE
        )
        texture.set_editor_property(
            "mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS
        )
        texture.set_editor_property("address_x", unreal.TextureAddress.TA_CLAMP)
        texture.set_editor_property("address_y", unreal.TextureAddress.TA_CLAMP)
        texture.set_editor_property("never_stream", True)
        texture.set_editor_property("filter", unreal.TextureFilter.TF_BILINEAR)
    else:
        texture.set_editor_property(
            "lod_group", getattr(unreal.TextureGroup, GROUPS[spec["group"]])
        )
    if save:
        unreal.EditorAssetLibrary.save_loaded_asset(texture, only_if_is_dirty=False)
    return texture


def run(*_args, **_kwargs) -> dict:
    raise NotImplementedError("textures import through `import_art.py assets` (kind texture)")
