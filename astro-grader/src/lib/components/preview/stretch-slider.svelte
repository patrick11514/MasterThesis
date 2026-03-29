<script lang="ts">
  import { Slider as SliderPrimitive } from 'bits-ui';
  import { untrack } from 'svelte';
  import { PreserveRatio, type SMH } from './preserve-ratio.svelte';

  type Props = {
    linked: boolean;
    R: SMH;
    G: SMH;
    B: SMH;
  };

  let { linked = $bindable(), R = $bindable(), G = $bindable(), B = $bindable() }: Props = $props();

  type STFChannel = {
    id: string;
    color: string;
    ratios: PreserveRatio;
  };

  //We take first snapshot of state, because we don't want to automatically update
  let channels: STFChannel[] = $state([
    {
      id: 'Red',
      color: '#ff0000',
      ratios: new PreserveRatio(R)
    },
    {
      id: 'Green',
      color: '#00ff00',
      ratios: new PreserveRatio(G)
    },
    {
      id: 'Blue',
      color: '#0000ff',
      ratios: new PreserveRatio(B)
    }
  ]);

  // Simple helper to check if two SMH tuples match
  const isSame = (a: SMH, b: SMH) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];

  // Effect to sync external prop changes into our local channel state
  $effect(() => {
    const newR = R;
    const newG = G;
    const newB = B;

    untrack(() => {
      const localR = channels[0].ratios.getState();
      const localG = channels[1].ratios.getState();
      const localB = channels[2].ratios.getState();

      const rChanged = !isSame(newR, localR);
      const gChanged = !isSame(newG, localG);
      const bChanged = !isSame(newB, localB);

      if (!rChanged && !gChanged && !bChanged) return;

      console.log('Updating from outside', { newR, newG, newB });

      // 4. Only update the specific channels that received new outside data
      if (rChanged) channels[0].ratios.setState(newR);
      if (gChanged) channels[1].ratios.setState(newG);
      if (bChanged) channels[2].ratios.setState(newB);
    });
  });

  let updating = $state([false, false, false]);

  const handleSliderChange = (channelIdx: number, v: number[] | undefined) => {
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

    if (channelIdx === 0) R = newState;
    if (channelIdx === 1) G = newState;
    if (channelIdx === 2) B = newState;

    if (!linked) return;

    // 1. Calculate the master's active range (width) BEFORE the move
    // Fallback to 1 to prevent division by zero if thumbs are perfectly squished
    const masterRange = h0 - s0 || 1;

    // 2. Calculate the "weight" of the movement across the total available space
    const shiftPct = diff / masterRange;

    for (let i = 0; i < 3; ++i) {
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

      if (i === 0) R = res;
      if (i === 1) G = res;
      if (i === 2) B = res;
    }
  };
</script>

<div class="flex flex-col gap-4 p-4">
  <div class="flex flex-col gap-3">
    {#each channels as channel, idx (channel.id)}
      <SliderPrimitive.Root
        value={channels[idx].ratios.getState()}
        type="multiple"
        onValueChange={(v) => handleSliderChange(idx, v)}
        min={0}
        max={1}
        step={0.01}
        autoSort={false}
        class="relative flex h-6 w-full touch-none items-center select-none"
      >
        {#snippet children({ thumbItems })}
          <span
            class="relative h-full w-full grow overflow-hidden rounded-sm"
            style="background: linear-gradient(to right, black, {channel.color});"
          ></span>
          {#each thumbItems as thumb (thumb.index)}
            <SliderPrimitive.Thumb
              index={thumb.index}
              class="absolute -ml-0.75 block h-8 w-1.5 cursor-ew-resize rounded-sm border border-gray-400 bg-white hover:bg-gray-200 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50"
            />
          {/each}
        {/snippet}
      </SliderPrimitive.Root>
    {/each}
  </div>
</div>
