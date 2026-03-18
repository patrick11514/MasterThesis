<script lang="ts">
  import { Toaster } from '$/lib/components/ui/sonner';

  let { children } = $props();
</script>

<Toaster position="top-center" />

<main class="h-screen w-screen overflow-hidden">
  {@render children?.()}
</main>
