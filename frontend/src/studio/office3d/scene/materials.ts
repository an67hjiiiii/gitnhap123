import * as THREE from 'three';
import type { StudioTextureSet } from './textures';

export interface StudioMaterialLibrary {
  oakFloor: THREE.MeshStandardMaterial;
  oakDesk: THREE.MeshStandardMaterial;
  darkWalnutWood: THREE.MeshStandardMaterial;
  oakSlatWood: THREE.MeshStandardMaterial;
  plasterWall: THREE.MeshStandardMaterial;
  featureWallSlate: THREE.MeshStandardMaterial;
  podiumSlate: THREE.MeshStandardMaterial;
  travertineFloor: THREE.MeshStandardMaterial;
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
  cognacLeather: THREE.MeshStandardMaterial;
  glassPanel: THREE.MeshPhysicalMaterial;
  planningBoardMat: THREE.MeshStandardMaterial;
  draftingPaperMat: THREE.MeshStandardMaterial;
  easelChartMat: THREE.MeshStandardMaterial;
  missionWallMat: THREE.MeshBasicMaterial;
  hubMapMat: THREE.MeshStandardMaterial;
  screenUltrawideMat: THREE.MeshStandardMaterial;
  screenSleepMat: THREE.MeshStandardMaterial;
  plantLeafRich: THREE.MeshStandardMaterial;
  plantLeafLight: THREE.MeshStandardMaterial;
  terracottaPot: THREE.MeshStandardMaterial;
  ceramicWhite: THREE.MeshStandardMaterial;
  eilikCeramicShell: THREE.MeshPhysicalMaterial;
  visorBlack: THREE.MeshPhysicalMaterial;
  lampShadeGlow: THREE.MeshStandardMaterial;
  warmLedStrip: THREE.MeshStandardMaterial;
  contactShadow: THREE.MeshBasicMaterial;
  zzzSpriteMat: THREE.SpriteMaterial;
  coveLightMat: THREE.MeshStandardMaterial;
  deskMatDark: THREE.MeshStandardMaterial;
  sofaFabric: THREE.MeshStandardMaterial;
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

  // Sàn gỗ sồi mật ong sâu ấm (Command Atrium V3) — tương phản cực nổi với Trục đá sáng & 11 Robot trắng sứ V12
  const oakFloor = track(
    new THREE.MeshStandardMaterial({
      map: textures.oakPlankFloorMap,
      bumpMap: textures.woodBumpMap,
      bumpScale: 0.02,
      color: 0xffffff,
      roughness: 0.52,
      metalness: 0.02,
    }),
  );

  // Mặt bàn gỗ óc chó nâu đậm tự nhiên
  const oakDesk = track(
    new THREE.MeshStandardMaterial({
      map: textures.oakDeskMap,
      bumpMap: textures.woodBumpMap,
      bumpScale: 0.018,
      color: 0xffffff,
      roughness: 0.46,
      metalness: 0.03,
    }),
  );

  // Gỗ óc chó nâu ấm tự nhiên cho bàn làm việc, tủ kệ, bậc thang (nhân với oakDeskMap nên dùng tông sáng ấm để giữ rõ vân gỗ)
  const darkWalnutWood = track(
    new THREE.MeshStandardMaterial({
      map: textures.oakDeskMap,
      bumpMap: textures.woodBumpMap,
      bumpScale: 0.02,
      color: 0xa6764c,
      roughness: 0.48,
      metalness: 0.02,
    }),
  );

  // Lam gỗ sồi vàng mật trang trí tường chính diện, giá vẽ, thang thư viện
  const oakSlatWood = track(
    new THREE.MeshStandardMaterial({
      color: 0xc99660,
      bumpMap: textures.woodBumpMap,
      bumpScale: 0.014,
      roughness: 0.48,
      metalness: 0.02,
    }),
  );

  // Tường hông xám ấm kiến trúc (không chói trắng gắt, hài hòa với tường Slate đậm phía bắc)
  const plasterWall = track(
    new THREE.MeshStandardMaterial({
      color: 0xd8d1c7,
      bumpMap: textures.plasterBumpMap,
      bumpScale: 0.009,
      roughness: 0.88,
      metalness: 0.0,
    }),
  );

  // Tường chính diện phía Bắc: Xanh Slate kiến trúc đậm tạo chiều sâu & tôn bật Màn hình 2K
  const featureWallSlate = track(
    new THREE.MeshStandardMaterial({
      color: 0x263140,
      bumpMap: textures.plasterBumpMap,
      bumpScale: 0.008,
      roughness: 0.78,
      metalness: 0.06,
    }),
  );

