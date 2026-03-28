import type { File } from '../../types/File';
import type { ImageData } from '../../types/ImageData';

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
  public shadows = $state<Vec3>(Vec3.init(0.0));
  public midtones = $state<Vec3>(Vec3.init(0.5));
  public highlights = $state<Vec3>(Vec3.init(1.0));
}

export const previewState = new PreviewState();
