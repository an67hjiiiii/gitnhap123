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

const PODIUM_H = 0.28;

/**
 * Kiến trúc Văn Phòng Đa Tầng "Command Atrium" V3 (17.6m × 13.4m):
 * - Bục Chỉ Huy Đá Xám Than nâng cao +0.28m có nẹp đồng thau & LED vàng ấm hắt gầm
 * - Tường chính diện Xanh Slate đậm + Lam gỗ sồi 3D + Màn hình Trung tâm 2K (6.4m × 2.38m) nghiêng nhẹ dễ đọc từ xa
 * - Sàn gỗ sồi mật ong sâu tương phản mạnh với Trục lối đi & Sảnh hội ý trung tâm lát đá Travertine viền đồng
 * - Đầy đủ công cụ nhận diện chuyên biệt cho 11 Phòng Ban (Vault + Qdrant Core, Bàn bản vẽ + Giá biểu đồ,
 *   Cổng QC + Bàn duyệt mộc, Studio Xuất bản Ultrawide + Kệ báo cáo, và 6 phòng chuyên ngành hàng nam)
 * - Giữ nguyên 100% lớp chuyển cảnh mượt ra khuôn viên 360° Đại học Duy Tân.
 */
export function buildStudioArchitecture(
  materials: StudioMaterialLibrary,
  textures: StudioTextureSet,
): StudioArchitectureInstance {
  const group = new THREE.Group();
  group.name = 'command_atrium_v3_office';

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

  const paperMat = trackMat(
    new THREE.MeshStandardMaterial({ color: 0xfaf7f0, roughness: 0.88 }),
  );
  const darkMetalMat = materials.darkMonitorFrame;
  const brassMat = materials.brassAccent;
  const walnutMat = materials.darkWalnutWood;
  const oakTrimMat = materials.oakSlatWood;

  // =========================================================================
  // 0. LỚP NỀN CHUYỂN CẢNH TRONG PHÒNG <-> KHUÔN VIÊN 360° ĐH DUY TÂN
  // =========================================================================
  const interiorSurroundMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0xe6dfd3,
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

  // =========================================================================
  // 1. SÀN CHÍNH GỖ SỒI MẬT ONG SÂU & BỆ TẦNG THƯỢNG NHÀ G (17.6m × 13.4m)
  // =========================================================================
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

  // Lan can kính ban công phía Nam (chỉ hiện khi lăn chuột zoom ra khuôn viên ĐH Duy Tân)
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

  // =========================================================================
  // 2. BỤC CHỈ HUY ĐÁ XÁM THAN (+0.28m) + NẸP ĐỒNG + LED HẮT GẦM + BẬC THANG
  // =========================================================================
  const podiumDepth = 3.84; // z = -6.56 .. -2.72
  const podiumCenterZ = -6.56 + podiumDepth * 0.5;

  const podiumSlab = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(slabW - 0.58, PODIUM_H, podiumDepth)),
    materials.podiumSlate,
  );
  podiumSlab.position.set(0, PODIUM_H * 0.5, podiumCenterZ);
  podiumSlab.castShadow = true;
  podiumSlab.receiveShadow = true;
  group.add(podiumSlab);

  // Viền nẹp đồng thau chạy dọc mép trước bục chỉ huy
  const podiumBrassLip = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(slabW - 0.56, 0.036, 0.05)),
    brassMat,
  );
  podiumBrassLip.position.set(0, PODIUM_H - 0.014, -2.71);
  group.add(podiumBrassLip);

  // Dải LED vàng ấm hắt gầm 2 cánh trái/phải của bục chỉ huy
  [-5.1, 5.1].forEach((lx) => {
    const led = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(6.4, 0.04, 0.04)),
      materials.warmLedStrip,
    );
    led.position.set(lx, 0.045, -2.70);
    group.add(led);
  });

  // Bậc thang gỗ óc chó trung tâm (2 bậc mượt từ z = -2.72 ra z = -2.18, rộng 2.6m)
  const step1 = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(2.65, PODIUM_H * 0.66, 0.30)),
    walnutMat,
  );
  step1.position.set(0, PODIUM_H * 0.33, -2.57);
  step1.castShadow = true;
  step1.receiveShadow = true;
  group.add(step1);

  const step2 = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(2.65, PODIUM_H * 0.34, 0.28)),
    walnutMat,
  );
  step2.position.set(0, PODIUM_H * 0.17, -2.30);
  step2.castShadow = true;
  step2.receiveShadow = true;
  group.add(step2);

  // Nẹp đồng mảnh trên mũi bậc thang
  [-2.42, -2.16].forEach((sz, idx) => {
    const nosing = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(2.66, 0.018, 0.024)),
      brassMat,
    );
    nosing.position.set(0, idx === 0 ? PODIUM_H * 0.66 : PODIUM_H * 0.34, sz);
    group.add(nosing);
  });

  // =========================================================================
  // 3. TRỤC LỐI ĐI CHÍNH & SẢNH HỘI Ý ĐÁ TRAVERTINE SÁNG VIỀN ĐỒNG THAU
  // =========================================================================
  const axisRunner = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(1.48, 0.02, 7.9)),
    materials.travertineFloor,
  );
  axisRunner.position.set(0, 0.01, 1.82);
  axisRunner.receiveShadow = true;
  group.add(axisRunner);

  [-0.75, 0.75].forEach((bx) => {
    const strip = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.032, 0.024, 7.92)),
      brassMat,
    );
    strip.position.set(bx, 0.013, 1.82);
    group.add(strip);
  });

  // Hành lang ngang nối giữa Khu Cốt Lõi và 6 Phòng Chuyên Ngành (z = 2.15)
  const crossWalk = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(14.8, 0.016, 1.12)),
    materials.travertineFloor,
  );
  crossWalk.position.set(0, 0.008, 2.15);
  crossWalk.receiveShadow = true;
  group.add(crossWalk);

  [-0.57, 0.57].forEach((dz) => {
    const trim = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(14.8, 0.02, 0.024)),
      brassMat,
    );
    trim.position.set(0, 0.011, 2.15 + dz);
    group.add(trim);
  });

  // =========================================================================
  // 4. TƯỜNG CHÍNH DIỆN XANH SLATE ĐẬM + LAM GỖ 3D & TƯỜNG HÔNG XÁM ẤM
  // =========================================================================
  const wallT = 0.28;
  const northWallH = 3.55;
  const sideWallH = 2.95;

  // Tường Bắc chính diện Xanh Slate đậm tạo điểm nhấn sang trọng
  const northWall = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(slabW, northWallH, wallT)),
    materials.featureWallSlate,
  );
  northWall.position.set(0, northWallH * 0.5, -slabD * 0.5 + wallT * 0.5);
  northWall.castShadow = true;
  northWall.receiveShadow = true;
  group.add(northWall);

  const northCap = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(slabW + 0.02, 0.06, wallT + 0.02)),
    materials.cutawayWallCap,
  );
  northCap.position.set(0, northWallH + 0.03, -slabD * 0.5 + wallT * 0.5);
  group.add(northCap);

  // Lam gỗ sồi 3D trang trí hai bên Màn hình Trung Tâm
  for (let i = 0; i < 11; i++) {
    const xL = -4.28 + i * 0.095;
    const slatL = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.042, northWallH - PODIUM_H - 0.24, 0.075)),
      oakTrimMat,
    );
    slatL.position.set(xL, PODIUM_H + (northWallH - PODIUM_H - 0.14) * 0.5, -slabD * 0.5 + wallT + 0.038);
    slatL.castShadow = true;
    group.add(slatL);

    const xR = 3.34 + i * 0.095;
    const slatR = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.042, northWallH - PODIUM_H - 0.24, 0.075)),
      oakTrimMat,
    );
    slatR.position.set(xR, PODIUM_H + (northWallH - PODIUM_H - 0.14) * 0.5, -slabD * 0.5 + wallT + 0.038);
    slatR.castShadow = true;
    group.add(slatR);
  }

  // Hai tường hông Xám ấm có chân tường gỗ óc chó & cửa sổ khung đen rèm sáo mảnh
  const addCutawaySideWall = (x: number, z: number, w: number, h: number, d: number) => {
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

    const baseboard = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w + 0.035, 0.16, d + 0.035)),
      walnutMat,
    );
    baseboard.position.set(x, 0.08, z);
    group.add(baseboard);
  };

  addCutawaySideWall(-slabW * 0.5 + wallT * 0.5, -4.6, wallT, sideWallH, 4.1);
  addCutawaySideWall(-slabW * 0.5 + wallT * 0.5, 1.5, wallT, sideWallH, 3.2);
  addCutawaySideWall(-slabW * 0.5 + wallT * 0.5, -1.25, wallT, 0.85, 2.7);
  addCutawaySideWall(slabW * 0.5 - wallT * 0.5, -4.6, wallT, sideWallH, 4.1);
  addCutawaySideWall(slabW * 0.5 - wallT * 0.5, 1.5, wallT, sideWallH, 3.2);
  addCutawaySideWall(slabW * 0.5 - wallT * 0.5, -1.25, wallT, 0.85, 2.7);
  addCutawaySideWall(-slabW * 0.5 + wallT * 0.5, 4.9, wallT, 1.05, 3.6);
  addCutawaySideWall(slabW * 0.5 - wallT * 0.5, 4.9, wallT, 1.05, 3.6);

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
    header.position.set(wx, sideWallH - 0.04, -1.25);
    group.add(header);

    // 4 thanh rèm sáo gỗ mỏng phần đỉnh cửa sổ tăng chiều sâu kiến trúc
    for (let b = 0; b < 4; b++) {
      const blind = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.06, 0.018, 2.52)),
        oakTrimMat,
      );
      blind.position.set(wx, 2.72 - b * 0.095, -1.25);
      group.add(blind);
    }
  });

  // =========================================================================
  // 5. ĐÈN CHIẾU NỘI THẤT ẤM & HELPERS DÙNG CHUNG
  // =========================================================================
  const interiorLights: THREE.PointLight[] = [];
  const lampPositions: Array<[number, number, number]> = [
    [0, 3.3, -3.2],
    [-5.4, 2.6, -1.8],
    [5.4, 2.6, -1.8],
    [0, 2.8, 4.4],
  ];
  lampPositions.forEach(([lx, ly, lz]) => {
    const pl = new THREE.PointLight(0xffbe76, 0.45, 13.5, 1.6);
    pl.position.set(lx, ly, lz);
    group.add(pl);
    interiorLights.push(pl);
  });

  const addDeskLamp = (parent: THREE.Object3D, x: number, y: number, z: number, rotY = 0) => {
    const l = new THREE.Group();
    l.position.set(x, y, z);
    l.rotation.y = rotY;
    const base = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.075, 0.088, 0.024, 14)),
      brassMat,
    );
    l.add(base);
    const stem = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.012, 0.014, 0.34, 8)),
      darkMetalMat,
    );
    stem.position.set(0, 0.17, -0.02);
    stem.rotation.x = 0.16;
    l.add(stem);
    const arm = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.01, 0.012, 0.2, 8)),
      darkMetalMat,
    );
    arm.position.set(0, 0.33, 0.06);
    arm.rotation.x = 1.12;
    l.add(arm);
    const shade = new THREE.Mesh(
      trackGeo(new THREE.ConeGeometry(0.085, 0.11, 14)),
      materials.lampShadeGlow,
    );
    shade.position.set(0, 0.34, 0.14);
    shade.rotation.x = 0.32;
    l.add(shade);
    parent.add(l);
  };

  const addOfficeChair = (
    parent: THREE.Object3D,
    x: number,
    z: number,
    rotY: number,
    accentHex: number,
    yOffset = 0,
  ) => {
    const ch = new THREE.Group();
    ch.position.set(x, yOffset, z);
    ch.rotation.y = rotY;

    const seat = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.54, 0.08, 0.5)),
      materials.fabricChairBlue,
    );
    seat.position.y = 0.44;
    seat.castShadow = true;
    ch.add(seat);

    const back = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.5, 0.52, 0.07)),
      materials.fabricChairBlue,
    );
    back.position.set(0, 0.72, 0.22);
    back.castShadow = true;
    ch.add(back);

    const trim = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.42, 0.04, 0.08)),
      trackMat(new THREE.MeshStandardMaterial({ color: accentHex, roughness: 0.45 })),
    );
    trim.position.set(0, 0.95, 0.22);
    ch.add(trim);

    const post = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.03, 0.032, 0.38, 10)),
      darkMetalMat,
    );
    post.position.y = 0.22;
    ch.add(post);

    for (let i = 0; i < 5; i++) {
      const a = (i / 5) * Math.PI * 2;
      const leg = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.038, 0.034, 0.28)),
        darkMetalMat,
      );
      leg.position.set(Math.sin(a) * 0.14, 0.04, Math.cos(a) * 0.14);
      leg.rotation.y = a;
      ch.add(leg);
    }
    parent.add(ch);
  };

  const addTallTree = (x: number, y: number, z: number, scale = 1.0) => {
    const p = new THREE.Group();
    p.position.set(x, y, z);
    p.scale.setScalar(scale);

    const pot = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.3, 0.22, 0.52, 16)),
      materials.terracottaPot,
    );
    pot.position.y = 0.26;
    pot.castShadow = true;
    p.add(pot);

    const potBand = new THREE.Mesh(
      trackGeo(new THREE.TorusGeometry(0.295, 0.016, 8, 20)),
      brassMat,
    );
    potBand.rotation.x = Math.PI / 2;
    potBand.position.y = 0.48;
    p.add(potBand);

    const trunk = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.03, 0.048, 1.28, 8)),
      walnutMat,
    );
    trunk.position.set(0, 1.1, 0);
    trunk.rotation.z = 0.04;
    trunk.castShadow = true;
    p.add(trunk);

    const clusters: Array<[number, number, number, number]> = [
      [0, 1.86, 0, 0.35],
      [-0.24, 1.66, 0.14, 0.25],
      [0.25, 1.72, -0.12, 0.27],
      [-0.12, 1.52, -0.2, 0.23],
      [0.16, 2.04, 0.1, 0.23],
    ];
    clusters.forEach(([cx, cy, cz, r], idx) => {
      const mat = idx % 2 === 0 ? materials.plantLeafRich : materials.plantLeafLight;
      for (let k = 0; k < 4; k++) {
        const ang = (k / 4) * Math.PI * 2 + idx * 0.9;
        const lf = new THREE.Mesh(trackGeo(new THREE.SphereGeometry(r * 0.62, 9, 7)), mat);
        lf.scale.set(1.15, 0.68, 0.96);
        lf.position.set(cx + Math.cos(ang) * r * 0.42, cy + (k % 2) * 0.07, cz + Math.sin(ang) * r * 0.42);
        lf.castShadow = true;
        p.add(lf);
      }
    });
    group.add(p);
  };

  addTallTree(-8.05, PODIUM_H, -5.85, 0.98);
  addTallTree(8.05, PODIUM_H, -5.85, 0.98);
  addTallTree(-8.1, 0, 2.25, 0.95);
  addTallTree(8.1, 0, 2.25, 0.95);

  const addStationCollider = (agentId: AgentId, x: number, y: number, z: number, w: number, d: number) => {
    const col = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(w, 0.55, d)),
      trackMat(new THREE.MeshBasicMaterial({ visible: false })),
    );
    col.position.set(x, y + 0.28, z);
    col.userData.agentId = agentId;
    col.layers.set(1);
    group.add(col);
    stationColliders.push(col);
  };

  // =========================================================================
  // 6. KHU 01: MÀN HÌNH TRUNG TÂM 2K (6.4m × 2.38m) & BÀN CHỈ HUY ORCHESTRATOR
  // =========================================================================
  const heroGroup = new THREE.Group();
  heroGroup.position.set(0, PODIUM_H + 1.88, -6.08);
  heroGroup.rotation.x = 0.095; // nghiêng nhẹ hướng về mắt người xem toàn cảnh

  const heroFrame = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(6.58, 2.52, 0.14)),
    darkMetalMat,
  );
  heroFrame.castShadow = true;
  heroGroup.add(heroFrame);

  const heroBrassTrim = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(6.66, 2.60, 0.08)),
    brassMat,
  );
  heroBrassTrim.position.z = -0.04;
  heroGroup.add(heroBrassTrim);

  const heroBackGlow = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(6.74, 2.68, 0.04)),
    materials.warmLedStrip,
  );
  heroBackGlow.position.z = -0.10;
  heroGroup.add(heroBackGlow);

  const heroScreen = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(6.38, 2.36)),
    materials.missionWallMat,
  );
  heroScreen.position.z = 0.076;
  heroGroup.add(heroScreen);
  group.add(heroGroup);

  // Bục bảng kế hoạch thấp gọn của Orchestrator đặt phía trước Màn hình 2K (không che màn hình)
  const orchGroup = new THREE.Group();
  orchGroup.position.set(0, PODIUM_H, -4.88);

  const cmdConsole = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(2.55, 0.62, 0.56)),
    walnutMat,
  );
  cmdConsole.position.y = 0.31;
  cmdConsole.castShadow = true;
  cmdConsole.receiveShadow = true;
  orchGroup.add(cmdConsole);

  const cmdTop = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(2.62, 0.06, 0.62)),
    oakTrimMat,
  );
  cmdTop.position.y = 0.64;
  cmdTop.castShadow = true;
  orchGroup.add(cmdTop);

  const cmdBoard = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(2.3, 0.48)),
    materials.planningBoardMat,
  );
  cmdBoard.position.set(0, 0.68, 0.02);
  cmdBoard.rotation.x = -Math.PI * 0.42;
  orchGroup.add(cmdBoard);

  // 7 thẻ kế hoạch 3D nổi bật bật dần lên khi Orchestrator phân rã nhiệm vụ
  const wbCardColors = [0xf59e0b, 0x10b981, 0x0ea5e9, 0xec4899, 0x8b5cf6, 0xf97316, 0x14b8a6];
  const wbCards: THREE.Mesh[] = [];
  for (let i = 0; i < 7; i++) {
    const card = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.24, 0.14, 0.024)),
      trackMat(
        new THREE.MeshStandardMaterial({
          color: wbCardColors[i],
          emissive: new THREE.Color(wbCardColors[i]),
          emissiveIntensity: 0.45,
          roughness: 0.35,
        }),
      ),
    );
    card.position.set(-0.96 + i * 0.32, 0.78, -0.14);
    card.rotation.x = -0.25;
    card.visible = false;
    orchGroup.add(card);
    wbCards.push(card);
  }
  group.add(orchGroup);
  addStationCollider('orchestrator', 0, PODIUM_H, -3.9, 3.2, 2.4);

  // =========================================================================
  // 7. KHU 02: KHO TRI THỨC & THƯ VIỆN RAG (TRÊN BỤC TRÁI, y = 0.28)
  // =========================================================================
  const ragGroup = new THREE.Group();
  ragGroup.position.set(0, PODIUM_H, 0);

  // 7a. Két Bạc Vault có Bánh Lái Đồng Xoay & Ngăn Kéo Hồ Sơ Trượt
  const vault = new THREE.Group();
  vault.position.set(-6.85, 0, -5.28);

  const vBody = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(1.18, 1.56, 0.92)),
    materials.brushedSteel,
  );
  vBody.position.y = 0.78;
  vBody.castShadow = true;
  vBody.receiveShadow = true;
  vault.add(vBody);

  const vDoor = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.98, 1.38, 0.06)),
    materials.chromeMetal,
  );
  vDoor.position.set(0, 0.78, 0.46);
  vault.add(vDoor);

  const vaultWheel = new THREE.Group();
  vaultWheel.position.set(0.08, 0.78, 0.53);
  const wheelRing = new THREE.Mesh(
    trackGeo(new THREE.TorusGeometry(0.21, 0.032, 10, 22)),
    brassMat,
  );
  vaultWheel.add(wheelRing);
  for (let i = 0; i < 4; i++) {
    const sp = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.015, 0.015, 0.4, 8)),
      brassMat,
    );
    sp.rotation.z = (i * Math.PI) / 4;
    vaultWheel.add(sp);
  }
  vault.add(vaultWheel);

  const vaultLedMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x10b981,
      emissive: new THREE.Color(0x10b981),
      emissiveIntensity: 0.4,
      roughness: 0.3,
    }),
  );
  const vaultLedMesh = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.84, 0.048, 0.06)),
    vaultLedMat,
  );
  vaultLedMesh.position.set(0, 1.59, 0.43);
  vault.add(vaultLedMesh);

  // Ngăn kéo trượt hồ sơ RAG bên cạnh két (đặt gần vị trí đứng CABINET_SPOT [-5.45, -4.45])
  const drawerCabinet = new THREE.Group();
  drawerCabinet.position.set(-5.45, 0, -5.42);
  const cabShell = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.96, 0.96, 0.74)),
    walnutMat,
  );
  cabShell.position.y = 0.48;
  cabShell.castShadow = true;
  drawerCabinet.add(cabShell);

  const slidingDrawer = new THREE.Group();
  slidingDrawer.position.set(0, 0.68, 0.02);
  const drFront = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.86, 0.32, 0.62)),
    oakTrimMat,
  );
  slidingDrawer.add(drFront);
  const drHandle = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.28, 0.03, 0.05)),
    brassMat,
  );
  drHandle.position.set(0, 0.04, 0.33);
  slidingDrawer.add(drHandle);
  for (let f = 0; f < 5; f++) {
    const tab = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.72, 0.24, 0.024)),
      trackMat(
        new THREE.MeshStandardMaterial({
          color: f % 2 === 0 ? 0x10b981 : 0xf59e0b,
          roughness: 0.55,
        }),
      ),
    );
    tab.position.set(0, 0.06, -0.2 + f * 0.09);
    slidingDrawer.add(tab);
  }
  drawerCabinet.add(slidingDrawer);
  ragGroup.add(vault);
  ragGroup.add(drawerCabinet);

  // 7b. Tủ Sách Chạm Trần có LED kệ & Thang Trượt Gỗ
  const shelf = new THREE.Group();
  shelf.position.set(-5.45, 0.96, -5.66);
  const sBack = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(1.75, 1.92, 0.05)),
    walnutMat,
  );
  sBack.position.set(0, 0.96, -0.2);
  shelf.add(sBack);
  [-0.85, 0.85].forEach((sx) => {
    const side = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.06, 1.92, 0.42)),
      walnutMat,
    );
    side.position.set(sx, 0.96, 0);
    shelf.add(side);
  });
  const bookCols = [0x0f766e, 0x1d4ed8, 0xc2410c, 0xbe123c, 0x5b21b6, 0x047857, 0xb45309, 0x334155];
  for (let tier = 0; tier < 4; tier++) {
    const ty = 0.08 + tier * 0.45;
    const board = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(1.7, 0.04, 0.4)),
      walnutMat,
    );
    board.position.set(0, ty, 0);
    shelf.add(board);

    const led = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(1.56, 0.016, 0.02)),
      materials.warmLedStrip,
    );
    led.position.set(0, ty - 0.022, 0.14);
    shelf.add(led);

    if (tier < 3) {
      for (let b = 0; b < 9; b++) {
        const bh = 0.24 + ((tier * 3 + b) % 4) * 0.03;
        const bk = new THREE.Mesh(
          trackGeo(new THREE.BoxGeometry(0.12, bh, 0.24)),
          trackMat(new THREE.MeshStandardMaterial({ color: bookCols[(tier * 5 + b) % bookCols.length], roughness: 0.62 })),
        );
        bk.position.set(-0.68 + b * 0.165, ty + 0.02 + bh * 0.5, 0.02);
        shelf.add(bk);
      }
    }
  }
  const rail = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.016, 0.016, 1.78, 10)),
    brassMat,
  );
  rail.rotation.z = Math.PI / 2;
  rail.position.set(0, 1.66, 0.23);
  shelf.add(rail);
  ragGroup.add(shelf);

  // 7c. Trụ Lõi Vector Qdrant Kính Trong 4 Đĩa Xanh Ngọc Phát Sáng
  const qdrant = new THREE.Group();
  qdrant.position.set(-4.08, 0, -5.22);
  const qBase = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.30, 0.34, 0.22, 20)),
    darkMetalMat,
  );
  qBase.position.y = 0.11;
  qBase.castShadow = true;
  qdrant.add(qBase);

  const qTop = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.30, 0.30, 0.12, 20)),
    darkMetalMat,
  );
  qTop.position.y = 1.56;
  qTop.castShadow = true;
  qdrant.add(qTop);

  const qGlass = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.26, 0.26, 1.28, 20)),
    trackMat(
      new THREE.MeshPhysicalMaterial({
        color: 0xa7f3d0,
        roughness: 0.08,
        transparent: true,
        opacity: 0.34,
        depthWrite: false,
      }),
    ),
  );
  qGlass.position.y = 0.88;
  qdrant.add(qGlass);

  const qdrantDiscMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x10b981,
      emissive: new THREE.Color(0x10b981),
      emissiveIntensity: 0.9,
      roughness: 0.28,
    }),
  );
  const qdrantDiscs: THREE.Mesh[] = [];
  for (let d = 0; d < 4; d++) {
    const disc = new THREE.Mesh(
      trackGeo(new THREE.CylinderGeometry(0.18, 0.18, 0.055, 18)),
      qdrantDiscMat,
    );
    disc.position.y = 0.44 + d * 0.27;
    qdrant.add(disc);
    qdrantDiscs.push(disc);
  }
  ragGroup.add(qdrant);

  // Bàn đọc tài liệu bên trái (khớp sleepPos [-6.45, -3.2])
  const ragDesk = new THREE.Group();
  ragDesk.position.set(-7.18, 0, -3.2);
  const ragTop = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.76, 0.07, 1.45)),
    walnutMat,
  );
  ragTop.position.y = 0.72;
  ragTop.castShadow = true;
  ragDesk.add(ragTop);
  [-0.58, 0.58].forEach((dz) => {
    const l = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.62, 0.7, 0.055)), darkMetalMat);
    l.position.set(0, 0.35, dz);
    ragDesk.add(l);
  });
  addDeskLamp(ragDesk, -0.1, 0.75, -0.45, 1.2);
  ragGroup.add(ragDesk);
  addOfficeChair(ragGroup, -6.45, -3.2, Math.PI * 0.5, 0x009e73, 0);

  group.add(ragGroup);
  addStationCollider('rag', -5.6, PODIUM_H, -4.2, 3.6, 2.8);

  // =========================================================================
  // 8. SẢNH HỘI Ý TRUNG TÂM TRÒN (BÀN BẢN ĐỒ KÍNH C27 + 2 GHẾ BĂNG CONG DA COGNAC)
  // =========================================================================
  const atrium = new THREE.Group();
  atrium.position.set(0, 0, -0.45);

  const stonePad = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(2.24, 2.26, 0.028, 48)),
    materials.travertineFloor,
  );
  stonePad.position.y = 0.014;
  stonePad.receiveShadow = true;
  atrium.add(stonePad);

  const brassRing = new THREE.Mesh(
    trackGeo(new THREE.TorusGeometry(2.25, 0.026, 10, 56)),
    brassMat,
  );
  brassRing.rotation.x = Math.PI / 2;
  brassRing.position.y = 0.03;
  atrium.add(brassRing);

  const hubPed = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.42, 0.56, 0.52, 28)),
    walnutMat,
  );
  hubPed.position.y = 0.26;
  hubPed.castShadow = true;
  atrium.add(hubPed);

  const hubRim = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(1.06, 1.02, 0.075, 36)),
    oakTrimMat,
  );
  hubRim.position.y = 0.55;
  hubRim.castShadow = true;
  atrium.add(hubRim);

  const hubMapDisc = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.89, 0.89, 0.082, 36)),
    materials.hubMapMat,
  );
  hubMapDisc.position.y = 0.554;
  atrium.add(hubMapDisc);

  // 2 ghế băng cong da bò Cognac đối xứng 2 bên bàn bản đồ
  [-1, 1].forEach((side) => {
    const seatArc = new THREE.Mesh(
      trackGeo(new THREE.TorusGeometry(1.74, 0.2, 12, 24, Math.PI * 0.42)),
      materials.cognacLeather,
    );
    seatArc.rotation.x = Math.PI / 2;
    seatArc.rotation.z = side < 0 ? Math.PI * 0.79 : -Math.PI * 0.21;
    seatArc.scale.set(1, 1, 0.74);
    seatArc.position.y = 0.34;
    seatArc.castShadow = true;
    atrium.add(seatArc);

    const baseArc = new THREE.Mesh(
      trackGeo(new THREE.TorusGeometry(1.74, 0.14, 8, 20, Math.PI * 0.40)),
      walnutMat,
    );
    baseArc.rotation.x = Math.PI / 2;
    baseArc.rotation.z = side < 0 ? Math.PI * 0.80 : -Math.PI * 0.20;
    baseArc.position.y = 0.15;
    atrium.add(baseArc);
  });

  // Phong bì yêu cầu 3D bay lơ lửng khi có câu hỏi mới gửi vào hệ thống
  const requestEnvelope = new THREE.Group();
  requestEnvelope.position.set(0, 0.78, 0);
  const envBody = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.46, 0.06, 0.32)),
    trackMat(
      new THREE.MeshStandardMaterial({
        color: 0xf59e0b,
        emissive: new THREE.Color(0xf59e0b),
        emissiveIntensity: 0.45,
        roughness: 0.35,
      }),
    ),
  );
  requestEnvelope.add(envBody);
  const envSeal = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.065, 0.065, 0.072, 14)),
    trackMat(new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfef3c7, emissiveIntensity: 0.5 })),
  );
  requestEnvelope.add(envSeal);
  requestEnvelope.visible = false;
  atrium.add(requestEnvelope);

  group.add(atrium);

  // =========================================================================
  // 9. KHU 03: DATA ANALYST (BÀN BẢN VẼ NGHIÊNG + GIÁ BIỂU ĐỒ 3 CHÂN + HOLO)
  // =========================================================================
  const analystGroup = new THREE.Group();
  analystGroup.position.set(-5.4, 0, -0.32);

  const aRug = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.45, 0.016, 2.75)),
    materials.rugBlue,
  );
  aRug.position.set(0.35, 0.008, 0.18);
  aRug.receiveShadow = true;
  analystGroup.add(aRug);

  const aTop = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(1.76, 0.07, 0.92)),
    walnutMat,
  );
  aTop.position.set(0, 0.74, 0);
  aTop.rotation.x = 0.11;
  aTop.castShadow = true;
  aTop.receiveShadow = true;
  analystGroup.add(aTop);

  [-0.76, 0.76].forEach((lx) => {
    const leg = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.06, 0.7, 0.76)), darkMetalMat);
    leg.position.set(lx, 0.35, 0);
    leg.castShadow = true;
    analystGroup.add(leg);
  });

  const blueprint = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.92, 0.014, 0.62)),
    materials.draftingPaperMat,
  );
  blueprint.position.set(-0.12, 0.785, 0.02);
  blueprint.rotation.x = 0.11;
  analystGroup.add(blueprint);

  const ruler = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.46, 0.015, 0.06)),
    trackMat(new THREE.MeshStandardMaterial({ color: 0x2563eb, roughness: 0.35 })),
  );
  ruler.position.set(-0.08, 0.80, 0.14);
  ruler.rotation.set(0.11, 0.22, 0);
  analystGroup.add(ruler);

  const calc = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.18, 0.028, 0.26)),
    darkMetalMat,
  );
  calc.position.set(0.56, 0.79, 0.08);
  calc.rotation.set(0.11, -0.18, 0);
  analystGroup.add(calc);

  addDeskLamp(analystGroup, -0.7, 0.77, -0.32, 0.5);
  addOfficeChair(analystGroup, 0, 0.74, 0, 0x1d4ed8, 0);

  // Giá vẽ biểu đồ 3 chân
  const easel = new THREE.Group();
  easel.position.set(1.68, 0, -0.28);
  easel.rotation.y = -0.52;
  const easelLegGeo = trackGeo(new THREE.CylinderGeometry(0.022, 0.026, 1.52, 8));
  [
    [-0.34, 0.12, -0.1],
    [0.34, 0.12, -0.1],
    [0, -0.26, 0.24],
  ].forEach(([lx, lz, rx]) => {
    const leg = new THREE.Mesh(easelLegGeo, oakTrimMat);
    leg.position.set(lx, 0.74, lz);
    leg.rotation.x = rx;
    leg.castShadow = true;
    easel.add(leg);
  });
  const eFrame = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.94, 1.14, 0.05)), walnutMat);
  eFrame.position.set(0, 1.14, 0.06);
  eFrame.rotation.x = -0.14;
  eFrame.castShadow = true;
  easel.add(eFrame);

  const eChart = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(0.86, 1.06)),
    materials.easelChartMat,
  );
  eChart.position.set(0, 1.14, 0.09);
  eChart.rotation.x = -0.14;
  easel.add(eChart);
  analystGroup.add(easel);

  // Cột biểu đồ hologram 3D phát sáng khi Data Analyst đang phân tích
  const analystHoloGroup = new THREE.Group();
  analystHoloGroup.position.set(0.12, 0.88, -0.1);
  const analystBars: THREE.Mesh[] = [];
  const barColors = [0x38bdf8, 0x2563eb, 0x10b981, 0xf59e0b];
  for (let i = 0; i < 4; i++) {
    const bar = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.1, 0.52, 0.1)),
      trackMat(
        new THREE.MeshStandardMaterial({
          color: barColors[i],
          emissive: new THREE.Color(barColors[i]),
          emissiveIntensity: 0.75,
          transparent: true,
          opacity: 0.86,
        }),
      ),
    );
    bar.position.set(-0.24 + i * 0.16, 0.26, 0);
    analystHoloGroup.add(bar);
    analystBars.push(bar);
  }
  analystHoloGroup.visible = false;
  analystGroup.add(analystHoloGroup);

  group.add(analystGroup);
  addStationCollider('analyst', -5.4, 0, -0.1, 3.6, 2.8);

  // =========================================================================
  // 10. KHU 04: REVIEWER & CỔNG KIỂM ĐỊNH QC (CỔNG MỞ + BÀN DUYỆT MỘC)
  // =========================================================================
  const qcGate = new THREE.Group();
  qcGate.position.set(3.52, 0, -0.25);

  const qcGateLedMat = trackMat(
    new THREE.MeshStandardMaterial({
      color: 0x94a3b8,
      emissive: new THREE.Color(0x94a3b8),
      emissiveIntensity: 0.2,
      roughness: 0.28,
    }),
  );
  const qcGateLedMeshes: THREE.Mesh[] = [];

  [-0.66, 0.66].forEach((px) => {
    const pillar = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.18, 1.4, 0.36)),
      materials.brushedSteel,
    );
    pillar.position.set(px, 0.7, 0);
    pillar.castShadow = true;
    qcGate.add(pillar);

    const trim = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.2, 0.04, 0.38)),
      brassMat,
    );
    trim.position.set(px, 1.3, 0);
    qcGate.add(trim);

    const led = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.2, 0.052, 0.38)),
      qcGateLedMat,
    );
    led.position.set(px, 1.42, 0);
    qcGate.add(led);
    qcGateLedMeshes.push(led);
  });

  const qcHeader = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(1.52, 0.08, 0.16)),
    darkMetalMat,
  );
  qcHeader.position.set(0, 1.4, 0);
  qcGate.add(qcHeader);

  // 2 cánh thanh chắn kính xoay mở mượt khi Reviewer đóng dấu đạt chuẩn
  const qcBarrierMat = trackMat(
    new THREE.MeshPhysicalMaterial({
      color: 0x86efac,
      roughness: 0.08,
      transparent: true,
      opacity: 0.3,
      depthWrite: false,
    }),
  );
  const qcGateArmLeft = new THREE.Group();
  qcGateArmLeft.position.set(-0.56, 0.72, 0);
  const armL = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.54, 0.56, 0.03)), qcBarrierMat);
  armL.position.x = 0.27;
  qcGateArmLeft.add(armL);
  qcGate.add(qcGateArmLeft);

  const qcGateArmRight = new THREE.Group();
  qcGateArmRight.position.set(0.56, 0.72, 0);
  const armR = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.54, 0.56, 0.03)), qcBarrierMat);
  armR.position.x = -0.27;
  qcGateArmRight.add(armR);
  qcGate.add(qcGateArmRight);
  group.add(qcGate);

  const reviewerGroup = new THREE.Group();
  reviewerGroup.position.set(5.4, 0, -0.32);

  const rRug = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(3.25, 0.016, 2.75)),
    materials.rugSand,
  );
  rRug.position.set(-0.22, 0.008, 0.18);
  rRug.receiveShadow = true;
  reviewerGroup.add(rRug);

  const rTop = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(1.76, 0.08, 0.88)), walnutMat);
  rTop.position.y = 0.72;
  rTop.castShadow = true;
  rTop.receiveShadow = true;
  reviewerGroup.add(rTop);

  const rDrawer = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.44, 0.68, 0.76)), walnutMat);
  rDrawer.position.set(0.56, 0.34, 0);
  rDrawer.castShadow = true;
  reviewerGroup.add(rDrawer);

  const rLeg = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.06, 0.68, 0.74)), darkMetalMat);
  rLeg.position.set(-0.76, 0.34, 0);
  reviewerGroup.add(rLeg);

  for (let i = 0; i < 4; i++) {
    const sheet = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.28, 0.018, 0.36)), paperMat);
    sheet.position.set(-0.48, 0.77 + i * 0.02, 0.05);
    sheet.rotation.y = (i - 1.5) * 0.07;
    reviewerGroup.add(sheet);
  }
  const clip = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.3, 0.02, 0.4)),
    trackMat(new THREE.MeshStandardMaterial({ color: 0xdc1e3c, roughness: 0.48 })),
  );
  clip.position.set(0.02, 0.77, 0.14);
  clip.rotation.y = -0.12;
  reviewerGroup.add(clip);

  const clipPaper = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.24, 0.024, 0.33)), paperMat);
  clipPaper.position.set(0.02, 0.775, 0.15);
  clipPaper.rotation.y = -0.12;
  reviewerGroup.add(clipPaper);

  const stampBase = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.044, 0.05, 0.03, 12)),
    darkMetalMat,
  );
  stampBase.position.set(0.34, 0.78, 0.18);
  reviewerGroup.add(stampBase);

  const stampHandle = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(0.018, 0.028, 0.09, 10)),
    trackMat(new THREE.MeshStandardMaterial({ color: 0xdc1e3c, roughness: 0.4 })),
  );
  stampHandle.position.set(0.34, 0.84, 0.18);
  reviewerGroup.add(stampHandle);

  const rMon = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.68, 0.4, 0.035)), darkMetalMat);
  rMon.position.set(0.1, 1.06, -0.22);
  rMon.castShadow = true;
  reviewerGroup.add(rMon);

  const rScr = new THREE.Mesh(
    trackGeo(new THREE.PlaneGeometry(0.62, 0.34)),
    materials.createScreenMat(textures.screenHrMap),
  );
  rScr.position.set(0.1, 1.06, -0.2);
  reviewerGroup.add(rScr);

  addDeskLamp(reviewerGroup, -0.68, 0.76, -0.28, 0.55);
  addOfficeChair(reviewerGroup, 0, 0.74, 0, 0xdc1e3c, 0);

  // Huy hiệu đạt chuẩn QC bay xoay tròn trên bàn Reviewer khi duyệt đạt
  const qcBadgeGroup = new THREE.Group();
  qcBadgeGroup.position.set(0.05, 1.38, 0.05);
  const qcRing = new THREE.Mesh(
    trackGeo(new THREE.TorusGeometry(0.24, 0.032, 10, 24)),
    trackMat(
      new THREE.MeshStandardMaterial({
        color: 0x16a34a,
        emissive: new THREE.Color(0x16a34a),
        emissiveIntensity: 0.9,
      }),
    ),
  );
  qcBadgeGroup.add(qcRing);
  const qcCore = new THREE.Mesh(
    trackGeo(new THREE.OctahedronGeometry(0.12, 0)),
    trackMat(new THREE.MeshStandardMaterial({ color: 0x86efac, emissive: 0x22c55e, emissiveIntensity: 0.8 })),
  );
  qcBadgeGroup.add(qcCore);
  qcBadgeGroup.visible = false;
  reviewerGroup.add(qcBadgeGroup);

  group.add(reviewerGroup);
  addStationCollider('reviewer', 5.4, 0, -0.1, 3.6, 2.8);

  // =========================================================================
  // 11. KHU 05: INTEGRATOR STUDIO XUẤT BẢN (TRÊN BỤC PHẢI, y = 0.28)
  // =========================================================================
  const intGroup = new THREE.Group();
  intGroup.position.set(0, PODIUM_H, 0);

  const intDesk = new THREE.Group();
  intDesk.position.set(5.6, 0, -4.18);

  const iTop = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(2.05, 0.08, 0.94)), walnutMat);
  iTop.position.y = 0.72;
  iTop.castShadow = true;
  iTop.receiveShadow = true;
  intDesk.add(iTop);

  const iDrawer = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.46, 0.68, 0.8)), walnutMat);
  iDrawer.position.set(-0.72, 0.34, 0);
  iDrawer.castShadow = true;
  intDesk.add(iDrawer);

  const iLeg = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.06, 0.68, 0.78)), darkMetalMat);
  iLeg.position.set(0.92, 0.34, 0);
  intDesk.add(iLeg);

  // Màn hình cong Ultrawide đặc trưng của Studio Xuất bản
  const uwBack = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(2.4, 2.4, 0.44, 22, 1, true, -0.24, 0.48)),
    trackMat(new THREE.MeshStandardMaterial({ color: 0x1e2430, roughness: 0.35, metalness: 0.6, side: THREE.DoubleSide })),
  );
  uwBack.position.set(0, 1.1, 2.15);
  uwBack.rotation.y = Math.PI;
  intDesk.add(uwBack);

  const uwScr = new THREE.Mesh(
    trackGeo(new THREE.CylinderGeometry(2.38, 2.38, 0.39, 22, 1, true, -0.23, 0.46)),
    materials.screenUltrawideMat,
  );
  uwScr.position.set(0, 1.1, 2.15);
  uwScr.rotation.y = Math.PI;
  intDesk.add(uwScr);

  const uwStand = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.08, 0.32, 0.06)),
    materials.brushedSteel,
  );
  uwStand.position.set(0, 0.88, -0.28);
  intDesk.add(uwStand);

  for (let i = 0; i < 3; i++) {
    const rep = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(0.3, 0.04, 0.4)),
      trackMat(new THREE.MeshStandardMaterial({ color: 0x6d28d9, roughness: 0.48 })),
    );
    rep.position.set(0.68, 0.78 + i * 0.044, 0.14);
    rep.rotation.y = i * 0.08;
    rep.castShadow = true;
    intDesk.add(rep);
  }
  addOfficeChair(intDesk, 0, 0.73, 0, 0x6d28d9, 0);
  intGroup.add(intDesk);

  // Kệ Trưng Bày Báo Cáo chiếu đèn LED vàng ấm trên Tường Slate đậm
  const displayShelf = new THREE.Group();
  displayShelf.position.set(5.75, 1.44, -6.1);
  for (let r = 0; r < 2; r++) {
    const sh = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(2.05, 0.05, 0.28)), oakTrimMat);
    sh.position.y = r * 0.58;
    sh.castShadow = true;
    displayShelf.add(sh);

    const led = new THREE.Mesh(
      trackGeo(new THREE.BoxGeometry(1.92, 0.02, 0.024)),
      materials.warmLedStrip,
    );
    led.position.set(0, r * 0.58 - 0.03, 0.08);
    displayShelf.add(led);

    for (let b = 0; b < 4; b++) {
      const folder = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.24, 0.36, 0.05)),
        trackMat(new THREE.MeshStandardMaterial({ color: b % 2 === 0 ? 0x8b5cf6 : 0x38bdf8, roughness: 0.4 })),
      );
      folder.position.set(-0.68 + b * 0.45, r * 0.58 + 0.2, -0.02);
      folder.rotation.x = -0.14;
      displayShelf.add(folder);
    }
  }
  intGroup.add(displayShelf);

  // Máy in đóng quyển đặt cạnh bàn Integrator
  const printer = new THREE.Group();
  printer.position.set(7.25, 0, -4.55);
  const pCab = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.76, 0.74, 0.66)), walnutMat);
  pCab.position.y = 0.37;
  pCab.castShadow = true;
  printer.add(pCab);

  const pBody = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.66, 0.34, 0.54)),
    materials.whiteChairShell,
  );
  pBody.position.y = 0.91;
  pBody.castShadow = true;
  printer.add(pBody);

  const outPaper = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.28, 0.015, 0.34)), paperMat);
  outPaper.position.set(0, 0.88, 0.34);
  outPaper.rotation.x = 0.25;
  printer.add(outPaper);
  intGroup.add(printer);

  // Hiệu ứng quyển báo cáo hoàn tất tỏa hào quang trên bàn Integrator
  const finalReportGroup = new THREE.Group();
  finalReportGroup.position.set(5.6, 1.48, -4.18);
  const bookCover = new THREE.Mesh(
    trackGeo(new THREE.BoxGeometry(0.36, 0.46, 0.08)),
    trackMat(
      new THREE.MeshStandardMaterial({
        color: 0x6d28d9,
        emissive: new THREE.Color(0x8b5cf6),
        emissiveIntensity: 0.55,
        roughness: 0.3,
      }),
    ),
  );
  finalReportGroup.add(bookCover);
  const bookHalo = new THREE.Mesh(
    trackGeo(new THREE.TorusGeometry(0.36, 0.025, 10, 28)),
    trackMat(
      new THREE.MeshStandardMaterial({
        color: 0xfbbf24,
        emissive: new THREE.Color(0xfbbf24),
        emissiveIntensity: 1.0,
      }),
    ),
  );
  finalReportGroup.add(bookHalo);
  finalReportGroup.visible = false;
  intGroup.add(finalReportGroup);

  group.add(intGroup);
  addStationCollider('integrator', 5.6, PODIUM_H, -4.0, 3.4, 2.8);

  // =========================================================================
  // 12. 6 PHÒNG BAN CHUYÊN NGÀNH HÀNG NAM (06–11) VỚI CÔNG CỤ ĐẶC TRƯNG RIÊNG
  // =========================================================================
  const specScreenMeshes: Partial<Record<SpecialistAgentId, THREE.Mesh[]>> = {};
  const specStripMats: Partial<Record<SpecialistAgentId, THREE.MeshStandardMaterial>> = {};
  const specActiveScreenMats: Record<SpecialistAgentId, THREE.MeshStandardMaterial> = {
    software: materials.createScreenMat(textures.screenCodeMap),
    business: materials.createScreenMat(textures.screenBusinessMap),
    marketing: materials.createScreenMat(textures.screenMarketingMap),
    hr: materials.createScreenMat(textures.screenHrMap),
    finance: materials.createScreenMat(textures.screenFinanceMap),
    education: materials.createScreenMat(textures.screenEducationMap),
  };

  for (const specId of SPECIALIST_AGENT_IDS) {
    const profile = AGENT_PROFILES[specId];
    const [cx, cz] = profile.stationCenter;

    const bay = new THREE.Group();
    bay.position.set(cx, 0, cz);

    // Bàn gỗ óc chó đặt phía nam (z = +0.68 trong bay), robot ngồi ở z = -0.10 hướng mặt về bàn (yaw = 0)
    const desk = new THREE.Group();
    desk.position.set(0, 0, 0.68);
    desk.rotation.y = Math.PI; // mặt trước màn hình quay về robot ngồi ở phía bắc

    const dTop = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(2.05, 0.08, 0.84)), walnutMat);
    dTop.position.y = 0.72;
    dTop.castShadow = true;
    dTop.receiveShadow = true;
    desk.add(dTop);

    const dDrawer = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.42, 0.68, 0.74)), walnutMat);
    dDrawer.position.set(-0.74, 0.34, 0);
    dDrawer.castShadow = true;
    desk.add(dDrawer);

    const dLeg = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.055, 0.68, 0.72)), darkMetalMat);
    dLeg.position.set(0.92, 0.34, 0);
    desk.add(dLeg);

    // Dải đèn LED nhận diện màu phòng ban trên gờ bàn (sáng rực khi thức / đang làm lead)
    const stripMat = trackMat(
      new THREE.MeshStandardMaterial({
        color: profile.accentNumber,
        emissive: new THREE.Color(profile.accentNumber),
        emissiveIntensity: 0.14,
        roughness: 0.32,
      }),
    );
    specStripMats[specId] = stripMat;
    const strip = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(1.88, 0.036, 0.028)), stripMat);
    strip.position.set(0, 0.72, 0.425);
    desk.add(strip);

    // Vách kính ngăn cách tinh tế viền đồng thau bên phải (trừ bàn ngoài cùng bên phải và giữa trục đá)
    if (specId !== 'marketing' && specId !== 'education') {
      const partGlass = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.03, 0.96, 1.48)),
        materials.glassPanel,
      );
      partGlass.position.set(1.34, 0.48, 0.2);
      partGlass.renderOrder = 2;
      bay.add(partGlass);

      const partRail = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.048, 0.04, 1.5)),
        brassMat,
      );
      partRail.position.set(1.34, 0.97, 0.2);
      bay.add(partRail);
    }

    // Bàn phím & chuột
    const kb = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.44, 0.02, 0.14)), darkMetalMat);
    kb.position.set(-0.08, 0.772, 0.16);
    desk.add(kb);
    const mouse = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.065, 0.022, 0.095)), darkMetalMat);
    mouse.position.set(0.24, 0.772, 0.16);
    desk.add(mouse);

    addOfficeChair(bay, 0, -0.1, Math.PI, profile.accentNumber, 0);

    // Cụm màn hình & công cụ nhận diện riêng từng phòng ban
    const scrList: THREE.Mesh[] = [];
    if (specId === 'software') {
      // 06. Software: Màn hình chính + Màn hình dọc code + PC Case LED xanh dương
      const mainF = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.68, 0.4, 0.032)), darkMetalMat);
      mainF.position.set(-0.18, 1.1, -0.2);
      mainF.castShadow = true;
      desk.add(mainF);
      const mainP = new THREE.Mesh(trackGeo(new THREE.PlaneGeometry(0.63, 0.35)), materials.screenSleepMat);
      mainP.position.z = 0.018;
      mainF.add(mainP);
      scrList.push(mainP);

      const vertF = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.32, 0.52, 0.032)), darkMetalMat);
      vertF.position.set(0.36, 1.14, -0.16);
      vertF.rotation.y = -0.24;
      vertF.castShadow = true;
      desk.add(vertF);
      const vertP = new THREE.Mesh(trackGeo(new THREE.PlaneGeometry(0.28, 0.47)), materials.screenSleepMat);
      vertP.position.z = 0.018;
      vertF.add(vertP);
      scrList.push(vertP);

      const pcCase = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.24, 0.46, 0.44)), darkMetalMat);
      pcCase.position.set(-0.74, 0.99, -0.1);
      pcCase.castShadow = true;
      desk.add(pcCase);
      const pcLed = new THREE.Mesh(
        trackGeo(new THREE.BoxGeometry(0.02, 0.34, 0.28)),
        trackMat(new THREE.MeshBasicMaterial({ color: 0x38bdf8 })),
      );
      pcLed.position.set(-0.615, 0.99, -0.08);
      desk.add(pcLed);
    } else {
      // Các phòng 07–11: Cụm màn hình kép Studio chữ V
      const stand = new THREE.Mesh(
        trackGeo(new THREE.CylinderGeometry(0.024, 0.036, 0.26, 8)),
        materials.brushedSteel,
      );
      stand.position.set(-0.08, 0.87, -0.24);
      desk.add(stand);

      [-0.35, 0.35].forEach((mx, mIdx) => {
        const monG = new THREE.Group();
        monG.position.set(-0.08 + mx, 1.12, -0.2);
        monG.rotation.y = mIdx === 0 ? 0.14 : -0.14;
        const frame = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.64, 0.4, 0.032)), darkMetalMat);
        frame.castShadow = true;
        monG.add(frame);
        const scr = new THREE.Mesh(trackGeo(new THREE.PlaneGeometry(0.59, 0.35)), materials.screenSleepMat);
        scr.position.z = 0.018;
        monG.add(scr);
        scrList.push(scr);
        desk.add(monG);
      });

      // Đạo cụ đặc trưng từng phòng
      if (specId === 'business') {
        // Mô hình cột tăng trưởng 3 bậc màu Teal
        [0.1, 0.17, 0.26].forEach((bh, i) => {
          const bar = new THREE.Mesh(
            trackGeo(new THREE.BoxGeometry(0.08, bh, 0.08)),
            trackMat(new THREE.MeshStandardMaterial({ color: 0x0d9488, roughness: 0.35 })),
          );
          bar.position.set(0.62 + i * 0.1, 0.76 + bh * 0.5, 0.06);
          desk.add(bar);
        });
      } else if (specId === 'marketing') {
        // Đèn Ring-Light sáng + Khối phễu Ads cam
        const ringStand = new THREE.Mesh(
          trackGeo(new THREE.CylinderGeometry(0.014, 0.02, 0.42, 8)),
          darkMetalMat,
        );
        ringStand.position.set(0.76, 0.96, -0.12);
        desk.add(ringStand);
        const ringLight = new THREE.Mesh(
          trackGeo(new THREE.TorusGeometry(0.14, 0.02, 10, 22)),
          trackMat(new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff7ed, emissiveIntensity: 1.4 })),
        );
        ringLight.position.set(0.76, 1.24, -0.12);
        ringLight.rotation.y = -0.3;
        desk.add(ringLight);
      } else if (specId === 'hr') {
        // Khay CV 3 tầng màu hồng đặc trưng
        for (let t = 0; t < 3; t++) {
          const tray = new THREE.Mesh(
            trackGeo(new THREE.BoxGeometry(0.28, 0.026, 0.34)),
            trackMat(new THREE.MeshStandardMaterial({ color: 0xe04f7b, roughness: 0.45 })),
          );
          tray.position.set(0.72, 0.78 + t * 0.075, 0.05);
          desk.add(tray);
          const cv = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.23, 0.015, 0.28)), paperMat);
          cv.position.set(0.72, 0.8 + t * 0.075, 0.05);
          desk.add(cv);
        }
      } else if (specId === 'finance') {
        // Chồng sổ cái lục bảo + máy tính tài chính
        for (let l = 0; l < 3; l++) {
          const ledger = new THREE.Mesh(
            trackGeo(new THREE.BoxGeometry(0.26, 0.04, 0.34)),
            trackMat(new THREE.MeshStandardMaterial({ color: 0x047857, roughness: 0.5 })),
          );
          ledger.position.set(0.7, 0.78 + l * 0.044, 0.04);
          ledger.rotation.y = l * 0.08;
          desk.add(ledger);
        }
      } else if (specId === 'education') {
        // Quả địa cầu đồng thau nghiên cứu học thuật
        const gBase = new THREE.Mesh(
          trackGeo(new THREE.CylinderGeometry(0.08, 0.1, 0.03, 12)),
          brassMat,
        );
        gBase.position.set(0.74, 0.775, 0.02);
        desk.add(gBase);
        const gArc = new THREE.Mesh(
          trackGeo(new THREE.TorusGeometry(0.145, 0.012, 8, 20, Math.PI)),
          brassMat,
        );
        gArc.position.set(0.74, 0.94, 0.02);
        gArc.rotation.z = -Math.PI * 0.5;
        desk.add(gArc);
        const globe = new THREE.Mesh(
          trackGeo(new THREE.SphereGeometry(0.125, 16, 12)),
          trackMat(new THREE.MeshStandardMaterial({ color: 0x3b82f6, roughness: 0.42 })),
        );
        globe.position.set(0.74, 0.94, 0.02);
        desk.add(globe);
      }
    }

    specScreenMeshes[specId] = scrList;
    bay.add(desk);
    group.add(bay);
    addStationCollider(specId, cx, 0, cz, 2.5, 2.8);
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

  // Gộp toàn bộ mesh tĩnh theo vật liệu để giữ draw calls cực thấp & mượt 60 FPS
  const allSpecScreens = Object.values(specScreenMeshes).flatMap((arr) => arr ?? []);
  geometries.push(
    ...mergeStaticMeshes(group, [
      interiorSurround,
      southGlassRailing,
      southHandrail,
      requestEnvelope,
      slidingDrawer,
      vaultWheel,
      vaultLedMesh,
      ...qdrantDiscs,
      analystHoloGroup,
      qcBadgeGroup,
      qcGateArmLeft,
      qcGateArmRight,
      ...qcGateLedMeshes,
      finalReportGroup,
      ...wbCards,
      ...stationColliders,
      ...allSpecScreens,
    ]),
  );

  return {
    group,
    stationColliders,
    setAwakeAgents: (ids) => {
      awakeSet = new Set(ids);
      for (const specId of SPECIALIST_AGENT_IDS) {
        const meshes = specScreenMeshes[specId];
        if (!meshes) continue;
        const mat = awakeSet.has(specId)
          ? specActiveScreenMats[specId]
          : materials.screenSleepMat;
        for (const m of meshes) m.material = mat;
      }
    },
    setLeadHighlight: (id) => {
      leadAgent = id;
    },
    setAtmosphereLight: (warmLampIntensity) => {
      for (const pl of interiorLights) {
        pl.intensity = 0.35 + warmLampIntensity * 3.2;
      }
      materials.lampShadeGlow.emissiveIntensity = 0.16 + warmLampIntensity * 1.15;
    },
    setExteriorReveal: (reveal, indoorBgColor) => {
      const surroundOpacity = THREE.MathUtils.clamp(1 - reveal * 1.95, 0, 1);
      interiorSurround.visible = surroundOpacity > 0.01;
      if (interiorSurround.visible) {
        interiorSurroundMat.depthWrite = surroundOpacity >= 0.99;
        interiorSurroundMat.opacity = surroundOpacity;
        interiorSurroundMat.color.copy(indoorBgColor);
      }
      southGlassRailing.visible = reveal > 0.05;
      southHandrail.visible = reveal > 0.05;
    },
    setEffects: (next) => {
      fx = next;
    },
    update: (dt, elapsed) => {
      requestEnvelope.visible = fx.requestArrived;
      if (fx.requestArrived) {
        requestEnvelope.position.y = 0.78 + Math.sin(elapsed * 3.0) * 0.06;
        requestEnvelope.rotation.y += dt * 1.1;
      }

      const targetDrawerZ = fx.cabinetOpen ? 0.44 : 0.02;
      slidingDrawer.position.z = THREE.MathUtils.damp(
        slidingDrawer.position.z,
        targetDrawerZ,
        6.5,
        dt,
      );

      // Két Vault xoay bánh lái đồng & Lõi Vector Qdrant nhấp nháy xanh ngọc khi RAG hoạt động
      if (fx.cabinetOpen) {
        vaultWheel.rotation.z += dt * 1.6;
      }
      vaultLedMat.emissiveIntensity = THREE.MathUtils.damp(
        vaultLedMat.emissiveIntensity,
        fx.cabinetOpen ? 1.65 : awakeSet.has('rag') ? 0.65 : 0.18,
        7,
        dt,
      );
      const qTarget = fx.cabinetOpen
        ? 1.55 + Math.sin(elapsed * 5.2) * 0.35
        : awakeSet.has('rag')
          ? 0.95
          : 0.35;
      qdrantDiscMat.emissiveIntensity = THREE.MathUtils.damp(
        qdrantDiscMat.emissiveIntensity,
        qTarget,
        6,
        dt,
      );
      qdrantDiscs.forEach((disc, idx) => {
        disc.position.y = 0.44 + idx * 0.27 + (fx.cabinetOpen ? Math.sin(elapsed * 4.5 + idx) * 0.022 : 0);
      });

      // Cổng Kiểm định QC: mở 2 cánh kính & bật đèn xanh lục khi đạt chuẩn; đèn hổ phách khi đang kiểm định
      const gateOpen = fx.qcApproved;
      const targetArmAngle = gateOpen ? 1.32 : 0;
      qcGateArmLeft.rotation.y = THREE.MathUtils.damp(qcGateArmLeft.rotation.y, targetArmAngle, 7, dt);
      qcGateArmRight.rotation.y = THREE.MathUtils.damp(qcGateArmRight.rotation.y, -targetArmAngle, 7, dt);
      const reviewerBusy = awakeSet.has('reviewer');
      if (gateOpen) {
        qcGateLedMat.color.setHex(0x10b981);
        qcGateLedMat.emissive.setHex(0x10b981);
      } else if (reviewerBusy) {
        qcGateLedMat.color.setHex(0xf59e0b);
        qcGateLedMat.emissive.setHex(0xf59e0b);
      } else {
        qcGateLedMat.color.setHex(0x94a3b8);
        qcGateLedMat.emissive.setHex(0x94a3b8);
      }
      qcGateLedMat.emissiveIntensity = THREE.MathUtils.damp(
        qcGateLedMat.emissiveIntensity,
        gateOpen ? 1.65 : reviewerBusy ? 1.05 : 0.18,
        7,
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
          const h = 0.38 + 0.72 * (Math.sin(elapsed * 4.5 + i * 1.2) * 0.5 + 0.5);
          bar.scale.y = THREE.MathUtils.damp(bar.scale.y, h, 8, dt);
          bar.position.y = bar.scale.y * 0.26;
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
        const target = isLead ? 1.7 : awake ? 0.92 : 0.12;
        mat.emissiveIntensity = THREE.MathUtils.damp(mat.emissiveIntensity, target, 6, dt);
      }
    },
    dispose: () => {
      geometries.forEach((g) => g.dispose());
      extraMats.forEach((m) => m.dispose());
    },
  };
}
