import * as THREE from 'three';
import type { WeatherMode } from '../types';

export interface WeatherSystemInstance {
  group: THREE.Group;
  setMode: (mode: WeatherMode) => void;
  getMode: () => WeatherMode;
  setExteriorReveal: (reveal: number) => void;
  getDisplayBgColor: () => THREE.Color;
  update: (dt: number, elapsed: number) => void;
  dispose: () => void;
}

interface WeatherPalette {
  indoorBg: number;
  bg: number;
  indoorFogDensity: number;
  fogDensity: number;
  hemiSky: number;
  hemiGround: number;
  hemiIntensity: number;
  keyColor: number;
  keyIntensity: number;
  keyPos: [number, number, number];
  fillColor: number;
  fillIntensity: number;
  envIntensity: number;
  exposure: number;
  warmLampIntensity: number;
  cityNightGlow: number;
}

const WEATHER_PALETTES: Record<WeatherMode, WeatherPalette> = {
  sunny: {
    indoorBg: 0xe6dfd3,
    bg: 0xcbe0f2,
    indoorFogDensity: 0.0064,
    fogDensity: 0.0024,
    hemiSky: 0xfff9ee,
    hemiGround: 0xbba890,
    hemiIntensity: 0.96,
    keyColor: 0xffefd6,
    keyIntensity: 2.1,
    keyPos: [16, 28, 18],
    fillColor: 0xc7e0ff,
    fillIntensity: 0.5,
    envIntensity: 0.62,
    exposure: 1.04,
    warmLampIntensity: 0.12,
    cityNightGlow: 0.05,
  },
  sunset: {
    indoorBg: 0xd9b39a,
    bg: 0xd99b7a,
    indoorFogDensity: 0.0072,
    fogDensity: 0.003,
    hemiSky: 0xffb884,
    hemiGround: 0x62423a,
    hemiIntensity: 0.85,
    keyColor: 0xff823a,
    keyIntensity: 2.25,
    keyPos: [-26, 14, 16],
    fillColor: 0x7e8fd1,
    fillIntensity: 0.48,
    envIntensity: 0.54,
    exposure: 1.04,
    warmLampIntensity: 0.92,
    cityNightGlow: 0.68,
  },
  night: {
    indoorBg: 0x10182b,
    bg: 0x0b1326,
    indoorFogDensity: 0.0085,
    fogDensity: 0.0036,
    hemiSky: 0x385898,
    hemiGround: 0x161729,
    hemiIntensity: 0.62,
    keyColor: 0x93c5fd,
    keyIntensity: 0.92,
    keyPos: [-18, 28, -14],
    fillColor: 0x3b4d68,
    fillIntensity: 0.36,
    envIntensity: 0.3,
    exposure: 1.0,
    warmLampIntensity: 2.45,
    cityNightGlow: 1.35,
  },
  storm: {
    indoorBg: 0x1b2636,
    bg: 0x1a2636,
    indoorFogDensity: 0.0095,
    fogDensity: 0.0046,
    hemiSky: 0x4c637d,
    hemiGround: 0x1b222e,
    hemiIntensity: 0.65,
    keyColor: 0x94b8db,
    keyIntensity: 0.78,
    keyPos: [16, 26, -16],
    fillColor: 0x475e78,
    fillIntensity: 0.36,
    envIntensity: 0.34,
    exposure: 1.0,
    warmLampIntensity: 2.2,
    cityNightGlow: 1.15,
  },
};

/**
 * Full City-Scale 3D Atmospheric Weather System:
 * - Sunny: Crisp daylight blue sky + warm architectural sunlight + drifting golden air motes
 * - Sunset: Golden-amber horizon + long skyscraper shadows + warm desk & tower window glow
 * - Night: Midnight starfield dome over the entire city + illuminated skyscrapers + warm interior lamps
 * - Storm: 540 slanted 3D raindrops sweeping across the tower & skyline + dramatic 3D lightning flashes & jagged sky bolt!
 */
