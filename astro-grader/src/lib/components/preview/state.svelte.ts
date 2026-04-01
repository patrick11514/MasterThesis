import type { ImageOptions } from '$/lib/types/ImageOptions';
import type { File } from '../../types/File';
import type { ImageData } from '../../types/ImageData';
import type { SMH } from './preserve-ratio.svelte';

type ImageState = 'loading' | 'downloading' | undefined;

class PreviewState {
  public imageState = $state<ImageState>();

  public previewImage = $state<File>();
  public previewData = $state<ImageData>();
  public imageOptions = $state<ImageOptions>();

  public R = $state<SMH>([0.0, 0.5, 1.0]);
  public G = $state<SMH>([0.0, 0.5, 1.0]);
  public B = $state<SMH>([0.0, 0.5, 1.0]);
}

export const previewState = new PreviewState();
