"""The master materials of art-pipeline 7 and the look's post-process material (WP14.1, 14.2).

`python scripts/unreal/import_art.py masters` rebuilds every master graph from
this file and saves it, so the `.uasset` files under
`/Game/Verse/Materials/Master/` (lockable, merged by the integration owner)
always follow the text here. The parameter names are frozen (art-pipeline
7, Frozen interface 6) and documented in `art/verse/style-unreal.md`.

Graphs are small: parameters feed a few Custom HLSL nodes. The weapon
master clamps its tints in the shader to the black-only rule of
art-pipeline 8.2 (base at most #1A1A1B, worn edge at most #3B3F47), so no
instance can make a weapon lighter or coloured.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MASTER_FOLDER = "/Game/Verse/Materials/Master"
POST_FOLDER = "/Game/Verse/PostProcess"
LUT_PATH = "/Game/Verse/PostProcess/T_Verse_Grade_LUT_M.T_Verse_Grade_LUT_M"
WHITE = "/Engine/EngineResources/WhiteSquareTexture.WhiteSquareTexture"
BLACK = "/Engine/EngineResources/Black.Black"
FLAT_NORMAL = "/Engine/EngineMaterials/FlatNormal.FlatNormal"

#: Linear caps of the black-only weapon rule (sRGB #1A1A1B and #3B3F47).
WEAPON_BASE_CAP = (0.0103, 0.0103, 0.0109)
WEAPON_EDGE_CAP = (0.0437, 0.0497, 0.0630)

# Value noise used by several masters. Custom nodes paste code into one
# function body, so the helper is a guarded macro.
NOISE = r"""
#ifndef VERSE_HASH2
#define VERSE_HASH2(p) frac(sin(dot(p, float2(127.1, 311.7))) * 43758.5453)
#endif
float2 vp = UV * Scale;
float2 vi = floor(vp);
float2 vf = frac(vp);
vf = vf * vf * (3.0 - 2.0 * vf);
float va = VERSE_HASH2(vi);
float vb = VERSE_HASH2(vi + float2(1, 0));
float vc = VERSE_HASH2(vi + float2(0, 1));
float vd = VERSE_HASH2(vi + float2(1, 1));
float n1 = lerp(lerp(va, vb, vf.x), lerp(vc, vd, vf.x), vf.y);
float2 wp = vp * 4.37 + 17.0;
float2 wi = floor(wp);
float2 wf = frac(wp);
wf = wf * wf * (3.0 - 2.0 * wf);
float wa = VERSE_HASH2(wi);
float wb = VERSE_HASH2(wi + float2(1, 0));
float wc = VERSE_HASH2(wi + float2(0, 1));
float wd = VERSE_HASH2(wi + float2(1, 1));
float n2 = lerp(lerp(wa, wb, wf.x), lerp(wc, wd, wf.x), wf.y);
return float2(n1, n2);
"""


@dataclass
class Param:
    kind: str  # scalar, vector, switch, texture
    name: str
    default: object
    doc: str
    group: str = "Verse"


@dataclass
class MasterSpec:
    name: str
    folder: str
    use: str
    params: list[Param] = field(default_factory=list)


def _p(kind: str, name: str, default, doc: str) -> Param:
    return Param(kind, name, default, doc)


SURFACE_PARAMS = [
    _p(
        "vector",
        "BaseTint",
        (0.016, 0.017, 0.019, 1.0),
        "Albedo tint (linear); multiplies the texture set",
    ),
    _p("scalar", "RoughnessMin", 0.45, "Roughness on worn, polished areas"),
    _p("scalar", "RoughnessMax", 0.85, "Roughness on untouched areas"),
    _p("scalar", "Metallic", 0.0, "0 dielectric (paint, concrete, rubber), 1 bare steel"),
    _p("scalar", "EdgeWear", 0.5, "Strength of vertex colour R (edge wear) and world noise wear"),
    _p("vector", "EdgeTint", (0.044, 0.050, 0.063, 1.0), "Colour of worn edges"),
    _p("scalar", "GrimeAmount", 0.5, "Strength of vertex colour G (grime) and noise grime"),
    _p("scalar", "NoiseScale", 1.5, "World noise frequency per metre"),
    _p("scalar", "PanelCm", 0.0, "World-space panel seam grid in cm on the face's plane (0 off)"),
    _p("scalar", "PanelDark", 0.55, "How much a panel seam darkens and roughens the surface"),
    _p("switch", "UseTriplanar", False, "Object-relative triplanar mapping for pieces without UVs"),
    _p("scalar", "TriplanarScale", 1.0, "Texture repeats per metre in triplanar mode"),
    _p(
        "scalar",
        "TriplanarWorld",
        0.0,
        "1 maps triplanar textures to the world grid (seamless across pieces)",
    ),
    _p(
        "switch",
        "UseTextureSet",
        False,
        "Sample Set1 (and Set2/Set3 by noise masks) instead of flat tint",
    ),
    _p("texture", "Set1_BC", WHITE, "Texture set 1 base colour (sRGB)"),
    _p("texture", "Set1_ORM", WHITE, "Texture set 1 AO/roughness/metallic"),
    _p("texture", "Set1_N", FLAT_NORMAL, "Texture set 1 normal (UV or triplanar)"),
    _p("scalar", "NormalStrength", 1.0, "Strength of the set 1 normal in triplanar mode"),
    _p("texture", "Set2_BC", WHITE, "Texture set 2 base colour (triplanar blend, noise mask)"),
    _p("texture", "Set3_BC", WHITE, "Texture set 3 base colour (triplanar blend, vertex colour B)"),
    _p("scalar", "Set2Amount", 0.0, "Share of set 2"),
    _p("scalar", "Set3Amount", 0.0, "Share of set 3"),
    _p("switch", "UseHoleMask", False, "Per-piece hole mask (destruction 5); implies Masked blend"),
    _p("texture", "HoleMask", WHITE, "Hole mask render target, R = 1 solid, 0 hole"),
    _p("vector", "HoleMaskUV", (1.0, 1.0, 0.0, 0.0), "UV0 to mask space: xy scale, zw offset"),
]

MASTERS: list[MasterSpec] = [
    MasterSpec(
        "M_Verse_Surface",
        MASTER_FOLDER,
        "Opaque hard surface: steel, concrete, paint, rubber",
        SURFACE_PARAMS,
    ),
    MasterSpec(
        "M_Verse_Floor",
        MASTER_FOLDER,
        "Floors and decks, world-space grid",
        [
            _p("vector", "BaseTint", (0.009, 0.0095, 0.010, 1.0), "Deck plate colour"),
            _p("vector", "SeamTint", (0.004, 0.004, 0.0045, 1.0), "Seam line colour"),
            _p("scalar", "GridCm", 120.0, "Seam grid size in cm on the global grid"),
            _p("scalar", "SeamCm", 0.8, "Seam width in cm"),
            _p("scalar", "RoughnessMin", 0.35, "Roughness in the gloss lanes"),
            _p("scalar", "RoughnessMax", 0.9, "Roughness elsewhere"),
            _p("scalar", "LaneCm", 600.0, "Spacing of the worn gloss lanes (along X)"),
            _p("scalar", "LaneWidthCm", 140.0, "Width of a worn lane"),
            _p("scalar", "WearAmount", 0.6, "Strength of lane wear and noise"),
            _p("scalar", "NoiseScale", 0.8, "World noise frequency per metre"),
            _p(
                "switch", "UseHoleMask", False, "Never on the hall floor; for breakable deck panels"
            ),
            _p("texture", "HoleMask", WHITE, "Hole mask, R = 1 solid"),
            _p("vector", "HoleMaskUV", (1.0, 1.0, 0.0, 0.0), "UV0 to mask space"),
        ],
    ),
    MasterSpec(
        "M_Verse_Emissive",
        MASTER_FOLDER,
        "Light panels, indicators, lamps, reticles and opaque weapon VFX (unlit, two-sided)",
        [
            _p(
                "vector",
                "EmissiveColor",
                (1.0, 0.37, 0.04, 1.0),
                "Linear colour, palette-checked (amber, red, work-light white)",
            ),
            _p("scalar", "EmissiveNits", 40.0, "Brightness multiplier"),
            _p("scalar", "Fade", 1.0, "0..1 runtime fade (VFX lifetime)"),
            _p(
                "switch",
                "UseVertexFalloff",
                False,
                "Multiply by vertex colour R (hot core to cool tip)",
            ),
        ],
    ),
    MasterSpec(
        "M_Verse_Glass",
        MASTER_FOLDER,
        "Glazing, lenses, energy fields and soft VFX (translucent)",
        [
            _p("vector", "BaseTint", (0.02, 0.021, 0.022, 1.0), "Glass tint"),
            _p("scalar", "Opacity", 0.25, "Coverage"),
            _p("scalar", "Roughness", 0.06, "Surface roughness"),
            _p(
                "vector",
                "EmissiveColor",
                (0.0, 0.0, 0.0, 1.0),
                "Self-light of energy fields and flashes",
            ),
            _p("scalar", "EmissiveNits", 0.0, "Brightness multiplier"),
            _p("scalar", "Fade", 1.0, "0..1 runtime fade"),
            _p("switch", "UseVertexFalloff", False, "Opacity and emission times vertex colour R"),
        ],
    ),
    MasterSpec(
        "M_Verse_Screen",
        MASTER_FOLDER,
        "Desk monitors (render target from VerseScreens)",
        [
            _p("texture", "ScreenTexture", BLACK, "Render target of the desk's terminal"),
            _p("scalar", "EmissiveNits", 6.0, "Screen brightness"),
            _p("vector", "ScreenTint", (1.0, 1.0, 1.0, 1.0), "Tint"),
            _p("scalar", "Roughness", 0.2, "Glass front roughness"),
        ],
    ),
    MasterSpec(
        "M_Verse_Character",
        MASTER_FOLDER,
        "Skin, cloth, gear (subsurface profile); UV0 stable for wound masks",
        [
            _p("vector", "BaseTint", (1.0, 1.0, 1.0, 1.0), "Albedo tint"),
            _p("texture", "BaseColorMap", WHITE, "Base colour (sRGB)"),
            _p("texture", "ORMMap", WHITE, "AO, roughness, metallic"),
            _p("texture", "NormalMap", FLAT_NORMAL, "Normal"),
            _p("scalar", "RoughnessScale", 1.0, "Roughness multiplier"),
            _p("scalar", "Roughness", 1.0, "Roughness without a map (multiplies ORM green)"),
            _p("scalar", "Metallic", 1.0, "Metallic without a map (multiplies ORM blue)"),
            _p("scalar", "Sheen", 0.0, "Cloth sheen at grazing angles"),
            _p("scalar", "SubsurfaceAmount", 0.0, "Skin subsurface opacity"),
        ],
    ),
    MasterSpec(
        "M_Verse_Weapon",
        MASTER_FOLDER,
        "All weapons: black only, edge wear, oil, grime; no emissive",
        [
            _p(
                "vector",
                "BaseTint",
                (0.0060, 0.0062, 0.0068, 1.0),
                "Base colour; clamped in shader to #1A1A1B",
            ),
            _p(
                "vector",
                "EdgeTint",
                (0.0437, 0.0497, 0.0630, 1.0),
                "Worn edge colour; clamped to #3B3F47",
            ),
            _p("scalar", "EdgeWear", 1.0, "Strength of vertex colour R (chamfer middles)"),
            _p("scalar", "EdgeMetallic", 1.0, "Metallic of worn edges (1 steel, 0 polymer)"),
            _p("scalar", "Metallic", 1.0, "Metallic of the body"),
            _p("scalar", "RoughnessMin", 0.25, "Roughness of polished, oiled areas"),
            _p("scalar", "RoughnessMax", 0.6, "Roughness of the body"),
            _p("scalar", "OilAmount", 0.35, "Oil film: darker and glossier patches"),
            _p("scalar", "GrimeAmount", 0.4, "Strength of vertex colour G (seams)"),
            _p("scalar", "NoiseScale", 9.0, "Noise frequency per UV metre"),
            _p("scalar", "Specular", 0.5, "Dielectric specular (F0 = 0.08 x value)"),
        ],
    ),
    MasterSpec(
        "M_Verse_Decal",
        MASTER_FOLDER,
        "DBuffer decal: markings, stencils, grime, scorch",
        [
            _p("vector", "BaseTint", (0.007, 0.007, 0.007, 1.0), "Decal colour"),
            _p("scalar", "Opacity", 0.85, "Coverage"),
            _p("scalar", "Roughness", 0.9, "Roughness written to the DBuffer"),
            _p("texture", "DecalMask", WHITE, "Shape mask, R"),
            _p("switch", "UseRadialMask", False, "Procedural round mask with ragged rim (scorch)"),
            _p("scalar", "NoiseScale", 6.0, "Rim noise frequency"),
        ],
    ),
]

POST_TONEMAP = MasterSpec(
    "M_Verse_PostTonemap",
    POST_FOLDER,
    "Replaces the tonemapper: exposure, bloom, then the AgX grade LUT",
    [
        _p("texture", "GradeLut", LUT_PATH, "T_Verse_Grade_LUT_M (32^3 strip)"),
        _p("scalar", "BloomScale", 1.0, "Bloom added before the grade"),
        _p("scalar", "LutSize", 32.0, "Lattice size of the strip"),
    ],
)


# --------------------------------------------------------------------------
# Custom HLSL bodies (inputs named as in the connections below)
# --------------------------------------------------------------------------

WEAPON_COLOUR_TEMPLATE = """
float3 tint = min(BaseTint.rgb, float3(BASE_CAP));
float3 edge = min(EdgeTint.rgb, float3(EDGE_CAP));
float wear = saturate(VC.r * EdgeWear * (0.55 + 0.45 * N.y));
float grime = saturate(VC.g * GrimeAmount * (0.5 + 0.5 * N.x));
float3 c = lerp(tint, edge, wear);
c *= 1.0 - 0.45 * grime;
c *= 1.0 - 0.35 * OilAmount * smoothstep(0.45, 0.8, N.x);
return c;
"""
WEAPON_COLOUR = WEAPON_COLOUR_TEMPLATE.replace(
    "BASE_CAP", ", ".join(str(v) for v in WEAPON_BASE_CAP)
).replace("EDGE_CAP", ", ".join(str(v) for v in WEAPON_EDGE_CAP))

WEAPON_ROUGH = """
float wear = saturate(VC.r * EdgeWear * (0.55 + 0.45 * N.y));
float oil = OilAmount * smoothstep(0.45, 0.8, N.x);
float r = lerp(RoughnessMax, RoughnessMin, wear);
r = lerp(r, RoughnessMin * 0.7, oil);
r = lerp(r, 0.95, saturate(VC.g * GrimeAmount * 0.6));
return saturate(r * (0.9 + 0.2 * N.y));
"""

WEAPON_METAL = """
float wear = saturate(VC.r * EdgeWear * (0.55 + 0.45 * N.y));
return saturate(lerp(Metallic, EdgeMetallic, wear));
"""

SURFACE_COLOUR = """
float wear = saturate(VC.r * EdgeWear + EdgeWear * smoothstep(0.72, 0.95, N.y) * 0.5);
float grime = saturate(VC.g * GrimeAmount + GrimeAmount * smoothstep(0.55, 0.9, N.x) * 0.5);
float3 c = BaseTint.rgb * Tex.rgb;
c = lerp(c, EdgeTint.rgb, wear);
return c * (1.0 - 0.5 * grime);
"""

SURFACE_ROUGH = """
float wear = saturate(VC.r * EdgeWear + EdgeWear * smoothstep(0.72, 0.95, N.y) * 0.5);
float r = lerp(RoughnessMax, RoughnessMin, wear) * Orm.g;
return saturate(r * (0.85 + 0.3 * N.x));
"""

TRIPLANAR = """
float3 o = ObjPos * (1.0 - World);
float3 p = (WorldPos - o) * 0.01 * Scale + frac(o * 0.0137) * 7.0;
float3 w = pow(abs(Nrm), 4.0);
w /= (w.x + w.y + w.z);
float3 a = Texture2DSample(Tex, TexSampler, p.yz).rgb;
float3 b = Texture2DSample(Tex, TexSampler, p.xz).rgb;
float3 c = Texture2DSample(Tex, TexSampler, p.xy).rgb;
return a * w.x + b * w.y + c * w.z;
"""

PANEL = """
float3 n = abs(Nrm);
float2 p = (n.x > n.y && n.x > n.z) ? WorldPos.yz : ((n.y > n.z) ? WorldPos.xz : WorldPos.xy);
float cell = max(PanelCm, 1.0);
float2 g = abs(frac(p / cell + 0.5) - 0.5) * cell;
float seam = 1.0 - smoothstep(0.5, 1.3, min(g.x, g.y));
float bevel = 1.0 - smoothstep(1.3, 3.0, min(g.x, g.y));
return PanelCm > 0.5 ? saturate(seam + bevel * 0.35) * PanelDark : 0.0;
"""

TRI_ORM = """
float3 o = ObjPos * (1.0 - World);
float3 p = (WorldPos - o) * 0.01 * Scale + frac(o * 0.0137) * 7.0;
float3 w = pow(abs(Nrm), 4.0);
w /= (w.x + w.y + w.z);
float3 a = Texture2DSample(Tex, TexSampler, p.yz).rgb;
float3 b = Texture2DSample(Tex, TexSampler, p.xz).rgb;
float3 c = Texture2DSample(Tex, TexSampler, p.xy).rgb;
return a * w.x + b * w.y + c * w.z;
"""

# World-space triplanar normal (UDN blend of the three projections around the vertex normal).
TRI_NORMAL = """
float3 o = ObjPos * (1.0 - World);
float3 p = (WorldPos - o) * 0.01 * Scale + frac(o * 0.0137) * 7.0;
float3 w = pow(abs(Nrm), 4.0);
w /= (w.x + w.y + w.z);
float2 tx = Texture2DSample(Tex, TexSampler, p.yz).rg * 2.0 - 1.0;
float2 ty = Texture2DSample(Tex, TexSampler, p.xz).rg * 2.0 - 1.0;
float2 tz = Texture2DSample(Tex, TexSampler, p.xy).rg * 2.0 - 1.0;
float3 d = float3(0.0, tx.x, tx.y) * w.x + float3(ty.x, 0.0, ty.y) * w.y + float3(tz.x, tz.y, 0.0) * w.z;
return normalize(Nrm + d * Strength);
"""

FLOOR_COLOUR = """
float2 p = WorldPos.xy;
float2 g = abs(frac(p / GridCm + 0.5) - 0.5) * GridCm;
float seam = 1.0 - smoothstep(SeamCm * 0.5, SeamCm, min(g.x, g.y));
float ld = abs(frac(p.x / LaneCm) - 0.5) * LaneCm;
float lane = 1.0 - smoothstep(LaneWidthCm * 0.3, LaneWidthCm * 0.5, ld);
float wear = saturate(lane * WearAmount * (0.6 + 0.4 * N.x));
float3 c = BaseTint.rgb * (1.0 + 0.6 * wear) * (0.85 + 0.3 * N.y);
return lerp(c, SeamTint.rgb, seam);
"""

FLOOR_ROUGH = """
float2 p = WorldPos.xy;
float ld = abs(frac(p.x / LaneCm) - 0.5) * LaneCm;
float lane = 1.0 - smoothstep(LaneWidthCm * 0.3, LaneWidthCm * 0.5, ld);
float wear = saturate(lane * WearAmount * (0.6 + 0.4 * N.x));
return saturate(lerp(RoughnessMax, RoughnessMin, wear) * (0.9 + 0.2 * N.y));
"""

HOLE = """
float2 uv = UV * HoleMaskUV.xy + HoleMaskUV.zw;
return Texture2DSample(Mask, MaskSampler, uv).r;
"""

DECAL_MASK = """
float2 d = UV - 0.5;
float r = length(d) * 2.0;
float rim = 0.75 + 0.25 * N.x;
return saturate(1.0 - smoothstep(rim - 0.25, rim, r)) * (0.7 + 0.3 * N.y);
"""

POST = """
float3 c = (Scene.rgb + Bloom.rgb * BloomScale) * Exposure;
float3 u = saturate((log2(max(c, 1e-10) / 0.18) - (EV_MIN)) / (EV_RANGE));
float n = LutSize;
float3 s = u * (n - 1.0);
float b0 = floor(s.b);
float b1 = min(b0 + 1.0, n - 1.0);
float fb = s.b - b0;
float2 px = float2(s.r + 0.5, s.g + 0.5);
float2 inv = float2(1.0 / (n * n), 1.0 / n);
float3 c0 = Texture2DSampleLevel(Lut, LutSampler, (px + float2(b0 * n, 0)) * inv, 0).rgb;
float3 c1 = Texture2DSampleLevel(Lut, LutSampler, (px + float2(b1 * n, 0)) * inv, 0).rgb;
return lerp(c0, c1, fb);
"""


def post_code(ev_min: float, ev_max: float) -> str:
    return POST.replace("EV_MIN", repr(ev_min)).replace("EV_RANGE", repr(ev_max - ev_min))


# --------------------------------------------------------------------------
# Graph building (editor only)
# --------------------------------------------------------------------------


class Graph:
    def __init__(self, unreal, material):
        self.u = unreal
        self.mat = material
        self.mel = unreal.MaterialEditingLibrary
        self.y = 0
        self.nodes: dict[str, object] = {}
        self.errors: list[str] = []
        self.custom_links: dict[str, dict[str, tuple[str, str]]] = {}

    def _new(self, cls, x=-900):
        node = self.mel.create_material_expression(self.mat, cls, x, self.y)
        self.y += 140
        return node

    def param(self, p: Param):
        u = self.u
        if p.kind == "scalar":
            node = self._new(u.MaterialExpressionScalarParameter)
            node.set_editor_property("default_value", float(p.default))
        elif p.kind == "vector":
            node = self._new(u.MaterialExpressionVectorParameter)
            node.set_editor_property("default_value", u.LinearColor(*p.default))
        elif p.kind == "switch":
            node = self._new(u.MaterialExpressionStaticSwitchParameter)
            node.set_editor_property("default_value", bool(p.default))
        else:
            node = self._new(u.MaterialExpressionTextureObjectParameter)
            texture = u.load_asset(p.default)
            if texture is None:
                self.errors.append(f"{self.mat.get_name()}: default texture {p.default} missing")
            else:
                node.set_editor_property("texture", texture)
            if p.name in ("Set1_BC", "Set2_BC", "Set3_BC", "BaseColorMap"):
                node.set_editor_property("sampler_type", u.MaterialSamplerType.SAMPLERTYPE_COLOR)
            elif p.name in ("Set1_N", "NormalMap"):
                node.set_editor_property("sampler_type", u.MaterialSamplerType.SAMPLERTYPE_NORMAL)
            elif p.name == "ScreenTexture":
                node.set_editor_property("sampler_type", u.MaterialSamplerType.SAMPLERTYPE_COLOR)
            else:
                node.set_editor_property(
                    "sampler_type", u.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR
                )
        node.set_editor_property("parameter_name", p.name)
        node.set_editor_property("group", p.group)
        node.set_editor_property("desc", p.doc)
        self.nodes[p.name] = node
        return node

    def node(self, cls, key: str, **props):
        n = self._new(cls, x=-1300)
        for k, v in props.items():
            n.set_editor_property(k, v)
        self.nodes[key] = n
        return n

    def custom(self, key: str, code: str, inputs: dict[str, tuple[str, str]], out: str = "3"):
        u = self.u
        n = self._new(u.MaterialExpressionCustom, x=-400)
        n.set_editor_property("code", code)
        n.set_editor_property("description", key)
        kinds = {
            "1": u.CustomMaterialOutputType.CMOT_FLOAT1,
            "2": u.CustomMaterialOutputType.CMOT_FLOAT2,
            "3": u.CustomMaterialOutputType.CMOT_FLOAT3,
            "4": u.CustomMaterialOutputType.CMOT_FLOAT4,
        }
        n.set_editor_property("output_type", kinds[out])
        custom_inputs = []
        for name in inputs:
            ci = u.CustomInput()
            ci.set_editor_property("input_name", name)
            custom_inputs.append(ci)
        n.set_editor_property("inputs", custom_inputs)
        self.nodes[key] = n
        self.custom_links[key] = dict(inputs)
        for name, (src, pin) in inputs.items():
            self.link(src, pin, n, name)
        return n

    def unlinked(self) -> dict[str, list[str]]:
        """Custom-node inputs that have no expression connected, per node key."""
        mel = self.mel
        out = {}
        for key in self.custom_links:
            node = self.nodes[key]
            names = [
                str(ci.get_editor_property("input_name"))
                for ci in node.get_editor_property("inputs")
            ]
            connected = mel.get_inputs_for_material_expression(self.mat, node)
            missing = [n for n, e in zip(names, connected, strict=False) if e is None]
            missing += names[len(connected) :]
            if missing:
                out[key] = missing
        return out

    def relink(self, missing: dict[str, list[str]]) -> None:
        for key, names in missing.items():
            for name in names:
                src, pin = self.custom_links[key][name]
                self.link(src, pin, self.nodes[key], name)

    def link(self, src, pin: str, dst, dst_pin: str) -> None:
        source = self.nodes[src] if isinstance(src, str) else src
        target = self.nodes[dst] if isinstance(dst, str) else dst
        if not self.mel.connect_material_expressions(source, pin, target, dst_pin):
            self.errors.append(f"{self.mat.get_name()}: link {src}.{pin} -> {dst_pin} failed")

    def out(self, src, pin: str, prop: str) -> None:
        source = self.nodes[src] if isinstance(src, str) else src
        prop_enum = getattr(self.u.MaterialProperty, prop)
        if not self.mel.connect_material_property(source, pin, prop_enum):
            self.errors.append(f"{self.mat.get_name()}: output {prop} failed")

    def switch_node(self, param_name: str, key: str):
        """A second static switch node sharing `param_name` (one value, many uses)."""
        node = self._new(self.u.MaterialExpressionStaticSwitchParameter)
        node.set_editor_property("parameter_name", param_name)
        node.set_editor_property("group", "Verse")
        first = self.nodes.get(param_name)
        if first is not None:
            node.set_editor_property("default_value", first.get_editor_property("default_value"))
        self.nodes[key] = node
        return node

    def switch(self, key: str, switch_name: str, true_src, false_src) -> object:
        sw = self.nodes[switch_name]
        self.link(true_src[0], true_src[1], sw, "True")
        self.link(false_src[0], false_src[1], sw, "False")
        return sw


def _common_nodes(g: Graph) -> None:
    u = g.u
    g.node(u.MaterialExpressionVertexColor, "VC")
    g.node(u.MaterialExpressionTextureCoordinate, "UV")
    g.node(u.MaterialExpressionWorldPosition, "WorldPos")


def _noise(g: Graph, uv_key: str = "UV", scale_key: str = "NoiseScale", key: str = "N"):
    return g.custom(key, NOISE, {"UV": (uv_key, ""), "Scale": (scale_key, "")}, out="2")


def build_weapon(g: Graph) -> None:
    _common_nodes(g)
    _noise(g)
    ins = {k: (k, "") for k in ("BaseTint", "EdgeTint", "EdgeWear", "GrimeAmount", "OilAmount")}
    ins.update({"VC": ("VC", ""), "N": ("N", "")})
    g.custom("Colour", WEAPON_COLOUR, ins)
    rough = {
        k: (k, "") for k in ("RoughnessMin", "RoughnessMax", "EdgeWear", "OilAmount", "GrimeAmount")
    }
    rough.update({"VC": ("VC", ""), "N": ("N", "")})
    g.custom("Rough", WEAPON_ROUGH, rough, out="1")
    metal = {k: (k, "") for k in ("Metallic", "EdgeMetallic", "EdgeWear")}
    metal.update({"VC": ("VC", ""), "N": ("N", "")})
    g.custom("Metal", WEAPON_METAL, metal, out="1")
    g.out("Colour", "", "MP_BASE_COLOR")
    g.out("Rough", "", "MP_ROUGHNESS")
    g.out("Metal", "", "MP_METALLIC")
    g.out("Specular", "", "MP_SPECULAR")


def _hole(g: Graph) -> None:
    u = g.u
    g.custom(
        "Hole",
        HOLE,
        {"UV": ("UV", ""), "HoleMaskUV": ("HoleMaskUV", ""), "Mask": ("HoleMask", "")},
        out="1",
    )
    g.node(u.MaterialExpressionConstant, "One", r=1.0)
    g.switch("HoleSw", "UseHoleMask", ("Hole", ""), ("One", ""))
    g.out("UseHoleMask", "", "MP_OPACITY_MASK")


def build_surface(g: Graph) -> None:
    u = g.u
    _common_nodes(g)
    g.node(u.MaterialExpressionObjectPositionWS, "ObjPos")
    g.node(u.MaterialExpressionVertexNormalWS, "Nrm")
    g.node(u.MaterialExpressionConstant3Vector, "White3", constant=u.LinearColor(1, 1, 1, 1))
    g.custom(
        "WorldUV",
        "return WorldPos.xy * 0.01 + WorldPos.z * 0.0071;",
        {"WorldPos": ("WorldPos", "")},
        out="2",
    )
    _noise(g, uv_key="WorldUV")
    tri_in = {
        "WorldPos": ("WorldPos", ""),
        "ObjPos": ("ObjPos", ""),
        "Nrm": ("Nrm", ""),
        "Scale": ("TriplanarScale", ""),
        "World": ("TriplanarWorld", ""),
    }
    g.custom("Tri1", TRIPLANAR, {**tri_in, "Tex": ("Set1_BC", "")})
    g.custom("Tri2", TRIPLANAR, {**tri_in, "Tex": ("Set2_BC", "")})
    g.custom("Tri3", TRIPLANAR, {**tri_in, "Tex": ("Set3_BC", "")})
    blend = """
