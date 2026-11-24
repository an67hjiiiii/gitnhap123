import * as THREE from 'three';
import { AGENT_PROFILES, SPECIALIST_AGENT_IDS } from '../agents';
import { mergeStaticMeshes } from './mergeStatic';
import type { AgentId, SpecialistAgentId } from '../types';
import type { StudioMaterialLibrary } from './materials';
import type { StudioTextureSet } from './textures';

export interface StudioArchitectureInstance {
  group: THREE.Group;
  stationColliders: THREE.Mesh[];
  setAwakeAgents: (awakeIds: Set<AgentId>) => void;
  setLeadHighlight: (agentId: AgentId | null) => void;
  setAtmosphereLight: (warmLampIntensity: number) => void;
  setExteriorReveal: (reveal: number, indoorBgColor: THREE.Color) => void;
  setEffects: (effects: {
    requestArrived: boolean;
    cabinetOpen: boolean;
    whiteboardCards: number;
    analystChartActive: boolean;
    qcApproved: boolean;
    finalReportReady: boolean;
  }) => void;
  update: (dt: number, elapsed: number) => void;
  dispose: () => void;
}

/**
 * High-Craft Realistic Architectural Cutaway Office (17.6m x 13.4m):
 * - Rich Smoked Honey-Walnut Hardwood Plank Floors (with real bump grain!)
 * - Matte Architectural Stucco Cutaway Walls with dark charcoal caps, floor baseboards & framed glass windows
 * - Warm Cozy Interior Lamps (desk lamps + warm interior pool PointLights glowing brightly at Sunset / Night / Storm!)
 * - Live 3D Mission Control Wall, Sliding-Drawer RAG Filing Cabinet + Bookshelf,
 *   Analyst Drafting Desk + Chart Easel, Reviewer Inspection Desk, Integrator Studio & 6 Computer Bays!
 */
