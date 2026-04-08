import { invoke } from '@tauri-apps/api/core';
import { toast } from 'svelte-sonner';
import { parseFiles } from './files';
import { FILE_TYPES, type Files } from './files/types';
import type { Config } from './types/Config';
import type { File } from './types/File';
import type { NightPrefix } from './types/NightPrefix';

type FeState = {
  nights: Files;
  current_preview_file?: string | null;
};

class AppState {
  public files = $state<Files>({});
  public nightPrefixes = $state<NightPrefix[]>([]);
  public currentPreviewFilePath = $state<string | null>(null);
  public loaded = false;
  public framesShown = $state(Object.fromEntries(FILE_TYPES.map((type) => [type, true])));

  private persistFeState = async () => {
    try {
      await invoke('set_fe_state', {
        feState: {
          nights: this.files,
          current_preview_file: this.currentPreviewFilePath
        } satisfies FeState
      });
    } catch (error) {
      toast.error('Failed to persist app state', {
        description: error as string
      });
    }
  };

  public setCurrentPreviewFile(path: string | null) {
    this.currentPreviewFilePath = path;
    void invoke('set_fe_current_preview_file', { path });
  }

  private currentPreviewStillExists() {
    if (!this.currentPreviewFilePath) {
      return false;
    }

    return Object.values(this.files)
      .flat()
      .some((file) => file.path === this.currentPreviewFilePath);
  }

  async loadConfig() {
    try {
      const config = await invoke<Config>('config_get');
      const feState = await invoke<FeState>('get_fe_state');

      this.nightPrefixes = config.night_prefixes;
      this.files = feState.nights ?? {};
      this.currentPreviewFilePath = feState.current_preview_file ?? null;

      if (!this.currentPreviewStillExists()) {
        this.currentPreviewFilePath = null;
      }

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

    if (!this.currentPreviewStillExists()) {
      this.currentPreviewFilePath = null;
    }

    void this.persistFeState();

    return dedup.length;
  }

  reApplyFilters() {
    const allFiles = Object.values(appState.files).flat();
    const parsed = parseFiles(allFiles, this.nightPrefixes);
    this.files = parsed;

    if (!this.currentPreviewStillExists()) {
      this.currentPreviewFilePath = null;
    }

    void this.persistFeState();
  }

  removeFiles(night: string, filePath: string | null = null) {
    if (filePath) {
      this.files[night] = this.files[night].filter((file) => file.path !== filePath);

      if (this.files[night].length === 0) {
        delete this.files[night];
      }
    } else {
      delete this.files[night];
    }

    if (!this.currentPreviewStillExists()) {
      this.currentPreviewFilePath = null;
    }

    void this.persistFeState();
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
