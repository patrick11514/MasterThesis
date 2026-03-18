<script lang="ts">
  import { ModeWatcher } from 'mode-watcher';
  import type { LayoutProps } from './$types';
  import './layout.css';
  const { children }: LayoutProps = $props();
</script>

<ModeWatcher />
{@render children()}
