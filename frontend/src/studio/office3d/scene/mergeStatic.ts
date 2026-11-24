import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

/**
 * Gộp các khối đứng yên dùng chung vật liệu thành một khối để giảm số lệnh vẽ (Đợt 2, 23/11).
 * `keep`: các vật có chuyển động, đổi vật liệu hoặc ẩn/hiện; chúng và mọi vật con được giữ nguyên.
 * Chỉ gộp khối ở lớp mặc định (lớp 1 là vùng bấm chọn) và không phải InstancedMesh/SkinnedMesh.
 * Trả về các hình khối mới để nơi gọi giải phóng khi đóng trang.
 */
export function mergeStaticMeshes(root: THREE.Object3D, keep: THREE.Object3D[]): THREE.BufferGeometry[] {
  const keepSet = new Set(keep);
  const isKept = (o: THREE.Object3D | null): boolean => {
    for (let p = o; p && p !== root; p = p.parent) if (keepSet.has(p)) return true;
    return false;
  };
  const visibleChain = (o: THREE.Object3D): boolean => {
    for (let p: THREE.Object3D | null = o; p && p !== root; p = p.parent) if (!p.visible) return false;
    return true;
  };

  root.updateMatrixWorld(true);
  const rootInverse = new THREE.Matrix4().copy(root.matrixWorld).invert();
  const buckets = new Map<string, { material: THREE.Material; meshes: THREE.Mesh[] }>();

  root.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh || (mesh as THREE.InstancedMesh).isInstancedMesh || (mesh as THREE.SkinnedMesh).isSkinnedMesh) return;
    if (Array.isArray(mesh.material) || mesh.layers.mask !== 1 || isKept(mesh) || !visibleChain(mesh)) return;
    if (mesh.morphTargetInfluences?.length || mesh.children.length) return; // khối làm cha của vật khác: giữ
    const g = mesh.geometry;
    const attrs = Object.keys(g.attributes).sort().join(',');
    const key = [mesh.material.uuid, +mesh.castShadow, +mesh.receiveShadow, mesh.renderOrder, attrs, g.index ? 'i' : 'n'].join('|');
    const b = buckets.get(key) ?? { material: mesh.material, meshes: [] };
    b.meshes.push(mesh);
    buckets.set(key, b);
  });

  const created: THREE.BufferGeometry[] = [];
  const m = new THREE.Matrix4();
  for (const { material, meshes } of buckets.values()) {
    if (meshes.length < 2) continue;
    const parts = meshes.map((mesh) => {
      const g = mesh.geometry.clone();
      g.applyMatrix4(m.multiplyMatrices(rootInverse, mesh.matrixWorld));
      return g;
    });
    const merged = mergeGeometries(parts, false);
    parts.forEach((g) => g.dispose());
    if (!merged) continue; // thuộc tính không khớp: để nguyên các khối cũ
    const out = new THREE.Mesh(merged, material);
    out.castShadow = meshes[0].castShadow;
    out.receiveShadow = meshes[0].receiveShadow;
    out.renderOrder = meshes[0].renderOrder;
    out.matrixAutoUpdate = false;
    root.add(out);
    meshes.forEach((mesh) => mesh.removeFromParent());
    created.push(merged);
  }
  return created;
}
