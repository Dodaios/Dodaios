// A Wedding of Wisps. Author: alro (al-ro), 2023.
// https://www.shadertoy.com/view/cdcSDX
// License: MIT, as named in the shader's Common tab.
// One pass. Buffer A (mouse camera), Buffer B (2048 curl-advected
// positions), Buffer C (300 camera-facing discs) and the Image blue-noise
// dither are not available here. A 32x5 loop draws two wisps per step (320),
// each a small additive spark plus a faint halo in that spark's colour. The
// wide mist is a soft back glow in the same colour, not a filled disc. The
// cosine palette, ACES curve and gamma match the original. Trails stay off,
// as in Buffer C.
//
// States:
// 0 idle: the wedding at rest, many tiny sparks in a slow curl.
// 1 listening: the cloud leans in and brightens with uLevel.
// 2 thinking: two counter-rotating vortices, cooler sparks.
// 3 talking: the cloud blooms outward and pulses with uLevel.
// 4 success: sparks rise and a warm gold flash fills the core.
// 5 error: sparks shatter into red embers.
// 6 sleeping: the cloud sinks, slows and dims to embers.
// 7 working: sparks climb a helix.
// 8 searching: the view sweeps and a beam lights the sparks it crosses.
// 9 held: vLocal is squashed and the cloud flattens.

vec3 acesFilm(vec3 x) {
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

vec3 hash31(float n) {
    vec3 p3 = fract(vec3(n) * vec3(0.1031, 0.11369, 0.13787));
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.xxy + p3.yxx) * p3.zyx);
}

vec3 wispColour(float t) {
    vec3 a = vec3(0.65);
    vec3 b = vec3(0.35);
    vec3 c = vec3(1.0);
    vec3 d = vec3(0.15, 0.5, 0.75);
    return a + b * cos(6.283185 * (c * t + d));
}

vec3 stateTone(float hue, float st) {
    vec3 tone = wispColour(hue);
    if (st > 3.5 && st < 4.5) {
        tone = mix(tone, vec3(1.0, 0.75, 0.3), 0.82);
    } else if (st > 4.5 && st < 5.5) {
        tone = mix(tone, vec3(1.0, 0.08, 0.04), 0.9);
    } else if (st > 5.5 && st < 6.5) {
        tone = mix(tone, vec3(0.3, 0.42, 0.9), 0.7);
    } else if (st > 6.5 && st < 7.5) {
        tone = mix(tone, vec3(1.0, 0.8, 0.45), 0.4);
    }
    return tone;
}

vec3 gVeil = vec3(0.0);
float gVeilW = 0.0;
vec3 gHalo = vec3(0.0);
float gHaloW = 0.0;

vec3 placeWisp(float n, float tt, float warpAmp, float st) {
    vec3 h = hash31(n * 1.17 + 2.0);
    float pick = pow(fract(h.x * 17.13 + h.y * 9.17 + h.z), 1.45);
    vec3 dir = h - 0.5;
    vec3 p = dir * (pick * 1.55 / max(length(dir), 0.001));
    if (st > 6.5 && st < 7.5) {
        float climb = fract(n * 0.009 + uTime * 0.22);
        float ang = n * 0.41 + climb * 6.283185;
        float rad = 0.12 + 0.95 * fract(n * 0.173);
        p = vec3(cos(ang) * rad, (climb - 0.5) * 2.15, sin(ang) * rad);
        return p;
    }
    if (st > 4.5 && st < 5.5) {
        float tick = floor(uTime * 6.0);
        p = (hash31(n * 3.7 + tick * 11.0) - 0.5) * vec3(2.7, 2.3, 2.5);
        return p;
    }
    p.x += warpAmp * sin(p.y * 2.35 + tt + h.x * 5.0);
    p.y += warpAmp * sin(p.z * 2.1 + tt * 0.8 + h.y * 5.0);
    p.z += warpAmp * sin(p.x * 2.45 + tt * 1.05 + h.z * 5.0);
    p.x += warpAmp * 0.4 * sin(p.y * 4.5 - tt * 0.72);
    p.y += warpAmp * 0.4 * sin(p.z * 3.9 - tt * 0.6);
    p.z += warpAmp * 0.4 * sin(p.x * 4.2 - tt * 0.86);
    if (st > 0.5 && st < 1.5) {
        vec3 focus = vec3(0.0, 0.36, 0.48);
        p = mix(p, focus + (h - 0.5) * 0.22, 0.16 + 0.48 * uLevel);
    } else if (st > 1.5 && st < 2.5) {
        float side = mod(n, 2.0) * 2.0 - 1.0;
        float cs = cos(uTime * 2.1 * side);
        float sn = sin(uTime * 2.1 * side);
        p.x -= side * 0.36;
        float nx = cs * p.x - sn * p.z;
        float nz = sn * p.x + cs * p.z;
        p.x = nx + side * 0.36;
        p.z = nz;
        p *= 0.8;
    } else if (st > 2.5 && st < 3.5) {
        float mouth = 0.5 + 0.5 * sin(uTime * 8.0);
        p *= 1.0 + mouth * (0.1 + 0.62 * uLevel);
    } else if (st > 3.5 && st < 4.5) {
        p.y += 0.48 + 0.1 * sin(uTime * 2.4 + n);
        p *= 0.88;
    } else if (st > 5.5 && st < 6.5) {
        p.y -= 0.7 + 0.04 * sin(uTime * 0.35 + n);
        p *= 0.78;
    } else if (st > 8.5) {
        p.x *= 1.16;
        p.y *= 0.4;
    }
    return p;
}

