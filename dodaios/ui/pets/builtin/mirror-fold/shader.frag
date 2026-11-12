// Mirror Fold. Author: mrange, 2024.
// https://www.shadertoy.com/view/XfyXRV
// CC0: Let's self reflect
// License: CC0, as named on the Shadertoy page.
// One pass of the kaleidoscopic solid. The host has no room for the original
// 90-step march or its 6-bounce inner shell, so this keeps the same fold,
// edge glow and inner sphere with shorter loops: 3 folds, an outer march of
// 28, 4 inner bounces and an inner march of 22. The sky, ground and beer
// tint are not drawn: a miss is clear, and only the solid keeps colour.
// The solid is knighty's (https://www.shadertoy.com/view/MsKGzw).
// Rotation: MIT, Inigo Quilez. hsv: WTFPL, sam hocevar. Tone map: Matt Taylor.
//
// States:
// 0 idle: the mirrored solid turns slowly.
// 1 listening: a slight lean, and the edges brighten with uLevel.
// 2 thinking: a fast, cool spin.
// 3 talking: the solid pulses in size with uLevel.
// 4 success: the edges flare gold.
// 5 error: red edges, smaller than idle, with a shiver that stays inside.
// 6 sleeping: a slow breath, quieter and warm, resting in the frame.
// 7 working: a brighter, quicker spin.
// 8 searching: a short arc at idle's distance. The solid stays idle-sized.
// 9 held: slower, with a short bob. No flat lens.

const float PI = 3.141592654;
const float REFR = 0.9;
const float RREFR = 1.111111111;
const vec3 POLY_NC = vec3(-0.5, -0.5, 0.707106781);
const vec3 POLY_PAB = vec3(0.0, 0.0, 1.0);
const vec3 POLY_PBC = vec3(0.816496581, 0.0, 0.577350269);
const vec3 POLY_PCA = vec3(0.0, 0.816496581, 0.577350269);
const vec3 POLY_P = vec3(0.184114924, 0.368229847, 0.911322377);
const vec4 HSV_K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);

mat3 gRot = mat3(1.0);
vec2 gGd = vec2(1.0);
float gZoom = 2.0;
vec3 gGlow0 = vec3(0.0);
vec3 gGlow1 = vec3(0.0);
vec3 gBeer = vec3(0.0);
vec3 gSun = vec3(0.0);
vec3 gBottom = vec3(0.0);
vec3 gTop = vec3(0.0);
float gHit = 0.0;
float gEdge = 1.0;

vec3 hsv2rgb(vec3 c) {
    vec3 p = abs(fract(c.xxx + HSV_K.xyz) * 6.0 - HSV_K.www);
    return c.z * mix(HSV_K.xxx, clamp(p - HSV_K.xxx, 0.0, 1.0), c.y);
}

vec3 tone(float h, float s, float v) {
    return hsv2rgb(vec3(fract(h), s, v));
}

mat3 orient(vec3 d, vec3 z) {
    vec3 v = cross(z, d);
    float c = dot(z, d);
    float k = 1.0 / max(1.0 + c, 0.0001);
    return mat3(
        v.x * v.x * k + c, v.y * v.x * k - v.z, v.z * v.x * k + v.y,
        v.x * v.y * k + v.z, v.y * v.y * k + c, v.z * v.y * k - v.x,
        v.x * v.z * k - v.y, v.y * v.z * k + v.x, v.z * v.z * k + c
    );
}

vec3 acesApprox(vec3 v) {
    v = max(v, vec3(0.0));
    v *= 0.6;
    return clamp((v * (2.51 * v + 0.03)) / (v * (2.43 * v + 0.59) + 0.14), 0.0, 1.0);
}

float sphere(vec3 p, float r) {
    return length(p) - r;
}

float box(vec2 p, vec2 b) {
    vec2 d = abs(p) - b;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
}

