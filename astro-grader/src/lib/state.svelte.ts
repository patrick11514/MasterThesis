import { invoke } from '@tauri-apps/api/core';
import { toast } from 'svelte-sonner';
import { parseFiles } from './files';
import { FILE_TYPES, type Files } from './files/types';
import type { Config } from './types/Config';
import type { File } from './types/File';
import type { NightPrefix } from './types/NightPrefix';

class AppState {
  public files = $state<Files>({});
  public nightPrefixes = $state<NightPrefix[]>([]);
  public loaded = false;
  public framesShown = $state(Object.fromEntries(FILE_TYPES.map((type) => [type, true])));

  async loadConfig() {
    try {
      const config = await invoke<Config>('config_get');
      this.nightPrefixes = config.night_prefixes;

      this.loaded = true;
    } catch (error) {
      toast.error('Failed to load config', {
        // Type safety: Tauri converts Result<X, Y> into thrown error of Y, and `config_get` returns Result<Config, String>
        description: error as string
      });
    }
  }

  async saveConfig() {
    try {
      const config = {
        night_prefixes: this.nightPrefixes
      } satisfies Config;

      await invoke('config_set', { config });
      toast.success('Config saved');
    } catch (error) {
      toast.error('Failed to save config', {
        description: error as string
      });
    }
  }

  storeFiles(newFiles: File[]) {
    const allFiles = Object.values(appState.files).flat();

    const dedup = newFiles.filter((file) => !allFiles.some((f) => f.path === file.path));
    const files = [...allFiles, ...dedup];

    const parsed = parseFiles(files, this.nightPrefixes);
    this.files = parsed;

    return dedup.length;
  }

  reApplyFilters() {
    const allFiles = Object.values(appState.files).flat();
    const parsed = parseFiles(allFiles, this.nightPrefixes);
    this.files = parsed;
  }

  removeFiles(night: string, filePath: string | null = null) {
    if (filePath) {
      this.files[night] = this.files[night].filter((file) => file.path !== filePath);
    } else {
      delete this.files[night];
    }
  }
}

const appState = new AppState();
const promise = appState.loadConfig();

export const getAppState = async () => {
  if (!appState.loaded) {
    await promise;
  }
  return appState;
};

export type AppStateType = typeof appState;