vec3 shadeWisp(float n, vec2 uv, vec3 ro, vec3 ww, vec3 uu, vec3 vv, float tt, float warpAmp, float st, float gain) {
    vec3 p = placeWisp(n, tt, warpAmp, st);
    float keep = 1.0 - smoothstep(1.15, 1.8, length(p));
    vec3 rel = p - ro;
    float z = dot(rel, ww);
    vec2 plane = vec2(dot(rel, uu), dot(rel, vv));
    vec2 screen = plane / max(z, 0.25) / 1.1547 + 0.5;
    float alive = step(0.2, z) * keep;
    if (st > 4.5 && st < 5.5) {
        alive *= step(0.2, hash31(n + 19.0).z);
    }
    vec2 delta = screen - uv;
    float d2 = dot(delta, delta);
    float flickSpeed = 13.0;
    if (st > 5.5 && st < 6.5) {
        flickSpeed = 1.1;
    }
    float flick = 0.5 + 0.5 * sin(uTime * flickSpeed + n * 0.17);
    float near = 1.0 - smoothstep(0.0, 1.2, length(p));
    float coreW = mix(0.0000065, 0.000015, flick);
    if (st > 3.5 && st < 4.5) {
        coreW *= 1.7;
    }
    if (st > 5.5 && st < 6.5) {
        coreW *= 0.45;
    }
    float core = exp(-d2 / coreW);
    float halo = 0.05 * exp(-d2 / 0.00015);
    float mistAmp = 0.0075;
    if (st > 4.5 && st < 5.5) {
        mistAmp = 0.0016;
    }
    float amp = mix(0.45, 1.45, near);
    float body = core * (0.4 + 0.6 * flick) * amp;
    float fringe = halo * (0.65 + 0.35 * flick) * amp;
    float veil = exp(-d2 / 0.0015) * (mistAmp / 0.0075) * amp;
    if (st > 7.5 && st < 8.5) {
        float beamX = 0.5 + 0.34 * sin(uTime * 0.85);
        float onBeam = 1.0 - smoothstep(0.0, 0.06, abs(screen.x - beamX));
        float lit = 0.4 + 1.55 * onBeam;
        body *= lit;
        fringe *= lit;
        veil *= lit;
    }
    float hue = n / 1088.0 + 0.15 * uTime;
    if (st > 1.5 && st < 2.5) {
        hue += 0.38;
    }
    vec3 tone = stateTone(hue, st);
    if (st > 5.5 && st < 6.5) {
        body *= 0.35;
        fringe *= 0.35;
        veil *= 0.35;
    }
    float live = gain * alive;
    gVeil += tone * veil * live;
    gVeilW += veil * live;
    // Kept out of `col`. Tone mapping crushed this fringe, and the cover
    // alpha then stored it as black RGB.
    gHalo += tone * fringe * live;
    gHaloW += fringe * live;
    return tone * body * live;
}

