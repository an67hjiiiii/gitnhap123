import * as THREE from 'three';
import type { StudioTextureSet } from './textures';

export interface StudioMaterialLibrary {
  oakFloor: THREE.MeshStandardMaterial;
  oakDesk: THREE.MeshStandardMaterial;
  darkWalnutWood: THREE.MeshStandardMaterial;
  plasterWall: THREE.MeshStandardMaterial;
  cutawayWallCap: THREE.MeshStandardMaterial;
  basePlinth: THREE.MeshStandardMaterial;
  rugBlue: THREE.MeshStandardMaterial;
  rugSand: THREE.MeshStandardMaterial;
  brushedSteel: THREE.MeshPhysicalMaterial;
  chromeMetal: THREE.MeshPhysicalMaterial;
  brassAccent: THREE.MeshPhysicalMaterial;
  darkMonitorFrame: THREE.MeshStandardMaterial;
  whiteChairShell: THREE.MeshStandardMaterial;
  fabricChairBlue: THREE.MeshPhysicalMaterial;
  glassPanel: THREE.MeshPhysicalMaterial;
  planningBoardMat: THREE.MeshStandardMaterial;
  draftingPaperMat: THREE.MeshStandardMaterial;
  easelChartMat: THREE.MeshStandardMaterial;
  missionWallMat: THREE.MeshBasicMaterial;
  screenSleepMat: THREE.MeshStandardMaterial;
  plantLeafRich: THREE.MeshStandardMaterial;
  plantLeafLight: THREE.MeshStandardMaterial;
  terracottaPot: THREE.MeshStandardMaterial;
  ceramicWhite: THREE.MeshStandardMaterial;
  eilikCeramicShell: THREE.MeshPhysicalMaterial;
  visorBlack: THREE.MeshPhysicalMaterial;
  lampShadeGlow: THREE.MeshStandardMaterial;
  contactShadow: THREE.MeshBasicMaterial;
  zzzSpriteMat: THREE.SpriteMaterial;
  createSoftRobotMat: (hex: number) => THREE.MeshPhysicalMaterial;
  createScreenMat: (map: THREE.CanvasTexture) => THREE.MeshStandardMaterial;
  createAccentGlow: (hex: number, intensity?: number) => THREE.MeshStandardMaterial;
  dispose: () => void;
}

