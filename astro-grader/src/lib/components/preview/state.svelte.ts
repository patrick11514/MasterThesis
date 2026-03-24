import type { File } from '../../types/File';
import type { ImageData } from '../../types/ImageData';

class PreviewState {
  public previewImage = $state<File>();
  public previewData = $state<ImageData>();
  public stretchLevel = $state(0.5);
}

export const previewState = new PreviewState();
