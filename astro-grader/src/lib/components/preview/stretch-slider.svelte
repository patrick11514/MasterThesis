<script lang="ts">
  import { tick } from 'svelte';
  import { ColorSlider } from '../ui/color-slider';
  import type { Vec3 } from './state.svelte';

  type Props = {
    linked: boolean;
    shadows: Vec3;
    midtones: Vec3;
    highlights: Vec3;
  };
  const {
    linked = $bindable(false),
    shadows = $bindable(),
    midtones = $bindable(),
    highlights = $bindable()
  }: Props = $props();

  let syncing = $state(false);

  const getValue = (idx: number): Vec3['data'] => [
    shadows.data[idx],
    midtones.data[idx],
    highlights.data[idx]
  ];

  const setValue = (idx: number, [newS, newM, newH]: Vec3['data']) => {
    if (syncing) return;

    if (!linked) {
      shadows.data[idx] = newS;
      midtones.data[idx] = newM;
      highlights.data[idx] = newH;
      return;
    }

    syncing = true;
    const [oldS, oldM, oldH] = getValue(idx);

    // 1. Identify which handle actively moved
    // (Priority: Shadows and Highlights drive Midtones, so check them first)
    let changedHandle: 'S' | 'M' | 'H' | null = null;
    let oldVal = 0,
      newVal = 0;

    if (newS !== oldS) {
      changedHandle = 'S';
      oldVal = oldS;
      newVal = newS;
    } else if (newH !== oldH) {
      changedHandle = 'H';
      oldVal = oldH;
      newVal = newH;
    } else if (newM !== oldM) {
      changedHandle = 'M';
      oldVal = oldM;
      newVal = newM;
    }

    if (changedHandle !== null) {
      // 2. Calculate Proportional Jump (Percentage of available space used)
      const isIncreasing = newVal > oldVal;
      let pctJump = 0;

      if (isIncreasing) {
        const space = 1.0 - oldVal;
        pctJump = space > 0 ? (newVal - oldVal) / space : 0;
      } else {
        const space = oldVal - 0.0;
        pctJump = space > 0 ? (oldVal - newVal) / space : 0;
      }

      // Helper to apply the percentage jump to target's available space
      const getNewTarget = (targetOld: number) => {
        let targetNew = targetOld;
        if (isIncreasing) {
          targetNew = targetOld + (1.0 - targetOld) * pctJump;
        } else {
          targetNew = targetOld - (targetOld - 0.0) * pctJump;
        }
        // Round to 4 decimals to avoid IEEE 754 precision echo bugs
        return Math.max(0, Math.min(1, Math.round(targetNew * 10000) / 10000));
      };

      // 3. Apply to all sliders
      for (let i = 0; i < 3; i++) {
        if (i === idx) {
          // The actively dragged slider gets the raw exact values
          shadows.data[i] = newS;
          midtones.data[i] = newM;
          highlights.data[i] = newH;
        } else {
          // The linked sliders get proportional updates
          const targetS = shadows.data[i];
          const targetM = midtones.data[i];
          const targetH = highlights.data[i];

          // Calculate current ratio so the parent can preserve the midtone itself
          const currentDelta = targetH - targetS;
          const ratio = currentDelta === 0 ? 0.5 : (targetM - targetS) / currentDelta;

          if (changedHandle === 'S') {
            const newTargetS = getNewTarget(targetS);
            shadows.data[i] = newTargetS;

            // Re-apply ratio to new delta to keep midtone proportionately locked
            const exactMidtone = newTargetS + ratio * (targetH - newTargetS);
            midtones.data[i] = Math.max(0, Math.min(1, Math.round(exactMidtone * 10000) / 10000));
          } else if (changedHandle === 'H') {
            const newTargetH = getNewTarget(targetH);
            highlights.data[i] = newTargetH;

            // Re-apply ratio
            const exactMidtone = targetS + ratio * (newTargetH - targetS);
            midtones.data[i] = Math.max(0, Math.min(1, Math.round(exactMidtone * 10000) / 10000));
          } else if (changedHandle === 'M') {
            // Midtone moved independently, S and H stay where they are
            midtones.data[i] = getNewTarget(targetM);
          }
        }
      }
    }

    tick().then(() => {
      syncing = false;
    });
  };

  const colors = ['#ff0000', '#00ff00', '#0000ff'];
</script>

<div class="flex h-16 flex-col gap-2">
  {#each colors as color, idx (color)}
    <ColorSlider
      {color}
      bind:value={
        () => getValue(idx),
        ([s, m, h]) => {
          setValue(idx, [s, m, h]);
        }
      }
    />
  {/each}
</div>
