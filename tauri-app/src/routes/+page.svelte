<script lang="ts">
  import { Button } from '$/lib/components/ui/button';
  import { resolve } from '$app/paths';
  import { invoke } from '@tauri-apps/api/core';
  import { open } from '@tauri-apps/plugin-dialog';

  let image = $state<string | null>(null);
  let canvasElement: HTMLCanvasElement;

  let rawData = $state<{ width: number; height: number; data: Float32Array } | null>(null);
  let linked = $state(true);
  let stretchLevel = $state(0.15); // MTF stretch factor (0.0 to 1.0)

  // Timings
  let timeJS = $state<number | null>(null);
  let timeWorkers = $state<number | null>(null);
  let timeTauri = $state<number | null>(null);

  type StretcherType = 'js' | 'workers' | 'tauri';
  let selectedStretcher = $state<StretcherType>('js');

  const convert = async () => {
    const file = await open({
      multiple: false,
      directory: false,
      filters: [
        {
          name: 'FITS',
          extensions: ['fits']
        }
      ]
    });

    if (!file) return;

    const data = await invoke<ArrayBuffer>('test3', {
      src: file
    });

    const dataView = new DataView(data);
    const width = dataView.getUint32(0, true);
    const height = dataView.getUint32(4, true);

    const numPixels = width * height;
    const f32 = new Float32Array(data, 8, numPixels * 3);

    rawData = { width, height, data: f32 };

    // Clear timings on new load
    timeJS = null;
    timeWorkers = null;
    timeTauri = null;
  };

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

    if (linked) {
      const overallMin = Math.min(rMin, gMin, bMin);
      const overallMax = Math.max(rMax, gMax, bMax);
      rMin = overallMin;
      rMax = overallMax;
      gMin = overallMin;
      gMax = overallMax;
      bMin = overallMin;
      bMax = overallMax;
    }
    return { rMin, rMax, gMin, gMax, bMin, bMax };
  };

  const stretchJS = () => {
    if (!rawData || !canvasElement) return;
    const start = performance.now();
    const { width, height, data } = rawData;
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

      r = mtf(r, stretchLevel);
      g = mtf(g, stretchLevel);
      b = mtf(b, stretchLevel);

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

    timeJS = performance.now() - start;
  };

  const stretchWorkers = async () => {
    if (!rawData || !canvasElement) return;
    const start = performance.now();
    const { width, height, data } = rawData;
    const numPixels = width * height;

    // We compute min/max on main thread first to avoid complex messaging.
    // For huge images, doing it in worker is better, but this simplifies it.
    const { rMin, rMax, gMin, gMax, bMin, bMax } = getMinMax(data, numPixels);

    const numCores = navigator.hardwareConcurrency || 4;
    const rowsPerWorker = Math.ceil(height / numCores);

    const promises: Promise<{ offset: number; chunk: Uint8ClampedArray }>[] = [];

    for (let i = 0; i < numCores; i++) {
      const startRow = i * rowsPerWorker;
      const endRow = Math.min(startRow + rowsPerWorker, height);

      if (startRow >= height) break;

      const chunkHeight = endRow - startRow;
      const startPixel = startRow * width;
      const pixelCount = chunkHeight * width;

      // Slice the float32array for this chunk
      const chunkData = data.slice(startPixel * 3, (startPixel + pixelCount) * 3);

      promises.push(
        new Promise((resolve) => {
          const worker = new Worker(new URL('$/lib/workers/stretch.worker.ts', import.meta.url), {
            type: 'module'
          });
          worker.onmessage = (e) => {
            resolve({ offset: startPixel * 4, chunk: e.data });
            worker.terminate();
          };
          worker.postMessage(
            {
              data: chunkData,
              width,
              height: chunkHeight,
              rMin,
              rMax,
              gMin,
              gMax,
              bMin,
              bMax,
              stretchLevel
            },
            [chunkData.buffer]
          );
        })
      );
    }

    const results = await Promise.all(promises);
    const finalClamped = new Uint8ClampedArray(numPixels * 4);

    for (const { offset, chunk } of results) {
      finalClamped.set(chunk, offset);
    }

    const imageData = new ImageData(finalClamped, width, height);
    canvasElement.width = width;
    canvasElement.height = height;
    const ctx = canvasElement.getContext('2d');
    ctx!.putImageData(imageData, 0, 0);

    timeWorkers = performance.now() - start;
  };

  const stretchTauri = async () => {
    if (!rawData || !canvasElement) return;
    const start = performance.now();
    const { width, height, data } = rawData;

    // Convert Float32Array to Uint8Array for zero-copy-like argument passing
    const u8Data = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);

    const rgbaBuffer = await invoke<ArrayBuffer>('test4_stretch', {
      data: Array.from(u8Data), // Need to send as JS Array of numbers, or handle via proper ArrayBuffer payload
      width,
      height,
      linked,
      stretchLevel
    });

    const clamped = new Uint8ClampedArray(rgbaBuffer);
    const imageData = new ImageData(clamped, width, height);

    canvasElement.width = width;
    canvasElement.height = height;
    const ctx = canvasElement.getContext('2d');
    ctx!.putImageData(imageData, 0, 0);

    timeTauri = performance.now() - start;
  };
  let debounceTimer: ReturnType<typeof setTimeout>;
  $effect(() => {
    let _l = linked;
    let _s = stretchLevel;
    let _st = selectedStretcher;
    if (rawData) {
      if (_st === 'js') stretchJS();
      else if (_st === 'workers') stretchWorkers();
      else if (_st === 'tauri') stretchTauri();
    }
  });