void main() {
    gVeil = vec3(0.0);
    gVeilW = 0.0;
    gHalo = vec3(0.0);
    gHaloW = 0.0;
    float st = floor(uState + 0.5);
    vec2 face = vLocal.xy;
    if (st > 8.5) {
        face.x *= 0.76;
        face.y *= 1.52;
    }
    vec2 uv = face + 0.5;

    float speed = 0.72;
    float warpAmp = 0.34;
    float gain = 1.55;
    if (st > 0.5 && st < 1.5) {
        speed = 0.8;
        gain = 1.4 + 1.05 * uLevel;
    } else if (st > 1.5 && st < 2.5) {
        speed = 1.45;
        warpAmp = 0.5;
        gain = 1.65;
    } else if (st > 2.5 && st < 3.5) {
        speed = 0.9;
        warpAmp = 0.3;
        gain = 1.35 + 1.25 * uLevel;
    } else if (st > 3.5 && st < 4.5) {
        speed = 0.85;
        warpAmp = 0.26;
        gain = 2.05;
    } else if (st > 4.5 && st < 5.5) {
        speed = 0.2;
        gain = 1.45;
    } else if (st > 5.5 && st < 6.5) {
        speed = 0.06;
        warpAmp = 0.1;
        gain = 0.85;
    } else if (st > 6.5 && st < 7.5) {
        speed = 0.9;
        gain = 1.6;
    } else if (st > 7.5 && st < 8.5) {
        speed = 0.7;
        warpAmp = 0.3;
    } else if (st > 8.5) {
        speed = 0.28;
        warpAmp = 0.16;
    }

    float polarX = 2.9;
    float polarY = 1.7;
    if (st > 7.5 && st < 8.5) {
        polarX += sin(uTime * 0.7) * 0.9;
    }
    float sy = sin(polarY);
    float cy = cos(polarY);
    vec3 ro = 4.05 * normalize(vec3(-cos(polarX) * sy, cy, -sin(polarX) * sy));
    vec3 ww = normalize(-ro);
    vec3 uu = normalize(cross(vec3(0.0, 1.0, 0.0), ww));
    vec3 vv = cross(ww, uu);
    float tt = uTime * speed;

    vec3 col = vec3(0.0);
    for (int i = 0; i < 32; i++) {
        for (int k = 0; k < 5; k++) {
            float n = float(i) * 5.0 + float(k);
            col += shadeWisp(n, uv, ro, ww, uu, vv, tt, warpAmp, st, gain);
            col += shadeWisp(n + 160.0, uv, ro, ww, uu, vv, tt, warpAmp, st, gain);
        }
    }

    if (st > 3.5 && st < 4.5) {
        float flash = pow(max(sin(uTime * 4.0), 0.0), 2.0);
        float rad = length(uv - vec2(0.5, 0.46));
        col += vec3(1.0, 0.64, 0.22) * flash * (1.0 - smoothstep(0.0, 0.34, rad)) * 0.55;
    }
    if (st > 7.5 && st < 8.5) {
        float beamX = 0.5 + 0.34 * sin(uTime * 0.85);
        float beam = 1.0 - smoothstep(0.0, 0.018, abs(uv.x - beamX));
        col += vec3(0.45, 0.8, 1.0) * beam * 0.28;
    }

    col = acesFilm(max(col, 0.0));
    col = pow(col, vec3(0.454545));
    // The desktop FBO is read back as premultiplied, then stored straight.
    // The hot core is the tone-mapped spark. `cover` (`peak * 8`) is already
    // opaque while that core's shoulder is still dark, which drew a black
    // ring inside the coloured halo. The shoulder takes this spark's colour
    // (the same tint as the halo). The wide mist stays below a fill.
    float peak = max(col.r, max(col.g, col.b));
    float cover = clamp(peak * 8.0, 0.0, 1.0);
    vec3 tint = gVeil / max(gVeilW, 0.0001);
    tint = pow(clamp(tint, 0.0, 1.0), vec3(0.454545));
    float glowA = 0.72 * gVeilW / (gVeilW + 36.0);
    vec3 glow = tint * glowA;
    vec3 haloTint = gHalo / max(gHaloW, 0.0001);
    haloTint = pow(clamp(haloTint, 0.0, 1.0), vec3(0.454545));
    // One spark's fringe weight peaks near 0.07. This stays under 0.62.
    float haloA = 0.62 * gHaloW / (gHaloW + 0.04);
    vec3 haloGlow = haloTint * haloA;
    vec3 spark = max(clamp(col, 0.0, 1.0), haloTint) * cover;
    float rest = 1.0 - cover;
    vec3 behind = haloGlow + glow * (1.0 - haloA);
    float behindA = haloA + glowA * (1.0 - haloA);
    gl_FragColor = vec4(spark + behind * rest, cover + behindA * rest);
}
