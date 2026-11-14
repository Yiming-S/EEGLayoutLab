import * as THREE from 'three';
import { mriMmToDisplay } from '../lib/fixed64-results.ts';
import {
  sourceRegion,
  UNASSIGNED_SOURCE_COLOR,
} from '../lib/source-regions.ts';
import { releaseGroup } from './resources.ts';
import type { LayoutOptions } from './types.ts';

export function createSourceLayer(scene: THREE.Scene) {
  const group = new THREE.Group();
  scene.add(group);
  return {
    group,
    setLayout(options: LayoutOptions) {
      releaseGroup(group);
      for (const [i, xyz] of (options.sourceXyzMm ?? []).entries()) {
        const color =
          sourceRegion(options.sourceRegions?.[i])?.color ??
          UNASSIGNED_SOURCE_COLOR;
        const markerGroup = new THREE.Group();
        group.add(markerGroup);
        markerGroup.position.set(...mriMmToDisplay(xyz));
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(0.025, 12, 10),
          new THREE.MeshBasicMaterial({
            color,
            depthTest: false,
            depthWrite: false,
            transparent: true,
            opacity: 1,
          }),
        );
        marker.renderOrder = 10;
        markerGroup.userData = { sourceIndex: i, marker };
        markerGroup.add(marker);
        const labelCanvas = document.createElement('canvas');
        labelCanvas.width = 128;
        labelCanvas.height = 64;
        const ctx = labelCanvas.getContext('2d');
        if (ctx) {
          ctx.fillStyle = '#ffffff';
          ctx.fillRect(0, 0, 128, 64);
          ctx.strokeStyle = color;
          ctx.lineWidth = 8;
          ctx.strokeRect(4, 4, 120, 56);
          ctx.fillStyle = '#182c3a';
          ctx.font = 'bold 38px sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(`S${i + 1}`, 64, 34);
          const texture = new THREE.CanvasTexture(labelCanvas);
          texture.colorSpace = THREE.SRGBColorSpace;
          const label = new THREE.Sprite(
            new THREE.SpriteMaterial({
              map: texture,
              depthTest: false,
              depthWrite: false,
              toneMapped: false,
            }),
          );
          label.position.set(0.055, 0, 0.06);
          label.scale.set(0.14, 0.07, 1);
          label.renderOrder = 12;
          markerGroup.add(label);
        }
        const normal = options.sourceNormals?.[i];
        if (normal) {
          const direction = new THREE.Vector3(...normal).normalize();
          const arrow = new THREE.ArrowHelper(
            direction,
            new THREE.Vector3(),
            0.12,
            color,
            0.035,
            0.018,
          );
          markerGroup.add(arrow);
        }
      }
    },
    select(index: number | undefined) {
      for (const object of group.children)
        if (Number.isInteger(object.userData.sourceIndex))
          object.userData.marker.scale.setScalar(
            object.userData.sourceIndex === index ? 1.6 : 1,
          );
    },
  };
}
