<script lang="ts">
  import type { ImageData } from '$/lib/types/ImageData';
  import { getData } from '$/lib/utils';
  import { invoke } from '@tauri-apps/api/core';
  import { toast } from 'svelte-sonner';
  import type { File } from '../../types/File';
  import * as Resizable from '../ui/resizable';
  import { previewState } from './state.svelte';

  let canvasElement = $state<HTMLCanvasElement | null>(null);
  let rawData = $state<{
    width: number;
    height: number;
    data: Uint8Array;
  } | null>(null);

  const loadImage = async (image: File) => {
    try {
      let start = Date.now();

      const previewData = await invoke<ImageData>('fits_read_image', {
        path: image.path
      });

      previewState.previewData = previewData;

      console.log('Time to read image:', Date.now() - start, 'ms');
      console.log('Downloading image...');
      start = Date.now();
      const data = await getData<ArrayBuffer>('astro-grader://preview');

      if (!data) {
        toast.error('Failed to load preview data');
        return;
      }

      rawData = {
        width: previewData.width,
        height: previewData.height,
        data: new Uint8Array(data)
      };
    } catch (_err) {
      const err = _err as string;

      toast.error(image.name, {
        description: err
      });
    }
  };

  $effect(() => {
    if (previewState.previewImage) {
      loadImage(previewState.previewImage);
    }
  });
</script>

<Resizable.Pane defaultSize={80}>
  <canvas bind:this={canvasElement} class="mt-4 h-auto w-full border shadow-sm"></canvas>
</Resizable.Pane>