float m2 = saturate(Set2Amount * smoothstep(0.35, 0.65, N.x) * 2.0);
float m3 = saturate(Set3Amount * VC.b);
return lerp(lerp(A, B, m2), C, m3);
"""
    g.custom(
        "TriBlend",
        blend,
        {
            "A": ("Tri1", ""),
            "B": ("Tri2", ""),
            "C": ("Tri3", ""),
            "Set2Amount": ("Set2Amount", ""),
            "Set3Amount": ("Set3Amount", ""),
            "N": ("N", ""),
            "VC": ("VC", ""),
        },
    )
    g.custom(
        "UvTex",
        "return Texture2DSample(Tex, TexSampler, UV).rgb;",
        {"Tex": ("Set1_BC", ""), "UV": ("UV", "")},
    )
    g.custom(
        "UvOrm",
        "return Texture2DSample(Tex, TexSampler, UV).rgb;",
        {"Tex": ("Set1_ORM", ""), "UV": ("UV", "")},
    )
    g.custom(
        "UvNrm",
        "return Texture2DSample(Tex, TexSampler, UV).rgb * 2.0 - 1.0;",
        {"Tex": ("Set1_N", ""), "UV": ("UV", "")},
    )
    g.custom("TriOrm", TRI_ORM, {**tri_in, "Tex": ("Set1_ORM", "")})
    g.custom(
        "TriNrmW",
        TRI_NORMAL,
        {**tri_in, "Tex": ("Set1_N", ""), "Strength": ("NormalStrength", "")},
    )
    g.node(
        u.MaterialExpressionTransform,
        "TriNrm",
        transform_source_type=u.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_WORLD,
        transform_type=u.MaterialVectorCoordTransform.TRANSFORM_TANGENT,
    )
    g.link("TriNrmW", "", "TriNrm", "")
    # UseTriplanar picks the mapping, UseTextureSet picks texture vs flat white.
    g.switch("MapSw", "UseTriplanar", ("TriBlend", ""), ("UvTex", ""))
    g.switch("TexSw", "UseTextureSet", ("UseTriplanar", ""), ("White3", ""))
    g.node(u.MaterialExpressionConstant3Vector, "OrmFlat", constant=u.LinearColor(1, 1, 0, 1))
    g.node(u.MaterialExpressionConstant3Vector, "NrmFlat", constant=u.LinearColor(0, 0, 1, 1))
    orm_map = g.switch_node("UseTriplanar", "OrmMapSw")
    g.link("TriOrm", "", orm_map, "True")
    g.link("UvOrm", "", orm_map, "False")
    orm_sw = g.switch_node("UseTextureSet", "OrmSw")
    g.link("OrmMapSw", "", orm_sw, "True")
    g.link("OrmFlat", "", orm_sw, "False")
    nrm_map = g.switch_node("UseTriplanar", "NrmMapSw")
    g.link("TriNrm", "", nrm_map, "True")
    g.link("UvNrm", "", nrm_map, "False")
    nrm_sw = g.switch_node("UseTextureSet", "NrmSw")
    g.link("NrmMapSw", "", nrm_sw, "True")
    g.link("NrmFlat", "", nrm_sw, "False")
    ins = {k: (k, "") for k in ("BaseTint", "EdgeTint", "EdgeWear", "GrimeAmount")}
    ins.update({"VC": ("VC", ""), "N": ("N", ""), "Tex": ("UseTextureSet", "")})
    g.custom("Colour", SURFACE_COLOUR, ins)
    g.custom(
        "Panel",
        PANEL,
        {
            "WorldPos": ("WorldPos", ""),
            "Nrm": ("Nrm", ""),
            "PanelCm": ("PanelCm", ""),
            "PanelDark": ("PanelDark", ""),
        },
        out="1",
    )
    g.custom(
        "ColourPanel",
        "return C * (1.0 - P);",
        {"C": ("Colour", ""), "P": ("Panel", "")},
    )
    rough = {k: (k, "") for k in ("RoughnessMin", "RoughnessMax", "EdgeWear")}
    rough.update({"VC": ("VC", ""), "N": ("N", ""), "Orm": ("OrmSw", "")})
    g.custom("RoughBase", SURFACE_ROUGH, rough, out="1")
    g.custom(
        "Rough",
        "return saturate(R + P * 0.3);",
        {"R": ("RoughBase", ""), "P": ("Panel", "")},
        out="1",
    )
    g.custom(
        "Metal",
        "return saturate(Metallic * Orm.b + (1.0 - Orm.b) * Metallic);",
        {"Metallic": ("Metallic", ""), "Orm": ("OrmSw", "")},
        out="1",
    )
    g.out("ColourPanel", "", "MP_BASE_COLOR")
    g.out("Rough", "", "MP_ROUGHNESS")
    g.out("Metal", "", "MP_METALLIC")
    g.out("NrmSw", "", "MP_NORMAL")
    _hole(g)


def build_floor(g: Graph) -> None:
    _common_nodes(g)
    g.custom("WorldUV", "return WorldPos.xy * 0.01;", {"WorldPos": ("WorldPos", "")}, out="2")
    _noise(g, uv_key="WorldUV")
    keys = ("BaseTint", "SeamTint", "GridCm", "SeamCm", "LaneCm", "LaneWidthCm", "WearAmount")
    ins = {k: (k, "") for k in keys}
    ins.update({"WorldPos": ("WorldPos", ""), "N": ("N", "")})
    g.custom("Colour", FLOOR_COLOUR, ins)
    rough = {
        k: (k, "") for k in ("RoughnessMin", "RoughnessMax", "LaneCm", "LaneWidthCm", "WearAmount")
    }
    rough.update({"WorldPos": ("WorldPos", ""), "N": ("N", "")})
    g.custom("Rough", FLOOR_ROUGH, rough, out="1")
    g.out("Colour", "", "MP_BASE_COLOR")
    g.out("Rough", "", "MP_ROUGHNESS")
    _hole(g)


def build_emissive(g: Graph) -> None:
    u = g.u
    g.node(u.MaterialExpressionVertexColor, "VC")
    g.node(u.MaterialExpressionConstant, "One", r=1.0)
    g.custom("VcR", "return VC.r;", {"VC": ("VC", "")}, out="1")
    g.switch("Fall", "UseVertexFalloff", ("VcR", ""), ("One", ""))
    g.custom(
        "Emit",
        "return EmissiveColor.rgb * EmissiveNits * saturate(Fade) * Falloff;",
        {
            "EmissiveColor": ("EmissiveColor", ""),
            "EmissiveNits": ("EmissiveNits", ""),
            "Fade": ("Fade", ""),
            "Falloff": ("UseVertexFalloff", ""),
        },
    )
    g.out("Emit", "", "MP_EMISSIVE_COLOR")


def build_glass(g: Graph) -> None:
    u = g.u
    g.node(u.MaterialExpressionVertexColor, "VC")
    g.node(u.MaterialExpressionConstant, "One", r=1.0)
    g.custom("VcR", "return VC.r;", {"VC": ("VC", "")}, out="1")
    g.switch("Fall", "UseVertexFalloff", ("VcR", ""), ("One", ""))
    g.custom(
        "Emit",
        "return EmissiveColor.rgb * EmissiveNits * saturate(Fade) * Falloff;",
        {
            "EmissiveColor": ("EmissiveColor", ""),
            "EmissiveNits": ("EmissiveNits", ""),
            "Fade": ("Fade", ""),
            "Falloff": ("UseVertexFalloff", ""),
        },
    )
    g.custom(
        "Alpha",
        "return saturate(Opacity * saturate(Fade) * Falloff);",
        {"Opacity": ("Opacity", ""), "Fade": ("Fade", ""), "Falloff": ("UseVertexFalloff", "")},
        out="1",
    )
    g.out("BaseTint", "", "MP_BASE_COLOR")
    g.out("Roughness", "", "MP_ROUGHNESS")
    g.out("Emit", "", "MP_EMISSIVE_COLOR")
    g.out("Alpha", "", "MP_OPACITY")


def build_screen(g: Graph) -> None:
    u = g.u
    g.node(u.MaterialExpressionTextureCoordinate, "UV")
    g.custom(
        "Emit",
        "return Texture2DSample(Tex, TexSampler, UV).rgb * ScreenTint.rgb * EmissiveNits;",
        {
            "Tex": ("ScreenTexture", ""),
            "UV": ("UV", ""),
            "ScreenTint": ("ScreenTint", ""),
            "EmissiveNits": ("EmissiveNits", ""),
        },
    )
    g.node(
        u.MaterialExpressionConstant3Vector,
        "Black3",
        constant=u.LinearColor(0.005, 0.005, 0.005, 1),
    )
    g.out("Black3", "", "MP_BASE_COLOR")
    g.out("Roughness", "", "MP_ROUGHNESS")
    g.out("Emit", "", "MP_EMISSIVE_COLOR")


def build_character(g: Graph) -> None:
    u = g.u
    g.node(u.MaterialExpressionTextureCoordinate, "UV")
    g.node(u.MaterialExpressionFresnel, "Fres")
    g.custom(
        "Colour",
        "float3 c = Texture2DSample(Tex, TexSampler, UV).rgb * BaseTint.rgb;\n"
        "return c + Sheen * F * 0.2 * c;",
        {
            "Tex": ("BaseColorMap", ""),
            "UV": ("UV", ""),
            "BaseTint": ("BaseTint", ""),
            "Sheen": ("Sheen", ""),
            "F": ("Fres", ""),
        },
    )
    g.custom(
        "Orm",
        "return Texture2DSample(Tex, TexSampler, UV).rgb;",
        {"Tex": ("ORMMap", ""), "UV": ("UV", "")},
    )
    g.custom(
        "Rough",
        "return saturate(Orm.g * RoughnessScale * Roughness);",
        {
            "Orm": ("Orm", ""),
            "RoughnessScale": ("RoughnessScale", ""),
            "Roughness": ("Roughness", ""),
        },
        out="1",
    )
    g.custom(
        "Metal",
        "return saturate(Orm.b * Metallic);",
        {"Orm": ("Orm", ""), "Metallic": ("Metallic", "")},
        out="1",
    )
    g.custom(
        "Nrm",
        "return Texture2DSample(Tex, TexSampler, UV).rgb;",
        {"Tex": ("NormalMap", ""), "UV": ("UV", "")},
    )
    g.out("Colour", "", "MP_BASE_COLOR")
    g.out("Rough", "", "MP_ROUGHNESS")
    g.out("Metal", "", "MP_METALLIC")
    g.out("Nrm", "", "MP_NORMAL")
    g.out("SubsurfaceAmount", "", "MP_OPACITY")


def build_decal(g: Graph) -> None:
    u = g.u
    g.node(u.MaterialExpressionTextureCoordinate, "UV")
    _noise(g)
    g.custom("Radial", DECAL_MASK, {"UV": ("UV", ""), "N": ("N", "")}, out="1")
    g.custom(
        "Mask",
        "return Texture2DSample(Tex, TexSampler, UV).r;",
        {"Tex": ("DecalMask", ""), "UV": ("UV", "")},
        out="1",
    )
    g.switch("Sw", "UseRadialMask", ("Radial", ""), ("Mask", ""))
    g.custom(
        "Alpha",
        "return saturate(M * Opacity);",
        {"M": ("UseRadialMask", ""), "Opacity": ("Opacity", "")},
        out="1",
    )
    g.out("BaseTint", "", "MP_BASE_COLOR")
    g.out("Roughness", "", "MP_ROUGHNESS")
    g.out("Alpha", "", "MP_OPACITY")


def build_post(g: Graph, ev_min: float, ev_max: float) -> None:
    u = g.u
    ids = u.SceneTextureId
    g.node(u.MaterialExpressionSceneTexture, "Scene", scene_texture_id=ids.PPI_POST_PROCESS_INPUT0)
    g.node(u.MaterialExpressionSceneTexture, "Bloom", scene_texture_id=ids.PPI_POST_PROCESS_INPUT2)
    g.node(u.MaterialExpressionEyeAdaptation, "Exposure")
    g.custom(
        "Grade",
        post_code(ev_min, ev_max),
        {
            "Scene": ("Scene", "Color"),
            "Bloom": ("Bloom", "Color"),
            "Exposure": ("Exposure", ""),
            "BloomScale": ("BloomScale", ""),
            "LutSize": ("LutSize", ""),
            "Lut": ("GradeLut", ""),
        },
    )
    g.out("Grade", "", "MP_EMISSIVE_COLOR")


BUILDERS = {
    "M_Verse_Weapon": build_weapon,
    "M_Verse_Surface": build_surface,
    "M_Verse_Floor": build_floor,
    "M_Verse_Emissive": build_emissive,
    "M_Verse_Glass": build_glass,
    "M_Verse_Screen": build_screen,
    "M_Verse_Character": build_character,
    "M_Verse_Decal": build_decal,
}


def _material_settings(u, name: str, mat) -> None:
    mat.set_editor_property("blend_mode", u.BlendMode.BLEND_OPAQUE)
    if name == "M_Verse_Emissive":
        mat.set_editor_property("shading_model", u.MaterialShadingModel.MSM_UNLIT)
        mat.set_editor_property("two_sided", True)
    if name == "M_Verse_Glass":
        mat.set_editor_property("blend_mode", u.BlendMode.BLEND_TRANSLUCENT)
        mat.set_editor_property("two_sided", True)
    if name == "M_Verse_Screen":
        mat.set_editor_property("shading_model", u.MaterialShadingModel.MSM_DEFAULT_LIT)
    if name == "M_Verse_Character":
        mat.set_editor_property("shading_model", u.MaterialShadingModel.MSM_SUBSURFACE_PROFILE)
    if name == "M_Verse_Decal":
        mat.set_editor_property("material_domain", u.MaterialDomain.MD_DEFERRED_DECAL)
        mat.set_editor_property("blend_mode", u.BlendMode.BLEND_TRANSLUCENT)
    # A packaged or -game build never compiles a usage on demand: without these flags the decks'
    # instanced and Nanite meshes render with the engine's default checker material.
    if name not in ("M_Verse_Decal", POST_TONEMAP.name):
        mat.set_editor_property("used_with_instanced_static_meshes", True)
        mat.set_editor_property("used_with_nanite", True)
    for flag in ("used_with_skeletal_mesh", "used_with_static_lighting"):
        if flag == "used_with_skeletal_mesh" and name in (
            "M_Verse_Weapon",
            "M_Verse_Character",
            "M_Verse_Glass",
            "M_Verse_Emissive",
        ):
            mat.set_editor_property(flag, True)


def _ensure(u, folder: str, name: str):
    path = f"{folder}/{name}"
    lib = u.EditorAssetLibrary
    if lib.does_asset_exist(path):
        mat = lib.load_asset(path)
        u.MaterialEditingLibrary.delete_all_material_expressions(mat)
        return mat
    factory = u.MaterialFactoryNew()
    return u.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, u.Material, factory)


def run(only: list[str], *, save: bool = True) -> dict:
    import sys

    import unreal as u

    from verse_pipeline import REPO_ROOT

    sys.path.insert(0, str(REPO_ROOT / "art" / "verse"))
    from weapons.look import agx

    report = {"built": [], "errors": []}
    wanted = set(only)
    specs = [*MASTERS, POST_TONEMAP]
    for spec in specs:
        if wanted and spec.name not in wanted:
            continue
        mat = _ensure(u, spec.folder, spec.name)
        g = Graph(u, mat)
        for p in spec.params:
            g.param(p)
        if spec is POST_TONEMAP:
            mat.set_editor_property("material_domain", u.MaterialDomain.MD_POST_PROCESS)
            mat.set_editor_property(
                "blendable_location", u.BlendableLocation.BL_REPLACING_TONEMAPPER
            )
            build_post(g, agx.EV_MIN, agx.EV_MAX)
        else:
            _material_settings(u, spec.name, mat)
            BUILDERS[spec.name](g)
        u.MaterialEditingLibrary.layout_material_expressions(mat)
        missing = g.unlinked()
        if missing:
            report.setdefault("relinked", {})[spec.name] = missing
            g.relink(missing)
            for key, names in g.unlinked().items():
                g.errors.append(f"{spec.name}: {key} inputs still unconnected: {names}")
        if spec.name == "M_Verse_Decal":
            mat.set_editor_property("material_domain", u.MaterialDomain.MD_DEFERRED_DECAL)
            mat.set_editor_property("blend_mode", u.BlendMode.BLEND_TRANSLUCENT)
            blend = mat.get_editor_property("blend_mode")
            if blend != u.BlendMode.BLEND_TRANSLUCENT:
                g.errors.append(f"{spec.name}: blend mode is {blend}, not translucent")
        u.MaterialEditingLibrary.recompile_material(mat)
        report["errors"] += g.errors
        if save:
            u.EditorAssetLibrary.save_loaded_asset(mat, only_if_is_dirty=False)
        report["built"].append(spec.name)
    report["ok"] = not report["errors"]
    return report


def parameter_table() -> list[dict]:
    """The documented parameters of every master (pure; used by the docs and tests)."""
    rows = []
    for spec in [*MASTERS, POST_TONEMAP]:
        for p in spec.params:
            rows.append({"master": spec.name, "kind": p.kind, "name": p.name, "doc": p.doc})
    return rows
