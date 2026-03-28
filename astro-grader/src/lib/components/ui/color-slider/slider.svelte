<script lang="ts">
  import { cn } from '$/lib/utils.js';
  import { Slider as SliderPrimitive } from 'bits-ui';
  import { PreserveRatio } from './preserve-ratio';

  type Props = {
    value?: [number, number, number];
    color?: string;
    class?: string;
  };
  let { value = $bindable([0.0, 0.5, 1.0]), color = '#ffffff', class: className }: Props = $props();

  let wasUpdated = $state(false);
  const ratio = new PreserveRatio(value);
</script>

<SliderPrimitive.Root
  value={value as never}
  type="multiple"
  onValueChange={(v) => {
    if (wasUpdated) {
      wasUpdated = false;
      return;
    }
    if (!v || v.length !== 3) return;

    const next = [...v] as [number, number, number];

    next[0] = Math.min(next[0], v[1]);
    next[1] = Math.max(Math.min(next[1], v[2]), v[0]);
    next[2] = Math.max(next[2], v[1]);

    const [s0, m0, h0] = value;
    let [s1, m1, h1] = next;

    // Detect which single thumb was moved
    const sMoved = s1 !== s0;
    const mMoved = m1 !== m0;
    const hMoved = h1 !== h0;

    wasUpdated = true;

    if (sMoved) {
      value = ratio.updateShadows(s1);
    } else if (mMoved) {
      value = ratio.updateMidtone(m1);
    } else if (hMoved) {
      value = ratio.updateHighlights(h1);
    }
  }}
  min={0}
  max={1}
  step={0.01}
  autoSort={false}
  class={cn('relative flex h-6 w-full touch-none items-center select-none', className)}
>
  {#snippet children({ thumbItems })}
    <span
      class="relative h-full w-full grow overflow-hidden rounded-sm"
      style="background: linear-gradient(to right, black, {color});"
    >
    </span>
    {#each thumbItems as thumb (thumb.index)}
      <SliderPrimitive.Thumb
        index={thumb.index}
        class="absolute -ml-0.75 block h-8 w-1.5 cursor-ew-resize rounded-sm border border-gray-400 bg-white hover:bg-gray-200 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50"
      />
    {/each}
  {/snippet}
</SliderPrimitive.Root>
