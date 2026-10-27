/**
 * The planet behind the viewports, drawn per pixel on a full-screen triangle
 * (docs/verse/realtime.md, "Outside the hull"). The camera sits at the origin
 * of a space where the Earth's radius is 1; every ray is intersected with the
 * true spheres of the ground, the cloud layer and the atmosphere, so the limb
 * is exact at any zoom and the clouds float above the ground.
 *
 * Light: the sun's radiance reaches each point through the atmosphere
 * (Rayleigh + Mie, marched), which reddens the terminator by itself; the
 * view ray gathers the same in-scattering on its way, which gives the blue
 * limb and the haze over the ground. Output is premultiplied: the ground is
 * opaque, the thin atmosphere over open space only dims the stars behind it.
 */

export const SPACE_VERTEX = /* glsl */ `
uniform mat4 verseInvViewProj;
varying vec3 vDir;
void main() {
  vec4 far = verseInvViewProj * vec4( position.xy, 1.0, 1.0 );
  vDir = far.xyz / far.w;
  gl_Position = vec4( position.xy, 1.0, 1.0 );
}
`;

export const SPACE_FRAGMENT = /* glsl */ `
precision highp float;
uniform vec3 earthCentre;
uniform mat3 worldToEarth;
uniform float spin;
uniform float cloudSpin;
uniform vec3 sunDir;
uniform float sunRadiance;
uniform float nightGain;
uniform float hazeGain;
uniform float ready;
uniform sampler2D dayMap;
uniform sampler2D nightMap;
uniform sampler2D cloudMap;
uniform sampler2D reliefMap;
varying vec3 vDir;

#ifndef VIEW_STEPS
#define VIEW_STEPS 12
#endif
#define LIGHT_STEPS 6
const float PI = 3.141592653589793;
const float R_GROUND = 1.0;
const float R_CLOUD = 1.0018;
const float R_TOP = 1.0165;
// Scale heights in Earth radii, a little taller than real so the limb reads at a glance.
const float H_RAY = 0.00145;
const float H_MIE = 0.00025;
// Scattering per Earth radius (per-metre values x 6.371e6).
const vec3 BETA_RAY = vec3( 36.9, 86.0, 210.9 );
const float BETA_MIE = 133.8;
const float MIE_EXT = 1.11;
const float MIE_G = 0.76;

vec2 sphere( vec3 d, float r ) {
  float b = dot( earthCentre, d );
  float c = dot( earthCentre, earthCentre ) - r * r;
  float h = b * b - c;
  if ( h < 0.0 ) return vec2( 1e9, -1e9 );
  h = sqrt( h );
  return vec2( b - h, b + h );
}

vec2 density( vec3 p ) {
  float alt = max( length( p - earthCentre ) - R_GROUND, 0.0 );
  return vec2( exp( -alt / H_RAY ), exp( -alt / H_MIE ) );
}

vec3 extinction( vec2 depth ) {
  return exp( -( BETA_RAY * depth.x + BETA_MIE * MIE_EXT * depth.y ) );
}

// Optical depth from p towards the sun; the ground in the way puts it in shadow.
vec2 sunDepth( vec3 p ) {
  vec3 o = p - earthCentre;
  float b = dot( o, sunDir );
  float c = dot( o, o ) - R_TOP * R_TOP;
  float far = -b + sqrt( max( b * b - c, 0.0 ) );
  float cg = dot( o, o ) - R_GROUND * R_GROUND * 0.9995;
  if ( b < 0.0 && b * b - cg > 0.0 ) return vec2( 1e4 );
  vec2 depth = vec2( 0.0 );
  float prev = 0.0;
  for ( int i = 1; i <= LIGHT_STEPS; i++ ) {
    float s = float( i ) / float( LIGHT_STEPS );
    float t = far * s * s;
    depth += density( p + sunDir * ( 0.5 * ( prev + t ) ) ) * ( t - prev );
    prev = t;
  }
  return depth;
}

// White balance: sunlight through the atmosphere straight down reads neutral, as a camera on the ship would see it.
vec3 sunAt( vec3 p ) {
  vec3 zenith = extinction( vec2( H_RAY, H_MIE ) );
  return extinction( sunDepth( p ) ) / zenith * sunRadiance;
}

vec2 equirect( vec3 local, float turn ) {
  float lon = atan( -local.z, local.x ) - turn;
  float u = lon / ( 2.0 * PI ) + 0.5;
  float v = 0.5 - asin( clamp( local.y, -1.0, 1.0 ) ) / PI;
  return vec2( u, v );
}

// Mip-safe sample across the longitude seam.
vec4 seamless( sampler2D map, vec2 uv ) {
  vec2 uv2 = vec2( fract( uv.x + 0.5 ) - 0.5, uv.y );
  vec2 dx = dFdx( uv ), dy = dFdy( uv );
  vec2 dx2 = dFdx( uv2 ), dy2 = dFdy( uv2 );
  if ( abs( dx2.x ) + abs( dy2.x ) < abs( dx.x ) + abs( dy.x ) ) { dx = dx2; dy = dy2; }
  return textureGrad( map, uv, dx, dy );
}

// A point on the sphere of radius r: the ray's hit, or where it passes closest (keeps derivatives smooth).
vec3 onSphere( vec3 d, float r, vec2 hit ) {
  vec3 p = hit.x < 1e8 ? d * hit.x : d * dot( earthCentre, d );
  return earthCentre + normalize( p - earthCentre ) * r;
}

void main() {
  vec3 d = normalize( vDir );
  vec2 top = sphere( d, R_TOP );
  vec2 ground = sphere( d, R_GROUND );
  vec2 cloud = sphere( d, R_CLOUD );
  bool hitGround = ground.x < 1e8 && ground.x > 0.0;
  bool hitCloud = cloud.x < 1e8 && cloud.x > 0.0;

  // Texture lookups on every pixel so the derivatives stay defined.
  vec3 gp = onSphere( d, R_GROUND, ground );
  vec3 gn = normalize( gp - earthCentre );
  vec3 gLocal = worldToEarth * gn;
  vec2 guv = equirect( gLocal, spin );
  vec3 day = seamless( dayMap, guv ).rgb;
  vec3 lights = seamless( nightMap, guv ).rgb;
  vec4 relief = seamless( reliefMap, guv );
  vec3 cp = onSphere( d, R_CLOUD, cloud );
  vec3 cn = normalize( cp - earthCentre );
  vec2 cuv = equirect( worldToEarth * cn, cloudSpin );
  float cover = seamless( cloudMap, cuv ).r;

  // The sun's disc and glare (behind everything else).
  float cosSun = dot( d, sunDir );
  float disc = smoothstep( 0.999955, 0.99997, cosSun );
  float glare = pow( max( cosSun, 0.0 ), 2200.0 ) * 0.35 + pow( max( cosSun, 0.0 ), 120.0 ) * 0.012;
  vec3 colour = vec3( 1.0, 0.97, 0.92 ) * ( disc * 60.0 + glare ) * sunRadiance;
  float alpha = 0.0;

  float far = hitGround ? ground.x : top.y;
  float near = max( top.x, 0.0 );
  vec3 transmit = vec3( 1.0 );
  vec3 inscatter = vec3( 0.0 );

  if ( top.x < 1e8 && top.y > 0.0 ) {
    float mu = cosSun;
    float pivot = clamp( dot( earthCentre, d ), near, far );
    vec3 ray = vec3( 0.0 );
    vec3 mie = vec3( 0.0 );
    // Then both halves in order from the camera, with the depth so far.
    vec2 depth = vec2( 0.0 );
    float prevT = near;
    for ( int half_ = 0; half_ < 2; half_++ ) {
      float span = half_ == 0 ? pivot - near : far - pivot;
      if ( span <= 0.0 ) continue;
      for ( int i = 1; i <= VIEW_STEPS; i++ ) {
        // Near half from the camera towards the pivot: crowd the samples at the pivot.
        float s = float( i ) / float( VIEW_STEPS );
        float t = half_ == 0 ? near + span * ( 1.0 - ( 1.0 - s ) * ( 1.0 - s ) ) : pivot + span * s * s;
        float ds = t - prevT;
        vec3 p = d * ( 0.5 * ( prevT + t ) );
        vec2 dens = density( p ) * ds;
        depth += dens * 0.5;
        vec3 att = extinction( sunDepth( p ) + depth );
        depth += dens * 0.5;
        ray += dens.x * att;
        mie += dens.y * att;
        prevT = t;
      }
    }
    float rayPhase = 3.0 / ( 16.0 * PI ) * ( 1.0 + mu * mu );
    float g2 = MIE_G * MIE_G;
    float miePhase = 3.0 / ( 8.0 * PI ) * ( ( 1.0 - g2 ) * ( 1.0 + mu * mu ) ) / ( ( 2.0 + g2 ) * pow( 1.0 + g2 - 2.0 * MIE_G * mu, 1.5 ) );
    inscatter = ( ray * BETA_RAY * rayPhase + mie * BETA_MIE * miePhase ) / extinction( vec2( H_RAY, H_MIE ) ) * sunRadiance * hazeGain;
    transmit = extinction( depth );
  }

  if ( hitGround || hitCloud ) {
    // Ground: terrain slope from the relief map, in the local east/north frame.
    vec3 north = normalize( transpose( worldToEarth ) * vec3( 0.0, 1.0, 0.0 ) );
    vec3 east = normalize( cross( north, gn ) );
    vec3 up = cross( gn, east );
    vec2 slope = ( relief.rg - 0.5 ) * 2.0;
    float water = relief.b;
    vec3 n = normalize( gn + ( east * slope.x + up * slope.y ) * ( 1.0 - water ) * 0.6 );
    float muG = dot( n, sunDir );
    vec3 sunAtGround = sunAt( gp );
    // Cloud shadow: the cover a little towards the sun.
    vec3 shadowP = gp + ( sunDir - gn * dot( sunDir, gn ) ) * ( ( R_CLOUD - R_GROUND ) / max( dot( sunDir, gn ), 0.15 ) );
    float shade = 1.0 - 0.6 * seamless( cloudMap, equirect( worldToEarth * normalize( shadowP - earthCentre ), cloudSpin ) ).r;
    vec3 albedo = day * mix( 1.0, 0.85, water );
    // Lambertian: radiance = albedo / pi x irradiance.
    vec3 groundColour = albedo / PI * max( muG, 0.0 ) * sunAtGround * shade;
    // Sun glint on open water.
    vec3 h = normalize( sunDir - d );
    float nh = max( dot( gn, h ), 0.0 );
    float a2 = 0.045;
    float dn = nh * nh * ( a2 - 1.0 ) + 1.0;
    float ggx = a2 / ( PI * dn * dn );
    float fresnel = 0.02 + 0.98 * pow( 1.0 - max( dot( -d, h ), 0.0 ), 5.0 );
    groundColour += water * ggx * fresnel * max( dot( gn, sunDir ), 0.0 ) * sunAtGround * shade * 0.25;
    // City lights on the night side.
    float night = smoothstep( 0.04, -0.12, dot( gn, sunDir ) );
    groundColour += lights * lights * nightGain * night * ( 1.0 - 0.8 * cover );

    // Cloud layer over it.
    float muC = dot( cn, sunDir );
    vec3 sunAtCloud = sunAt( cp );
    float ca = smoothstep( 0.08, 0.75, cover ) * 0.97;
    vec3 cloudColour = vec3( 0.92 / PI ) * ( max( muC, 0.0 ) * 0.9 + 0.1 * smoothstep( -0.1, 0.2, muC ) ) * sunAtCloud * mix( 0.75, 1.0, cover );
    vec3 surface = hitGround ? mix( groundColour, cloudColour, ca ) : cloudColour;
    float cover01 = hitGround ? 1.0 : ca;
    colour = colour * ( 1.0 - cover01 ) + surface * cover01;
    alpha = cover01;
  }

  vec3 premul = colour * transmit + inscatter;
  float behind = 1.0 - dot( transmit, vec3( 0.333 ) );
  alpha = alpha + ( 1.0 - alpha ) * behind;
  gl_FragColor = vec4( premul * ready, alpha * ready );
}
`;
