<script lang="ts">
  import { MoonIcon, SunIcon } from '@lucide/svelte';
  import { mode, toggleMode } from 'mode-watcher';
  import { Button } from './button';

  const {
    class: cls
  }: {
    class?: string;
  } = $props();
</script>

<Button variant="outline" size="sm" onclick={toggleMode} class={cls}>
  {#if mode.current === 'light'}
    <SunIcon />
  {:else}
    <MoonIcon />
  {/if}
</Button>
