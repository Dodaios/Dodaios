"""Deck-local materials of the Operations deck (registered into lib.materials).

Only what the shared library does not have: warm mess light, bunk reading
lamps, fabric, table tops, display glass and the rank-tile enamels. Names are
prefixed ``M_Ops_`` so they never collide with the kit library.
"""

from __future__ import annotations

from lib import materials as lm
from lib.materials import (
    _emitter,
    _Graph,
    _lamp,
    _painted_metal,
    _plate_fields,
    _scratches,
    _set_emission_sampling,
    material,
)


@material("M_Ops_Light_Warm", viewport=(1.0, 0.9, 0.75))
def _light_warm(g: _Graph) -> None:
    """Mess-hall ceiling diffuser, 3 800 K, a little dimmer than duty lighting."""
    _emitter(g, 9.0, kelvin=3800.0)


@material("M_Ops_Light_Dim", viewport=(0.9, 0.9, 0.95))
def _light_dim(g: _Graph) -> None:
    """Night-cycle diffuser for quarters and stores, 5 200 K."""
    _emitter(g, 3.0, kelvin=5200.0)


@material("M_Ops_Light_Reading", viewport=(1.0, 0.8, 0.55))
def _light_reading(g: _Graph) -> None:
    """Bunk reading lamp lens, 4 000 K."""
    _emitter(g, 14.0, kelvin=4000.0, falloff=0.1)


@material("M_Ops_Light_Hatch", viewport=(1.0, 0.85, 0.65))
def _light_hatch(g: _Graph) -> None:
    """Back-lit galley wall behind the serving line, 3 400 K: dim enough to
    stay a warm gradient behind the shelving, never a clipped slab."""
    _emitter(g, 2.4, kelvin=3400.0, falloff=0.08)


@material("M_Ops_Light_Ring", viewport=(0.95, 0.97, 1.0))
def _light_ring(g: _Graph) -> None:
    """Ready-room ring diffuser, 6 000 K, dimmer than duty panels so its
    mirror in the deck stays a soft grey ring, not a white one."""
    _emitter(g, 6.5, kelvin=6000.0)


@material("M_Fabric_Linen", viewport=(0.4, 0.41, 0.43))
def _linen_cool(g: _Graph) -> None:
    """Deck override of the kit's pillow/sheet role: cool pale grey cotton
    (the kit's stand-in reads beige under the reading lamps)."""
    _wool(g, (0.34, 0.36, 0.39), sheen=0.3)


@material("M_Ops_Light_Med", viewport=(0.95, 0.97, 1.0))
def _light_med(g: _Graph) -> None:
    """Medical bay diffuser, 6 800 K, clinical."""
    _emitter(g, 18.0, kelvin=6800.0)


@material("M_Ops_Fabric_Blanket", viewport=(0.07, 0.075, 0.07))
def _blanket(g: _Graph) -> None:
    """Issued wool blanket, dark olive-grey, matte with a soft weave."""
    co = g.coord()
    weave = g.noise(co, 420.0, detail=1)
    folds = g.noise(co, 3.0, detail=3, rough=0.5)
    base = g.mix_color(g.add(0.8, g.mul(folds, 0.35)), (0, 0, 0), (0.06, 0.064, 0.058))
    bsdf = g.principled(
        Base_Color=base,
        Roughness=0.92,
        Sheen_Weight=0.35,
        Sheen_Roughness=0.4,
        Normal=g.bump(g.add(g.mul(weave, 0.2), g.mul(folds, 0.6)), 0.25, 0.004),
    )
    g.output(bsdf.outputs[0])


@material("M_Ops_Fabric_Sheet", viewport=(0.45, 0.46, 0.47))
def _sheet(g: _Graph) -> None:
    """Pale grey bed linen and pillows."""
    co = g.coord()
    folds = g.noise(co, 4.0, detail=3)
    bsdf = g.principled(
        Base_Color=g.mix_color(g.add(0.85, g.mul(folds, 0.2)), (0, 0, 0), (0.42, 0.43, 0.44)),
        Roughness=0.85,
        Sheen_Weight=0.25,
        Normal=g.bump(folds, 0.3, 0.004),
    )
    g.output(bsdf.outputs[0])


