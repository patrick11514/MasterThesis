<script lang="ts">
  import { Toaster } from '$/lib/components/ui/sonner';
  import { ModeWatcher } from 'mode-watcher';
  import type { LayoutProps } from './$types';
  import './layout.css';
  const { children }: LayoutProps = $props();
</script>

<ModeWatcher />
<Toaster position="top-center" />

<main class="h-screen w-screen overflow-hidden">
  {@render children?.()}
</main>
