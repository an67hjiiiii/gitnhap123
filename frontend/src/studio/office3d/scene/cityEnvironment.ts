import * as THREE from 'three';

export interface CityEnvironmentInstance {
  group: THREE.Group;
  groundMat: THREE.MeshStandardMaterial;
  setNightGlow: (intensity: number) => void;
  update: (dt: number, elapsed: number, exteriorReveal: number) => void;
  dispose: () => void;
}

const STREET_Y = -24.0;

/**
 * Procedural Skyscraper Facade Texture (Daytime cool architectural glass + Emissive lit office windows!)
 */
function createSkyscraperFacadeTextures(maxAniso: number): {
  colorMap: THREE.CanvasTexture;
  emissiveMap: THREE.CanvasTexture;
} {
  const w = 256;
  const h = 512;

  const colorCanvas = document.createElement('canvas');
  colorCanvas.width = w;
  colorCanvas.height = h;
  const cCtx = colorCanvas.getContext('2d')!;

  const emisCanvas = document.createElement('canvas');
  emisCanvas.width = w;
  emisCanvas.height = h;
  const eCtx = emisCanvas.getContext('2d')!;

  // Architectural concrete / aluminum curtain wall base
  cCtx.fillStyle = '#536070';
  cCtx.fillRect(0, 0, w, h);

  eCtx.fillStyle = '#000000';
  eCtx.fillRect(0, 0, w, h);

  const cols = 8;
  const rows = 20;
  const cw = w / cols;
  const rh = h / rows;

  // Deterministic pseudo-random helper so skyscraper lights look crisp & organic
  let seed = 4219;
  const rand = () => {
    seed = (seed * 16807) % 2147483647;
    return (seed - 1) / 2147483646;
  };

  for (let r = 0; r < rows; r++) {
    // Horizontal architectural slab band
    cCtx.fillStyle = '#8b96a3';
    cCtx.fillRect(0, r * rh, w, 4);

    for (let c = 0; c < cols; c++) {
      const wx = c * cw + 4;
      const wy = r * rh + 6;
      const ww = cw - 8;
      const wh = rh - 10;

      // Reflective sky-tinted window pane
      const glassTone = rand() > 0.5 ? '#7ea2c2' : '#6586a6';
      cCtx.fillStyle = glassTone;
      cCtx.fillRect(wx, wy, ww, wh);

      // Subtle vertical glint
      cCtx.fillStyle = 'rgba(255,255,255,0.16)';
      cCtx.fillRect(wx + 2, wy + 2, 4, wh - 4);

      // Night/Sunset lit interior office rooms (~45% lit with cozy warm amber / cool studio white)
      const litRoll = rand();
      if (litRoll > 0.52) {
        const warm = litRoll > 0.72;
        eCtx.fillStyle = warm ? '#ffd180' : '#bae6fd';
        eCtx.fillRect(wx, wy, ww, wh);
      }
    }
  }

  const colorMap = new THREE.CanvasTexture(colorCanvas);
  colorMap.colorSpace = THREE.SRGBColorSpace;
  colorMap.wrapS = THREE.RepeatWrapping;
  colorMap.wrapT = THREE.RepeatWrapping;
  colorMap.anisotropy = maxAniso;

  const emissiveMap = new THREE.CanvasTexture(emisCanvas);
  emissiveMap.colorSpace = THREE.SRGBColorSpace;
  emissiveMap.wrapS = THREE.RepeatWrapping;
  emissiveMap.wrapT = THREE.RepeatWrapping;
  emissiveMap.anisotropy = maxAniso;

  return { colorMap, emissiveMap };
}

/**
 * Procedural City Road Grid & Parks Ground Texture (360m x 360m urban blocks around HQ!)
 */