  // Bục Chỉ Huy nâng cao +0.28m lát đá Xám Than kiến trúc
  const podiumSlate = track(
    new THREE.MeshStandardMaterial({
      map: textures.darkSlateStoneMap,
      roughness: 0.54,
      metalness: 0.08,
    }),
  );

  // Trục Lối Đi Chính & Sảnh Hội Ý Tròn lát đá Travertine sáng ấm
  const travertineFloor = track(
    new THREE.MeshStandardMaterial({
      map: textures.travertineStoneMap,
      roughness: 0.56,
      metalness: 0.02,
    }),
  );

  const cutawayWallCap = track(
    new THREE.MeshStandardMaterial({
      color: 0x1a212b,
      roughness: 0.62,
      metalness: 0.24,
    }),
  );

  const basePlinth = track(
    new THREE.MeshStandardMaterial({
      color: 0x625a52,
      roughness: 0.84,
      metalness: 0.04,
    }),
  );

  // Thảm dệt cho 2 khu Analyst & Reviewer (tông đá xanh xám sang trọng)
  const rugBlue = track(
    new THREE.MeshStandardMaterial({
      map: textures.wovenRugBlueMap,
      bumpMap: textures.fabricBumpMap,
      bumpScale: 0.02,
      color: 0x4b5769,
      roughness: 0.92,
      metalness: 0.0,
    }),
  );

  const rugSand = track(
    new THREE.MeshStandardMaterial({
      map: textures.wovenRugSandMap,
      bumpMap: textures.fabricBumpMap,
      bumpScale: 0.02,
      color: 0x5c6470,
      roughness: 0.92,
      metalness: 0.0,
    }),
  );

  const brushedSteel = track(
    new THREE.MeshPhysicalMaterial({
      color: 0xcbd4df,
      roughness: 0.26,
      metalness: 0.72,
      clearcoat: 0.2,
    }),
  );

  const chromeMetal = track(
    new THREE.MeshPhysicalMaterial({
      color: 0xe6edf5,
      roughness: 0.2,
      metalness: 0.78,
    }),
  );

  // Đồng thau ấm sáng làm viền bục, viền sảnh đá, khung màn hình, tay đỡ kính & bánh lái Vault
  const brassAccent = track(
    new THREE.MeshPhysicalMaterial({
      color: 0xe0b05e,
      roughness: 0.28,
      metalness: 0.86,
    }),
  );

  const darkMonitorFrame = track(
    new THREE.MeshStandardMaterial({
      color: 0x1b222c,
      roughness: 0.38,
      metalness: 0.62,
    }),
  );

  const whiteChairShell = track(
    new THREE.MeshStandardMaterial({
      color: 0xf1f5f9,
      roughness: 0.54,
      metalness: 0.04,
    }),
  );

  const fabricChairBlue = track(
    new THREE.MeshPhysicalMaterial({
      color: 0x384252,
      bumpMap: textures.fabricBumpMap,
      bumpScale: 0.014,
      roughness: 0.88,
      metalness: 0.0,
      sheen: 0.35,
      sheenRoughness: 0.82,
      sheenColor: new THREE.Color(0x94a3b8),
    }),
  );

  // Da bò Cognac cao cấp cho 2 ghế băng cong tại Sảnh Hội Ý Trung Tâm
  const cognacLeather = track(
    new THREE.MeshStandardMaterial({
      color: 0xae6636,
      bumpMap: textures.fabricBumpMap,
      bumpScale: 0.01,
      roughness: 0.5,
      metalness: 0.04,
    }),
  );

  const glassPanel = track(
    new THREE.MeshPhysicalMaterial({
      color: 0xdbeafe,
      roughness: 0.1,
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
      emissiveIntensity: 0.16,
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
      emissiveIntensity: 0.14,
    }),
  );

  const missionWallMat = track(
    new THREE.MeshBasicMaterial({
      map: textures.missionWallMap,
    }),
  );

  // Mặt kính Bản Đồ Mạng 11 Agent C27 trên bàn tròn trung tâm
  const hubMapMat = track(
    new THREE.MeshStandardMaterial({
      map: textures.hubMapTex,
      emissiveMap: textures.hubMapTex,
      emissive: new THREE.Color(0xffffff),
      emissiveIntensity: 0.82,
      roughness: 0.16,
      metalness: 0.08,
    }),
  );

