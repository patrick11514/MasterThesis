import type { File } from '../../types/File';
import type { ImageData } from '../../types/ImageData';
import type { SMH } from './preserve-ratio.svelte';

class PreviewState {
  public previewImage = $state<File>();
  public previewData = $state<ImageData>();
  public R = $state<SMH>([0.0, 0.5, 1.0]);
  public G = $state<SMH>([0.0, 0.5, 1.0]);
  public B = $state<SMH>([0.0, 0.5, 1.0]);

  get channels() {
    const R = this.R;
    const G = this.G;
    const B = this.B;

    if (this.previewData?.layout === 'Grayscale') {
      return [
        {
          id: 'Gray',
          color: '#ffffff',
          get value() {
            return R;
          },
          set value(v) {
            previewState.R = v;
            previewState.G = v;
            previewState.B = v;
          }
        }
      ];
    }
    return [
      {
        id: 'Red',
        color: '#ff0000',
        get value() {
          return R;
        },
        set value(v) {
          previewState.R = v;
        }
      },
      {
        id: 'Green',
        color: '#00ff00',
        get value() {
          return G;
        },
        set value(v) {
          previewState.G = v;
        }
      },
      {
        id: 'Blue',
        color: '#0000ff',
        get value() {
          return B;
        },
        set value(v) {
          previewState.B = v;
        }
      }
    ];
  }
}

export const previewState = new PreviewState();