export function createWeatherSystem(params: {
  scene: THREE.Scene;
  renderer: THREE.WebGLRenderer;
  hemiLight: THREE.HemisphereLight;
  keyLight: THREE.DirectionalLight;
  fillLight: THREE.DirectionalLight;
  onWarmLampUpdate: (intensity: number) => void;
  onCityNightGlow: (intensity: number) => void;
}): WeatherSystemInstance {
  const {
    scene,
    renderer,
    hemiLight,
    keyLight,
    fillLight,
    onWarmLampUpdate,
    onCityNightGlow,
  } = params;
  const group = new THREE.Group();
  group.name = 'weather_atmosphere_system';

  const geometries: THREE.BufferGeometry[] = [];
  const materials: THREE.Material[] = [];

  // =========================================================================
  // 1. CITY-SCALE STORM RAIN STREAKS (540 slanted falling 3D raindrops)
  // =========================================================================
  const RAIN_COUNT = 540;
  const rainPositions = new Float32Array(RAIN_COUNT * 2 * 3);
  const rainSpeeds = new Float32Array(RAIN_COUNT);

  const resetDrop = (i: number, randomY: boolean) => {
    // 45% close around the penthouse office, 55% wide across the building & city skyline!
    const nearOffice = i < RAIN_COUNT * 0.45;
    let x = (Math.random() - 0.5) * (nearOffice ? 30 : 96);
    let z = (Math.random() - 0.5) * (nearOffice ? 26 : 96);
    if (nearOffice && Math.abs(x) < 7.2 && Math.abs(z) < 5.4 && Math.random() < 0.55) {
      x += x >= 0 ? 8.8 : -8.8;
    }
    const y = randomY ? -22 + Math.random() * 52 : 24 + Math.random() * 8;
    const len = nearOffice ? 0.8 + Math.random() * 0.5 : 1.5 + Math.random() * 0.8;
    const idx = i * 6;
    rainPositions[idx] = x;
    rainPositions[idx + 1] = y;
    rainPositions[idx + 2] = z;
    rainPositions[idx + 3] = x - len * 0.28;
    rainPositions[idx + 4] = y - len;
    rainPositions[idx + 5] = z + len * 0.16;
    rainSpeeds[i] = 18 + Math.random() * 10;
  };

  for (let i = 0; i < RAIN_COUNT; i++) {
    resetDrop(i, true);
  }
  const rainGeo = new THREE.BufferGeometry();
  rainGeo.setAttribute('position', new THREE.BufferAttribute(rainPositions, 3));
  geometries.push(rainGeo);

  const rainMat = new THREE.LineBasicMaterial({
    color: 0xcbe3ff,
    transparent: true,
    opacity: 0,
    depthWrite: false,
  });
  materials.push(rainMat);
  const rainLines = new THREE.LineSegments(rainGeo, rainMat);
  rainLines.visible = false;
  rainLines.frustumCulled = false;
  group.add(rainLines);

  // =========================================================================
  // 2. DRAMATIC SKYLINE 3D LIGHTNING FLASH LIGHT + TALL JAGGED SKY BOLT!
  // =========================================================================
  const lightningLight = new THREE.DirectionalLight(0xdbeeff, 0);
  lightningLight.position.set(-22, 42, -26);
  group.add(lightningLight);

  const boltPoints = [
    new THREE.Vector3(-18, 42, -28),
    new THREE.Vector3(-15, 31, -27),
    new THREE.Vector3(-20, 21, -28),
    new THREE.Vector3(-15, 9, -26),
    new THREE.Vector3(-19, -5, -27),
    new THREE.Vector3(-16, -23, -26),
  ];
  const boltCurve = new THREE.CatmullRomCurve3(boltPoints);
  const boltGeo = new THREE.TubeGeometry(boltCurve, 20, 0.28, 6, false);
  geometries.push(boltGeo);
  const boltMat = new THREE.MeshBasicMaterial({
    color: 0xf0f8ff,
    transparent: true,
    opacity: 0,
    depthWrite: false,
  });
  materials.push(boltMat);
  const lightningBolt = new THREE.Mesh(boltGeo, boltMat);
  lightningBolt.visible = false;
  group.add(lightningBolt);

  // =========================================================================
  // 3. WIDE NIGHT STARFIELD DOME & SUNNY GOLDEN AIR MOTES
  // =========================================================================
  const STAR_COUNT = 200;
  const starPos = new Float32Array(STAR_COUNT * 3);
  for (let i = 0; i < STAR_COUNT; i++) {
    const theta = Math.random() * Math.PI * 2;
    const radius = 58 + Math.random() * 95;
    starPos[i * 3] = Math.cos(theta) * radius;
    starPos[i * 3 + 1] = 16 + Math.random() * 75;
    starPos[i * 3 + 2] = Math.sin(theta) * radius;
  }
  const starGeo = new THREE.BufferGeometry();
  starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
  geometries.push(starGeo);
  const starMat = new THREE.PointsMaterial({
    color: 0xe2eeff,
    size: 0.72,
    transparent: true,
    opacity: 0,
    depthWrite: false,
  });
  materials.push(starMat);
  const stars = new THREE.Points(starGeo, starMat);
  stars.visible = false;
  group.add(stars);

  // Soft sunlit motes near the penthouse office
  const MOTE_COUNT = 65;
  const motePos = new Float32Array(MOTE_COUNT * 3);
  for (let i = 0; i < MOTE_COUNT; i++) {
    motePos[i * 3] = (Math.random() - 0.5) * 24;
    motePos[i * 3 + 1] = 1.0 + Math.random() * 8.5;
    motePos[i * 3 + 2] = (Math.random() - 0.5) * 20;
  }
  const moteGeo = new THREE.BufferGeometry();
  moteGeo.setAttribute('position', new THREE.BufferAttribute(motePos, 3));
  geometries.push(moteGeo);
  const moteMat = new THREE.PointsMaterial({
    color: 0xfff3d4,
    size: 0.12,
    transparent: true,
    opacity: 0.34,
    depthWrite: false,
  });
  materials.push(moteMat);
  const motes = new THREE.Points(moteGeo, moteMat);
  group.add(motes);

  // State & Reusable scratch Color/Vector3
  let currentMode: WeatherMode = 'sunny';
  let exteriorReveal = 0;
  const curBg = new THREE.Color(WEATHER_PALETTES.sunny.indoorBg);
  const targetIndoorBg = new THREE.Color(WEATHER_PALETTES.sunny.indoorBg);
  const targetOutdoorBg = new THREE.Color(WEATHER_PALETTES.sunny.bg);
  const blendedTargetBg = new THREE.Color(WEATHER_PALETTES.sunny.indoorBg);
  const targetHemiSky = new THREE.Color(WEATHER_PALETTES.sunny.hemiSky);
  const targetHemiGround = new THREE.Color(WEATHER_PALETTES.sunny.hemiGround);
  const targetKeyCol = new THREE.Color(WEATHER_PALETTES.sunny.keyColor);
  const targetFillCol = new THREE.Color(WEATHER_PALETTES.sunny.fillColor);
  const targetKeyPos = new THREE.Vector3(...WEATHER_PALETTES.sunny.keyPos);
  const flashBgColor = new THREE.Color(0x94b8db);
  const displayBgColor = new THREE.Color(WEATHER_PALETTES.sunny.indoorBg);

  let currentWarmLamp = WEATHER_PALETTES.sunny.warmLampIntensity;
  let currentCityNightGlow = WEATHER_PALETTES.sunny.cityNightGlow;
  let lightningTimer = 2.4;
  let lightningFlash = 0;

  const applyImmediate = (mode: WeatherMode) => {
    const p = WEATHER_PALETTES[mode];
    targetIndoorBg.setHex(p.indoorBg);
    targetOutdoorBg.setHex(p.bg);
    curBg.setHex(p.indoorBg);
    displayBgColor.copy(curBg);
    scene.background = curBg.clone();
    if (scene.fog instanceof THREE.FogExp2) {
      scene.fog.color.copy(curBg);
      scene.fog.density = p.indoorFogDensity;
    }
    hemiLight.color.setHex(p.hemiSky);
    hemiLight.groundColor.setHex(p.hemiGround);
    hemiLight.intensity = p.hemiIntensity;
    keyLight.color.setHex(p.keyColor);
    keyLight.intensity = p.keyIntensity;
    keyLight.position.set(...p.keyPos);
    fillLight.color.setHex(p.fillColor);
    fillLight.intensity = p.fillIntensity;
    scene.environmentIntensity = p.envIntensity;
    renderer.toneMappingExposure = p.exposure;
    currentWarmLamp = p.warmLampIntensity;
    currentCityNightGlow = p.cityNightGlow;
    onWarmLampUpdate(currentWarmLamp);
    onCityNightGlow(currentCityNightGlow);
  };

  applyImmediate('sunny');

  return {
    group,
    setMode: (mode: WeatherMode) => {
      currentMode = mode;
      const p = WEATHER_PALETTES[mode];
      targetIndoorBg.setHex(p.indoorBg);
      targetOutdoorBg.setHex(p.bg);
      targetHemiSky.setHex(p.hemiSky);
      targetHemiGround.setHex(p.hemiGround);
      targetKeyCol.setHex(p.keyColor);
      targetFillCol.setHex(p.fillColor);
      targetKeyPos.set(...p.keyPos);
      if (mode === 'storm') {
        lightningTimer = 1.0;
      } else {
        lightningFlash = 0;
      }
    },
    getMode: () => currentMode,
    setExteriorReveal: (reveal: number) => {
      exteriorReveal = reveal;
    },
    getDisplayBgColor: () => displayBgColor,
    update: (dt, elapsed) => {
      const p = WEATHER_PALETTES[currentMode];
      const lerpFactor = 1 - Math.exp(-3.6 * dt);

      blendedTargetBg.copy(targetIndoorBg).lerp(targetOutdoorBg, exteriorReveal);
      curBg.lerp(blendedTargetBg, lerpFactor);
      hemiLight.color.lerp(targetHemiSky, lerpFactor);
      hemiLight.groundColor.lerp(targetHemiGround, lerpFactor);
      hemiLight.intensity = THREE.MathUtils.damp(hemiLight.intensity, p.hemiIntensity, 3.2, dt);

      keyLight.color.lerp(targetKeyCol, lerpFactor);
      keyLight.intensity = THREE.MathUtils.damp(keyLight.intensity, p.keyIntensity, 3.2, dt);
      keyLight.position.lerp(targetKeyPos, lerpFactor);

      fillLight.color.lerp(targetFillCol, lerpFactor);
      fillLight.intensity = THREE.MathUtils.damp(fillLight.intensity, p.fillIntensity, 3.2, dt);

      scene.environmentIntensity = THREE.MathUtils.damp(
        scene.environmentIntensity,
        p.envIntensity,
        3.2,
        dt,
      );
      renderer.toneMappingExposure = THREE.MathUtils.damp(
        renderer.toneMappingExposure,
        p.exposure,
        3.2,
        dt,
      );

      currentWarmLamp = THREE.MathUtils.damp(currentWarmLamp, p.warmLampIntensity, 3.2, dt);
      currentCityNightGlow = THREE.MathUtils.damp(
        currentCityNightGlow,
        p.cityNightGlow,
        3.2,
        dt,
      );
      onWarmLampUpdate(currentWarmLamp);
      onCityNightGlow(currentCityNightGlow);

      // Storm Lightning Strobe Logic
      if (currentMode === 'storm') {
        lightningTimer -= dt;
        if (lightningTimer <= 0) {
          lightningFlash = 1.0;
          lightningBolt.position.x = (Math.random() - 0.5) * 44;
          lightningBolt.position.z = (Math.random() - 0.5) * 32 - 12;
          lightningTimer = 3.0 + Math.random() * 4.4;
        }
      }
      if (lightningFlash > 0.005) {
        lightningFlash = Math.max(0, lightningFlash - dt * 3.8);
        const flicker = lightningFlash > 0.45 && lightningFlash < 0.62 ? 0.25 : lightningFlash;
        lightningLight.intensity = flicker * 5.6;
        lightningBolt.visible = flicker > 0.3;
        boltMat.opacity = flicker * 0.96;
      } else {
        lightningLight.intensity = 0;
        lightningBolt.visible = false;
      }

      // Apply background + fog (with lightning flash sky illumination!)
      displayBgColor.copy(curBg);
      if (lightningFlash > 0.05) {
        displayBgColor.lerp(flashBgColor, Math.min(0.65, lightningFlash * 0.7));
      }
      if (scene.background instanceof THREE.Color) {
        scene.background.copy(displayBgColor);
      }
      if (scene.fog instanceof THREE.FogExp2) {
        scene.fog.color.copy(displayBgColor);
        const targetFog = THREE.MathUtils.lerp(
          p.indoorFogDensity,
          p.fogDensity,
          exteriorReveal,
        );
        scene.fog.density = THREE.MathUtils.damp(scene.fog.density, targetFog, 3.6, dt);
      }

      // Rain Animation across penthouse & entire city
      const isStorm = currentMode === 'storm';
      const targetRainOpacity = isStorm ? 0.54 : 0;
      rainMat.opacity = THREE.MathUtils.damp(rainMat.opacity, targetRainOpacity, 4.5, dt);
      rainLines.visible = rainMat.opacity > 0.02;

      if (rainLines.visible) {
        const attr = rainGeo.getAttribute('position') as THREE.BufferAttribute;
        const arr = attr.array as Float32Array;
        for (let i = 0; i < RAIN_COUNT; i++) {
          const idx = i * 6;
          const dy = rainSpeeds[i] * dt;
          const dx = -dy * 0.28;
          const dz = dy * 0.16;
          arr[idx] += dx;
          arr[idx + 1] -= dy;
          arr[idx + 2] += dz;
          arr[idx + 3] += dx;
          arr[idx + 4] -= dy;
          arr[idx + 5] += dz;

          if (arr[idx + 4] < -24) {
            resetDrop(i, false);
          }
        }
        attr.needsUpdate = true;
      }

      // Starfield Dome at Night
      const targetStarOpacity = currentMode === 'night' ? 0.85 : 0;
      starMat.opacity = THREE.MathUtils.damp(starMat.opacity, targetStarOpacity, 3.0, dt);
      stars.visible = starMat.opacity > 0.03;
      if (stars.visible) {
        stars.rotation.y = elapsed * 0.008;
      }

      // Sunny / Sunset drifting office motes
      if (currentMode === 'sunny' || currentMode === 'sunset') {
        motes.visible = true;
        moteMat.color.setHex(currentMode === 'sunset' ? 0xffc68a : 0xfff3d4);
        moteMat.opacity = 0.34;
        motes.rotation.y = elapsed * 0.025;
        motes.position.y = Math.sin(elapsed * 0.6) * 0.25;
      } else {
        motes.visible = false;
      }
    },
    dispose: () => {
      geometries.forEach((g) => g.dispose());
      materials.forEach((m) => m.dispose());
    },
  };
}
