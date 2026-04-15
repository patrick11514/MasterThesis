<script lang="ts">
  import { appEvents } from '$/lib/events.svelte';
  import { FileIcon, FolderIcon, LayersIcon, SaveIcon } from '@lucide/svelte';
  import { platform } from '@tauri-apps/plugin-os';
  import * as Command from '../ui/command';

  let open = $state(false);

  const openCommandPalette = () => {
    open = true;
  };

  const save = () => {
    appEvents.emit('Save');
  };

  const load = () => {
    appEvents.emit('Load');
  };

  const importFiles = () => {
    appEvents.emit('ImportFITS');
  };

  const importDirectory = () => {
    appEvents.emit('ImportFITSDirectory');
  };

  const groupFrames = () => {
    appEvents.emit('GroupFrames');
  };

  //This wrapper closes the command palette before executing the command
  //to prevent issues, when some commands open another dialog, which will
  //be blocked by command palette
  const wrap = (fn: () => void) => {
    return () => {
      open = false;
      fn();
    };
  };

  const handleKeydown = (e: KeyboardEvent) => {
    let activated = false;

    const ctrl = e.ctrlKey;
    const meta = e.metaKey;
    const shift = e.shiftKey;

    // Command Dialog
    const K = e.key === 'k' || e.key === 'K';
    const P = e.key === 'p' || e.key === 'P';
    if (
      //
      ((ctrl || meta) && K) ||
      ((ctrl || meta) && shift && P)
    ) {
      activated = true;
      open = !open;
    }

    // Save
    const S = e.key === 's' || e.key === 'S';
    if ((ctrl || meta) && S) {
      activated = true;
      save();
    }
    // Load
    const O = e.key === 'o' || e.key === 'O';
    if ((ctrl || meta) && O) {
      activated = true;
      load();
    }
    // Import
    const I = e.key === 'i' || e.key === 'I';
    if ((ctrl || meta) && I && !shift) {
      activated = true;
      importFiles();
    }
    // Group frames
    const G = e.key === 'g' || e.key === 'G';
    if ((ctrl || meta) && G) {
      activated = true;
      groupFrames();
    }

    if (activated) {
      e.preventDefault();
    }
  };

  const _platform = platform();

  appEvents.on('OpenCommandPalette', openCommandPalette);
</script>

<svelte:document onkeydown={handleKeydown} />

<Command.Dialog bind:open>
  <Command.Input placeholder="Type a command or search..." />
  <Command.List>
    <Command.Empty>No results found.</Command.Empty>
    <Command.Group heading="Project">
      <Command.Item onclick={wrap(save)}>
        <SaveIcon class="me-2 size-4" />
        <span>Save</span>
        <Command.Shortcut>
          {#if _platform === 'macos'}
            ⌘
          {:else}
            CTRL +
          {/if}
          S
        </Command.Shortcut>
      </Command.Item>
      <Command.Item onclick={wrap(load)}>
        <FileIcon class="me-2 size-4" />
        <span>Load</span>
        <Command.Shortcut>
          {#if _platform === 'macos'}
            ⌘
          {:else}
            CTRL +
          {/if}
          O
        </Command.Shortcut>
      </Command.Item>
    </Command.Group>

    <Command.Separator />

    <Command.Group heading="Import FITS Data">
      <Command.Item onclick={wrap(importFiles)}>
        <FileIcon class="me-2 size-4" />
        <span>Import files</span>
        <Command.Shortcut>
          {#if _platform === 'macos'}
            ⌘
          {:else}
            CTRL +
          {/if}
          I
        </Command.Shortcut>
      </Command.Item>
      <Command.Item onclick={wrap(importDirectory)}>
        <FolderIcon class="me-2 size-4" />
        <span>Import folder</span>
        <Command.Shortcut>
          {#if _platform === 'macos'}
            ⌘ + Shift
          {:else}
            CTRL + Shift +
          {/if}
          I
        </Command.Shortcut>
      </Command.Item>
    </Command.Group>

    <Command.Separator />

    <Command.Group heading="Processing">
      <Command.Item onclick={wrap(groupFrames)}>
        <LayersIcon class="me-2 size-4" />
        <span>Group frames</span>
        <Command.Shortcut>
          {#if _platform === 'macos'}
            ⌘
          {:else}
            CTRL
          {/if}
          G
        </Command.Shortcut>
      </Command.Item>
    </Command.Group>
  </Command.List>
</Command.Dialog>