@material("M_Ops_Table_Top", viewport=(0.03, 0.03, 0.032))
def _table_top(g: _Graph) -> None:
    """Black lacquered table top: coaster rings and wipe marks in the gloss."""
    co = g.coord()
    wipe = g.remap(g.noise(co, 1.4, detail=5, rough=0.65), 0.35, 0.7, smooth=True)
    marks = g.remap(g.noise(co, 9.0, detail=3), 0.55, 0.7, smooth=True)
    bsdf = g.principled(
        Base_Color=(0.012, 0.012, 0.013),
        Roughness=g.add(0.12, g.mul(wipe, 0.12)),
        Coat_Weight=1.0,
        Coat_Roughness=g.add(0.02, g.mul(wipe, 0.08), g.mul(marks, 0.05)),
    )
    g.output(bsdf.outputs[0])


@material("M_Ops_Glass_Case", viewport=(0.7, 0.75, 0.8))
def _glass_case(g: _Graph) -> None:
    """Display-case glass: clear with fingerprints."""
    co = g.coord()
    smudge = g.remap(g.noise(co, 6.0, detail=4), 0.5, 0.75, smooth=True)
    bsdf = g.principled(
        Base_Color=(0.9, 0.93, 0.95),
        Roughness=g.add(0.01, g.mul(smudge, 0.12)),
        Transmission_Weight=1.0,
        IOR=1.5,
    )
    g.output(bsdf.outputs[0])


def _enamel(g: _Graph, colour) -> None:
    _painted_metal(g, colour, rough=(0.18, 0.28), chip=0.1, grime=0.2, sheen_coat=0.6)


@material("M_Ops_Enamel_Steel", viewport=(0.5, 0.5, 0.52))
def _en_steel(g: _Graph) -> None:
    _enamel(g, (0.38, 0.39, 0.41))


@material("M_Ops_Enamel_Blue", viewport=(0.05, 0.12, 0.35))
def _en_blue(g: _Graph) -> None:
    _enamel(g, (0.025, 0.06, 0.2))


@material("M_Ops_Enamel_Red", viewport=(0.35, 0.03, 0.02))
def _en_red(g: _Graph) -> None:
    _enamel(g, (0.25, 0.018, 0.012))


@material("M_Ops_Enamel_Gold", viewport=(0.6, 0.45, 0.15))
def _en_gold(g: _Graph) -> None:
    bsdf = g.principled(Base_Color=(0.75, 0.55, 0.22), Metallic=1.0, Roughness=0.22)
    g.output(bsdf.outputs[0])


@material("M_Ops_Uniform_Olive", viewport=(0.12, 0.12, 0.1))
def _uni_olive(g: _Graph) -> None:
    _cloth(g, (0.075, 0.075, 0.062))


@material("M_Ops_Uniform_Black", viewport=(0.02, 0.02, 0.02))
def _uni_black(g: _Graph) -> None:
    _cloth(g, (0.012, 0.012, 0.013))


@material("M_Ops_Uniform_White", viewport=(0.6, 0.6, 0.6))
def _uni_white(g: _Graph) -> None:
    _cloth(g, (0.55, 0.55, 0.54))


@material("M_Ops_Uniform_Charcoal", viewport=(0.05, 0.05, 0.05))
def _uni_charcoal(g: _Graph) -> None:
    _cloth(g, (0.035, 0.036, 0.038))


def _cloth(g: _Graph, colour) -> None:
    co = g.coord()
    folds = g.noise(co, 5.0, detail=3)
    bsdf = g.principled(
        Base_Color=g.mix_color(g.add(0.8, g.mul(folds, 0.3)), (0, 0, 0), colour),
        Roughness=0.8,
        Sheen_Weight=0.3,
        Normal=g.bump(folds, 0.3, 0.003),
    )
    g.output(bsdf.outputs[0])


@material("M_Ops_Lamp_Warm", viewport=(1.0, 0.7, 0.4))
def _lamp_warm(g: _Graph) -> None:
    _lamp(g, (1.0, 0.62, 0.3), 6.0)


def ensure() -> None:
    """Import side effect registers the materials; nothing else to do."""
    assert "M_Ops_Light_Warm" in lm.names()


@material("M_Ops_Floor_WhiteTile", viewport=(0.6, 0.62, 0.63))
def _floor_white_tile(g: _Graph) -> None:
    """Clinical white satin tile 0.6 x 0.6 m with grey seams (simulator, med bay)."""
    pos, seam, bevel_band, _bolt, rnd = _plate_fields(g, 0.6, 0.6)
    smudge = g.remap(g.noise(pos, 0.5, detail=5, rough=0.6), 0.35, 0.75, smooth=True)
    scuff = g.remap(g.noise(pos, 7.0, detail=6, rough=0.7), 0.6, 0.75, smooth=True)
    base = g.mix_color(g.add(0.93, g.mul(rnd, 0.07)), (0, 0, 0), (0.58, 0.6, 0.61))
    base = g.mix_color(g.mul(smudge, 0.12), base, (0.4, 0.41, 0.42))
    base = g.mix_color(seam, base, (0.16, 0.165, 0.17))
    bsdf = g.principled(
        Base_Color=base,
        Roughness=g.add(0.2, g.mul(smudge, 0.12), g.mul(scuff, 0.1), g.mul(seam, 0.4)),
        Normal=g.bump(g.mul(bevel_band, -1.0), 0.3, 0.002),
        Coat_Weight=0.3,
        Coat_Roughness=0.1,
    )
    g.output(bsdf.outputs[0])


