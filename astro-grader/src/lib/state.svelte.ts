import { invoke } from '@tauri-apps/api/core';
import { toast } from 'svelte-sonner';
import type { File, Files } from './files/types';
import type { Config } from './types/Config';

type NightFilter = {
  text: string;
  type: 'prefix' | 'suffix';
};

const DEFAULT_NIGHT_NAME = 'Unsorted';

class AppState {
  public files = $state<Files>({});
  public nightFilter = $state<NightFilter[]>([]);
  public config = $state() as Config;

  async loadConfig() {
    try {
      const config = await invoke<Config>('config_get');
      console.log(config);
      this.config = config;
    } catch (error) {
      toast.error('Failed to load config', {
        // Type safety: Tauri converts Result<X, Y> into thrown error of Y, and `config_get` returns Result<Config, String>
        description: error as string
      });
    }
  }

  async saveConfig() {
    try {
      await invoke('config_set', { config: this.config });
      toast.success('Config saved');
    } catch (error) {
      toast.error('Failed to save config', {
        description: error as string
      });
    }
  }
}

const appState = new AppState();
const promise = appState.loadConfig();

export const getAppState = async () => {
  if (!appState.config) {
    await promise;
  }

  return appState;
};

export const storeFiles = (files: File[]) => {
  const allFiles = Object.values(appState.files).flat();

  const dedup = files.filter((file) => !allFiles.some((f) => f.path === file.path));

  if (appState.nightFilter.length == 0) {
    if (!(DEFAULT_NIGHT_NAME in appState.files)) {
      appState.files[DEFAULT_NIGHT_NAME] = [];
    }

    appState.files[DEFAULT_NIGHT_NAME] = [...appState.files[DEFAULT_NIGHT_NAME], ...dedup];
  }

  //TODO

  return dedup.length;
};