export function createStudioMaterials(
  textures: StudioTextureSet,
  isSoftwareGl: boolean,
): StudioMaterialLibrary {
  const tracked: THREE.Material[] = [];
  const track = <T extends THREE.Material>(m: T): T => {
    tracked.push(m);
    return m;
  };

  // Tactile Honey-Walnut Hardwood Plank Floor with real bump grain (never plasticky!)
  const oakFloor = track(
    new THREE.MeshStandardMaterial({
      map: textures.oakPlankFloorMap,
      bumpMap: textures.woodBumpMap,
      bumpScale: 0.028,
      color: 0xffffff,
      roughness: 0.72,
      metalness: 0.02,
    }),
  );

  // Rich Natural Walnut Desk Surface with micro-wood bump
  const oakDesk = track(
    new THREE.MeshStandardMaterial({
      map: textures.oakDeskMap,
      bumpMap: textures.woodBumpMap,
      bumpScale: 0.018,
      color: 0xffffff,
      roughness: 0.65,
      metalness: 0.03,
    }),
  );

  // Deep Espresso Walnut Cabinetry & Bookshelves
  const darkWalnutWood = track(
    new THREE.MeshStandardMaterial({
      map: textures.oakDeskMap,
      bumpMap: textures.woodBumpMap,
      bumpScale: 0.02,
      color: 0x6b472b,
      roughness: 0.68,
      metalness: 0.03,
    }),
  );

  // Warm Architectural Matte Stucco Wall with fine tactile plaster grain
  const plasterWall = track(
    new THREE.MeshStandardMaterial({
      color: 0xeae3d8,
      bumpMap: textures.plasterBumpMap,
      bumpScale: 0.014,
      roughness: 0.92,
      metalness: 0.0,
    }),
  );

  const cutawayWallCap = track(
    new THREE.MeshStandardMaterial({
      color: 0x202630,
      roughness: 0.82,
      metalness: 0.05,
    }),
  );

  const basePlinth = track(
    new THREE.MeshStandardMaterial({
      color: 0x8e8377,
      roughness: 0.88,
      metalness: 0.02,
    }),
  );

  // Tactile Woven Wool Area Rugs with fabric bump
  const rugBlue = track(
    new THREE.MeshStandardMaterial({
      map: textures.wovenRugBlueMap,
      bumpMap: textures.fabricBumpMap,
      bumpScale: 0.022,
      roughness: 0.96,
      metalness: 0.0,
    }),
  );

  const rugSand = track(
    new THREE.MeshStandardMaterial({
      map: textures.wovenRugSandMap,
      bumpMap: textures.fabricBumpMap,
      bumpScale: 0.022,
      roughness: 0.96,
      metalness: 0.0,
    }),
  );

  const brushedSteel = track(
    new THREE.MeshPhysicalMaterial({
      color: 0xadb6c2,
      roughness: 0.38,
      metalness: 0.82,
      clearcoat: 0.1,
    }),
  );

  const chromeMetal = track(
    new THREE.MeshPhysicalMaterial({
      color: 0xdce3eb,
      roughness: 0.18,
      metalness: 0.92,
    }),
  );

  const brassAccent = track(
    new THREE.MeshPhysicalMaterial({
      color: 0xc48b32,
      roughness: 0.32,
      metalness: 0.86,
    }),
  );

  const darkMonitorFrame = track(
    new THREE.MeshStandardMaterial({
      color: 0x1a2029,
      roughness: 0.52,
      metalness: 0.22,
    }),
  );

  const whiteChairShell = track(
    new THREE.MeshStandardMaterial({
      color: 0xece8e1,
      roughness: 0.68,
      metalness: 0.02,
    }),
  );

  const fabricChairBlue = track(
    new THREE.MeshPhysicalMaterial({
      color: 0x3b5c7a,
      bumpMap: textures.fabricBumpMap,
      bumpScale: 0.015,
      roughness: 0.94,
      metalness: 0.0,
      sheen: 0.55,
      sheenRoughness: 0.85,
      sheenColor: new THREE.Color(0x88aac8),
    }),
  );

  const glassPanel = track(
    new THREE.MeshPhysicalMaterial({
      color: 0xcfe4f5,
      roughness: 0.12,
      metalness: 0.04,
      transparent: true,
      opacity: isSoftwareGl ? 0.3 : 0.24,
      depthWrite: false,
    }),
  );

  const planningBoardMat = track(
    new THREE.MeshStandardMaterial({
      map: textures.planningBoardMap,
      roughness: 0.32,
      metalness: 0.03,
      emissive: new THREE.Color(0xffffff),
      emissiveMap: textures.planningBoardMap,
      emissiveIntensity: 0.14,
    }),
  );

  const draftingPaperMat = track(
    new THREE.MeshStandardMaterial({
      map: textures.draftingPaperMap,
      roughness: 0.88,
      metalness: 0.0,
    }),
  );

  const easelChartMat = track(
    new THREE.MeshStandardMaterial({
      map: textures.easelChartMap,
      roughness: 0.55,
      metalness: 0.0,
      emissive: new THREE.Color(0xffffff),
      emissiveMap: textures.easelChartMap,
      emissiveIntensity: 0.12,
    }),
  );

  const missionWallMat = track(
    new THREE.MeshBasicMaterial({
      map: textures.missionWallMap,
    }),
  );

  const screenSleepMat = track(
    new THREE.MeshStandardMaterial({
      map: textures.screenSleepMap,
      roughness: 0.35,
      metalness: 0.14,
      emissive: new THREE.Color(0x0f172a),
      emissiveIntensity: 0.1,
    }),
  );

  // Rich Deep Botanical Foliage Greens (real matte organic leaves, zero plastic shine!)
  const plantLeafRich = track(
    new THREE.MeshStandardMaterial({
      color: 0x2c5c34,
      roughness: 0.78,
      metalness: 0.01,
    }),
  );

  const plantLeafLight = track(
    new THREE.MeshStandardMaterial({
      color: 0x447c45,
      roughness: 0.74,
      metalness: 0.01,
    }),
  );

  const terracottaPot = track(
    new THREE.MeshStandardMaterial({
      color: 0xa65e3e,
      bumpMap: textures.plasterBumpMap,
      bumpScale: 0.016,
      roughness: 0.86,
      metalness: 0.0,
    }),
  );

  const ceramicWhite = track(
    new THREE.MeshStandardMaterial({
      color: 0xebe6dd,
      roughness: 0.56,
      metalness: 0.02,
    }),
  );

  // Eilik Signature Soft-Touch Satin Warm-Pearl Ceramic Body Shell (clean & velvety, zero chalky wash!)
  const eilikCeramicShell = track(
    new THREE.MeshPhysicalMaterial({
      color: 0xf0eee9,
      roughness: 0.42,
      metalness: 0.02,
      clearcoat: 0.16,
      clearcoatRoughness: 0.35,
    }),
  );

  // Glossy Curved Black Glass OLED Face Visor (deep mirror black like Eilik photos!)
  const visorBlack = track(
    new THREE.MeshPhysicalMaterial({
      color: 0x040508,
      roughness: 0.04,
      metalness: 0.06,
      clearcoat: 1.0,
      clearcoatRoughness: 0.04,
    }),
  );

  // Warm Interior Architectural Lamp Shade (lights up cozily at sunset, night & storm!)
  const lampShadeGlow = track(
    new THREE.MeshStandardMaterial({
      color: 0xfbf4e4,
      emissive: new THREE.Color(0xffb85c),
      emissiveIntensity: 0.15,
      roughness: 0.5,
    }),
  );

  const contactShadow = track(
    new THREE.MeshBasicMaterial({
      map: textures.contactShadowMap,
      transparent: true,
      opacity: 0.92,
      depthWrite: false,
    }),
  );

  const zzzSpriteMat = track(
    new THREE.SpriteMaterial({
      map: textures.zzzSpriteMap,
      transparent: true,
      opacity: 0.92,
      depthWrite: false,
    }),
  );

  // Deep Rich Saturated Enamel Accent Material for Eilik's V-Collar, Crown Cap, Ear-Cups & Arms!
  const createSoftRobotMat = (hex: number) =>
    track(
      new THREE.MeshPhysicalMaterial({
        color: hex,
        roughness: 0.38,
        metalness: 0.04,
        clearcoat: 0.24,
        clearcoatRoughness: 0.28,
      }),
    );

  const createScreenMat = (map: THREE.CanvasTexture) =>
    track(
      new THREE.MeshStandardMaterial({
        map,
        roughness: 0.25,
        metalness: 0.06,
        emissive: new THREE.Color(0xffffff),
        emissiveMap: map,
        emissiveIntensity: 0.85,
      }),
    );

  const createAccentGlow = (hex: number, intensity = 0.65) =>
    track(
      new THREE.MeshStandardMaterial({
        color: hex,
        emissive: new THREE.Color(hex),
        emissiveIntensity: intensity,
        roughness: 0.36,
        metalness: 0.1,
      }),
    );

  return {
    oakFloor,
    oakDesk,
    darkWalnutWood,
    plasterWall,
    cutawayWallCap,
    basePlinth,
    rugBlue,
    rugSand,
    brushedSteel,
    chromeMetal,
    brassAccent,
    darkMonitorFrame,
    whiteChairShell,
    fabricChairBlue,
    glassPanel,
    planningBoardMat,
    draftingPaperMat,
    easelChartMat,
    missionWallMat,
    screenSleepMat,
    plantLeafRich,
    plantLeafLight,
    terracottaPot,
    ceramicWhite,
    eilikCeramicShell,
    visorBlack,
    lampShadeGlow,
    contactShadow,
    zzzSpriteMat,
    createSoftRobotMat,
    createScreenMat,
    createAccentGlow,
    dispose: () => {
      tracked.forEach((m) => m.dispose());
    },
  };
}
