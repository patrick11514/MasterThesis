<script lang="ts">
  import AppSidebar from '$/lib/components/app-sidebar.svelte';
  import * as Sidebar from '$/lib/components/ui/sidebar';
  import { Toaster } from '$/lib/components/ui/sonner';

  let { children } = $props();
</script>

<Toaster position="top-center" />

<Sidebar.Provider>
  <AppSidebar />

  <main>
    <Sidebar.Trigger />
    {@render children?.()}
  </main>
</Sidebar.Provider>
