<script lang="ts">
  import { previewState } from './state.svelte';
</script>

<section>
  <input type="range" min="0" max="1" step="0.01" bind:value={previewState.stretchLevel} />
  <pre>
  {JSON.stringify(previewState.previewData, null, 2)}
  </pre>
</section>
