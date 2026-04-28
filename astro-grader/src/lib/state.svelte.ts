import { Channel, invoke } from '@tauri-apps/api/core';
import { open, save } from '@tauri-apps/plugin-dialog';
import { toast } from 'svelte-sonner';
import { buildCalibrateRequest, buildCalibrationProgressPreview } from './calibration';
import { appEvents } from './events.svelte';
import { parseFiles } from './files';
import { FILE_TYPES } from './files/types';
import type { AstroSession } from './types/AstroSession';
import type { CalibrationProgressMessage } from './types/CalibrationProgressMessage';
import type { CalibrationStorageMode } from './types/CalibrationStorageMode';
import type { Config } from './types/Config';
import type { FeState } from './types/FeState';
import type { File } from './types/File';
import type { NightPrefix } from './types/NightPrefix';
import { sortFunction } from './utils';

class AppState {
  public rawNights = $state<Record<string, File[]>>({});
  public groupedNights = $state<AstroSession[]>([]);
  public activeGroupedSessionUuid = $state<string | null>(null);
  public nightPrefixes = $state<NightPrefix[]>([]);
  public temperatureStep = $state(1);
  public exposureStep = $state(0);
  public gainStep = $state(0);
  public currentPreviewFilePath = $state<string | null>(null);
  public calibrationStorageMode = $state<CalibrationStorageMode>('NextToOriginal');
  public tempFolderPath = $state('');
  public calibrationProgress = $state<CalibrationProgressMessage | null>(null);
  public loaded = false;
  public framesShown = $state(Object.fromEntries(FILE_TYPES.map((type) => [type, true])));

  private sortRawNights(rawNights: Record<string, File[]>) {
    const sortedRawNights: Record<string, File[]> = {};

    if (rawNights.Unsorted) {
      sortedRawNights.Unsorted = rawNights.Unsorted;
    }

    const sortedKeys = Object.keys(rawNights)
      .filter((key) => key !== 'Unsorted')
      .sort((left, right) => sortFunction(left, right));

    for (const key of sortedKeys) {
      sortedRawNights[key] = rawNights[key];
    }

    return sortedRawNights;
  }