@material("M_Ops_Table_Grey", viewport=(0.55, 0.56, 0.55))
def _table_grey(g: _Graph) -> None:
    """Light grey mess table laminate: satin, wiped, a few cup rings."""
    co = g.coord()
    wipe = g.remap(g.noise(co, 1.6, detail=5, rough=0.65), 0.35, 0.7, smooth=True)
    rings = g.remap(g.noise(co, 11.0, detail=2), 0.62, 0.7, smooth=True)
    base = g.mix_color(g.mul(rings, 0.25), (0.5, 0.515, 0.5), (0.36, 0.37, 0.36))
    bsdf = g.principled(
        Base_Color=base,
        Roughness=g.add(0.32, g.mul(wipe, 0.14)),
        Coat_Weight=0.4,
        Coat_Roughness=g.add(0.08, g.mul(wipe, 0.1)),
    )
    g.output(bsdf.outputs[0])


@material("M_Ops_Wall_White", viewport=(0.62, 0.63, 0.64))
def _wall_white(g: _Graph) -> None:
    """Clinical white panel paint (simulator, med bay)."""
    _painted_metal(g, (0.62, 0.635, 0.645), rough=(0.26, 0.38), chip=0.08, grime=0.35, scratch=0.3)


@material("M_Ops_Light_Maint", viewport=(0.9, 0.85, 0.75))
def _light_maint(g: _Graph) -> None:
    """Caged maintenance lamp in hull structure, 5 000 K (reads white, not amber)."""
    _emitter(g, 9.0, kelvin=5000.0, sampling="AUTO")


@material("M_Ops_Light_Pip", viewport=(1.0, 1.0, 1.0))
def _light_pip(g: _Graph) -> None:
    """Small white marker pip (records runner, door edges)."""
    _lamp(g, (0.95, 0.97, 1.0), 9.0)


@material("M_Ops_Light_SimBar", viewport=(0.92, 0.95, 1.0))
def _light_sim(g: _Graph) -> None:
    """Simulator pod interior wash, blue-white 8 000 K."""
    _emitter(g, 6.0, kelvin=8000.0, falloff=0.1)


@material("M_Ops_Light_Corridor", viewport=(1.0, 1.0, 1.0))
def _light_corridor(g: _Graph) -> None:
    """Corridor ceiling diffuser, 6 000 K, a step below duty panels so the
    mirrored rhythm in the floor stays below clipping."""
    _emitter(g, 4.0, kelvin=6000.0)


@material("M_Ops_Floor_SatinGrey", viewport=(0.16, 0.165, 0.17))
def _floor_satin_grey(g: _Graph) -> None:
    """Working-deck plate: mid grey satin, 1.2 m plates, boot-worn lanes. No
    lacquer, so overhead fixtures mirror as soft pools, not crisp panels."""
    pos, seam, bevel_band, bolt, rnd = _plate_fields(g, 1.2, 1.2)
    smudge = g.remap(g.noise(pos, 0.4, detail=5, rough=0.62), 0.3, 0.75, smooth=True)
    scuff = g.remap(g.noise(pos, 6.0, detail=6, rough=0.7), 0.55, 0.75, smooth=True)
    base = g.mix_color(g.add(0.9, g.mul(rnd, 0.16)), (0, 0, 0), (0.105, 0.108, 0.112))
    base = g.mix_color(g.mul(smudge, 0.35), base, (0.07, 0.068, 0.066))
    base = g.mix_color(g.mul(scuff, 0.4), base, (0.15, 0.152, 0.155))
    base = g.mix_color(seam, base, (0.02, 0.02, 0.021))
    bsdf = g.principled(
        Base_Color=base,
        Roughness=g.add(0.34, g.mul(smudge, 0.14), g.mul(scuff, -0.08), g.mul(seam, 0.3)),
        Metallic=g.mul(bolt, 1.0),
        Normal=g.bump(g.add(g.mul(bevel_band, -1.0), g.mul(bolt, 0.3)), 0.3, 0.002),
    )
    g.output(bsdf.outputs[0])


