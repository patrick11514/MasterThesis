// stretch.worker.ts

// The formula for MTF stretch
const mtf = (x: number, m: number) => {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  if (m === 0.5) return x;
  return ((m - 1) * x) / ((2 * m - 1) * x - m);
};

self.onmessage = (e: MessageEvent) => {
  const { data, width, height, rMin, rMax, gMin, gMax, bMin, bMax, stretchLevel } = e.data as {
    data: Float32Array;
    width: number;
    height: number;
    rMin: number;
    rMax: number;
    gMin: number;
    gMax: number;
    bMin: number;
    bMax: number;
    stretchLevel: number;
  };

  const numPixels = width * height;
  const rRange = rMax - rMin || 1;
  const gRange = gMax - gMin || 1;
  const bRange = bMax - bMin || 1;

  const clamped = new Uint8ClampedArray(numPixels * 4);

  for (let i = 0; i < numPixels; i++) {
    let r = (data[i * 3] - rMin) / rRange;
    let g = (data[i * 3 + 1] - gMin) / gRange;
    let b = (data[i * 3 + 2] - bMin) / bRange;

    r = mtf(r, stretchLevel);
    g = mtf(g, stretchLevel);
    b = mtf(b, stretchLevel);

    clamped[i * 4] = Math.max(0, Math.min(255, r * 255));
    clamped[i * 4 + 1] = Math.max(0, Math.min(255, g * 255));
    clamped[i * 4 + 2] = Math.max(0, Math.min(255, b * 255));
    clamped[i * 4 + 3] = 255;
  }

  // Transfer the buffer back to the main thread
  self.postMessage(clamped, { transfer: [clamped.buffer] });
};