function createCityGroundTexture(maxAniso: number): THREE.CanvasTexture {
  const size = 1024;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;

  // Urban concrete & sidewalk plaza base
  ctx.fillStyle = '#c8c4bc';
  ctx.fillRect(0, 0, size, size);

  // Landscaped park quadrants around city blocks
  const drawPark = (x: number, y: number, w: number, h: number) => {
    ctx.fillStyle = '#75966a';
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = '#d9d4c7';
    ctx.lineWidth = 4;
    ctx.strokeRect(x + 6, y + 6, w - 12, h - 12);
  };
  drawPark(80, 80, 180, 180);
  drawPark(760, 100, 180, 160);
  drawPark(110, 740, 190, 170);
  drawPark(730, 740, 200, 180);

  // Subtle city river / waterfront channel along far north edge
  ctx.fillStyle = '#4e7c9c';
  ctx.fillRect(0, 0, size, 64);
  ctx.fillStyle = '#d4cec2';
  ctx.fillRect(0, 64, size, 12);

  // Asphalt Avenues (multi-lane roads framing the central AI HQ block!)
  const roads = [180, 415, 609, 844];
  ctx.fillStyle = '#383e47';
  roads.forEach((pos) => {
    ctx.fillRect(pos - 24, 68, 48, size - 68);
    ctx.fillRect(0, pos - 24, size, 48);
  });

  // Crisp white dashed lane centerlines
  ctx.strokeStyle = '#d6dbe0';
  ctx.lineWidth = 2.5;
  ctx.setLineDash([12, 12]);
  roads.forEach((pos) => {
    ctx.beginPath();
    ctx.moveTo(pos, 72);
    ctx.lineTo(pos, size);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(0, pos);
    ctx.lineTo(size, pos);
    ctx.stroke();
  });
  ctx.setLineDash([]);

  // Central HQ Plaza Paving Stone Ring around our AI Tower
  ctx.fillStyle = '#dad3c7';
  ctx.fillRect(442, 442, 140, 140);
  ctx.strokeStyle = '#a89f91';
  ctx.lineWidth = 4;
  ctx.strokeRect(450, 450, 124, 124);

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = maxAniso;
  return tex;
}

/**
 * Rooftop "AI AGENT HQ" Illuminated Architectural Sign Texture
 */
function createHqSignTexture(): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 128;
  const ctx = canvas.getContext('2d')!;
  ctx.fillStyle = '#18202c';
  ctx.fillRect(0, 0, 512, 128);
  ctx.strokeStyle = '#e07a00';
  ctx.lineWidth = 6;
  ctx.strokeRect(8, 8, 496, 112);

  ctx.fillStyle = '#ffffff';
  ctx.font = '800 44px Inter, system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('AI AGENT TOWER', 256, 56);

  ctx.fillStyle = '#38bdf8';
  ctx.font = '600 20px Inter, system-ui, sans-serif';
  ctx.fillText('PENTHOUSE COMMAND STUDIO', 256, 98);

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

interface TrafficCar {
  axis: 'x' | 'z';
  lanePos: number;
  coord: number;
  dir: 1 | -1;
  speed: number;
  color: THREE.Color;
}

/**
 * Full 360° Living 3D Cityscape & Multi-Story AI Headquarters Tower:
 * - Our AI Agent Office sits on the penthouse floor (y = 0) atop an 8-story modern glass HQ Tower (y = 0 down to y = -24).
 * - Zooming out smoothly reveals the exterior tower facade, glowing rooftop crown & surrounding metropolis!
 * - 76 instanced skyscrapers with weather-synced night windows, landscaped avenues, trees, streetlights & animated traffic!
 */
