import * as THREE from 'three';
import { AGENT_PROFILES } from '../agents';
import type { AgentId, CarryItemKind, RobotAction } from '../types';
import type { StudioMaterialLibrary } from './materials';

export interface BeanRobotInstance {
  id: AgentId;
  root: THREE.Group;
  collider: THREE.Mesh;
  position: THREE.Vector3;
  action: RobotAction;
  carryItem: CarryItemKind;
  setHighlighted: (hovered: boolean, selected: boolean, isLead?: boolean) => void;
  setCarryItem: (kind: CarryItemKind) => void;
  setPoseTarget: (
    x: number,
    z: number,
    yaw: number,
    action: RobotAction,
    isMoving?: boolean,
    seated?: boolean,
  ) => void;
  getLabelAnchorWorld: (out: THREE.Vector3) => THREE.Vector3;
  update: (dt: number, elapsed: number) => void;
  dispose: () => void;
}

type FaceMood = 'happy' | 'focused' | 'excited' | 'thinking' | 'reviewing' | 'sleeping';

const ITEM_COLOR_MAP: Record<CarryItemKind, number> = {
  none: 0xffffff,
  request_brief: 0xe07a00,
  plan_card: 0x0077b6,
  rag_folder: 0x009e73,
  specialist_doc: 0xe65100,
  analytics_sheet: 0x1d4ed8,
  approved_sheet: 0x009e73,
  final_report: 0x6d28d9,
};

/**
 * Bright, iconic Eilik glowing OLED eye color paired vividly with each agent's deep accent!
 */
const OLED_EYE_COLOR: Record<AgentId, string> = {
  orchestrator: '#ffb703',
  rag: '#00f5d4',
  analyst: '#38d9ff',
  reviewer: '#ff4d6d',
  integrator: '#c084fc',
  software: '#00e5ff',
  business: '#2dd4bf',
  marketing: '#ff8a3d',
  hr: '#ff85b3',
  finance: '#34f5a5',
  education: '#818cf8',
};

function shortestAngleDelta(current: number, target: number): number {
  let diff = (target - current + Math.PI) % (Math.PI * 2);
  if (diff < 0) diff += Math.PI * 2;
  return diff - Math.PI;
}

/**
 * True Eilik Slim-Cute Legless Teardrop Egg Torso:
 * - Narrow rounded gliding base (NO legs!) that sits flush & slides/waddles ("lết") cleanly
 * - Sleek compact egg silhouette (max radius 0.215 — significantly slimmer than the cute oversized head!)
 * - phiStart = Math.PI places UV u = 0.5 dead-center on the front chest (+Z) so the V-bib has zero seam!
 */
function createEilikEggTorsoGeometry(): THREE.LatheGeometry {
  const pts: THREE.Vector2[] = [
    new THREE.Vector2(0.0, 0.0),
    new THREE.Vector2(0.075, 0.008),
    new THREE.Vector2(0.135, 0.045),
    new THREE.Vector2(0.185, 0.12),
    new THREE.Vector2(0.212, 0.225),
    new THREE.Vector2(0.215, 0.33),
    new THREE.Vector2(0.194, 0.42),
    new THREE.Vector2(0.142, 0.478),
    new THREE.Vector2(0.088, 0.502),
    new THREE.Vector2(0.0, 0.506),
  ];
  const geo = new THREE.LatheGeometry(pts, 44, Math.PI, Math.PI * 2);
  geo.computeVertexNormals();
  return geo;
}

/**
 * Flush High-Res Satin Ceramic Egg Torso Texture:
 * Paints the exact smooth V-shaped chest tongue, neck collar & side shoulder crescents
 * directly onto the curved egg shell (100% flush like the reference photos — zero chunky sticking-out slabs!)
 */
function createEilikTorsoTexture(accentHex: string): THREE.CanvasTexture {
  const w = 512;
  const h = 512;
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d')!;

  // Clean soft-matte warm pearl ceramic body base
  ctx.fillStyle = '#f2f0eb';
  ctx.fillRect(0, 0, w, h);

  // Subtle lower ceramic grounding gradient for realistic depth (no flat plastic!)
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, 'rgba(255,255,255,0.06)');
  grad.addColorStop(0.75, 'rgba(0,0,0,0.0)');
  grad.addColorStop(1, 'rgba(30,25,20,0.12)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, w, h);

  // 1. Rich deep colored neck collar band wrapping cleanly around the top of the egg
  ctx.fillStyle = accentHex;
  ctx.fillRect(0, 0, w, 78);

  // 2. Iconic Eilik Flush Rounded V-Tongue down the center of the front chest (u = 0.5 -> x = 256)
  ctx.beginPath();
  ctx.moveTo(192, 64);
  ctx.quadraticCurveTo(222, 118, 232, 245);
  ctx.arc(256, 250, 24, Math.PI, 0, true); // perfectly rounded bottom tip!
  ctx.quadraticCurveTo(290, 118, 320, 64);
  ctx.closePath();
  ctx.fill();

  // Subtle dark contact seam along the V-tongue edge for crisp studio toy fidelity
  ctx.strokeStyle = 'rgba(0,0,0,0.16)';
  ctx.lineWidth = 3;
  ctx.stroke();

  // 3. Cute colored side shoulder pockets around u = 0.25 (x = 128) and u = 0.75 (x = 384)
  [128, 384].forEach((sx) => {
    ctx.fillStyle = accentHex;
    ctx.beginPath();
    ctx.ellipse(sx, 118, 44, 62, 0, 0, Math.PI * 2);
    ctx.fill();
  });

  // 4. Tiny authentic front pinhole speaker dot beneath the V-tongue
  ctx.fillStyle = '#262a33';
  ctx.beginPath();
  ctx.arc(256, 314, 5.5, 0, Math.PI * 2);
  ctx.fill();

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

/**
 * Plump, Cute Short Eilik Flipper Arm (matches the compact rounded arms tucked against the body in both photos!)
 */
function createCuteFlipperArmGeometry(side: -1 | 1): THREE.TubeGeometry {
  const curve = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(side * 0.048, -0.085, 0.018),
    new THREE.Vector3(side * 0.036, -0.175, 0.048),
    new THREE.Vector3(side * 0.012, -0.228, 0.064),
  ]);
  return new THREE.TubeGeometry(curve, 16, 0.056, 16, false);
}