void polyFold(inout vec3 pos) {
    vec3 p = pos;
    for (int i = 0; i < 3; i++) {
        p.xy = abs(p.xy);
        p -= 2.0 * min(0.0, dot(p, POLY_NC)) * POLY_NC;
    }
    pos = p;
}

float polyPlane(vec3 pos) {
    float d0 = dot(pos, POLY_PAB);
    float d1 = dot(pos, POLY_PBC);
    float d2 = dot(pos, POLY_PCA);
    return max(d0, max(d1, d2));
}

float polyCorner(vec3 pos) {
    return length(pos) - 0.0125;
}

float dot2(vec3 p) {
    return dot(p, p);
}

float polyEdge(vec3 pos) {
    float dla = dot2(pos - min(0.0, pos.x) * vec3(1.0, 0.0, 0.0));
    float dlb = dot2(pos - min(0.0, pos.y) * vec3(0.0, 1.0, 0.0));
    float dlc = dot2(pos - min(0.0, dot(pos, POLY_NC)) * POLY_NC);
    return sqrt(min(min(dla, dlb), dlc)) - 0.002;
}

vec3 shape(vec3 pos) {
    pos *= gRot;
    pos /= gZoom;
    polyFold(pos);
    pos -= POLY_P;
    return vec3(polyPlane(pos), polyEdge(pos), polyCorner(pos)) * gZoom;
}

vec3 render0(vec3 ro, vec3 rd) {
    vec3 col = vec3(0.0);
    float srd = sign(rd.y);
    float tp = -(ro.y - 6.0) / max(abs(rd.y), 0.001);
    if (srd < 0.0) {
        col += gBottom * exp(-0.5 * length((ro + tp * rd).xz));
    }
    if (srd > 0.0) {
        vec3 pos = ro + tp * rd;
        float db = box(pos.xz, vec2(5.0, 9.0)) - 3.0;
        col += gTop * rd.y * rd.y * smoothstep(0.25, 0.0, db);
        col += 0.2 * gTop * exp(-0.5 * max(db, 0.0));
        col += 0.05 * sqrt(max(gTop, vec3(0.0))) * max(-db, 0.0);
    }
    vec3 sunDir = normalize(-ro);
    col += gSun / (1.001 - dot(sunDir, rd));
    return col;
}

float df2(vec3 p) {
    vec3 ds = shape(p);
    float d2 = ds.y - 0.005;
    float d0 = min(-ds.x, d2);
    float d1 = sphere(p, 1.0);
    gGd = min(gGd, vec2(d2, d1));
    return min(d0, d1);
}

float rayMarch2(vec3 ro, vec3 rd, float tinit) {
    float t = tinit;
    for (int i = 0; i < 22; i++) {
        float d = df2(ro + rd * t);
        if (d < 0.0005) {
            break;
        }
        t += d;
    }
    return t;
}

vec3 normal2(vec3 pos) {
    vec2 e = vec2(0.005, 0.0);
    return normalize(vec3(
        df2(pos + e.xyy) - df2(pos - e.xyy),
        df2(pos + e.yxy) - df2(pos - e.yxy),
        df2(pos + e.yyx) - df2(pos - e.yyx)
    ));
}

vec3 render2(vec3 ro, vec3 rd, float db) {
    vec3 agg = vec3(0.0);
    float ragg = 1.0;
    float tagg = 0.0;
    for (int bounce = 0; bounce < 4; bounce++) {
        if (ragg < 0.1) {
            break;
        }
        gGd = vec2(1000.0);
        float t2 = rayMarch2(ro, rd, min(db + 0.05, 0.3));
        vec2 gd2 = gGd;
        tagg += t2;
        vec3 p2 = ro + rd * t2;
        vec3 n2 = normal2(p2);
        vec3 r2 = reflect(rd, n2);
        vec3 rr2 = refract(rd, n2, RREFR);
        float fre2 = 1.0 + dot(n2, rd);
        vec3 beer = ragg * exp(0.2 * gBeer * tagg);
        float edge = max(gd2.x, 0.0005 + tagg * tagg * 0.0002 / max(ragg, 0.05));
        agg += gGlow1 * beer * ((1.0 + tagg * tagg * 0.04) * 6.0 / edge);
        vec3 ocol = 0.2 * beer * render0(p2, rr2);
        if (gd2.y <= 0.0005) {
            ragg *= 1.0 - 0.9 * fre2;
        } else {
            agg += ocol;
            ragg *= 0.8;
        }
        ro = p2;
        rd = r2;
        db = gd2.x;
    }
    return agg;
}