  public persistFeState = async () => {
    try {
      await invoke('set_fe_state', {
        feState: {
          raw_nights: this.rawNights,
          grouped_nights: this.groupedNights,
          active_grouped_session_uuid: this.activeGroupedSessionUuid,
          current_preview_file: this.currentPreviewFilePath,
          calibration_storage_mode: this.calibrationStorageMode
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

  public setActiveGroupedSession(uuid: string | null) {
    this.activeGroupedSessionUuid = uuid;
    void this.persistFeState();
  }

  private invalidateGroupedSessions() {
    this.groupedNights = [];
    this.activeGroupedSessionUuid = null;
  }

  private normalizeActiveGroupedSession() {
    if (this.groupedNights.length === 0) {
      this.activeGroupedSessionUuid = null;
      return;
    }

    const exists = this.groupedNights.some(
      (session) => session.uuid === this.activeGroupedSessionUuid
    );
    if (!exists) {
      this.activeGroupedSessionUuid = this.groupedNights[0]?.uuid ?? null;
    }
  }

  private currentPreviewStillExists() {
    if (!this.currentPreviewFilePath) {
      return false;
    }

    return Object.values(this.rawNights)
      .flat()
      .some((file) => file.path === this.currentPreviewFilePath);
  }

  async loadConfig() {
    try {
      const config = await invoke<Config>('config_get');
      const feState = await invoke<FeState>('get_fe_state');

      this.nightPrefixes = config.night_prefixes;
      this.calibrationStorageMode =
        feState.calibration_storage_mode ?? config.calibration_storage_mode;
      this.tempFolderPath = config.temp_folder_path;
      this.temperatureStep = config.temperature_step ?? 1;
      this.exposureStep = config.exposure_step ?? 0;
      this.gainStep = config.gain_step ?? 0;
      this.rawNights = this.sortRawNights(feState.raw_nights ?? {});
      this.groupedNights = feState.grouped_nights ?? [];
      this.activeGroupedSessionUuid = feState.active_grouped_session_uuid ?? null;
      this.currentPreviewFilePath = feState.current_preview_file ?? null;

      this.normalizeActiveGroupedSession();

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
        calibration_storage_mode: this.calibrationStorageMode,
        temp_folder_path: this.tempFolderPath,
        temperature_step: this.temperatureStep,
        exposure_step: this.exposureStep,
        gain_step: this.gainStep
      } satisfies Config;

      await invoke('config_set', { config });
      void this.persistFeState();
      toast.success('Config saved');
    } catch (error) {
      toast.error('Failed to save config', {
        description: error as string
      });
    }
  }

  storeFiles(newFiles: File[]) {
    const prevFiles = Object.values(this.rawNights).flat();

    const dedup = newFiles.filter((file) => !prevFiles.some((f) => f.path === file.path));
    const files = [...prevFiles, ...dedup];

    const parsed = parseFiles(files, this.nightPrefixes);
    this.rawNights = parsed;
    this.invalidateGroupedSessions();

    if (!this.currentPreviewStillExists()) {
      this.currentPreviewFilePath = null;
    }

    void this.persistFeState();

    return dedup.length;
  }

  reApplyFilters() {
    const prevFiles = Object.values(this.rawNights).flat();
    const parsed = parseFiles(prevFiles, this.nightPrefixes);
    this.rawNights = parsed;
    this.invalidateGroupedSessions();

    if (!this.currentPreviewStillExists()) {
      this.currentPreviewFilePath = null;
    }

    void this.persistFeState();
  }

  removeFiles(night: string, filePath: string | null = null) {
    if (!(night in this.rawNights)) {
      return;
    }

    if (filePath) {
      this.rawNights[night] = this.rawNights[night].filter((file) => file.path !== filePath);

      if (this.rawNights[night].length === 0) {
        delete this.rawNights[night];
      }
    } else {
      delete this.rawNights[night];
    }

    this.invalidateGroupedSessions();

    if (!this.currentPreviewStillExists()) {
      this.currentPreviewFilePath = null;
    }

    void this.persistFeState();
  }

  async groupFrames(onProgress?: (progress: { processed: number; total: number }) => void) {
    const totalFiles = Object.values(this.rawNights).flat().length;
    if (totalFiles === 0) {
      toast.error('No preview frames to group');
      return false;
    }

    try {
      const channel = new Channel<{ processed: number; total: number }>();
      channel.onmessage = (message) => {
        onProgress?.(message);
      };

      this.groupedNights = await invoke<AstroSession[]>('group_frames', { channel });

      this.normalizeActiveGroupedSession();

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

  async calibrateFrames() {
    if (this.calibrationProgress) {
      toast.error('Calibration is already running');
      return false;
    }

    const totalFiles = Object.values(this.rawNights).flat().length;
    if (totalFiles === 0) {
      toast.error('No frames to calibrate');
      return false;
    }

    const request = buildCalibrateRequest(
      Object.values(this.rawNights).flat(),
      this.calibrationStorageMode,
      this.tempFolderPath
    );

    const preview = buildCalibrationProgressPreview(this.groupedNights);
    this.calibrationProgress = preview;

    try {
      const channel = new Channel<CalibrationProgressMessage>();
      channel.onmessage = (message) => {
        if (preview) {
          this.calibrationProgress = message;
        }
      };

      await invoke('calibrate', { request, channel });

      // Don't clear calibrationProgress here - keep it open for user to see final status
      toast.success('Calibration completed');
      return true;
    } catch (error) {
      const errorMessage = String(error);

      if (errorMessage.includes('Calibration canceled')) {
        this.calibrationProgress = null;
        toast.info('Calibration canceled');
        return false;
      }

      toast.error('Failed to calibrate frames', {
        description: errorMessage
      });
      return false;
    }
  }

  closeCalibrationProgress() {
    this.calibrationProgress = null;
  }

  async cancelCalibration() {
    try {
      await invoke('calibrate_cancel');
    } catch (error) {
      toast.error('Failed to cancel calibration', {
        description: error as string
      });
    }
  }

  updateFileType(night: string, filePath: string, type: File['type']) {
    const files = this.rawNights[night];
    if (!files) {
      return;
    }

    const target = files.find((file) => file.path === filePath);
    if (!target) {
      return;
    }

    target.type = type;
    this.invalidateGroupedSessions();
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

export const getAppStateSync = () => appState;

export type AppStateType = typeof appState;

appEvents.on('Save', async () => {
  try {
    const path = await save({
      title: 'Save opened files',
      defaultPath: 'save.agproj'
    });

    if (!path) return;

    await invoke('save_state', {
      path
    });

    toast.success('State saved', {
      description:
        "App data successfully saved to file. You can load it later using the 'Load' button."
    });
  } catch (error) {
    toast.error('Failed to save state', {
      description: error as string
    });
  }
});

appEvents.on('Load', async () => {
  try {
    const file = await open({
      title: 'Load saved state',
      filters: [
        {
          name: 'Astro Grader Project',
          extensions: ['agproj']
        }
      ]
    });

    if (!file) return;

    await invoke<FeState>('load_state', { path: file });
    await appState.loadConfig();

    toast.success('State loaded', {
      description: 'App data successfully loaded from file.'
    });
  } catch (error) {
    toast.error('Failed to load state', {
      description: error as string
    });
  }
});