/**
 * Giant Curved Squircle Glossy Black OLED Face Display matching the exact expressive eyes
 * from the two reference photos (big bold glowing eyes on deep glossy black glass!)
 */
function createEilikOledFace(eyeHex: string, accentHex: string): {
  texture: THREE.CanvasTexture;
  draw: (mood: FaceMood, blink: boolean, lookX: number) => void;
} {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 384;
  const ctx = canvas.getContext('2d')!;
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;

  const draw = (mood: FaceMood, blink: boolean, lookX: number) => {
    ctx.clearRect(0, 0, 512, 384);

    // Pure deep glossy OLED black background
    ctx.fillStyle = '#030407';
    ctx.fillRect(0, 0, 512, 384);

    // Subtle glass sheen arc near upper edge for authentic curved acrylic screen look
    const sheenGrad = ctx.createLinearGradient(0, 0, 0, 120);
    sheenGrad.addColorStop(0, 'rgba(255,255,255,0.14)');
    sheenGrad.addColorStop(1, 'rgba(255,255,255,0.0)');
    ctx.fillStyle = sheenGrad;
    ctx.beginPath();
    ctx.ellipse(256, 46, 210, 54, 0, 0, Math.PI * 2);
    ctx.fill();

    const ox = lookX * 22;
    ctx.save();
    ctx.shadowColor = eyeHex;
    ctx.shadowBlur = mood === 'sleeping' ? 10 : 28;
    ctx.fillStyle = mood === 'sleeping' ? '#94a3b8' : eyeHex;
    ctx.strokeStyle = mood === 'sleeping' ? '#94a3b8' : eyeHex;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    if (mood === 'sleeping' || blink) {
      // Soft peaceful curved closed eyes
      ctx.lineWidth = 22;
      ctx.beginPath();
      ctx.arc(162 + ox, 198, 50, Math.PI * 0.14, Math.PI * 0.86, false);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(350 + ox, 198, 50, Math.PI * 0.14, Math.PI * 0.86, false);
      ctx.stroke();

      if (mood === 'sleeping') {
        ctx.shadowBlur = 6;
        ctx.fillStyle = 'rgba(148, 163, 184, 0.78)';
        ctx.beginPath();
        ctx.ellipse(256 + ox, 278, 16, 12, 0, 0, Math.PI * 2);
        ctx.fill();
      }
    } else if (mood === 'happy' || mood === 'excited') {
      // EXACT match to Photo 2 (image_4e522ca6.png): huge, thick, super-cute curved happy bean eyes!
      const drawHappyBeanEye = (cx: number, cy: number, tilt: number) => {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(tilt);
        ctx.beginPath();
        ctx.ellipse(0, 0, 74, 44, 0, Math.PI, Math.PI * 2, false);
        ctx.quadraticCurveTo(74, 18, 0, 12);
        ctx.quadraticCurveTo(-74, 18, -74, 0);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      };
      drawHappyBeanEye(162 + ox, 200, -0.08);
      drawHappyBeanEye(350 + ox, 200, 0.08);

      if (mood === 'excited') {
        // Adorable tiny glowing happy 'o' mouth when waking up / celebrating
        ctx.beginPath();
        ctx.ellipse(256 + ox, 272, 22, 26, 0, 0, Math.PI * 2);
        ctx.fill();
      } else {
        // Subtle cute 'ω' cat smile
        ctx.lineWidth = 11;
        ctx.beginPath();
        ctx.arc(238 + ox, 264, 18, 0.1 * Math.PI, 0.9 * Math.PI, false);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(274 + ox, 264, 18, 0.1 * Math.PI, 0.9 * Math.PI, false);
        ctx.stroke();
      }
    } else if (mood === 'focused') {
      // EXACT match to Photo 1 (image_55a5fc9e.png): HUGE bold glowing determined angled eyes!
      const drawDeterminedEye = (cx: number, cy: number, side: -1 | 1) => {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.beginPath();
        ctx.ellipse(0, 0, 78, 56, side * -0.15, 0, Math.PI * 2);
        ctx.fill();

        // Crisp inner angled brow slice (exactly like Photo 1's super cool expressive brow!)
        ctx.shadowBlur = 0;
        ctx.fillStyle = '#030407';
        ctx.beginPath();
        ctx.moveTo(-side * 86, -66);
        ctx.lineTo(side * 88, -20);
        ctx.lineTo(side * 88, -82);
        ctx.lineTo(-side * 86, -82);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      };
      drawDeterminedEye(162 + ox, 198, -1);
      drawDeterminedEye(350 + ox, 198, 1);
    } else if (mood === 'thinking') {
      // Big curious glowing left eye + cute squinted right eye
      ctx.beginPath();
      ctx.ellipse(162 + ox, 192, 66, 62, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(350 + ox, 200, 66, 30, -0.06, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(256 + ox, 276, 15, 0, Math.PI * 2);
      ctx.fill();
    } else if (mood === 'reviewing') {
      // Sharp glowing scanner eyes + bright checkmark
      ctx.beginPath();
      ctx.roundRect(92 + ox, 150, 134, 84, 34);
      ctx.roundRect(286 + ox, 150, 134, 84, 34);
      ctx.fill();
      ctx.lineWidth = 14;
      ctx.beginPath();
      ctx.moveTo(226 + ox, 276);
      ctx.lineTo(248 + ox, 296);
      ctx.lineTo(290 + ox, 254);
      ctx.stroke();
    }

    // Crisp gloss highlight dot on upper-right glass corner (like both real photos!)
    ctx.shadowBlur = 0;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.24)';
    ctx.beginPath();
    ctx.ellipse(396, 86, 32, 14, 0.42, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = accentHex;
    ctx.globalAlpha = 0.08;
    ctx.fillRect(0, 0, 512, 384);

    ctx.restore();
    texture.needsUpdate = true;
  };

  draw('sleeping', false, 0);
  return { texture, draw };
}

/**
 * True-to-Photo Legless Eilik Companion Robot:
 * - Zero legs — glides/scoots ("lết") smoothly across the floor on its rounded ceramic egg base!
 * - True adorable proportions: large rounded helmet head (1.42x wider than slim teardrop torso)
 * - Flush UV-painted deep-colored V-collar bib + shoulder pockets + top crown oval + thin C-ear tabs
 * - Giant curved glossy black squircle visor with huge vibrant glowing OLED eyes
 * - Short cute curved pearl-white flipper arms with role-specific handheld 3D props
 */
export function buildBeanRobotCharacter(
  id: AgentId,
  materials: StudioMaterialLibrary,
): BeanRobotInstance {
  const profile = AGENT_PROFILES[id];
  const geometries: THREE.BufferGeometry[] = [];
  const extraMats: THREE.Material[] = [];
  const extraTex: THREE.Texture[] = [];

  const trackGeo = <T extends THREE.BufferGeometry>(g: T): T => {
    geometries.push(g);
    return g;
  };
  const trackMat = <T extends THREE.Material>(m: T): T => {
    extraMats.push(m);
    return m;
  };

  const accentMat = materials.createSoftRobotMat(profile.accentNumber);
  const shellMat = materials.eilikCeramicShell;

  // Flush UV-painted satin ceramic torso material (crisp V-collar + shoulder accents, zero lumps!)
  const torsoTex = createEilikTorsoTexture(profile.accentHex);
  extraTex.push(torsoTex);
  const torsoMat = trackMat(
    new THREE.MeshPhysicalMaterial({
      map: torsoTex,
      roughness: 0.4,
      metalness: 0.02,
      clearcoat: 0.18,
      clearcoatRoughness: 0.32,
    }),
  );

  // Dynamic Eilik OLED Face CanvasTexture (bright huge eyes matching agent's signature color!)
  const eyeHex = OLED_EYE_COLOR[id] ?? '#38e8ff';
  const oledFace = createEilikOledFace(eyeHex, profile.accentHex);
  extraTex.push(oledFace.texture);
  const oledMat = trackMat(
    new THREE.MeshBasicMaterial({
      map: oledFace.texture,
    }),
  );

  const root = new THREE.Group();
  root.name = `eilik_robot_${id}`;
  root.position.set(profile.sleepPos[0], 0, profile.sleepPos[1]);
  root.rotation.y = profile.sleepFacingYaw;
  root.scale.setScalar(1.16);

  // Ground contact shadow directly beneath the gliding egg base
  const shadow = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(0.84, 0.84)),
    materials.contactShadow,
  );
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = 0.015;
  root.add(shadow);

  // Floor spotlight & gliding scoot halo ring
  const ringMat = trackMat(
    new THREE.MeshBasicMaterial({
      color: profile.accentNumber,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  const floorRing = new THREE.Mesh(
    trackGeo(new THREE.RingGeometry(0.32, 0.44, 36)),
    ringMat,
  );
  floorRing.rotation.x = -Math.PI / 2;
  floorRing.position.y = 0.022;
  root.add(floorRing);

  // =========================================================================
  // LEGLESS GLIDING EGG BODY PIVOT (NO LEGS! Rests flush on floor or chair!)
  // =========================================================================
  const bodyPivot = new THREE.Group();
  bodyPivot.position.y = profile.sleepSeated ? 0.39 : 0.02;
  root.add(bodyPivot);

  const torsoPivot = new THREE.Group();
  bodyPivot.add(torsoPivot);

  // Sleek slim teardrop egg torso
  const torsoMesh = new THREE.Mesh(trackGeo(createEilikEggTorsoGeometry()), torsoMat);
  torsoMesh.castShadow = true;
  torsoMesh.receiveShadow = true;
  torsoPivot.add(torsoMesh);

  // Subtle dark recessed base pad at bottom of egg (what it glides/scoots on!)
  const glidePad = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.088, 0.072, 0.02, 20)),
    materials.darkMonitorFrame,
  );
  glidePad.position.y = 0.008;
  torsoPivot.add(glidePad);

  // Clean recessed dark neck joint cylinder (gives crisp head/torso separation like both photos!)
  const neckJoint = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.095, 0.11, 0.055, 20)),
    materials.darkMonitorFrame,
  );
  neckJoint.position.y = 0.51;
  torsoPivot.add(neckJoint);

  // =========================================================================
  // SHORT CUTE TUCKED FLIPPER ARMS (Matches the compact rounded arms in both photos!)
  // =========================================================================
  const createCuteArm = (side: -1 | 1) => {
    const shoulder = new THREE.Group();
    shoulder.position.set(side * 0.215, 0.41, 0.01);

    // Rounded shoulder dome seamlessly blending into side pocket
    const shoulderCap = new THREE.Mesh(
      trackGeo(new THREE.SphereGeometry(0.057, 16, 14)),
      shellMat,
    );
    shoulder.add(shoulderCap);

    // Plump smooth curved pearl-white flipper arm
    const armMesh = new THREE.Mesh(trackGeo(createCuteFlipperArmGeometry(side)), shellMat);
    armMesh.castShadow = true;
    shoulder.add(armMesh);

    // Rich colored inner accent strip along inner arm edge (visible when arms lift!)
    const innerDot = new THREE.Mesh(
      trackGeo(new THREE.SphereGeometry(0.044, 14, 12)),
      accentMat,
    );
    innerDot.scale.set(0.65, 1.3, 0.85);
    innerDot.position.set(side * -0.012, -0.07, 0.012);
    shoulder.add(innerDot);

    // Smooth rounded mitten tip
    const handSphere = new THREE.Mesh(
      trackGeo(new THREE.SphereGeometry(0.058, 16, 14)),
      shellMat,
    );
    handSphere.position.set(side * 0.012, -0.228, 0.064);
    handSphere.castShadow = true;
    shoulder.add(handSphere);

    const handTip = new THREE.Group();
    handTip.position.set(side * 0.012, -0.23, 0.085);
    shoulder.add(handTip);

    torsoPivot.add(shoulder);
    return { shoulder, handTip };
  };
  const leftArmObj = createCuteArm(-1);
  const rightArmObj = createCuteArm(1);
  const leftArm = leftArmObj.shoulder;
  const rightArm = rightArmObj.shoulder;

  // =========================================================================
  // ROLE-SPECIFIC HANDHELD 3D PROPS (Attached cleanly to Flipper Tips!)
  // =========================================================================
  const leftPropRoot = new THREE.Group();
  const rightPropRoot = new THREE.Group();
  leftArmObj.handTip.add(leftPropRoot);
  rightArmObj.handTip.add(rightPropRoot);

  const penBodyMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: id === 'reviewer' ? 0xdc1e3c : id === 'analyst' ? 0x1d4ed8 : 0x334155,
      roughness: 0.35,
      metalness: 0.2,
    }),
  );
  const rulerMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xfacc15, roughness: 0.42 }),
  );
  const calcBodyMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.42 }),
  );
  const clipboardWoodMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0x9c6639, roughness: 0.62 }),
  );
  const paperWhiteMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xfcfbf8, roughness: 0.85 }),
  );

  if (id === 'orchestrator') {
    const board = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.22, 0.28, 0.022)),
      materials.darkMonitorFrame,
    );
    board.rotation.x = -0.35;
    leftPropRoot.add(board);
    const boardGlow = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.18, 0.22, 0.028)),
      materials.createAccentGlow(0xe07a00, 0.65),
    );
    boardGlow.rotation.x = -0.35;
    leftPropRoot.add(boardGlow);

    const baton = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.011, 0.015, 0.38, 10)),
      materials.brassAccent,
    );
    baton.rotation.x = Math.PI * 0.45;
    baton.position.set(0, -0.02, 0.14);
    rightPropRoot.add(baton);
  } else if (id === 'analyst') {
    const pen = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.011, 0.008, 0.22, 10)),
      penBodyMat,
    );
    pen.rotation.x = Math.PI * 0.38;
    pen.position.set(0, -0.02, 0.08);
    rightPropRoot.add(pen);

    const ruler = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.29, 0.014, 0.05)),
      rulerMat,
    );
    ruler.position.set(0.04, 0.02, 0.08);
    ruler.rotation.y = 0.25;
    leftPropRoot.add(ruler);

    const calc = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.13, 0.028, 0.17)),
      calcBodyMat,
    );
    calc.position.set(-0.04, 0.036, 0.04);
    leftPropRoot.add(calc);
    const calcScreen = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.095, 0.032, 0.05)),
      materials.createAccentGlow(0x38bdf8, 0.55),
    );
    calcScreen.position.set(-0.04, 0.038, -0.005);
    leftPropRoot.add(calcScreen);
  } else if (id === 'reviewer') {
    const clip = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.22, 0.29, 0.02)),
      clipboardWoodMat,
    );
    clip.rotation.x = -0.5;
    leftPropRoot.add(clip);
    const sheet = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.18, 0.24, 0.024)),
      paperWhiteMat,
    );
    sheet.rotation.x = -0.5;
    leftPropRoot.add(sheet);
    const metalClip = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.085, 0.032, 0.032)),
      materials.chromeMetal,
    );
    metalClip.position.set(0, 0.11, -0.045);
    leftPropRoot.add(metalClip);

    const pen = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.012, 0.008, 0.22, 10)),
      penBodyMat,
    );
    pen.rotation.x = Math.PI * 0.4;
    pen.position.set(0, -0.02, 0.08);
    rightPropRoot.add(pen);
  } else if (id === 'integrator') {
    const pen = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.012, 0.008, 0.21, 10)),
      penBodyMat,
    );
    pen.rotation.x = Math.PI * 0.38;
    pen.position.set(0, -0.02, 0.08);
    rightPropRoot.add(pen);
  }

  // =========================================================================
  // OVERSIZED ADORABLE EILIK HELMET HEAD (1.42x WIDER THAN SLIM TORSO!)
  // Matches both uploaded photos: huge curved black screen + flush crown oval + thin C-ears!
  // =========================================================================
  const headPivot = new THREE.Group();
  headPivot.position.y = 0.525;
  torsoPivot.add(headPivot);

  const cranium = new THREE.Mesh(
    trackGeo(new THREE.SphereGeometry(0.305, 40, 28)),
    shellMat,
  );
  cranium.position.y = 0.265;
  cranium.scale.set(1.06, 0.94, 0.93);
  cranium.castShadow = true;
  cranium.receiveShadow = true;
  headPivot.add(cranium);

  // Flush Colored Crown Touch-Pad Oval hugging the exact top curve of the helmet!
  const crownCap = new THREE.Mesh(
    trackGeo(new THREE.SphereGeometry(0.309, 28, 14, 0, Math.PI * 2, 0, 0.42)),
    accentMat,
  );
  crownCap.position.y = 0.267;
  crownCap.scale.set(1.06, 0.94, 0.93);
  headPivot.add(crownCap);

  // Thin Sleek C-Shaped Ear Tabs hugging left & right sides of the head (exact match to photos!)
  const earRimGeo = trackGeo(new THREE.TorusGeometry(0.082, 0.018, 12, 20, Math.PI * 1.15));
  const earPlateGeo = trackGeo(new THREE.CylinderGeometry(0.072, 0.072, 0.024, 18));
  [-1, 1].forEach((side) => {
    const earGroup = new THREE.Group();
    earGroup.position.set(side * 0.312, 0.26, -0.015);

    const plate = new THREE.Mesh(earPlateGeo, accentMat);
    plate.rotation.z = Math.PI / 2;
    earGroup.add(plate);

    const rim = new THREE.Mesh(earRimGeo, shellMat);
    rim.rotation.y = side > 0 ? 0 : Math.PI;
    rim.rotation.z = -Math.PI * 0.57;
    rim.scale.set(0.85, 1.05, 0.9);
    earGroup.add(rim);

    headPivot.add(earGroup);
  });

  // Giant Curved Glossy Black Glass Visor Housing (covers ~72% of front face with crisp white frame!)
  const visorHousing = new THREE.Mesh(
    trackGeo(
      new THREE.SphereGeometry(
        0.311,
        36,
        24,
        Math.PI * 0.5 - Math.PI * 0.37,
        Math.PI * 0.74,
        Math.PI * 0.21,
        Math.PI * 0.57,
      ),
    ),
    materials.visorBlack,
  );
  visorHousing.position.set(0, 0.265, 0.004);
  visorHousing.scale.set(1.06, 0.94, 0.935);
  headPivot.add(visorHousing);

  // Dynamic Glowing OLED Face Screen directly on front of the curved black visor!
  const oledPlane = new THREE.Mesh(
    trackGeo(
      new THREE.SphereGeometry(
        0.314,
        32,
        22,
        Math.PI * 0.5 - Math.PI * 0.33,
        Math.PI * 0.66,
        Math.PI * 0.24,
        Math.PI * 0.51,
      ),
    ),
    oledMat,
  );
  oledPlane.position.set(0, 0.265, 0.006);
  oledPlane.scale.set(1.06, 0.94, 0.935);
  headPivot.add(oledPlane);

  // Carried Document Folder Stack (visible when gliding/handing off/pulling from RAG cabinet)
  const carryGroup = new THREE.Group();
  carryGroup.position.set(0, 0.27, 0.34);
  carryGroup.visible = false;
  torsoPivot.add(carryGroup);

  const carryMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x009e73,
      roughness: 0.45,
      metalness: 0.05,
    }),
  );
  const folderBottom = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.3, 0.048, 0.22)),
    carryMat,
  );
  folderBottom.castShadow = true;
  carryGroup.add(folderBottom);
  const paperMid = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.26, 0.042, 0.19)),
    paperWhiteMat,
  );
  paperMid.position.y = 0.036;
  carryGroup.add(paperMid);
  const folderTop = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.28, 0.038, 0.2)),
    trackMat(new THREE.MeshStandardMaterial({ color: 0xe07a00, roughness: 0.48 })),
  );
  folderTop.position.set(0.02, 0.07, -0.01);
  folderTop.rotation.y = 0.14;
  carryGroup.add(folderTop);

  // Animated 3D Floating "Z z z" Sleeping Sprites
  const zzzGroup = new THREE.Group();
  zzzGroup.position.set(0, 1.08, 0.14);
  zzzGroup.visible = false;
  root.add(zzzGroup);

  const zSprites: THREE.Sprite[] = [];
  for (let i = 0; i < 3; i++) {
    const spMat = trackMat(materials.zzzSpriteMat.clone());
    const sp = new THREE.Sprite(spMat);
    sp.scale.setScalar(0.2 + i * 0.05);
    zzzGroup.add(sp);
    zSprites.push(sp);
  }

  // Layer-1 Click Collider
  const collider = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.42, 0.42, 1.38, 10)),
    trackMat(new THREE.MeshBasicMaterial({ visible: false })),
  );
  collider.position.y = 0.69;
  collider.userData.agentId = id;
  collider.layers.set(1);
  root.add(collider);

  // Runtime state
  let currentAction: RobotAction = 'sleeping';
  let currentCarry: CarryItemKind = 'none';
  let targetX = profile.sleepPos[0];
  let targetZ = profile.sleepPos[1];
  let targetYaw = profile.sleepFacingYaw;
  let isMovingFlag = false;
  let isSeatedFlag = profile.sleepSeated;
  let glideCycle = 0;
  let hovered = false;
  let selected = false;
  let isLeadFlag = false;
  let lastFaceKey = '';
  let faceTimer = 0;
  const phaseSeed = (parseInt(profile.code, 10) || 1) * 1.37;

  const resolveMood = (action: RobotAction): FaceMood => {
    if (action === 'sleeping') return 'sleeping';
    if (action === 'waking_up') return 'excited';
    if (action === 'thinking' || action === 'brainstorming') return 'thinking';
    if (action === 'reviewing_paper') return 'reviewing';
    if (
      action === 'working_computer' ||
      action === 'drafting_analysis' ||
      action === 'cabinet_rag' ||
      action === 'planning_board' ||
      action === 'integrating'
    ) {
      return 'focused';
    }
    return 'happy';
  };

  const setCarryItem = (kind: CarryItemKind) => {
    currentCarry = kind;
    carryGroup.visible = kind !== 'none' && currentAction !== 'sleeping';
    if (kind !== 'none') {
      carryMat.color.setHex(ITEM_COLOR_MAP[kind]);
    }
  };

  return {
    id,
    root,
    collider,
    position: root.position,
    get action() {
      return currentAction;
    },
    get carryItem() {
      return currentCarry;
    },
    setHighlighted: (h, s, lead = false) => {
      hovered = h;
      selected = s;
      isLeadFlag = lead;
    },
    setCarryItem,
    setPoseTarget: (x, z, yaw, action, isMoving = false, seated = false) => {
      targetX = x;
      targetZ = z;
      targetYaw = yaw;
      currentAction = action;
      isMovingFlag = isMoving;
      isSeatedFlag = seated;
    },
    getLabelAnchorWorld: (out: THREE.Vector3) => {
      const topY = currentAction === 'sleeping' ? 1.38 : isSeatedFlag ? 1.62 : 1.38;
      return out.set(root.position.x, topY, root.position.z);
    },
    update: (dt, elapsed) => {
      root.position.x = THREE.MathUtils.damp(root.position.x, targetX, 11, dt);
      root.position.z = THREE.MathUtils.damp(root.position.z, targetZ, 11, dt);
      const yawDelta = shortestAngleDelta(root.rotation.y, targetYaw);
      root.rotation.y += yawDelta * (1 - Math.exp(-9 * dt));

      const isSleeping = currentAction === 'sleeping';
      const carrying = currentCarry !== 'none' && !isSleeping;
      const isActive = !isSleeping && currentAction !== 'idle' && currentAction !== 'completed';

      const showRoleProps = !isSleeping && !carrying;
      leftPropRoot.visible = showRoleProps;
      rightPropRoot.visible = showRoleProps;
      carryGroup.visible =
        carrying &&
        (isMovingFlag || currentAction === 'handing_over' || currentAction === 'cabinet_rag');

      // Base resting height: flush on chair cushion when seated (0.39), flush gliding on floor when moving/standing (0.025)!
      let bodyY = isSeatedFlag ? 0.39 : 0.025 + Math.sin(elapsed * 2.8 + phaseSeed) * 0.012;
      let bodyZOffset = 0;
      let torsoX = 0;
      let torsoZ = Math.sin(elapsed * 1.9 + phaseSeed) * 0.032;
      let lArmX = carrying ? -0.95 : -0.08;
      let rArmX = carrying ? -0.95 : -0.08;
      let lArmZ = carrying ? 0.24 : 0.14 + Math.sin(elapsed * 2.3 + phaseSeed) * 0.06;
      let rArmZ = carrying ? -0.24 : -0.14 - Math.sin(elapsed * 2.3 + phaseSeed) * 0.06;
      let headY = Math.sin(elapsed * 1.15 + phaseSeed) * 0.2;
      let headX = Math.sin(elapsed * 1.6 + phaseSeed) * 0.045;
      let headZ = Math.cos(elapsed * 1.2 + phaseSeed) * 0.075;

      if (isSleeping) {
        // Slumped face-down sleeping posture ("nằm gục lên bàn")!
        const breath = Math.sin(elapsed * 1.45 + phaseSeed);
        bodyY = (isSeatedFlag ? 0.35 : 0.02) + breath * 0.01;
        bodyZOffset = isSeatedFlag ? 0.2 : 0.08;
        torsoX = 0.88 + breath * 0.032;
        torsoZ = 0.06;
        headX = 0.28 + breath * 0.028;
        headZ = 0.36;
        headY = 0.18;
        lArmX = -1.38;
        rArmX = -1.38;
        lArmZ = -0.32;
        rArmZ = 0.32;
      } else if (currentAction === 'waking_up') {
        // Adorable Eilik arms-up celebration hop!
        const hop = Math.abs(Math.sin(elapsed * 7.5)) * 0.11;
        bodyY = (isSeatedFlag ? 0.39 : 0.03) + hop;
        lArmX = -2.25 + Math.sin(elapsed * 9) * 0.15;
        rArmX = -2.25 - Math.sin(elapsed * 9) * 0.15;
        lArmZ = 0.5;
        rArmZ = -0.5;
        headX = -0.16;
        headZ = Math.sin(elapsed * 6) * 0.12;
      } else if (isMovingFlag || currentAction === 'walking') {
        // AUTHENTIC LEGLESS GLIDING / SCOOTING ("LẾT") LOCOMOTION!
        // Smooth rhythmic waddle-scoot across the floor with forward tilt & tiny hop!
        glideCycle += dt * 11.5;
        const waddle = Math.sin(glideCycle);
        const scootBounce = Math.abs(Math.cos(glideCycle)) * 0.042;
        bodyY = 0.022 + scootBounce;
        torsoX = 0.22; // Leaning forward eagerly as it glides/scoots!
        torsoZ = waddle * 0.165; // Cute side-to-side legless waddle tilt!
        headZ = -waddle * 0.1; // Head stabilizes adorably
        headX = -0.08;
        headY = 0;
        if (carrying) {
          lArmX = -1.08;
          rArmX = -1.08;
          lArmZ = 0.2;
          rArmZ = -0.2;
        } else {
          // Cute flipper balance flapping as it slides!
          lArmX = -0.35 - waddle * 0.38;
          rArmX = -0.35 + waddle * 0.38;
          lArmZ = 0.38;
          rArmZ = -0.38;
        }
      } else if (currentAction === 'planning_board') {
        rArmX = -1.7 + Math.sin(elapsed * 5.0) * 0.26;
        rArmZ = -0.36 + Math.cos(elapsed * 3.4) * 0.18;
        lArmX = -1.05;
        lArmZ = 0.3;
        headY = Math.sin(elapsed * 2.9) * 0.24;
        headX = -0.14;
      } else if (currentAction === 'cabinet_rag') {
        const pull = Math.sin(elapsed * 5.4);
        rArmX = -1.3 + pull * 0.28;
        lArmX = -1.2 - pull * 0.24;
        torsoX = 0.15;
        headY = Math.sin(elapsed * 3.2) * 0.24;
        headX = 0.05;
      } else if (currentAction === 'drafting_analysis') {
        torsoX = 0.16;
        rArmX = -1.16 + Math.sin(elapsed * 12) * 0.12;
        rArmZ = -0.24 + Math.cos(elapsed * 8.5) * 0.14;
        lArmX = -1.1;
        lArmZ = 0.26;
        headX = 0.22;
        headY = Math.sin(elapsed * 2.5) * 0.22;
        headZ = 0.1;
      } else if (currentAction === 'reviewing_paper') {
        lArmX = -1.18;
        lArmZ = 0.32;
        const check = Math.sin(elapsed * 6.8);
        rArmX = check > 0.2 ? -1.42 : -1.02;
        rArmZ = -0.24 + Math.cos(elapsed * 5.2) * 0.14;
        headX = 0.18;
        headY = Math.sin(elapsed * 2.7) * 0.18;
        headZ = -0.08;
      } else if (currentAction === 'working_computer' || currentAction === 'integrating') {
        torsoX = 0.12;
        lArmX = -1.1 + Math.sin(elapsed * 15 + phaseSeed) * 0.12;
        rArmX = -1.1 + Math.cos(elapsed * 15 + phaseSeed) * 0.12;
        lArmZ = 0.18;
        rArmZ = -0.18;
        headX = 0.08;
        headY = Math.sin(elapsed * 2.2 + phaseSeed) * 0.2;
      } else if (currentAction === 'thinking') {
        rArmX = -1.6;
        rArmZ = 0.32;
        lArmX = -0.4;
        headZ = 0.2 * Math.sin(elapsed * 1.9 + phaseSeed);
        headX = -0.06;
        headY = Math.sin(elapsed * 1.6) * 0.24;
      } else if (currentAction === 'brainstorming') {
        const talk = Math.sin(elapsed * 5.6 + phaseSeed);
        rArmX = -1.32 + talk * 0.36;
        rArmZ = -0.45;
        lArmX = -0.92 - talk * 0.26;
        lArmZ = 0.4;
        headY = Math.sin(elapsed * 3.0 + phaseSeed) * 0.36;
        headZ = Math.cos(elapsed * 2.5 + phaseSeed) * 0.14;
        bodyY = 0.025 + Math.abs(Math.sin(elapsed * 4.2 + phaseSeed)) * 0.045;
      } else if (currentAction === 'handing_over' || currentAction === 'receiving') {
        lArmX = -1.25;
        rArmX = -1.25;
        lArmZ = 0.18;
        rArmZ = -0.18;
        torsoX = 0.1;
        headX = 0.08;
      }

      // Smooth exponential damping
      bodyPivot.position.y = THREE.MathUtils.damp(bodyPivot.position.y, bodyY, 9.5, dt);
      bodyPivot.position.z = THREE.MathUtils.damp(bodyPivot.position.z, bodyZOffset, 9.5, dt);
      torsoPivot.rotation.x = THREE.MathUtils.damp(torsoPivot.rotation.x, torsoX, 9, dt);
      torsoPivot.rotation.z = THREE.MathUtils.damp(torsoPivot.rotation.z, torsoZ, 9.5, dt);
      leftArm.rotation.x = THREE.MathUtils.damp(leftArm.rotation.x, lArmX, 10, dt);
      rightArm.rotation.x = THREE.MathUtils.damp(rightArm.rotation.x, rArmX, 10, dt);
      leftArm.rotation.z = THREE.MathUtils.damp(leftArm.rotation.z, lArmZ, 10, dt);
      rightArm.rotation.z = THREE.MathUtils.damp(rightArm.rotation.z, rArmZ, 10, dt);
      headPivot.rotation.y = THREE.MathUtils.damp(headPivot.rotation.y, headY, 9, dt);
      headPivot.rotation.x = THREE.MathUtils.damp(headPivot.rotation.x, headX, 9, dt);
      headPivot.rotation.z = THREE.MathUtils.damp(headPivot.rotation.z, headZ, 9, dt);

      // Update dynamic OLED face expression (~12fps throttled for ultra-smooth FPS)
      faceTimer += dt;
      if (faceTimer >= 0.085) {
        faceTimer = 0;
        const mood = resolveMood(currentAction);
        const blink = !isSleeping && (elapsed + phaseSeed) % 4.1 > 3.94;
        const lookStep = isSleeping ? 0 : Math.round(Math.sin(elapsed * 1.4 + phaseSeed) * 2) / 2;
        const key = `${mood}_${blink ? 1 : 0}_${lookStep}`;
        if (key !== lastFaceKey) {
          lastFaceKey = key;
          oledFace.draw(mood, blink, lookStep);
        }
      }

      // Floating 3D Zzz sprites while sleeping
      zzzGroup.visible = isSleeping;
      if (isSleeping) {
        zSprites.forEach((sp, i) => {
          const cycle = (elapsed * 0.45 + phaseSeed + i * 0.33) % 1;
          sp.position.set(
            Math.sin(cycle * Math.PI * 2 + i) * 0.11 + i * 0.075,
            cycle * 0.68,
            0.12,
          );
          const sc = (0.14 + cycle * 0.13) * (1 - cycle * 0.25);
          sp.scale.setScalar(sc);
          sp.material.opacity = Math.sin(cycle * Math.PI) * 0.92;
        });
      }

      // Floor glide / lead spotlight halo ring
      const glideGlow = isMovingFlag ? 0.68 : 0;
      const leadPulse = isLeadFlag ? 0.72 + Math.sin(elapsed * 4.5) * 0.18 : 0;
      const targetRing = Math.max(
        glideGlow,
        isLeadFlag ? leadPulse : selected ? 0.85 : isActive ? 0.36 : hovered ? 0.35 : 0,
      );
      ringMat.opacity = THREE.MathUtils.damp(ringMat.opacity, targetRing, 9, dt);
      const ringScale =
        isMovingFlag
          ? 0.92 + Math.sin(elapsed * 12) * 0.1
          : isLeadFlag
            ? 1.06 + Math.sin(elapsed * 4.5) * 0.08
            : 1.0;
      floorRing.scale.setScalar(THREE.MathUtils.damp(floorRing.scale.x, ringScale, 8, dt));
    },
    dispose: () => {
      extraTex.forEach((t) => t.dispose());
      geometries.forEach((g) => g.dispose());
      extraMats.forEach((m) => m.dispose());
    },
  };
}