float df3(vec3 p) {
    vec3 ds = shape(p);
    gGd = min(gGd, ds.yz);
    float d0 = min(ds.x, min(ds.y, ds.z));
    return d0;
}

float rayMarch3(vec3 ro, vec3 rd) {
    float t = 0.1;
    for (int i = 0; i < 28; i++) {
        float d = df3(ro + rd * t);
        if (d < 0.0005 || t > 10.0) {
            break;
        }
        t += d;
    }
    return t;
}

vec3 normal3(vec3 pos) {
    vec2 e = vec2(0.005, 0.0);
    return normalize(vec3(
        df3(pos + e.xyy) - df3(pos - e.xyy),
        df3(pos + e.yxy) - df3(pos - e.yxy),
        df3(pos + e.yyx) - df3(pos - e.yyx)
    ));
}

vec3 render3(vec3 ro, vec3 rd) {
    gHit = 0.0;
    gGd = vec2(1000.0);
    float t1 = rayMarch3(ro, rd);
    vec2 gd1 = gGd;
    gEdge = gd1.x;
    float fres = 1.0;
    vec3 col = vec3(0.0);
    if (t1 < 10.0) {
        gHit = 1.0;
        vec3 p1 = ro + t1 * rd;
        vec3 n1 = normal3(p1);
        vec3 r1 = reflect(rd, n1);
        vec3 rr1 = refract(rd, n1, REFR);
        fres = 1.0 + dot(rd, n1);
        fres *= fres;
        col = render0(p1, r1) * (0.5 + 0.5 * fres);
        if (gd1.x > 0.0005 && gd1.y > 0.0005 && dot(rr1, rr1) > 0.0) {
            col += render2(p1, rr1, gd1.x) * (1.0 - 0.75 * fres);
        }
    }
    col += (gGlow0 + fres * gGlow0) / max(gd1.x, 0.0003);
    return col;
}

vec3 grade(vec3 col, float st) {
    if (st > 0.5 && st < 1.5) {
        col *= 1.08 + 0.55 * uLevel;
    } else if (st > 1.5 && st < 2.5) {
        col = mix(col, col.bgr, 0.62);
    } else if (st > 2.5 && st < 3.5) {
        float mouth = 0.5 + 0.5 * sin(uTime * 8.0);
        col *= 0.9 + mouth * (0.28 + 0.9 * uLevel);
    } else if (st > 3.5 && st < 4.5) {
        float flash = pow(max(sin(uTime * 4.0), 0.0), 2.0);
        col = mix(col, col * vec3(1.3, 0.84, 0.36) + vec3(0.08, 0.035, 0.0), 0.74);
        col += vec3(1.0, 0.68, 0.24) * flash * 0.42;
    } else if (st > 4.5 && st < 5.5) {
        col = mix(col, vec3(col.r * 1.45, col.g * 0.22, col.b * 0.14), 0.84);
    } else if (st > 5.5 && st < 6.5) {
        col *= vec3(0.8, 0.74, 0.68);
    }
    return col;
}

