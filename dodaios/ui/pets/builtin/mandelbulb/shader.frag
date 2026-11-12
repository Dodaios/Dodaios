// Mandelbulb. Author: mrange, 2023.
// https://www.shadertoy.com/view/mtScRc
// CC0: Inside the mandelbulb II
// License: CC0, as named on the Shadertoy page.
// One pass of the bulb. The Image pass is XorDev's FXAA, whose comment
// names the license Unknown, so it is not included. The published march
// is 60 steps and 5 bounces; a step must stay at or under 32, so this
// keeps the same 2-iteration bulb with a march of 32 and 4 bounces.
// The sky and the ground are not drawn behind the bulb: a miss is clear,
// and a ray that has already hit the glass may still reflect that sky.
// Mandelbulb: EvilRyu, license named Unknown in the source.
// hsv: WTFPL, sam hocevar. Box and ray-plane: MIT, Inigo Quilez.
// sRGB: nmz, license named Unknown. Tone map: Matt Taylor, license named Unknown.
//
// The original camera is 0.6 * vec3(0, 2, 5), distance 3.23, fov tan(tau/6).
// That crops the bulb. Idle keeps the same direction and the same fov at
// distance 5.50, 1.70 times farther, so the whole bulb sits inside the
// disc with air around the longest lobe. Every state uses that distance.
// Scale, bob and shiver move the whole field and stay inside that frame.
//
// States:
// 0 idle: the bulb turns slowly at the pulled-back camera.
// 1 listening: a lean toward the viewer, edges brighter with uLevel.
// 2 thinking: a fast, cool spin, and the interior morphs quicker.
// 3 talking: a size pulse that peaks at idle's size, with uLevel.
// 4 success: the glass flares gold.
// 5 error: red glass, slightly smaller, with a shiver that stays inside.
// 6 sleeping: a slow breath under idle's size, dim and warm.
// 7 working: a brighter, quicker spin.
// 8 searching: a short yaw of the bulb at idle's distance and size.
// 9 held: slower, with a short bob. No flat lens.

const float FOV = 1.732050808;
const float MAX_DIST = 20.0;
const vec4 HSV_K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);

mat3 gRot = mat3(1.0);
float gScale = 1.0;
float gMorph = 0.0;
vec3 gShift = vec3(0.0);
vec3 gSky = vec3(0.0);
vec3 gDiffuse = vec3(0.0);
vec3 gBeer = vec3(0.0);
vec3 gMat = vec3(0.8, 0.5, 1.05);
float gHit = 0.0;

vec3 hsv2rgb(vec3 c) {
    vec3 p = abs(fract(c.xxx + HSV_K.xyz) * 6.0 - HSV_K.www);
    return c.z * mix(HSV_K.xxx, clamp(p - HSV_K.xxx, 0.0, 1.0), c.y);
}

vec3 tone(float h, float s, float v) {
    return hsv2rgb(vec3(fract(h), s, v));
}

vec3 srgb(vec3 t) {
    return mix(1.055 * pow(max(t, 0.0), vec3(1.0 / 2.4)) - 0.055, 12.92 * t, step(t, vec3(0.0031308)));
}

vec3 acesApprox(vec3 v) {
    v = max(v, vec3(0.0));
    v *= 0.6;
    return clamp((v * (2.51 * v + 0.03)) / (v * (2.43 * v + 0.59) + 0.14), 0.0, 1.0);
}

float box(vec2 p, vec2 b) {
    vec2 d = abs(p) - b;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
}

float rayPlane(vec3 ro, vec3 rd, vec4 p) {
    return -(dot(ro, p.xyz) + p.w) / dot(rd, p.xyz);
}

float mandelBulb(vec3 p) {
    vec3 z = p;
    float dr = 1.0;
    float r = 0.0;
    for (int i = 0; i < 2; i++) {
        r = length(z);
        if (r > 2.0) {
            continue;
        }
        float theta = atan(z.y, z.x);
        float phi = asin(clamp(z.z / max(r, 0.0001), -1.0, 1.0)) + gMorph;
        dr = pow(r, 7.0) * dr * 8.0 + 1.0;
        r = pow(r, 8.0);
        theta *= 8.0;
        phi *= 8.0;
        z = r * vec3(cos(theta) * cos(phi), sin(theta) * cos(phi), sin(phi)) + p;
    }
    return 0.5 * log(max(r, 0.0001)) * r / dr;
}

