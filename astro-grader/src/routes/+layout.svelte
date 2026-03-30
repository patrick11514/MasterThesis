<script lang="ts">
  import { ModeWatcher } from 'mode-watcher';
  import { Toaster } from 'svelte-sonner';
  import type { LayoutProps } from './$types';
  import './layout.css';
  const { children }: LayoutProps = $props();
</script>

<ModeWatcher />
<Toaster position="top-center" />

<main class="h-screen w-screen overflow-hidden">
  {@render children?.()}
</main>