void main() {
    float st = floor(uState + 0.5);
    float rotSpeed = 0.25;
    float zoom = 2.0;
    float hue = 0.0;
    float glowV = 0.001;
    float cam = 5.0;
    float lift = 1.0;
    float orbit = 0.0;
    float jitter = 0.0;
    if (st > 0.5 && st < 1.5) {
        rotSpeed = 0.16;
        zoom = 2.0;
        glowV = 0.0014 + 0.0026 * uLevel;
        cam = 5.0;
        lift = 1.12;
    } else if (st > 1.5 && st < 2.5) {
        rotSpeed = 1.25;
        zoom = 2.0;
        hue = 0.46;
        glowV = 0.0018;
    } else if (st > 2.5 && st < 3.5) {
        float mouth = 0.5 + 0.5 * sin(uTime * 8.0);
        rotSpeed = 0.5;
        zoom = 1.65 + mouth * (0.22 + 0.72 * uLevel);
        hue = 0.08;
        glowV = 0.0012 + mouth * (0.0011 + 0.0032 * uLevel);
    } else if (st > 3.5 && st < 4.5) {
        rotSpeed = 0.85;
        zoom = 1.55;
        hue = 0.09;
        glowV = 0.0042;
    } else if (st > 4.5 && st < 5.5) {
        rotSpeed = 0.07;
        zoom = 1.48;
        hue = 0.97;
        glowV = 0.0028;
        jitter = 0.02 * sin(uTime * 5.0);
    } else if (st > 5.5 && st < 6.5) {
        float breath = 0.5 + 0.5 * sin(uTime * 0.42);
        rotSpeed = 0.035;
        zoom = 1.98 + 0.04 * breath;
        hue = 0.03;
        glowV = 0.0004 + 0.00012 * breath;
    } else if (st > 6.5 && st < 7.5) {
        rotSpeed = 0.95;
        zoom = 1.48;
        hue = 0.04;
        glowV = 0.0024;
    } else if (st > 7.5 && st < 8.5) {
        rotSpeed = 0.55;
        zoom = 2.0;
        hue = 0.16;
        glowV = 0.0016;
        orbit = sin(uTime * 0.5) * 0.28;
    } else if (st > 8.5) {
        rotSpeed = 0.1;
        zoom = 2.0;
        glowV = 0.00085;
        lift = 1.06 + 0.05 * sin(uTime * 1.4);
    }

    vec2 p = vLocal.xy * 2.15;
    gZoom = zoom;
    gGlow0 = tone(0.05 + hue, 0.7, glowV);
    gGlow1 = tone(0.95 + hue, 0.7, glowV);
    gSun = tone(0.06 + hue, 0.9, 0.01);
    gBottom = tone(0.66 + hue, 0.8, 0.5);
    gTop = tone(0.6 + hue, 0.9, 1.0);
    gBeer = vec3(0.0);

    float spin = uTime * rotSpeed + jitter;
    vec3 r0 = vec3(1.0, sin(vec2(sqrt(0.5), 1.0) * spin));
    vec3 r1 = vec3(cos(vec2(sqrt(0.5), 1.0) * 0.913 * spin), 1.0);
    gRot = orient(normalize(r0), normalize(r1));

    vec3 ro = vec3(sin(orbit) * cam, lift, -cos(orbit) * cam);
    vec3 ww = normalize(-ro);
    vec3 uu = normalize(cross(vec3(0.0, 1.0, 0.0), ww));
    vec3 vv = cross(ww, uu);
    vec3 rd = normalize(-p.x * uu + p.y * vv + 2.0 * ww);

    vec3 col = render3(ro, rd);
    col = acesApprox(col);
    col = sqrt(col);
    col = grade(col, st);
    float peak = max(col.r, max(col.g, col.b));
    float halo = 1.0 - smoothstep(0.02, 0.1, gEdge);
    float cover = max(gHit, clamp(peak * 6.0, 0.0, 1.0) * halo);
    col = clamp(col, 0.0, 1.0) * cover;
    // Premultiplied, as Wisp Swarm is. Clear pixels stay clear on the desktop
    // figure and in the web preview. The backdrop slider is a separate disc.
    gl_FragColor = vec4(col, cover);
}