mat3 rotX(float a) {
    float c = cos(a);
    float s = sin(a);
    return mat3(1.0, 0.0, 0.0, 0.0, c, s, 0.0, -s, c);
}

mat3 rotY(float a) {
    float c = cos(a);
    float s = sin(a);
    return mat3(c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c);
}

float df(vec3 p) {
    p -= gShift;
    p *= gRot;
    p /= gScale;
    return mandelBulb(p / 2.0) * 2.0 * gScale;
}

vec3 skyColor(vec3 ro, vec3 rd) {
    vec3 col = clamp(vec3(0.0025 / abs(rd.y)) * gSky, 0.0, 1.0);
    float tp0 = rayPlane(ro, rd, vec4(0.0, 1.0, 0.0, 4.0));
    float tp1 = rayPlane(ro, rd, vec4(0.0, -1.0, 0.0, 6.0));
    if (tp1 > 0.0) {
        vec3 pos = ro + tp1 * rd;
        float db = box(pos.xz, vec2(6.0, 9.0)) - 1.0;
        col += vec3(4.0) * gSky * rd.y * rd.y * smoothstep(0.25, 0.0, db);
        col += vec3(0.8) * gSky * exp(-0.5 * max(db, 0.0));
    }
    if (tp0 > 0.0) {
        vec3 pos = ro + tp0 * rd;
        float ds = length(pos.xz) - 0.5;
        col += vec3(0.25) * gSky * exp(-0.5 * max(ds, 0.0));
    }
    return clamp(col, 0.0, 10.0);
}

vec3 normal(vec3 pos) {
    vec2 e = vec2(0.005, 0.0);
    return normalize(vec3(
        df(pos + e.xyy) - df(pos - e.xyy),
        df(pos + e.yxy) - df(pos - e.yxy),
        df(pos + e.yyx) - df(pos - e.yyx)
    ));
}

float rayMarch(vec3 ro, vec3 rd, float dfactor) {
    float t = 0.0;
    for (int i = 0; i < 32; i++) {
        if (t > MAX_DIST) {
            t = MAX_DIST;
            break;
        }
        float d = dfactor * df(ro + rd * t);
        if (d < 0.0001) {
            break;
        }
        t += d;
    }
    return t;
}

vec3 render(vec3 ro, vec3 rd) {
    vec3 agg = vec3(0.0);
    vec3 ragg = vec3(1.0);
    gHit = 0.0;
    bool inside = df(ro) < 0.0;
    for (int bounce = 0; bounce < 4; bounce++) {
        float remain = max(ragg.x, max(ragg.y, ragg.z));
        if (remain < 0.025) {
            break;
        }
        float dfactor = inside ? -1.0 : 1.0;
        float st = rayMarch(ro, rd, dfactor);
        if (st >= MAX_DIST) {
            if (gHit > 0.5) {
                agg += ragg * skyColor(ro, rd);
            }
            break;
        }
        gHit = 1.0;
        vec3 sp = ro + rd * st;
        vec3 sn = normal(sp) * dfactor;
        float fre = 1.0 + dot(rd, sn);
        fre *= fre;
        fre = mix(0.1, 1.0, fre);
        vec3 ld = normalize(vec3(0.0, 10.0, 0.0) - sp);
        float dif = max(dot(ld, sn), 0.0);
        vec3 ref = reflect(rd, sn);
        float ior = inside ? 1.0 / gMat.z : gMat.z;
        vec3 refr = refract(rd, sn, ior);
        vec3 col = gDiffuse * dif * dif * (1.0 - gMat.x);
        float edge = smoothstep(1.0, 0.9, fre);
        col += skyColor(sp, ref) * gMat.y * fre * edge;
        if (inside) {
            ragg *= exp(-(st + 0.1) * gBeer);
        }
        agg += ragg * col;
        if (dot(refr, refr) == 0.0) {
            rd = ref;
        } else {
            ragg *= gMat.x;
            inside = !inside;
            rd = refr;
        }
        ro = sp + 0.1 * rd;
    }
    return agg;
}