export function buildCityEnvironment(maxAniso: number): CityEnvironmentInstance {
  const group = new THREE.Group();
  group.name = 'city_metropolis_environment';

  const geometries: THREE.BufferGeometry[] = [];
  const materials: THREE.Material[] = [];
  const textures: THREE.Texture[] = [];

  const trackGeo = <T extends THREE.BufferGeometry>(g: T): T => {
    geometries.push(g);
    return g;
  };
  const trackMat = <T extends THREE.Material>(m: T): T => {
    materials.push(m);
    return m;
  };

  const { colorMap: facadeColorMap, emissiveMap: facadeEmissiveMap } =
    createSkyscraperFacadeTextures(maxAniso);
  const groundTex = createCityGroundTexture(maxAniso);
  const hqSignTex = createHqSignTexture();
  textures.push(facadeColorMap, facadeEmissiveMap, groundTex, hqSignTex);

  // =========================================================================
  // 1. METROPOLIS STREET GROUND PLANE (y = -24.0)
  // =========================================================================
  const groundMat = trackMat(
    new THREE.MeshStandardMaterial({
      map: groundTex,
      roughness: 0.92,
      metalness: 0.02,
    }),
  );
  const cityGround = new THREE.Mesh(trackGeo(new THREE.PlaneGeometry(340, 340)), groundMat);
  cityGround.rotation.x = -Math.PI / 2;
  cityGround.position.y = STREET_Y;
  cityGround.receiveShadow = true;
  group.add(cityGround);

  // =========================================================================
  // 2. OUR AI AGENT HQ TOWER (8 Stories directly beneath the Penthouse Office y = 0!)
  // =========================================================================
  const hqGroup = new THREE.Group();
  group.add(hqGroup);

  const towerW = 18.6;
  const towerD = 14.4;
  const towerH = Math.abs(STREET_Y) - 0.34; // 23.66m tall!

  // Main glass curtain wall core of our HQ Tower
  const hqGlassMat = trackMat(
    new THREE.MeshStandardMaterial({
      map: facadeColorMap,
      emissiveMap: facadeEmissiveMap,
      emissive: new THREE.Color(0xffe0a3),
      emissiveIntensity: 0.2,
      roughness: 0.28,
      metalness: 0.35,
    }),
  );
  const hqCore = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(towerW - 0.5, towerH, towerD - 0.5)),
    hqGlassMat,
  );
  hqCore.position.set(0, STREET_Y + towerH * 0.5, 0);
  hqCore.castShadow = true;
  hqCore.receiveShadow = true;
  hqGroup.add(hqCore);

  // Architectural limestone/concrete horizontal floor ledges (8 stories!)
  const concreteMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xd9d2c5,
      roughness: 0.82,
      metalness: 0.04,
    }),
  );
  const darkMetalMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x222a36,
      roughness: 0.42,
      metalness: 0.65,
    }),
  );

  for (let fl = 0; fl < 8; fl++) {
    const fy = -2.85 * fl - 0.48;
    if (fy <= STREET_Y + 2.5) continue;
    const slab = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(towerW + 0.35, 0.34, towerD + 0.35)),
      concreteMat,
    );
    slab.position.set(0, fy, 0);
    hqGroup.add(slab);
  }

  // Sleek corner structural columns running the full height of the tower
  [
    [-towerW * 0.5, -towerD * 0.5],
    [towerW * 0.5, -towerD * 0.5],
    [-towerW * 0.5, towerD * 0.5],
    [towerW * 0.5, towerD * 0.5],
  ].forEach(([cx, cz]) => {
    const col = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.95, towerH + 0.5, 0.95)),
      concreteMat,
    );
    col.position.set(cx, STREET_Y + towerH * 0.5, cz);
    hqGroup.add(col);
  });

  // Grand Ground-Floor Entrance Lobby & Illuminated Canopy at Street Level (South face)
  const lobbyCanopy = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(8.5, 0.36, 3.2)),
    darkMetalMat,
  );
  lobbyCanopy.position.set(0, STREET_Y + 3.6, towerD * 0.5 + 1.4);
  hqGroup.add(lobbyCanopy);

  const lobbyPodium = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(towerW + 2.8, 0.5, towerD + 3.4)),
    concreteMat,
  );
  lobbyPodium.position.set(0, STREET_Y + 0.25, 0.5);
  hqGroup.add(lobbyPodium);

  // =========================================================================
  // 3. ZOOM-OUT ARCHITECTURAL PENTHOUSE ROOFTOP CROWN (Reveals smoothly when zooming out!)
  // =========================================================================
  const roofCrownGroup = new THREE.Group();
  group.add(roofCrownGroup);

  const roofRimMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x242c38,
      roughness: 0.45,
      metalness: 0.5,
      transparent: true,
      opacity: 0,
    }),
  );
  const roofGlassMat = trackMat(
    new THREE.MeshPhysicalMaterial({
      color: 0x9ec5e6,
      roughness: 0.12,
      metalness: 0.1,
      transparent: true,
      opacity: 0,
      depthWrite: false,
    }),
  );
  const roofSignMat = trackMat(
    new THREE.MeshBasicMaterial({
      map: hqSignTex,
      transparent: true,
      opacity: 0,
    }),
  );

  // Perimeter cantilevered roof frame at y = 3.25 (above cutaway walls)
  const roofBeams: Array<[number, number, number, number]> = [
    [0, -7.25, 19.2, 0.9],
    [0, 7.25, 19.2, 0.9],
    [-9.15, 0, 0.9, 13.6],
    [9.15, 0, 0.9, 13.6],
  ];
  roofBeams.forEach(([bx, bz, bw, bd]) => {
    const beam = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(bw, 0.42, bd)), roofRimMat);
    beam.position.set(bx, 3.25, bz);
    roofCrownGroup.add(beam);
  });

  // Subtle translucent skylight glass over the penthouse when viewed from afar in city orbit!
  const skylight = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(17.4, 13.6)),
    roofGlassMat,
  );
  skylight.rotation.x = -Math.PI / 2;
  skylight.position.set(0, 3.38, 0);
  skylight.renderOrder = 4;
  roofCrownGroup.add(skylight);

  // Sleek South Exterior Glass Curtain Wall that closes the penthouse cleanly when viewed from outside!
  const southCurtain = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(17.6, 2.35, 0.08)),
    roofGlassMat,
  );
  southCurtain.position.set(0, 1.9, 6.72);
  southCurtain.renderOrder = 4;
  roofCrownGroup.add(southCurtain);

  // Iconic "AI AGENT TOWER" Rooftop Billboard facing South & North
  const signGeo = trackGeo(new THREE.BoxGeometry(6.8, 1.65, 0.25));
  const signSouth = new THREE.Mesh(signGeo, roofSignMat);
  signSouth.position.set(0, 4.35, 7.25);
  roofCrownGroup.add(signSouth);

  const signNorth = new THREE.Mesh(signGeo, roofSignMat);
  signNorth.position.set(0, 4.35, -7.25);
  signNorth.rotation.y = Math.PI;
  roofCrownGroup.add(signNorth);

  // =========================================================================
  // 4. 360° SURROUNDING CITY SKYLINE (76 Instanced Skyscrapers & Towers!)
  // =========================================================================
  interface BuildingSpec {
    x: number;
    z: number;
    w: number;
    d: number;
    h: number;
    tint: number;
    hasSpire: boolean;
  }

  const buildingSpecs: BuildingSpec[] = [];
  let bSeed = 9137;
  const bRand = () => {
    bSeed = (bSeed * 48271) % 2147483647;
    return (bSeed - 1) / 2147483646;
  };

  const paletteTints = [
    0xd8e0e8, 0xc7d2de, 0xe2dcd2, 0xb8c7d9, 0xd4cdc2, 0xa8bacf, 0xcfd6dd,
  ];

  // Arrange skyscrapers in realistic city blocks circling our HQ Tower (clear of avenues & central HQ plaza!)
  const ringGrid = [-116, -92, -68, -44, -22, 0, 22, 44, 68, 92, 116];
  for (const gx of ringGrid) {
    for (const gz of ringGrid) {
      // Keep central AI HQ Plaza & primary avenues completely open!
      const distCenter = Math.hypot(gx, gz);
      if (distCenter < 33) continue;
      if (Math.abs(Math.abs(gx) - 34) < 5 || Math.abs(Math.abs(gz) - 34) < 5) continue;
      if (distCenter > 132) continue;
      // Leave scenic park clearings in 4 corners
      if (Math.abs(gx) > 78 && Math.abs(gz) > 78 && bRand() > 0.35) continue;

      const jitterX = (bRand() - 0.5) * 7.5;
      const jitterZ = (bRand() - 0.5) * 7.5;
      const w = 8.5 + bRand() * 9.5;
      const d = 8.5 + bRand() * 9.5;
      // Mid-ring towers rise proudly (some taller than our penthouse y=0 so skyline frames the horizon!)
      const nearFactor = distCenter < 75 ? 1.2 : 0.9;
      const h = (14 + bRand() * 38) * nearFactor;
      const tint = paletteTints[Math.floor(bRand() * paletteTints.length)];
      buildingSpecs.push({
        x: gx + jitterX,
        z: gz + jitterZ,
        w,
        d,
        h,
        tint,
        hasSpire: h > 36 && bRand() > 0.45,
      });
    }
  }

  const cityTowerMat = trackMat(
    new THREE.MeshStandardMaterial({
      map: facadeColorMap,
      emissiveMap: facadeEmissiveMap,
      emissive: new THREE.Color(0xffe09c),
      emissiveIntensity: 0.15,
      roughness: 0.44,
      metalness: 0.25,
    }),
  );

  const boxUnitGeo = trackGeo(new THREE.BoxGeometry(1, 1, 1));
  const towersInst = new THREE.InstancedMesh(boxUnitGeo, cityTowerMat, buildingSpecs.length);
  towersInst.receiveShadow = true;

  const capUnitGeo = trackGeo(new THREE.BoxGeometry(0.82, 0.85, 0.82));
  const rooftopCapMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x3b4452,
      roughness: 0.72,
      metalness: 0.2,
    }),
  );
  const capsInst = new THREE.InstancedMesh(capUnitGeo, rooftopCapMat, buildingSpecs.length);

  const spireSpecs = buildingSpecs.filter((b) => b.hasSpire);
  const spireGeo = trackGeo(new THREE.CylinderGeometry(0.08, 0.24, 7.5, 6));
  const spireInst = new THREE.InstancedMesh(spireGeo, darkMetalMat, Math.max(1, spireSpecs.length));

  const dummy = new THREE.Object3D();
  const tmpColor = new THREE.Color();

  buildingSpecs.forEach((b, i) => {
    dummy.position.set(b.x, STREET_Y + b.h * 0.5, b.z);
    dummy.scale.set(b.w, b.h, b.d);
    dummy.rotation.set(0, 0, 0);
    dummy.updateMatrix();
    towersInst.setMatrixAt(i, dummy.matrix);
    tmpColor.setHex(b.tint);
    towersInst.setColorAt(i, tmpColor);

    // Rooftop mechanical crown / penthouse cap
    dummy.position.set(b.x, STREET_Y + b.h + 0.42, b.z);
    dummy.scale.set(b.w * 0.72, 1.0, b.d * 0.72);
    dummy.updateMatrix();
    capsInst.setMatrixAt(i, dummy.matrix);
  });
  towersInst.instanceMatrix.needsUpdate = true;
  if (towersInst.instanceColor) towersInst.instanceColor.needsUpdate = true;
  towersInst.computeBoundingSphere();
  capsInst.instanceMatrix.needsUpdate = true;
  capsInst.computeBoundingSphere();

  spireSpecs.forEach((b, i) => {
    dummy.position.set(b.x, STREET_Y + b.h + 4.2, b.z);
    dummy.scale.set(1, 1, 1);
    dummy.updateMatrix();
    spireInst.setMatrixAt(i, dummy.matrix);
  });
  spireInst.instanceMatrix.needsUpdate = true;
  spireInst.computeBoundingSphere();

  group.add(towersInst, capsInst, spireInst);

  // =========================================================================
  // 5. CITY BOULEVARD TREES & STREETLAMPS (InstancedMesh — Super Fast!)
  // =========================================================================
  const treeCoords: Array<[number, number]> = [];
  for (let i = -5; i <= 5; i++) {
    const offset = i * 16;
    if (Math.abs(offset) > 14) {
      treeCoords.push([offset, 24.5], [offset, -24.5], [24.5, offset], [-24.5, offset]);
    }
  }
  // Park grove clusters
  for (let i = 0; i < 24; i++) {
    const angle = (i / 24) * Math.PI * 2;
    const rad = 16.5 + (i % 2) * 2.5;
    if (Math.abs(Math.cos(angle) * rad) > 11 || Math.abs(Math.sin(angle) * rad) > 9.5) {
      treeCoords.push([Math.cos(angle) * rad, Math.sin(angle) * rad]);
    }
  }

  const trunkGeo = trackGeo(new THREE.CylinderGeometry(0.18, 0.26, 2.2, 7));
  const trunkMat = trackMat(new THREE.MeshStandardMaterial({ color: 0x5c4330, roughness: 0.9 }));
  const canopyGeo = trackGeo(new THREE.DodecahedronGeometry(1.45, 1));
  const canopyMat = trackMat(new THREE.MeshStandardMaterial({ color: 0x3b6e3d, roughness: 0.82 }));

  const trunksInst = new THREE.InstancedMesh(trunkGeo, trunkMat, treeCoords.length);
  const canopiesInst = new THREE.InstancedMesh(canopyGeo, canopyMat, treeCoords.length);
  const leafPalette = [0x2f6336, 0x3f7842, 0x4b874a, 0x2c5933];

  treeCoords.forEach(([tx, tz], i) => {
    const sc = 0.85 + (i % 4) * 0.14;
    dummy.position.set(tx, STREET_Y + 1.1 * sc, tz);
    dummy.scale.setScalar(sc);
    dummy.rotation.set(0, i * 1.1, 0);
    dummy.updateMatrix();
    trunksInst.setMatrixAt(i, dummy.matrix);

    dummy.position.set(tx, STREET_Y + 2.85 * sc, tz);
    dummy.scale.set(sc * 1.05, sc * 0.95, sc * 1.05);
    dummy.updateMatrix();
    canopiesInst.setMatrixAt(i, dummy.matrix);
    tmpColor.setHex(leafPalette[i % leafPalette.length]);
    canopiesInst.setColorAt(i, tmpColor);
  });
  trunksInst.instanceMatrix.needsUpdate = true;
  canopiesInst.instanceMatrix.needsUpdate = true;
  if (canopiesInst.instanceColor) canopiesInst.instanceColor.needsUpdate = true;
  trunksInst.computeBoundingSphere();
  canopiesInst.computeBoundingSphere();
  group.add(trunksInst, canopiesInst);

  // Glowing Streetlamp Orbs along avenues around HQ
  const lampCoords: Array<[number, number]> = [];
  for (let i = -3; i <= 3; i++) {
    const p = i * 18;
    lampCoords.push([p, 30], [p, -30], [30, p], [-30, p]);
  }
  const lampOrbGeo = trackGeo(new THREE.SphereGeometry(0.42, 8, 8));
  const lampOrbMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xfff5d6,
      emissive: new THREE.Color(0xffb84d),
      emissiveIntensity: 0.25,
      roughness: 0.3,
    }),
  );
  const lampPoleGeo = trackGeo(new THREE.CylinderGeometry(0.08, 0.1, 4.2, 6));
  const lampPolesInst = new THREE.InstancedMesh(lampPoleGeo, darkMetalMat, lampCoords.length);
  const lampOrbsInst = new THREE.InstancedMesh(lampOrbGeo, lampOrbMat, lampCoords.length);
  lampCoords.forEach(([lx, lz], i) => {
    dummy.position.set(lx, STREET_Y + 2.1, lz);
    dummy.scale.set(1, 1, 1);
    dummy.rotation.set(0, 0, 0);
    dummy.updateMatrix();
    lampPolesInst.setMatrixAt(i, dummy.matrix);

    dummy.position.set(lx, STREET_Y + 4.35, lz);
    dummy.updateMatrix();
    lampOrbsInst.setMatrixAt(i, dummy.matrix);
  });
  lampPolesInst.instanceMatrix.needsUpdate = true;
  lampOrbsInst.instanceMatrix.needsUpdate = true;
  lampPolesInst.computeBoundingSphere();
  lampOrbsInst.computeBoundingSphere();
  group.add(lampPolesInst, lampOrbsInst);

  // =========================================================================
  // 6. ANIMATED CITY TRAFFIC CARS (28 Gliding Cars along Avenues below!)
  // =========================================================================
  const cars: TrafficCar[] = [];
  const carColors = [0xdc2626, 0x2563eb, 0xf8fafc, 0xf59e0b, 0x10b981, 0x475569];
  const avenueLines = [-33.5, 33.5, -108, 108];

  for (let i = 0; i < 28; i++) {
    const axis: 'x' | 'z' = i % 2 === 0 ? 'x' : 'z';
    const dir: 1 | -1 = i % 4 < 2 ? 1 : -1;
    const baseAve = avenueLines[i % avenueLines.length];
    cars.push({
      axis,
      lanePos: baseAve + dir * 2.2,
      coord: -120 + ((i * 27) % 240),
      dir,
      speed: 7.5 + (i % 5) * 1.9,
      color: new THREE.Color(carColors[i % carColors.length]),
    });
  }

  const carGeo = trackGeo(new THREE.BoxGeometry(1.5, 0.72, 3.1));
  const carMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.35,
      metalness: 0.35,
    }),
  );
  const carsInst = new THREE.InstancedMesh(carGeo, carMat, cars.length);
  carsInst.frustumCulled = false;

  const headlightGeo = trackGeo(new THREE.BoxGeometry(1.15, 0.25, 0.25));
  const headlightMat = trackMat(
    new THREE.MeshBasicMaterial({
      color: 0xfff3c4,
    }),
  );
  const headlightsInst = new THREE.InstancedMesh(headlightGeo, headlightMat, cars.length);
  headlightsInst.frustumCulled = false;

  cars.forEach((c, i) => {
    carsInst.setColorAt(i, c.color);
  });
  if (carsInst.instanceColor) carsInst.instanceColor.needsUpdate = true;
  group.add(carsInst, headlightsInst);

  // Hidden by default while user is zoomed inside the office room!
  group.visible = false;

  return {
    group,
    groundMat,
    setNightGlow: (intensity: number) => {
      // Smoothly illuminate skyscraper windows, HQ curtain walls & streetlights at Sunset / Night / Storm!
      const windowGlow = 0.08 + intensity * 0.95;
      cityTowerMat.emissiveIntensity = windowGlow;
      hqGlassMat.emissiveIntensity = 0.1 + intensity * 0.85;
      lampOrbMat.emissiveIntensity = 0.2 + intensity * 2.4;
    },
    update: (dt, _elapsed, exteriorReveal) => {
      // Completely hide the exterior tower & city when user is inside the room!
      const showCity = exteriorReveal > 0.015;
      group.visible = showCity;
      if (!showCity) return;

      // Smoothly reveal the rooftop perimeter crown, glass facade & "AI AGENT TOWER" sign!
      const roofAlpha = THREE.MathUtils.clamp((exteriorReveal - 0.18) / 0.72, 0, 1);
      roofCrownGroup.visible = roofAlpha > 0.01;
      if (roofCrownGroup.visible) {
        roofRimMat.opacity = roofAlpha * 0.96;
        roofGlassMat.opacity = roofAlpha * 0.22;
        roofSignMat.opacity = roofAlpha;
      }

      // Advance animated city traffic smoothly along avenues
      for (let i = 0; i < cars.length; i++) {
        const c = cars[i];
        c.coord += c.dir * c.speed * dt;
        if (c.coord > 135) c.coord = -135;
        if (c.coord < -135) c.coord = 135;

        if (c.axis === 'z') {
          dummy.position.set(c.lanePos, STREET_Y + 0.42, c.coord);
          dummy.rotation.set(0, c.dir > 0 ? 0 : Math.PI, 0);
        } else {
          dummy.position.set(c.coord, STREET_Y + 0.42, c.lanePos);
          dummy.rotation.set(0, c.dir > 0 ? Math.PI * 0.5 : -Math.PI * 0.5, 0);
        }
        dummy.scale.set(1, 1, 1);
        dummy.updateMatrix();
        carsInst.setMatrixAt(i, dummy.matrix);

        // Headlight bar at front nose of car
        if (c.axis === 'z') {
          dummy.position.set(c.lanePos, STREET_Y + 0.4, c.coord + c.dir * 1.55);
        } else {
          dummy.position.set(c.coord + c.dir * 1.55, STREET_Y + 0.4, c.lanePos);
        }
        dummy.updateMatrix();
        headlightsInst.setMatrixAt(i, dummy.matrix);
      }
      carsInst.instanceMatrix.needsUpdate = true;
      headlightsInst.instanceMatrix.needsUpdate = true;
    },
    dispose: () => {
      textures.forEach((t) => t.dispose());
      geometries.forEach((g) => g.dispose());
      materials.forEach((m) => m.dispose());
    },
  };
}