</script>

<main class="flex h-full w-full flex-col items-center justify-center gap-4 p-8">
  <a href={resolve('/test')}>test</a>

  <h1 class="text-4xl font-bold">Image Stretching Performance</h1>

  <div class="flex gap-4">
    <Button onclick={convert}>Load & Convert FITS</Button>
  </div>

  {#if rawData}
    <div class="mt-4 flex flex-col items-center gap-2 rounded bg-gray-100 p-4 dark:bg-zinc-800">
      <label class="flex cursor-pointer items-center gap-2 font-semibold">
        <input type="checkbox" bind:checked={linked} class="h-4 w-4" />
        Linked Stretch
      </label>

      <label class="flex items-center gap-2 font-semibold">
        Stretch (MTF): {stretchLevel.toFixed(3)}
        <input
          type="range"
          class="w-64"
          min="0.001"
          max="0.5"
          step="0.001"
          bind:value={stretchLevel}
        />
      </label>

      <div class="mt-4 flex w-full justify-center gap-6">
        <label class="flex cursor-pointer items-center gap-2">
          <input
            type="radio"
            name="stretcher"
            value="js"
            bind:group={selectedStretcher}
            class="h-4 w-4"
          />
          Single-thread JS
        </label>
        <label class="flex cursor-pointer items-center gap-2">
          <input
            type="radio"
            name="stretcher"
            value="workers"
            bind:group={selectedStretcher}
            class="h-4 w-4"
          />
          Web Workers
        </label>
        <label class="flex cursor-pointer items-center gap-2">
          <input
            type="radio"
            name="stretcher"
            value="tauri"
            bind:group={selectedStretcher}
            class="h-4 w-4"
          />
          Tauri (Rayon)
        </label>
      </div>

      <div class="mt-2 grid grid-cols-3 gap-8 text-center text-sm">
        <div>
          <p class="font-bold">Single-thread JS</p>
          <p>{timeJS !== null ? `${timeJS.toFixed(1)} ms` : '-'}</p>
        </div>
        <div>
          <p class="font-bold">Web Workers</p>
          <p>{timeWorkers !== null ? `${timeWorkers.toFixed(1)} ms` : '-'}</p>
        </div>
        <div>
          <p class="font-bold">Tauri (Rayon)</p>
          <p>{timeTauri !== null ? `${timeTauri.toFixed(1)} ms` : '-'}</p>
        </div>
      </div>
    </div>
  {/if}

  {#if image}
    <img src={image} alt="Converted image" />
  {/if}

  <canvas bind:this={canvasElement} class="mt-4 h-auto max-w-full border shadow-sm"></canvas>
</main>