@material("M_Ops_Light_Night", viewport=(0.9, 0.92, 1.0))
def _light_night(g: _Graph) -> None:
    """Quarters night strip, 5 600 K."""
    _emitter(g, 7.0, kelvin=5600.0)


@material("M_Ops_Light_MessCool", viewport=(0.95, 0.95, 1.0))
def _light_mess_cool(g: _Graph) -> None:
    """Mess-hall ceiling panel over each table, 6 000 K: small and bright, so
    its mirror in the black deck is a crisp dash below clipping while the
    room's light comes from the pools (the warmth comes from the sconces and
    the galley hatch)."""
    _emitter(g, 13.0, kelvin=6000.0)


@material("M_Ops_Starfield", viewport=(0.0, 0.0, 0.01))
def _starfield_slit(g: _Graph) -> None:
    """Star field behind the mess viewport slit. The slit is only ~1 m tall in
    the plate, so three layers: fine dust, a field of small stars, and a sparse
    set of bright ones (3-4 px at 96 px/m) that still read as points when the
    plate is seen whole, over a very faint cool drift so the band reads as
    deep space rather than a black slab."""
    co = g.coord(per_instance=False)
    vor = g.new("ShaderNodeTexVoronoi", inputs={"Scale": 6.0, "Randomness": 1.0})
    g.set(vor.inputs["Vector"], co)
    star = g.remap(vor.outputs["Distance"], 0.085, 0.0, smooth=True)
    mag = g.math("POWER", g.white(vor.outputs["Position"]), 3.0)
    vor2 = g.new("ShaderNodeTexVoronoi", inputs={"Scale": 19.0, "Randomness": 1.0})
    g.set(vor2.inputs["Vector"], co)
    dust = g.mul(g.remap(vor2.outputs["Distance"], 0.07, 0.0, smooth=True), 0.5)
    vor3 = g.new("ShaderNodeTexVoronoi", inputs={"Scale": 1.7, "Randomness": 1.0})
    g.set(vor3.inputs["Vector"], co)
    pick = g.remap(g.white(vor3.outputs["Position"]), 0.45, 0.5)
    core = g.remap(vor3.outputs["Distance"], 0.06, 0.0, smooth=True)
    halo = g.math("POWER", g.remap(vor3.outputs["Distance"], 0.16, 0.0), 3.0)
    bright = g.mul(pick, g.add(g.mul(core, 22.0), g.mul(halo, 0.9)))
    drift = g.mul(g.remap(g.noise(co, 0.55, detail=4, rough=0.55), 0.5, 0.82, smooth=True), 0.012)
    strength = g.add(g.mul(star, g.add(1.0, g.mul(mag, 9.0))), dust, bright, drift, 0.003)
    em = g.new("ShaderNodeEmission")
    g.set(em.inputs["Color"], (0.84, 0.9, 1.0))
    g.set(em.inputs["Strength"], strength)
    g.output(em.outputs[0])
    _set_emission_sampling(g.mat, "NONE")


@material("M_Ops_Floor_Satin", viewport=(0.04, 0.04, 0.045))
def _floor_satin(g: _Graph) -> None:
    """Working-deck graphite plate under a thin clear coat (mess, quarters).
    The ceiling rows mirror as soft-edged bars cut by the plate seams, about a
    third of their brightness; wear is fine boot scuffing and wipe streaks,
    never broad cloudy patches (those read as haze from above)."""
    pos, seam, bevel_band, bolt, rnd = _plate_fields(g)
    smudge = g.remap(g.noise(pos, 1.4, detail=5, rough=0.6), 0.45, 0.8, smooth=True)
    wipe_co = g.vmath("MULTIPLY", pos, (1.0, 6.0, 1.0))
    wipe = g.remap(g.noise(wipe_co, 2.0, detail=4, rough=0.5), 0.52, 0.76)
    scuff = _scratches(g, pos, contrast=(0.5, 0.8))
    base = g.mix_color(g.add(0.84, g.mul(rnd, 0.32)), (0, 0, 0), (0.052, 0.054, 0.058))
    base = g.mix_color(g.mul(scuff, 0.45), base, (0.09, 0.09, 0.092))
    base = g.mix_color(seam, base, (0.004, 0.004, 0.004))
    rough = g.add(0.28, g.mul(smudge, 0.1), g.mul(scuff, 0.12), g.mul(seam, 0.4))
    normal = g.bump(g.add(g.mul(bevel_band, -1.0), g.mul(bolt, 0.35)), 0.35, 0.003)
    coat = g.mul(g.lerp(seam, 1.0, 0.0), g.lerp(smudge, 0.55, 0.36))
    coat_rough = g.add(
        0.05, g.mul(rnd, 0.02), g.mul(smudge, 0.05), g.mul(wipe, 0.05), g.mul(scuff, 0.06)
    )
    bsdf = g.principled(
        Base_Color=base,
        Roughness=rough,
        Metallic=g.mul(bolt, 1.0),
        Normal=normal,
        Coat_Weight=coat,
        Coat_Roughness=coat_rough,
    )
    g.output(bsdf.outputs[0])