export function buildStudioArchitecture(
  materials: StudioMaterialLibrary,
  textures: StudioTextureSet,
): StudioArchitectureInstance {
  const group = new THREE.Group();
  group.name = 'realistic_agent_office';

  const geometries: THREE.BufferGeometry[] = [];
  const extraMats: THREE.Material[] = [];
  const stationColliders: THREE.Mesh[] = [];

  const trackGeo = <T extends THREE.BufferGeometry>(g: T): T => {
    geometries.push(g);
    return g;
  };
  const trackMat = <T extends THREE.Material>(m: T): T => {
    extraMats.push(m);
    return m;
  };

  // 0. Cozy Interior Studio Surround Plane (solid while inside the room so only the room is visible;
  // fades smoothly away as the user scrolls out to reveal the HQ Tower & 360° City!)
  const interiorSurroundMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xe8e2d7,
      roughness: 0.96,
      metalness: 0.0,
      transparent: true,
      opacity: 1,
    }),
  );
  const interiorSurround = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(240, 240)),
    interiorSurroundMat,
  );
  interiorSurround.rotation.x = -Math.PI / 2;
  interiorSurround.position.y = -0.37;
  interiorSurround.receiveShadow = true;
  group.add(interiorSurround);

  // 1. Penthouse Sky-Terrace Structural Base Slab (sits atop the 8-story AI Agent HQ Tower!)
  const slabW = 17.6;
  const slabD = 13.4;

  const plinth = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(slabW + 1.1, 0.36, slabD + 1.1)),
    materials.basePlinth,
  );
  plinth.position.set(0, -0.2, 0);
  plinth.receiveShadow = true;
  group.add(plinth);

  const floorDeck = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(slabW, 0.04, slabD)),
    materials.oakFloor,
  );
  floorDeck.position.set(0, -0.02, 0);
  floorDeck.receiveShadow = true;
  group.add(floorDeck);

  // Sleek Penthouse South Glass Balcony Parapet overlooking the city skyline!
  const southGlassRailing = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(slabW - 0.5, 0.72, 0.06)),
    materials.glassPanel,
  );
  southGlassRailing.position.set(0, 0.36, slabD * 0.5 - 0.04);
  southGlassRailing.renderOrder = 3;
  group.add(southGlassRailing);

  const southHandrail = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(slabW, 0.055, 0.1)),
    materials.cutawayWallCap,
  );
  southHandrail.position.set(0, 0.74, slabD * 0.5 - 0.04);
  group.add(southHandrail);

  // 3. Thick Matte Plaster Cutaway Walls with Dark Charcoal Cross-Section Cap & Wooden Baseboards!
  const addCutawayWall = (x: number, z: number, w: number, h: number, d: number) => {
    const wall = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w, h, d)),
      materials.plasterWall,
    );
    wall.position.set(x, h * 0.5, z);
    wall.castShadow = true;
    wall.receiveShadow = true;
    group.add(wall);

    const cap = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w + 0.012, 0.055, d + 0.012)),
      materials.cutawayWallCap,
    );
    cap.position.set(x, h + 0.028, z);
    group.add(cap);

    // Subtle dark walnut floor baseboard trim
    const baseboard = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w + 0.03, 0.14, d + 0.03)),
      materials.darkWalnutWood,
    );
    baseboard.position.set(x, 0.07, z);
    group.add(baseboard);
  };

  const wallH = 2.95;
  const wallT = 0.28;
  addCutawayWall(0, -slabD * 0.5 + wallT * 0.5, slabW, wallH, wallT);
  // West & East walls segmented with tall architectural window openings!
  addCutawayWall(-slabW * 0.5 + wallT * 0.5, -4.6, wallT, wallH, 4.1);
  addCutawayWall(-slabW * 0.5 + wallT * 0.5, 1.5, wallT, wallH, 3.2);
  addCutawayWall(-slabW * 0.5 + wallT * 0.5, -1.25, wallT, 0.85, 2.7); // Window sill West
  addCutawayWall(slabW * 0.5 - wallT * 0.5, -4.6, wallT, wallH, 4.1);
  addCutawayWall(slabW * 0.5 - wallT * 0.5, 1.5, wallT, wallH, 3.2);
  addCutawayWall(slabW * 0.5 - wallT * 0.5, -1.25, wallT, 0.85, 2.7); // Window sill East
  // Low south corner returns
  addCutawayWall(-slabW * 0.5 + wallT * 0.5, 4.9, wallT, 1.05, 3.6);
  addCutawayWall(slabW * 0.5 - wallT * 0.5, 4.9, wallT, 1.05, 3.6);

  // Architectural Window Frames & Glass Panes (let sunset/moonlight/rain feel super real!)
  [-slabW * 0.5 + wallT * 0.5, slabW * 0.5 - wallT * 0.5].forEach((wx) => {
    const glass = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.05, 1.95, 2.55)),
      materials.glassPanel,
    );
    glass.position.set(wx, 1.85, -1.25);
    glass.renderOrder = 3;
    group.add(glass);

    const mullion = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.09, 1.98, 0.06)),
      materials.cutawayWallCap,
    );
    mullion.position.set(wx, 1.85, -1.25);
    group.add(mullion);

    const header = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(wallT + 0.01, 0.14, 2.7)),
      materials.cutawayWallCap,
    );
    header.position.set(wx, wallH - 0.04, -1.25);
    group.add(header);
  });

  // Rich Woven Wool Area Rugs
  const addRug = (x: number, z: number, w: number, d: number, mat: THREE.Material) => {
    const rug = new THREE.Mesh(trackGeo(new THREE.PlaneGeometry(w, d)), mat);
    rug.rotation.x = -Math.PI / 2;
    rug.position.set(x, 0.012, z);
    rug.receiveShadow = true;
    group.add(rug);
  };
  addRug(0, -0.45, 5.4, 3.5, materials.rugBlue);
  addRug(-5.4, -0.1, 3.9, 3.0, materials.rugSand);
  addRug(5.4, -0.1, 3.9, 3.0, materials.rugSand);
  addRug(0, -4.25, 5.2, 2.7, materials.rugSand);

  // Warm Interior Architectural Pool Lights (turn ON cozily at Sunset, Night & Storm!)
  const interiorLights: THREE.PointLight[] = [];
  const lampPositions: Array<[number, number, number]> = [
    [0, 3.1, -2.6], // Central Orchestrator & Huddle warm glow
    [-5.4, 2.6, -1.8], // RAG & Data Analyst warm glow
    [5.4, 2.6, -1.8], // Integrator & Reviewer warm glow
    [0, 2.8, 4.4], // 6 Specialist Computer Bays warm glow
  ];
  lampPositions.forEach(([lx, ly, lz]) => {
    const pl = new THREE.PointLight(0xffb86c, 0, 12.5, 1.6);
    pl.position.set(lx, ly, lz);
    group.add(pl);
    interiorLights.push(pl);
  });

  // Reusable Architectural Desk Lamp (glows warmly during Sunset / Night / Storm!)
  const addDeskLamp = (parent: THREE.Object3D, x: number, y: number, z: number) => {
    const l = new THREE.Group();
    l.position.set(x, y, z);
    const base = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.085, 0.095, 0.03, 14)),
      materials.brassAccent,
    );
    l.add(base);
    const stem = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.014, 0.014, 0.42, 8)),
      materials.brassAccent,
    );
    stem.position.y = 0.21;
    l.add(stem);
    const shade = new THREE.Mesh(
      trackGeo(new THREE.ConeGeometry(0.135, 0.16, 16)),
      materials.lampShadeGlow,
    );
    shade.position.set(-0.07, 0.41, 0.04);
    shade.rotation.z = 0.34;
    l.add(shade);
    parent.add(l);
  };

  // Rich Multi-Layered Botanical Indoor Trees in Terracotta / Stoneware Planters
  const addPottedTree = (x: number, z: number, scale = 1.0) => {
    const p = new THREE.Group();
    p.position.set(x, 0, z);
    p.scale.setScalar(scale);

    const ao = new THREE.Mesh(
      trackGeo(new THREE.PlaneGeometry(1.0, 1.0)),
      materials.contactShadow,
    );
    ao.rotation.x = -Math.PI / 2;
    ao.position.y = 0.015;
    p.add(ao);

    const pot = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.25, 0.18, 0.38, 16)),
      materials.terracottaPot,
    );
    pot.position.y = 0.19;
    pot.castShadow = true;
    p.add(pot);

    const trunk = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.034, 0.052, 0.68, 8)),
      materials.darkWalnutWood,
    );
    trunk.position.y = 0.58;
    p.add(trunk);

    const leafGeo = trackGeo(new THREE.DodecahedronGeometry(0.22, 1));
    [
      [0, 1.1, 0, 1.04, true],
      [0.21, 0.94, 0.13, 0.84, false],
      [-0.2, 0.96, 0.11, 0.86, true],
      [0.09, 0.9, -0.19, 0.8, false],
      [-0.13, 0.86, -0.17, 0.76, true],
    ].forEach(([lx, ly, lz, sc, rich]) => {
      const leaf = new THREE.Mesh(
        leafGeo,
        rich ? materials.plantLeafRich : materials.plantLeafLight,
      );
      leaf.position.set(lx as number, ly as number, lz as number);
      leaf.scale.setScalar(sc as number);
      leaf.castShadow = true;
      p.add(leaf);
    });
    group.add(p);
  };

  const addPlanterBox = (x: number, z: number, w: number) => {
    const g = new THREE.Group();
    g.position.set(x, 0, z);

    const box = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w, 0.42, 0.42)),
      materials.darkWalnutWood,
    );
    box.position.y = 0.21;
    box.castShadow = true;
    box.receiveShadow = true;
    g.add(box);

    const bushGeo = trackGeo(new THREE.DodecahedronGeometry(0.18, 1));
    const count = Math.max(3, Math.floor(w / 0.34));
    for (let i = 0; i < count; i++) {
      const bx = -w * 0.41 + (i / (count - 1)) * w * 0.82;
      const b = new THREE.Mesh(
        bushGeo,
        i % 2 === 0 ? materials.plantLeafRich : materials.plantLeafLight,
      );
      b.position.set(bx, 0.53 + (i % 2) * 0.05, ((i % 3) - 1) * 0.04);
      b.scale.set(1.06, 0.86, 0.96);
      b.castShadow = true;
      g.add(b);
    }
    group.add(g);
  };

  addPottedTree(-8.05, -5.85, 1.18);
  addPottedTree(8.05, -5.85, 1.18);
  addPottedTree(-8.05, 1.75, 0.98);
  addPottedTree(8.05, 1.75, 0.98);
  addPlanterBox(-4.6, 2.75, 2.45);
  addPlanterBox(4.6, 2.75, 2.45);

  const addOfficeChair = (parent: THREE.Object3D, x: number, z: number, rotY: number) => {
    const ch = new THREE.Group();
    ch.position.set(x, 0, z);
    ch.rotation.y = rotY;

    const base = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.23, 0.26, 0.04, 14)),
      materials.darkMonitorFrame,
    );
    base.position.y = 0.03;
    ch.add(base);

    const stem = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.032, 0.032, 0.29, 10)),
      materials.darkMonitorFrame,
    );
    stem.position.y = 0.19;
    ch.add(stem);

    const seat = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.46, 0.075, 0.44)),
      materials.fabricChairBlue,
    );
    seat.position.y = 0.36;
    seat.castShadow = true;
    ch.add(seat);

    const back = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.42, 0.46, 0.065)),
      materials.fabricChairBlue,
    );
    back.position.set(0, 0.62, 0.19);
    back.castShadow = true;
    ch.add(back);

    parent.add(ch);
  };

  // Rich Walnut Top + Powder-Coated Charcoal Metal Legs (realistic architectural furniture!)
  const addWalnutDeskShell = (
    parent: THREE.Object3D,
    x: number,
    z: number,
    rotY: number,
    width: number,
    depth = 0.84,
  ): THREE.Group => {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    g.rotation.y = rotY;

    const ao = new THREE.Mesh(
      trackGeo(new THREE.PlaneGeometry(width + 0.55, depth + 0.6)),
      materials.contactShadow,
    );
    ao.rotation.x = -Math.PI / 2;
    ao.position.y = 0.014;
    g.add(ao);

    const top = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(width, 0.072, depth)),
      materials.oakDesk,
    );
    top.position.y = 0.72;
    top.castShadow = true;
    top.receiveShadow = true;
    g.add(top);

    [-width * 0.45, width * 0.45].forEach((lx) => {
      const leg = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.055, 0.7, depth - 0.12)),
        materials.darkMonitorFrame,
      );
      leg.position.set(lx, 0.35, 0);
      leg.castShadow = true;
      g.add(leg);
    });

    parent.add(g);
    return g;
  };

  // =========================================================================
  // 1. NORTH CENTER: LIVE 3D MISSION CONTROL WALL + ORCHESTRATOR PLANNING BOARD
  // =========================================================================
  const missionFrame = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(6.6, 2.2, 0.12)),
    materials.darkMonitorFrame,
  );
  missionFrame.position.set(0, 1.72, -6.34);
  missionFrame.castShadow = true;
  group.add(missionFrame);

  const missionFace = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(6.35, 2.0)),
    materials.missionWallMat,
  );
  missionFace.position.set(0, 1.72, -6.27);
  group.add(missionFace);

  const planBoardGroup = new THREE.Group();
  planBoardGroup.position.set(0.2, 0, -5.05);
  group.add(planBoardGroup);

  [-1.25, 1.25].forEach((px) => {
    const leg = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.025, 0.025, 1.55, 10)),
      materials.darkMonitorFrame,
    );
    leg.position.set(px, 0.78, 0);
    planBoardGroup.add(leg);
  });
  const planGlass = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(2.65, 1.12, 0.04)),
    materials.planningBoardMat,
  );
  planGlass.position.set(0, 1.15, 0);
  planGlass.castShadow = true;
  planBoardGroup.add(planGlass);

  const wbCards: THREE.Mesh[] = [];
  const cardColors = [0xf59e0b, 0x0284c7, 0x059669, 0xea580c, 0x6d28d9, 0xdb2777];
  const cardGeo = trackGeo(new THREE.BoxGeometry(0.32, 0.2, 0.024));
  for (let i = 0; i < 6; i++) {
    const c = new THREE.Mesh(
      cardGeo,
      trackMat(new THREE.MeshStandardMaterial({ color: cardColors[i], roughness: 0.55 })),
    );
    c.position.set(-0.78 + (i % 3) * 0.78, 1.32 - Math.floor(i / 3) * 0.34, 0.036);
    c.visible = false;
    planBoardGroup.add(c);
    wbCards.push(c);
  }

  // Central Low Walnut Reception Pedestal
  const receptionGroup = new THREE.Group();
  receptionGroup.position.set(0, 0, -0.45);
  group.add(receptionGroup);

  const recTable = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.68, 0.58, 0.44, 28)),
    materials.oakDesk,
  );
  recTable.position.y = 0.22;
  recTable.castShadow = true;
  recTable.receiveShadow = true;
  receptionGroup.add(recTable);

  const requestEnvelope = new THREE.Group();
  requestEnvelope.position.set(0, 0.66, 0);
  requestEnvelope.visible = false;
  const envBody = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.46, 0.06, 0.32)),
    materials.createAccentGlow(0xd97706, 0.72),
  );
  envBody.castShadow = true;
  requestEnvelope.add(envBody);
  const envRing = new THREE.Mesh(
    trackGeo(new THREE.TorusGeometry(0.38, 0.02, 10, 32)),
    materials.createAccentGlow(0x38bdf8, 0.85),
  );
  envRing.rotation.x = Math.PI / 2;
  requestEnvelope.add(envRing);
  receptionGroup.add(requestEnvelope);

  // =========================================================================
  // 2. NORTH-LEFT: TỦ HỒ SƠ TÀI LIỆU RAG + THƯ VIỆN SÁCH GỖ ÓC CHÓ
  // =========================================================================
  const ragZone = new THREE.Group();
  ragZone.position.set(-5.6, 0, -5.65);
  group.add(ragZone);

  const cabBody = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(1.15, 1.85, 0.78)),
    materials.darkWalnutWood,
  );
  cabBody.position.set(0.15, 0.925, 0);
  cabBody.castShadow = true;
  cabBody.receiveShadow = true;
  ragZone.add(cabBody);

  [1.52, 0.68, 0.28].forEach((dy) => {
    const face = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(1.02, 0.34, 0.05)),
      materials.oakDesk,
    );
    face.position.set(0.15, dy, 0.4);
    ragZone.add(face);
    const pull = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.24, 0.035, 0.04)),
      materials.brassAccent,
    );
    pull.position.set(0.15, dy + 0.04, 0.44);
    ragZone.add(pull);
  });

  // Animated Sliding Drawer packed with Colorful Hanging Folders
  const slidingDrawer = new THREE.Group();
  slidingDrawer.position.set(0.15, 1.1, 0.02);
  ragZone.add(slidingDrawer);

  const drBox = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.98, 0.3, 0.72)),
    materials.ceramicWhite,
  );
  slidingDrawer.add(drBox);

  const drFront = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(1.02, 0.34, 0.05)),
    materials.oakDesk,
  );
  drFront.position.z = 0.38;
  slidingDrawer.add(drFront);
  const drHandle = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.24, 0.035, 0.04)),
    materials.brassAccent,
  );
  drHandle.position.set(0, 0.04, 0.42);
  slidingDrawer.add(drHandle);

  const folderPalette = [0x059669, 0x1d4ed8, 0xd97706, 0xdb2777, 0x6d28d9];
  folderPalette.forEach((hex, idx) => {
    const f = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.84, 0.26, 0.055)),
      trackMat(new THREE.MeshStandardMaterial({ color: hex, roughness: 0.55 })),
    );
    f.position.set(0, 0.08, -0.22 + idx * 0.11);
    slidingDrawer.add(f);
  });

  // Tall Walnut Library Bookshelf packed with rich reference binders
  const shelf = new THREE.Group();
  shelf.position.set(-1.35, 0, 0.05);
  ragZone.add(shelf);

  const shelfBack = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(1.35, 2.25, 0.42)),
    materials.darkWalnutWood,
  );
  shelfBack.position.y = 1.125;
  shelfBack.castShadow = true;
  shelf.add(shelfBack);

  const bookColors = [0x0284c7, 0x059669, 0xd97706, 0xdc2626, 0x6d28d9, 0x0f766e];
  for (let row = 0; row < 4; row++) {
    const sy = 0.35 + row * 0.5;
    for (let b = 0; b < 6; b++) {
      const book = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.14, 0.32 + (b % 2) * 0.05, 0.28)),
        trackMat(
          new THREE.MeshStandardMaterial({
            color: bookColors[(row * 3 + b) % bookColors.length],
            roughness: 0.62,
          }),
        ),
      );
      book.position.set(-0.48 + b * 0.19, sy, 0.14);
      shelf.add(book);
    }
  }

  const ragSideDesk = addWalnutDeskShell(group, -7.25, -3.2, Math.PI * 0.5, 1.35, 0.68);
  addDeskLamp(ragSideDesk, 0.45, 0.77, -0.15);
  addOfficeChair(group, -6.45, -3.2, -Math.PI * 0.5);

  // =========================================================================
  // 3. MID-LEFT: BÀN BẢN VẼ & GIÁ BIỂU ĐỒ (Data Analyst — Bút, Thước, Máy tính!)
  // =========================================================================
  const analystDesk = addWalnutDeskShell(group, -5.4, -0.35, 0, 2.2, 0.96);
  addOfficeChair(group, -5.4, 0.45, 0);
  addDeskLamp(analystDesk, -0.82, 0.77, -0.26);

  const draftSheet = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(1.18, 0.74)),
    materials.draftingPaperMat,
  );
  draftSheet.rotation.x = -Math.PI / 2;
  draftSheet.position.set(-0.08, 0.758, 0.02);
  analystDesk.add(draftSheet);

  const deskCalc = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.24, 0.04, 0.32)),
    materials.darkMonitorFrame,
  );
  deskCalc.position.set(0.68, 0.775, 0.08);
  deskCalc.rotation.y = -0.22;
  analystDesk.add(deskCalc);

  const deskRuler = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.56, 0.015, 0.075)),
    trackMat(new THREE.MeshStandardMaterial({ color: 0xfacc15, roughness: 0.45 })),
  );
  deskRuler.position.set(-0.22, 0.766, 0.25);
  deskRuler.rotation.y = 0.18;
  analystDesk.add(deskRuler);

  const cup = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.055, 0.048, 0.13, 12)),
    materials.terracottaPot,
  );
  cup.position.set(0.75, 0.82, -0.24);
  analystDesk.add(cup);

  const easelGroup = new THREE.Group();
  easelGroup.position.set(-3.75, 0, -0.85);
  easelGroup.rotation.y = -Math.PI * 0.22;
  group.add(easelGroup);

  const easelBoard = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(1.1, 1.32, 0.05)),
    materials.darkWalnutWood,
  );
  easelBoard.position.set(0, 1.38, 0);
  easelBoard.rotation.x = -0.14;
  easelBoard.castShadow = true;
  easelGroup.add(easelBoard);

  const easelFace = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(0.98, 1.2)),
    materials.easelChartMat,
  );
  easelFace.position.set(0, 1.38, 0.032);
  easelFace.rotation.x = -0.14;
  easelGroup.add(easelFace);

  [-0.42, 0.42].forEach((ex) => {
    const leg = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.026, 0.026, 1.75, 8)),
      materials.darkWalnutWood,
    );
    leg.position.set(ex, 0.85, 0.05);
    leg.rotation.x = -0.12;
    easelGroup.add(leg);
  });

  const analystHoloGroup = new THREE.Group();
  analystHoloGroup.position.set(-5.4, 0.92, -0.35);
  analystHoloGroup.visible = false;
  const analystBars: THREE.Mesh[] = [];
  const barGeo = trackGeo(new THREE.BoxGeometry(0.11, 0.56, 0.11));
  const barMat = materials.createAccentGlow(0x2563eb, 0.78);
  for (let i = 0; i < 4; i++) {
    const b = new THREE.Mesh(barGeo, barMat);
    b.position.set(-0.27 + i * 0.18, 0.28, -0.2);
    analystHoloGroup.add(b);
    analystBars.push(b);
  }
  group.add(analystHoloGroup);

  // =========================================================================
  // 4. MID-RIGHT: BÀN KIỂM ĐỊNH CHẤT LƯỢNG (Reviewer)
  // =========================================================================
  const qcDesk = addWalnutDeskShell(group, 5.4, -0.35, 0, 2.05, 0.9);
  addOfficeChair(group, 5.4, 0.45, 0);
  addDeskLamp(qcDesk, 0.78, 0.77, -0.24);

  for (let i = 0; i < 2; i++) {
    const stack = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.42, 0.07, 0.52)),
      materials.ceramicWhite,
    );
    stack.position.set(-0.48 + i * 0.92, 0.79, -0.02);
    stack.rotation.y = i === 0 ? 0.12 : -0.15;
    stack.castShadow = true;
    qcDesk.add(stack);
  }
  const stampPad = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.18, 0.04, 0.14)),
    materials.createAccentGlow(0x059669, 0.55),
  );
  stampPad.position.set(0.06, 0.775, -0.16);
  qcDesk.add(stampPad);

  const qcBadgeGroup = new THREE.Group();
  qcBadgeGroup.position.set(5.4, 1.35, -0.35);
  qcBadgeGroup.visible = false;
  const qcRing = new THREE.Mesh(
    trackGeo(new THREE.TorusGeometry(0.28, 0.036, 12, 28)),
    materials.createAccentGlow(0x10b981, 0.92),
  );
  qcBadgeGroup.add(qcRing);
  group.add(qcBadgeGroup);

  // =========================================================================
  // 5. NORTH-RIGHT: BÀN BIÊN TẬP & ĐÓNG QUYỂN (Integrator — Gộp Writer!)
  // =========================================================================
  const intDesk = addWalnutDeskShell(group, 5.6, -4.25, 0, 2.2, 0.92);
  addOfficeChair(group, 5.6, -3.45, 0);
  addDeskLamp(intDesk, 0.78, 0.77, -0.22);

  const intMonFrame = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.92, 0.5, 0.04)),
    materials.darkMonitorFrame,
  );
  intMonFrame.position.set(-0.28, 1.12, -0.22);
  intMonFrame.castShadow = true;
  intDesk.add(intMonFrame);
  const intMonStand = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.03, 0.045, 0.24, 10)),
    materials.darkMonitorFrame,
  );
  intMonStand.position.set(-0.28, 0.85, -0.22);
  intDesk.add(intMonStand);
  const intMonScr = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(0.86, 0.44)),
    materials.createScreenMat(textures.screenEducationMap),
  );
  intMonScr.position.set(-0.28, 1.12, -0.198);
  intDesk.add(intMonScr);

  const finalReportGroup = new THREE.Group();
  finalReportGroup.position.set(5.6, 1.48, -4.15);
  finalReportGroup.visible = false;
  const bookCover = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.42, 0.52, 0.08)),
    materials.createAccentGlow(0x6d28d9, 0.78),
  );
  bookCover.rotation.y = -0.3;
  finalReportGroup.add(bookCover);
  const bookHalo = new THREE.Mesh(
    trackGeo(new THREE.TorusGeometry(0.45, 0.022, 10, 32)),
    materials.createAccentGlow(0xd97706, 0.95),
  );
  bookHalo.rotation.x = Math.PI * 0.42;
  finalReportGroup.add(bookHalo);
  group.add(finalReportGroup);

  // =========================================================================
  // 6. SOUTH WING: 6 PHÒNG BAN CHUYÊN NGÀNH LÀM VIỆC TRÊN MÁY TÍNH!
  // =========================================================================
  const specScreenMeshes: Partial<Record<SpecialistAgentId, THREE.Mesh>> = {};
  const specActiveScreenMats: Record<SpecialistAgentId, THREE.MeshStandardMaterial> = {
    software: materials.createScreenMat(textures.screenCodeMap),
    business: materials.createScreenMat(textures.screenBusinessMap),
    marketing: materials.createScreenMat(textures.screenMarketingMap),
    hr: materials.createScreenMat(textures.screenHrMap),
    finance: materials.createScreenMat(textures.screenFinanceMap),
    education: materials.createScreenMat(textures.screenEducationMap),
  };
  const specStripMats: Partial<Record<SpecialistAgentId, THREE.MeshStandardMaterial>> = {};

  for (let idx = 0; idx < SPECIALIST_AGENT_IDS.length; idx++) {
    const specId = SPECIALIST_AGENT_IDS[idx];
    const p = AGENT_PROFILES[specId];
    const [cx, cz] = p.stationCenter;

    const bay = new THREE.Group();
    bay.position.set(cx, 0, cz);
    group.add(bay);

    const pad = new THREE.Mesh(
      trackGeo(new THREE.PlaneGeometry(2.42, 2.7)),
      materials.rugSand,
    );
    pad.rotation.x = -Math.PI / 2;
    pad.position.y = 0.011;
    pad.receiveShadow = true;
    bay.add(pad);

    const stripMat = materials.createAccentGlow(p.accentNumber, 0.16);
    specStripMats[specId] = stripMat;
    const strip = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(2.15, 0.025, 0.08)),
      stripMat,
    );
    strip.position.set(0, 0.018, -1.32);
    bay.add(strip);

    if (idx < SPECIALIST_AGENT_IDS.length - 1) {
      const divBase = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.055, 0.65, 2.15)),
        materials.darkWalnutWood,
      );
      divBase.position.set(1.35, 0.325, 0.12);
      divBase.castShadow = true;
      bay.add(divBase);

      const divGlass = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.03, 0.46, 2.1)),
        materials.glassPanel,
      );
      divGlass.position.set(1.35, 0.88, 0.12);
      divGlass.renderOrder = 2;
      bay.add(divGlass);
    }

    const desk = addWalnutDeskShell(bay, 0, 0.68, Math.PI, 2.05, 0.82);
    addOfficeChair(bay, 0, -0.1, Math.PI);
    addDeskLamp(desk, 0.78, 0.77, -0.2);

    const stand = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.03, 0.045, 0.24, 10)),
      materials.darkMonitorFrame,
    );
    stand.position.set(0, 0.85, -0.22);
    desk.add(stand);

    const frame = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(1.12, 0.56, 0.04)),
      materials.darkMonitorFrame,
    );
    frame.position.set(0, 1.15, -0.22);
    frame.castShadow = true;
    desk.add(frame);

    const scr = new THREE.Mesh(
      trackGeo(new THREE.PlaneGeometry(1.04, 0.48)),
      materials.screenSleepMat,
    );
    scr.position.set(0, 1.15, -0.197);
    desk.add(scr);
    specScreenMeshes[specId] = scr;

    const kb = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.46, 0.02, 0.15)),
      materials.whiteChairShell,
    );
    kb.position.set(-0.08, 0.768, 0.14);
    desk.add(kb);

    const mouse = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.07, 0.022, 0.1)),
      materials.whiteChairShell,
    );
    mouse.position.set(0.3, 0.768, 0.15);
    desk.add(mouse);

    const col = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(2.5, 0.45, 2.8)),
      trackMat(new THREE.MeshBasicMaterial({ visible: false })),
    );
    col.position.set(cx, 0.22, cz);
    col.userData.agentId = specId;
    col.layers.set(1);
    group.add(col);
    stationColliders.push(col);
  }

  let awakeSet = new Set<AgentId>();
  let leadAgent: AgentId | null = null;
  let fx = {
    requestArrived: false,
    cabinetOpen: false,
    whiteboardCards: 0,
    analystChartActive: false,
    qcApproved: false,
    finalReportReady: false,
  };

  // Đợt 2: gộp khối tĩnh theo vật liệu (giữ nguyên các vật có chuyển động/ẩn hiện/đổi vật liệu)
  geometries.push(...mergeStaticMeshes(group, [
    interiorSurround, southGlassRailing, southHandrail, requestEnvelope, slidingDrawer, analystHoloGroup,
    qcBadgeGroup, finalReportGroup, ...wbCards, ...stationColliders,
    ...Object.values(specScreenMeshes).filter((x): x is THREE.Mesh => !!x),
  ]));

  return {
    group,
    stationColliders,
    setAwakeAgents: (ids) => {
      awakeSet = new Set(ids);
      for (const specId of SPECIALIST_AGENT_IDS) {
        const mesh = specScreenMeshes[specId];
        if (!mesh) continue;
        mesh.material = awakeSet.has(specId)
          ? specActiveScreenMats[specId]
          : materials.screenSleepMat;
      }
    },
    setLeadHighlight: (id) => {
      leadAgent = id;
    },
    setAtmosphereLight: (warmLampIntensity) => {
      for (const pl of interiorLights) {
        pl.intensity = warmLampIntensity * 3.4;
      }
      materials.lampShadeGlow.emissiveIntensity = 0.12 + warmLampIntensity * 1.15;
    },
    setExteriorReveal: (reveal, indoorBgColor) => {
      // Solid inside room (reveal = 0), fades completely out by reveal = 0.55 to expose building & city!
      const surroundOpacity = THREE.MathUtils.clamp(1 - reveal * 1.85, 0, 1);
      interiorSurround.visible = surroundOpacity > 0.01;
      if (interiorSurround.visible) {
        interiorSurroundMat.opacity = surroundOpacity;
        interiorSurroundMat.color.copy(indoorBgColor);
      }
      // Subtle balcony glass rail reveals only when zooming out to building exterior
      southGlassRailing.visible = reveal > 0.05;
      southHandrail.visible = reveal > 0.05;
    },
    setEffects: (next) => {
      fx = next;
    },
    update: (dt, elapsed) => {
      requestEnvelope.visible = fx.requestArrived;
      if (fx.requestArrived) {
        requestEnvelope.position.y = 0.64 + Math.sin(elapsed * 3.0) * 0.06;
        requestEnvelope.rotation.y += dt * 1.1;
      }

      const targetDrawerZ = fx.cabinetOpen ? 0.44 : 0.02;
      slidingDrawer.position.z = THREE.MathUtils.damp(
        slidingDrawer.position.z,
        targetDrawerZ,
        6.5,
        dt,
      );

      wbCards.forEach((card, i) => {
        const show = i < fx.whiteboardCards;
        card.visible = show;
        const sc = THREE.MathUtils.damp(card.scale.x, show ? 1 : 0.01, 10, dt);
        card.scale.setScalar(sc);
      });

      analystHoloGroup.visible = fx.analystChartActive;
      if (fx.analystChartActive) {
        analystBars.forEach((bar, i) => {
          const h = 0.35 + 0.72 * (Math.sin(elapsed * 4.5 + i * 1.2) * 0.5 + 0.5);
          bar.scale.y = THREE.MathUtils.damp(bar.scale.y, h, 8, dt);
          bar.position.y = bar.scale.y * 0.28;
        });
      }

      qcBadgeGroup.visible = fx.qcApproved;
      if (fx.qcApproved) {
        qcBadgeGroup.position.y = 1.38 + Math.sin(elapsed * 3.2) * 0.06;
        qcRing.rotation.y += dt * 1.8;
      }

      finalReportGroup.visible = fx.finalReportReady;
      if (fx.finalReportReady) {
        finalReportGroup.position.y = 1.48 + Math.sin(elapsed * 2.8) * 0.07;
        bookCover.rotation.y += dt * 1.1;
        bookHalo.rotation.z += dt * 1.8;
      }

      for (const specId of SPECIALIST_AGENT_IDS) {
        const mat = specStripMats[specId];
        if (!mat) continue;
        const awake = awakeSet.has(specId);
        const isLead = leadAgent === specId;
        const target = isLead ? 1.65 : awake ? 0.88 : 0.08;
        mat.emissiveIntensity = THREE.MathUtils.damp(mat.emissiveIntensity, target, 6, dt);
      }
    },
    dispose: () => {
      geometries.forEach((g) => g.dispose());
      extraMats.forEach((m) => m.dispose());
    },
  };
}
