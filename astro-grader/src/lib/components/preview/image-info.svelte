<script lang="ts">
  import { previewState } from './state.svelte';
  import Stretch from './stretch.svelte';
</script>

{#if previewState.previewData}
  <div
    class="flex w-full flex-1 flex-col items-stretch justify-stretch divide-y divide-muted-foreground p-1"
  >
    <div class="flex flex-col gap-1 py-2">
      <h2 class="text-xl font-semibold">Image Info</h2>
      TODO
    </div>
    <div class="flex w-full flex-col gap-1 py-2">
      <h2>Stretch</h2>
      <Stretch />
    </div>
    <div class="flex w-full flex-col gap-1 py-2">
      <h2>Debug</h2>
      <pre>
        {JSON.stringify(previewState.previewData, null, 2)}
        {JSON.stringify({ R: previewState.R, G: previewState.G, B: previewState.B }, null, 2)}
       </pre>
    </div>
  </div>
{:else}
  <div class="flex flex-col items-center justify-center gap-2 p-4">
    <h2 class="text-lg font-semibold">No image loaded</h2>
    <p class="text-sm text-muted-foreground">
      Please load a FITS file to see the image info and histogram.
    </p>
  </div>
{/if}