def _wool(g: _Graph, colour, sheen: float = 0.35) -> None:
    """Matte issued wool: soft weave bump, broad fold shading."""
    co = g.coord()
    weave = g.noise(co, 420.0, detail=1)
    folds = g.noise(co, 3.0, detail=3, rough=0.5)
    base = g.mix_color(g.add(0.82, g.mul(folds, 0.3)), (0, 0, 0), colour)
    bsdf = g.principled(
        Base_Color=base,
        Roughness=0.9,
        Sheen_Weight=sheen,
        Sheen_Roughness=0.4,
        Normal=g.bump(g.add(g.mul(weave, 0.2), g.mul(folds, 0.6)), 0.25, 0.004),
    )
    g.output(bsdf.outputs[0])


# Deck-level overrides of two kit fabric roles. The command kit resolves its
# materials through lib.materials first, so registering the role names here
# recolours them on this deck only (the only deck that uses either piece).


@material("M_Fabric_BlanketSlate", viewport=(0.07, 0.078, 0.09))
def _blanket_slate(g: _Graph) -> None:
    """Bunk blankets: cool slate wool, light enough to read as cloth over the
    dark bunk frames (the kit's stand-in is near black)."""
    _wool(g, (0.1, 0.112, 0.132))


@material("M_Fabric_UniformOlive", viewport=(0.1, 0.11, 0.12))
def _issue_tunic_slate(g: _Graph) -> None:
    """Folded issue tunics on the quartermaster's counter: cool slate grey,
    never olive."""
    _wool(g, (0.16, 0.172, 0.192), sheen=0.3)


@material("M_Ops_Glass_Slit", viewport=(0.6, 0.65, 0.7))
def _glass_slit(g: _Graph) -> None:
    """Mess viewport slit: anti-reflection coated glazing. At the camera's
    60 degree incidence plain glass mirrors the lit mess floor as a grey veil
    over the stars; the coating keeps the reflection to a faint sheen."""
    fres = g.new("ShaderNodeFresnel", inputs={"IOR": 1.1}).outputs[0]
    co = g.coord()
    smear = g.remap(g.noise(co, 1.2, detail=4), 0.5, 0.8, smooth=True)
    glossy = g.new("ShaderNodeBsdfGlossy", inputs={"Color": (1, 1, 1)})
    g.set(glossy.inputs["Roughness"], g.add(0.01, g.mul(smear, 0.03)))
    clear = g.new("ShaderNodeBsdfTransparent", inputs={"Color": (0.9, 0.93, 0.96)})
    mix = g.new("ShaderNodeMixShader")
    g.set(mix.inputs[0], g.add(fres, g.mul(smear, 0.006)))
    g.set(mix.inputs[1], clear.outputs[0])
    g.set(mix.inputs[2], glossy.outputs[0])
    g.output(mix.outputs[0])


@material("M_Ops_Floor_WashTile", viewport=(0.2, 0.205, 0.21))
def _floor_wash_tile(g: _Graph) -> None:
    """Washroom tile, 0.3 m, mid grey satin with dark grout: a zone change
    from the deck plate, never a bright slab."""
    pos, seam, bevel_band, _bolt, rnd = _plate_fields(g, 0.3, 0.3)
    smudge = g.remap(g.noise(pos, 1.5, detail=5, rough=0.6), 0.45, 0.8, smooth=True)
    base = g.mix_color(g.add(0.9, g.mul(rnd, 0.12)), (0, 0, 0), (0.15, 0.155, 0.162))
    base = g.mix_color(g.mul(smudge, 0.25), base, (0.1, 0.1, 0.104))
    grout = g.remap(bevel_band, 0.0, 0.6)
    base = g.mix_color(grout, base, (0.03, 0.03, 0.032))
    bsdf = g.principled(
        Base_Color=base,
        Roughness=g.add(0.22, g.mul(smudge, 0.12), g.mul(grout, 0.5)),
        Normal=g.bump(g.mul(bevel_band, -1.0), 0.3, 0.002),
        Coat_Weight=g.lerp(grout, 0.35, 0.0),
        Coat_Roughness=0.08,
    )
    g.output(bsdf.outputs[0])
