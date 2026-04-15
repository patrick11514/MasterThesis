<script lang="ts">
  import { appEvents } from '$/lib/events.svelte';
  import { platform } from '@tauri-apps/plugin-os';
  import { Button } from '../ui/button';
  import * as Kbd from '../ui/kbd';
  import ModeButton from '../ui/mode-button.svelte';

  const _platform = platform();
  console.log(_platform);
</script>

<div class="flex w-full items-center gap-2">
  <ModeButton />

  <Button
    variant="ghost"
    class="mx-auto"
    onclick={() => {
      appEvents.emit('OpenCommandPalette');
    }}
  >
    <Kbd.Group>
      {#if _platform === 'macos'}
        <Kbd.Root>⌘</Kbd.Root>
      {:else}
        <Kbd.Root>CTRL</Kbd.Root>
        <span>+</span>
      {/if}
      <Kbd.Root>K</Kbd.Root>
    </Kbd.Group>
  </Button>

  <ModeButton class="invisible" />
</div>