  // Màn hình cong Ultrawide cho Studio Xuất bản (05. Integrator)
  const screenUltrawideMat = track(
    new THREE.MeshStandardMaterial({
      map: textures.screenUltrawideMap,
      emissiveMap: textures.screenUltrawideMap,
      emissive: new THREE.Color(0xffffff),
      emissiveIntensity: 0.78,
      roughness: 0.22,
      metalness: 0.08,
      side: THREE.DoubleSide,
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

  // Tán lá cây kiến trúc xanh sâu tự nhiên
  const plantLeafRich = track(
    new THREE.MeshStandardMaterial({
      color: 0x1e563a,
      roughness: 0.62,
      metalness: 0.01,
    }),
  );

  const plantLeafLight = track(
    new THREE.MeshStandardMaterial({
      color: 0x357c55,
      roughness: 0.58,
      metalness: 0.01,
    }),
  );

  const terracottaPot = track(
    new THREE.MeshStandardMaterial({
      color: 0xe0d8cc,
      bumpMap: textures.plasterBumpMap,
      bumpScale: 0.012,
      roughness: 0.64,
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

  // Vỏ sứ trắng ngà mịn chuẩn Mẫu Robot V12 (độ nhám 0.60, không bị chói nhựa giả)
  const eilikCeramicShell = track(
    new THREE.MeshPhysicalMaterial({
      color: 0xf6f5f1,
      roughness: 0.6,
      metalness: 0.01,
      clearcoat: 0.08,
      clearcoatRoughness: 0.42,
    }),
  );

  // Mặt kính đen bóng sâu cho OLED Face Visor V12
  const visorBlack = track(
    new THREE.MeshPhysicalMaterial({
      color: 0x040508,
      roughness: 0.05,
      metalness: 0.05,
      clearcoat: 1.0,
      clearcoatRoughness: 0.04,
    }),
  );

  const lampShadeGlow = track(
    new THREE.MeshStandardMaterial({
      color: 0xfbf4e4,
      emissive: new THREE.Color(0xffb85c),
      emissiveIntensity: 0.2,
      roughness: 0.5,
    }),
  );

  // Dải LED vàng ấm hắt gầm Bục Chỉ Huy, hắt sau Màn hình 2K & kệ sách/báo cáo
  const warmLedStrip = track(
    new THREE.MeshStandardMaterial({
      color: 0xffedd5,
      emissive: new THREE.Color(0xfbbf24),
      emissiveIntensity: 1.45,
      roughness: 0.25,
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

  const coveLightMat = track(
    new THREE.MeshStandardMaterial({
      color: 0xe0f2fe,
      emissive: new THREE.Color(0xbae6fd),
      emissiveIntensity: 0.9,
      roughness: 0.25,
    }),
  );

  const deskMatDark = track(
    new THREE.MeshStandardMaterial({
      color: 0x262c36,
      roughness: 0.88,
      metalness: 0.04,
    }),
  );

  const sofaFabric = track(
    new THREE.MeshStandardMaterial({
      color: 0xf4f1ec,
      bumpMap: textures.fabricBumpMap,
      bumpScale: 0.012,
      roughness: 0.92,
      metalness: 0.0,
    }),
  );

  const createSoftRobotMat = (hex: number) =>
    track(
      new THREE.MeshPhysicalMaterial({
        color: hex,
        roughness: 0.52,
        metalness: 0.03,
        clearcoat: 0.12,
        clearcoatRoughness: 0.36,
      }),
    );

  const createScreenMat = (map: THREE.CanvasTexture) =>
    track(
      new THREE.MeshStandardMaterial({
        map,
        roughness: 0.24,
        metalness: 0.06,
        emissive: new THREE.Color(0xffffff),
        emissiveMap: map,
        emissiveIntensity: 0.82,
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
    oakSlatWood,
    plasterWall,
    featureWallSlate,
    podiumSlate,
    travertineFloor,
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
    cognacLeather,
    glassPanel,
    planningBoardMat,
    draftingPaperMat,
    easelChartMat,
    missionWallMat,
    hubMapMat,
    screenUltrawideMat,
    screenSleepMat,
    plantLeafRich,
    plantLeafLight,
    terracottaPot,
    ceramicWhite,
    eilikCeramicShell,
    visorBlack,
    lampShadeGlow,
    warmLedStrip,
    contactShadow,
    zzzSpriteMat,
    coveLightMat,
    deskMatDark,
    sofaFabric,
    createSoftRobotMat,
    createScreenMat,
    createAccentGlow,
    dispose: () => {
      tracked.forEach((m) => m.dispose());
    },
  };
}
