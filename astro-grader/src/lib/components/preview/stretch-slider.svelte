<script lang="ts">
  import { PreserveRatio, type SMH } from './preserve-ratio.svelte';

  type Props = {
    linked: boolean;
    channels: {
      id: string;
      value: SMH;
      color: string;
      ratios: PreserveRatio;
    }[];
    onChange?: (channels: SMH[]) => void;
  };

  let { linked = $bindable(), channels, onChange }: Props = $props();

  let updating = $state([false, false, false]);

  const handleSliderChange = (channelIdx: number, v: number[] | undefined) => {
    console.log('change', channelIdx, v);
    if (!v || v.length !== 3) return;

    // 1. Prevent infinite loops from Bits UI internal value syncing
    if (updating[channelIdx]) {
      updating[channelIdx] = false;
      return;
    }

    const ratios = channels[channelIdx].ratios;
    const current = ratios.getState();
    const next = [...v] as SMH;

    // Clamping + little offset, so the thumbs cannot move into eachother
    next[0] = Math.min(next[0], v[1] + 0.01);
    next[1] = Math.max(Math.min(next[1], v[2] + 0.01), v[0] - 0.01);
    next[2] = Math.max(next[2], v[1] - 0.01);

    const [s0, m0, h0] = current;
    const [s1, m1, h1] = next;

    // 3. Explicitly detect which thumb moved
    const sMoved = s1 !== s0;
    const mMoved = m1 !== m0;
    const hMoved = h1 !== h0;

    updating[channelIdx] = true;
    let newState: SMH;

    let diff: number;
    // 4. Update the specific value based on the movement
    if (sMoved) {
      diff = s1 - s0;
      newState = ratios.updateShadows(s1);
    } else if (mMoved) {
      diff = m1 - m0;
      newState = ratios.updateMidtone(m1);
    } else if (hMoved) {
      diff = h1 - h0;
      newState = ratios.updateHighlights(h1);
    } else {
      updating[channelIdx] = false; // Nothing moved
      return;
    }

    channels[channelIdx].value = newState;

    if (!linked) {
      if (onChange) onChange(channels.map((c) => c.value));
      return;
    }

    // 1. Calculate the master's active range (width) BEFORE the move
    // Fallback to 1 to prevent division by zero if thumbs are perfectly squished
    const masterRange = h0 - s0 || 1;

    // 2. Calculate the "weight" of the movement across the total available space
    const shiftPct = diff / masterRange;

    for (let i = 0; i < channels.length; ++i) {
      if (i === channelIdx) continue;

      const channel = channels[i];
      const targetCurrent = channel.ratios.getState();
      const [tS0, tM0, tH0] = targetCurrent;

      // 3. Find the target's available space
      const targetRange = tH0 - tS0 || 1;

      // 4. Translate the percentage back into physical distance for this specific channel
      const targetDiff = shiftPct * targetRange;

      updating[i] = true;
      let res: SMH;

      if (sMoved) {
        // Apply the diff and strictly clamp so it doesn't cross the midtone
        const newS = Math.max(0, Math.min(tM0 - 0.01, tS0 + targetDiff));
        res = channel.ratios.updateShadows(newS);
      } else if (mMoved) {
        // Clamp between shadows and highlights
        const newM = Math.max(tS0 + 0.01, Math.min(tH0 - 0.01, tM0 + targetDiff));
        res = channel.ratios.updateMidtone(newM);
      } else if (hMoved) {
        // Clamp between midtones and 1.0
        const newH = Math.max(tM0 + 0.01, Math.min(1, tH0 + targetDiff));
        res = channel.ratios.updateHighlights(newH);
      } else {
        updating[i] = false;
        continue;
      }

      channels[i].value = res;
    }

    if (onChange) onChange(channels.map((c) => c.value));
  };
</script>

<div class="flex flex-col gap-4 p-4">
  <div class="flex flex-col gap-3">
    {#each channels as channel, idx (channel.id)}
      {@const values = channel.ratios.getState()}

      <div class="relative flex h-6 w-full items-center select-none">
        <div
          class="absolute inset-0 overflow-hidden rounded-sm"
          style="background: linear-gradient(to right, black, {channel.color});"
        ></div>

        {#each values as val, valIdx (valIdx)}
          <input
            type="range"
            min="0"
            max="1"
            step="any"
            value={val}
            oninput={(e) => {
              // Reconstruct the array to pass back to your handler (mimicking bits-ui behavior)
              const newValues = [...values];
              newValues[valIdx] = parseFloat(e.currentTarget.value);
              handleSliderChange(idx, newValues);
            }}
            class="
              /* CRITICAL: Make the track ignore the
              
              mouse, but let the thumb capture it */ /* Webkit Thumb Styles (Matches your original
              design)
              */
              /*

              Firefox Thumb Styles */ pointer-events-none absolute inset-0 m-0 h-full
              w-full
              appearance-none
              bg-transparent
              focus:outline-none
              [&::-moz-range-thumb]:pointer-events-auto
              [&::-moz-range-thumb]:h-8
              [&::-moz-range-thumb]:w-1.5
              [&::-moz-range-thumb]:cursor-ew-resize
              [&::-moz-range-thumb]:appearance-none
              [&::-moz-range-thumb]:rounded-sm

              [&::-moz-range-thumb]:border [&::-moz-range-thumb]:border-gray-400 [&::-moz-range-thumb]:bg-white hover:[&::-moz-range-thumb]:bg-gray-200 [&::-webkit-slider-thumb]:pointer-events-auto
              [&::-webkit-slider-thumb]:h-8
              [&::-webkit-slider-thumb]:w-1.5
              [&::-webkit-slider-thumb]:cursor-ew-resize
              [&::-webkit-slider-thumb]:appearance-none
              [&::-webkit-slider-thumb]:rounded-sm
              [&::-webkit-slider-thumb]:border
              [&::-webkit-slider-thumb]:border-gray-400
              [&::-webkit-slider-thumb]:bg-white
              hover:[&::-webkit-slider-thumb]:bg-gray-200
            "
          />
        {/each}
      </div>
    {/each}
  </div>
</div>
