<script lang="ts">
  import type { ImageData } from '$/lib/types/ImageData';
  import { Channel, invoke } from '@tauri-apps/api/core';
  import { toast } from 'svelte-sonner';
  import type { File } from '../../types/File';
  import * as Resizable from '../ui/resizable';
  import { previewState } from './state.svelte';

  let canvasElement = $state<HTMLCanvasElement | null>(null);
  let rawData = $state<{ width: number; height: number; data: Float32Array } | null>(null);

  const loadImage = async (image: File) => {
    try {
      const channel = new Channel<ImageData>();
      channel.onmessage = (message) => {
        previewState.previewData = message;
      };

      const start = Date.now();

      const data = await invoke<ArrayBuffer>('fits_read_image', {
        path: image.path,
        reader: channel
      });

      console.log('Time to read image:', Date.now() - start, 'ms');

      const dataView = new DataView(data);
      const width = dataView.getUint32(0, true);
      const height = dataView.getUint32(4, true);

      const numPixels = width * height;
      const f32 = new Float32Array(data, 8, numPixels * 3);

      rawData = { width, height, data: f32 };
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

  $effect(() => {
    if (!canvasElement || !rawData || !previewState.stretchLevel) return;

    const ctx = canvasElement.getContext('2d');
    if (!ctx) return;

    stretchJS();
  });

  const getMinMax = (data: Float32Array, numPixels: number) => {
    let rMin = Infinity,
      rMax = -Infinity;
    let gMin = Infinity,
      gMax = -Infinity;
    let bMin = Infinity,
      bMax = -Infinity;

    for (let i = 0; i < numPixels; i++) {
      const r = data[i * 3];
      const g = data[i * 3 + 1];
      const b = data[i * 3 + 2];
      if (r < rMin) rMin = r;
      if (r > rMax) rMax = r;
      if (g < gMin) gMin = g;
      if (g > gMax) gMax = g;
      if (b < bMin) bMin = b;
      if (b > bMax) bMax = b;
    }

    return { rMin, rMax, gMin, gMax, bMin, bMax };
  };

  const stretchJS = () => {
    if (!rawData || !canvasElement) return;
    const { width, height, data } = rawData;

    console.log('Stretching image with JS', {
      width,
      height,
      stretchLevel: previewState.stretchLevel
    });

    const numPixels = width * height;

    const { rMin, rMax, gMin, gMax, bMin, bMax } = getMinMax(data, numPixels);

    const rRange = rMax - rMin || 1;
    const gRange = gMax - gMin || 1;
    const bRange = bMax - bMin || 1;

    const clamped = new Uint8ClampedArray(numPixels * 4);

    const mtf = (x: number, m: number) => {
      if (x <= 0) return 0;
      if (x >= 1) return 1;
      if (m === 0.5) return x;
      return ((m - 1) * x) / ((2 * m - 1) * x - m);
    };

    for (let i = 0; i < numPixels; i++) {
      let r = (data[i * 3] - rMin) / rRange;
      let g = (data[i * 3 + 1] - gMin) / gRange;
      let b = (data[i * 3 + 2] - bMin) / bRange;

      r = mtf(r, previewState.stretchLevel);
      g = mtf(g, previewState.stretchLevel);
      b = mtf(b, previewState.stretchLevel);

      clamped[i * 4] = r * 255;
      clamped[i * 4 + 1] = g * 255;
      clamped[i * 4 + 2] = b * 255;
      clamped[i * 4 + 3] = 255;
    }

    const imageData = new ImageData(clamped, width, height);
    canvasElement.width = width;
    canvasElement.height = height;
    const ctx = canvasElement.getContext('2d');
    ctx!.putImageData(imageData, 0, 0);
  };
</script>

<Resizable.Pane defaultSize={80}>
  <canvas bind:this={canvasElement} class="mt-4 h-auto w-full border shadow-sm"></canvas>
</Resizable.Pane>
