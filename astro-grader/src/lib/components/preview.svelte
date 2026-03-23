<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { getAppState } from '../state.svelte';
  import * as Resizable from './ui/resizable';

  const appState = await getAppState();

  let canvasElement = $state<HTMLCanvasElement | null>(null);
  let rawData = $state<{ width: number; height: number; data: Float32Array } | null>(null);

  const loadImage = async (path: string) => {
    const data = await invoke<ArrayBuffer>('fits_read_image', {
      path
    });

    const dataView = new DataView(data);
    const width = dataView.getUint32(0, true);
    const height = dataView.getUint32(4, true);

    const numPixels = width * height;
    const f32 = new Float32Array(data, 8, numPixels * 3);

    rawData = { width, height, data: f32 };
  };

  $effect(() => {
    if (appState.previewImage) {
      loadImage(appState.previewImage);
    }
  });

  $effect(() => {
    if (!canvasElement || !rawData) return;

    const ctx = canvasElement.getContext('2d');
    if (!ctx) return;

    const { width, height, data } = rawData;
    canvasElement.width = width;
    canvasElement.height = height;

    const imageData = ctx.createImageData(width, height);
    for (let i = 0; i < width * height; i++) {
      imageData.data[i * 4] = Math.min(255, Math.max(0, data[i])); // R
      imageData.data[i * 4 + 1] = Math.min(255, Math.max(0, data[i + width * height])); // G
      imageData.data[i * 4 + 2] = Math.min(255, Math.max(0, data[i + 2 * width * height])); // B
      imageData.data[i * 4 + 3] = 255; // A
    }

    ctx.putImageData(imageData, 0, 0);
  });
</script>

<Resizable.Pane defaultSize={80}>
  <canvas bind:this={canvasElement} class="mt-4 h-auto max-w-full border shadow-sm"></canvas>
</Resizable.Pane>
