import type { File } from '../../types/File';
import type { ImageData } from '../../types/ImageData';
import type { SMH } from './preserve-ratio.svelte';

export class Vec3 {
  public data = $state<[number, number, number]>([0, 0, 0]);

  static init(value: number) {
    const vec = new Vec3();
    vec.data = [value, value, value];
    return vec;
  }
}

class PreviewState {
  public previewImage = $state<File>();
  public previewData = $state<ImageData>();
  public R = $state<SMH>([0.0, 0.5, 1.0]);
  public G = $state<SMH>([0.0, 0.5, 1.0]);
  public B = $state<SMH>([0.0, 0.5, 1.0]);
}

export const previewState = new PreviewState();