vec3 grade(vec3 col, float st) {
    if (st > 0.5 && st < 1.5) {
        col *= 1.1 + 0.65 * uLevel;
    } else if (st > 1.5 && st < 2.5) {
        col = mix(col, col.bgr, 0.72);
    } else if (st > 2.5 && st < 3.5) {
        float mouth = 0.5 + 0.5 * sin(uTime * 8.0);
        col *= 0.88 + mouth * (0.28 + 0.95 * uLevel);
    } else if (st > 3.5 && st < 4.5) {
        float flash = pow(max(sin(uTime * 4.0), 0.0), 2.0);
        col = mix(col, col * vec3(1.35, 0.82, 0.28), 0.78);
        col += vec3(0.45, 0.28, 0.05) * flash;
    } else if (st > 4.5 && st < 5.5) {
        col = mix(col, vec3(col.r * 1.5, col.g * 0.2, col.b * 0.12), 0.86);
    } else if (st > 5.5 && st < 6.5) {
        col *= vec3(0.62, 0.5, 0.38);
    } else if (st > 6.5 && st < 7.5) {
        col *= 1.28;
    } else if (st > 7.5 && st < 8.5) {
        col = mix(col, col.grb, 0.45);
    } else if (st > 8.5) {
        col *= 0.78;
    }
    return col;
}

void main() {
    float st = floor(uState + 0.5);
    float rotSpeed = 1.0;
    float morph = 0.2;
    float scale = 1.0;
    float hue = 0.0;
    float tilt = 0.0;
    float yaw = 0.0;
    vec3 shift = vec3(0.0);
    if (st > 0.5 && st < 1.5) {
        rotSpeed = 0.45;
        morph = 0.12;
        tilt = 0.42;
        shift.y = -0.06;
    } else if (st > 1.5 && st < 2.5) {
        rotSpeed = 3.4;
        morph = 0.85;
        hue = 0.16;
    } else if (st > 2.5 && st < 3.5) {
        float mouth = 0.5 + 0.5 * sin(uTime * 8.0);
        rotSpeed = 1.35;
        morph = 0.35;
        scale = 0.9 + mouth * 0.1;
        hue = 0.04;
    } else if (st > 3.5 && st < 4.5) {
        rotSpeed = 2.1;
        morph = 0.28;
        hue = 0.08;
    } else if (st > 4.5 && st < 5.5) {
        rotSpeed = 0.2;
        morph = 0.05;
        scale = 0.88;
        hue = -0.04;
        shift = vec3(sin(uTime * 17.0), cos(uTime * 19.0), 0.0) * 0.035;
    } else if (st > 5.5 && st < 6.5) {
        float breath = 0.5 + 0.5 * sin(uTime * 0.42);
        rotSpeed = 0.12;
        morph = 0.04;
        scale = 0.92 + 0.08 * breath;
        hue = 0.03;
    } else if (st > 6.5 && st < 7.5) {
        rotSpeed = 2.6;
        morph = 0.45;
        hue = 0.05;
    } else if (st > 7.5 && st < 8.5) {
        rotSpeed = 1.15;
        morph = 0.3;
        yaw = sin(uTime * 0.7) * 0.55;
        hue = 0.1;
    } else if (st > 8.5) {
        rotSpeed = 0.32;
        morph = 0.08;
        shift.y = sin(uTime * 1.4) * 0.18;
    }

    gScale = scale;
    gMorph = uTime * morph;
    gShift = shift;
    gSky = tone(0.6 + hue, 0.86, 1.0);
    gDiffuse = tone(0.6 + hue, 0.85, 1.0);
    gBeer = -tone(0.05 + hue, 0.95, 2.0);
    float spin = uTime * rotSpeed;
    gRot = rotX(0.2 * spin + tilt) * rotY(0.3 * spin + yaw);

    vec2 p = vLocal.xy * 2.0;
    vec3 eye = vec3(0.0, 1.2, 3.0);
    vec3 ro = 5.5 * normalize(eye);
    vec3 ww = normalize(-ro);
    vec3 uu = normalize(cross(vec3(0.0, 1.0, 0.0), ww));
    vec3 vv = cross(ww, uu);
    vec3 rd = normalize(-p.x * uu + p.y * vv + FOV * ww);

    vec3 col = render(ro, rd);
    col = acesApprox(col);
    col = srgb(col);
    col = grade(col, st);
    col = clamp(col, 0.0, 1.0) * gHit;
    gl_FragColor = vec4(col, gHit);
}
