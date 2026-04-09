import { Channel, invoke } from '@tauri-apps/api/core';
import { toast } from 'svelte-sonner';
import { parseFiles } from './files';
import { FILE_TYPES } from './files/types';
import type { Config } from './types/Config';
import type { FeState } from './types/FeState';
import type { File } from './types/File';
import type { NightPrefix } from './types/NightPrefix';
import type { Nights } from './types/Nights';

class AppState {
  public files = $state<Nights>({
    PreviewNights: {}
  });
  public nightPrefixes = $state<NightPrefix[]>([]);
  public temperatureStep = $state(1);
  public exposureStep = $state(0);
  public gainStep = $state(0);
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

    if (!('PreviewNights' in this.files)) {
      return false;
    }

    return Object.values(this.files.PreviewNights)
      .flat()
      .some((file) => file.path === this.currentPreviewFilePath);
  }

  async loadConfig() {
    try {
      const config = await invoke<Config>('config_get');
      const feState = await invoke<FeState>('get_fe_state');

      this.nightPrefixes = config.night_prefixes;
      this.temperatureStep = config.temperature_step ?? 1;
      this.exposureStep = config.exposure_step ?? 0;
      this.gainStep = config.gain_step ?? 0;
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
        night_prefixes: this.nightPrefixes,
        temperature_step: this.temperatureStep,
        exposure_step: this.exposureStep,
        gain_step: this.gainStep
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
    const prevFiles =
      'PreviewNights' in this.files
        ? Object.values(this.files.PreviewNights as Record<string, File[]>).flat()
        : [];

    const dedup = newFiles.filter((file) => !prevFiles.some((f) => f.path === file.path));
    const files = [...prevFiles, ...dedup];

    const parsed = parseFiles(files, this.nightPrefixes);
    this.files = {
      PreviewNights: parsed
    };

    if (!this.currentPreviewStillExists()) {
      this.currentPreviewFilePath = null;
    }

    void this.persistFeState();

    return dedup.length;
  }

  reApplyFilters() {
    const prevFiles =
      'PreviewNights' in this.files
        ? Object.values(this.files.PreviewNights as Record<string, File[]>).flat()
        : [];
    const parsed = parseFiles(prevFiles, this.nightPrefixes);
    this.files = {
      PreviewNights: parsed
    };

    if (!this.currentPreviewStillExists()) {
      this.currentPreviewFilePath = null;
    }

    void this.persistFeState();
  }

  removeFiles(night: string, filePath: string | null = null) {
    if (!('PreviewNights' in this.files)) {
      return;
    }

    if (filePath) {
      this.files.PreviewNights[night] = this.files.PreviewNights[night].filter(
        (file) => file.path !== filePath
      );

      if (this.files.PreviewNights[night].length === 0) {
        delete this.files.PreviewNights[night];
      }
    } else {
      delete this.files.PreviewNights[night];
    }

    if (!this.currentPreviewStillExists()) {
      this.currentPreviewFilePath = null;
    }

    void this.persistFeState();
  }

  async groupFrames(onProgress?: (progress: { processed: number; total: number }) => void) {
    if (!('PreviewNights' in this.files)) {
      toast.error('Frames are already grouped');
      return false;
    }

    const totalFiles = Object.values(this.files.PreviewNights).flat().length;
    if (totalFiles === 0) {
      toast.error('No preview frames to group');
      return false;
    }

    try {
      const channel = new Channel<{ processed: number; total: number }>();
      channel.onmessage = (message) => {
        onProgress?.(message);
      };

      const feState = await invoke<FeState>('group_frames', { channel });

      this.files = feState.nights;
      this.currentPreviewFilePath = feState.current_preview_file ?? null;

      if (!this.currentPreviewStillExists()) {
        this.currentPreviewFilePath = null;
      }

      void this.persistFeState();
      toast.success('Frames grouped');

      return true;
    } catch (error) {
      toast.error('Failed to group frames', {
        description: error as string
      });
      return false;
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
