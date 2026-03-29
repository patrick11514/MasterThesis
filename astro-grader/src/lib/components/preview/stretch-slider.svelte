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

    // 2. Reintroduce clamping! Thumbs cannot cross each other.
    next[0] = Math.min(next[0], v[1]);
    next[1] = Math.max(Math.min(next[1], v[2]), v[0]);
    next[2] = Math.max(next[2], v[1]);

    const [s0, m0, h0] = current;
    const [s1, m1, h1] = next;

    // 3. Explicitly detect which thumb moved
    const sMoved = s1 !== s0;
    const mMoved = m1 !== m0;
    const hMoved = h1 !== h0;

    updating[channelIdx] = true;
    let newState: SMH;

    // 4. Update the specific value based on the movement
    if (sMoved) {
      newState = ratios.updateShadows(s1);
    } else if (mMoved) {
      newState = ratios.updateMidtone(m1);
    } else if (hMoved) {
      newState = ratios.updateHighlights(h1);
    } else {
      updating[channelIdx] = false; // Nothing moved
      return;
    }

    // 5. Sync the new state back to the parent $bindable props
    if (channelIdx === 0) R = newState;
    if (channelIdx === 1) G = newState;
    if (channelIdx === 2) B = newState;

    // Note: If `linked` is true, this is where you would also iterate
    // over the other channels and apply `newState` to them!
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
