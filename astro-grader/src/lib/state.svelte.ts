import { Channel, invoke } from '@tauri-apps/api/core';
import { open, save } from '@tauri-apps/plugin-dialog';
import { toast } from 'svelte-sonner';
import { buildCalibrateRequest, buildCalibrationProgressPreview } from './calibration';
import { appEvents } from './events.svelte';
import { parseFiles } from './files';
import { FILE_TYPES } from './files/types';
import type { AstroSession } from './types/AstroSession';
import type { CalibrationProgressMessage } from './types/CalibrationProgressMessage';
import type { CalibrationProgressStep } from './types/CalibrationProgressStep';
import type { CalibrationStorageMode } from './types/CalibrationStorageMode';
import type { Config } from './types/Config';
import type { FeState } from './types/FeState';
import type { File } from './types/File';
import type { FileBatchOperationKind } from './types/FileBatchOperationKind';
import type { FileBatchOperationProgressMessage } from './types/FileBatchOperationProgressMessage';
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
  public crossNightReference = $state(false);
  public maxFwhm = $state(0);
  public rejectionThreshold = $state(0.5);
  public currentPreviewFilePath = $state<string | null>(null);
  public calibrationStorageMode = $state<CalibrationStorageMode>('NextToOriginal');
  public tempFolderPath = $state('');
  public calibrationProgress = $state<CalibrationProgressMessage | null>(null);
  public batchProgress = $state<CalibrationProgressMessage | null>(null);
  public metricsProgress = $state<CalibrationProgressMessage | null>(null);
  public fileOperationProgress = $state<FileBatchOperationProgressMessage | null>(null);
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

  private applyFeState(feState: FeState) {
    this.rawNights = this.sortRawNights(feState.raw_nights ?? {});
    this.groupedNights = feState.grouped_nights ?? [];
    this.activeGroupedSessionUuid = feState.active_grouped_session_uuid ?? null;
    this.currentPreviewFilePath = feState.current_preview_file ?? null;
    this.calibrationStorageMode = feState.calibration_storage_mode ?? this.calibrationStorageMode;

    this.normalizeActiveGroupedSession();

    if (!this.currentPreviewStillExists()) {
      this.currentPreviewFilePath = null;
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
      this.crossNightReference = config.cross_night_reference ?? false;
      this.maxFwhm = config.max_fwhm ?? 0;
      this.rejectionThreshold = config.rejection_threshold ?? 0.5;
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
        gain_step: this.gainStep,
        cross_night_reference: this.crossNightReference,
        max_fwhm: this.maxFwhm,
        rejection_threshold: this.rejectionThreshold
      } satisfies Config;

      await invoke('config_set', { config });
      void this.persistFeState();
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

      const updatedState = await invoke<FeState>('calibrate', { request, channel });
      this.applyFeState(updatedState);
      void this.persistFeState();

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

  closeMetricsProgress() {
    this.metricsProgress = null;
  }

  closeBatchProgress() {
    this.batchProgress = null;
  }

  closeFileOperationProgress() {
    this.fileOperationProgress = null;
  }

  private buildFileOperationPreview(operation: FileBatchOperationKind, totalCount: number) {
    return {
      started_at: BigInt(Date.now()),
      finished_at: null,
      status: 'Running' as const,
      operation,
      processed_count: 0,
      total_count: totalCount,
      current_path: null,
      error: null
    } satisfies FileBatchOperationProgressMessage;
  }

  private async runFileOperation(
    operation: FileBatchOperationKind,
    paths: string[],
    targetDirectory?: string
  ) {
    if (this.fileOperationProgress) {
      toast.error('A file operation is already running');
      return false;
    }

    if (paths.length === 0) {
      toast.error('No files selected');
      return false;
    }

    this.fileOperationProgress = this.buildFileOperationPreview(operation, paths.length);

    try {
      const channel = new Channel<FileBatchOperationProgressMessage>();
      channel.onmessage = (message) => {
        this.fileOperationProgress = message;
      };

      const updatedState = await invoke<FeState>('batch_file_operation', {
        request: {
          operation,
          paths,
          target_directory: targetDirectory ?? null
        },
        channel
      });

      this.applyFeState(updatedState);
      void this.persistFeState();

      toast.success(operation === 'Move' ? 'Moved selected files' : 'Deleted selected files');

      return true;
    } catch (error) {
      const errorMessage = String(error);
      toast.error(
        operation === 'Move' ? 'Failed to move selected files' : 'Failed to delete selected files',
        {
          description: errorMessage
        }
      );

      if (this.fileOperationProgress) {
        this.fileOperationProgress = {
          ...this.fileOperationProgress,
          status: 'Failed',
          finished_at: BigInt(Date.now()),
          error: errorMessage
        };
      }

      return false;
    }
  }

  async moveSelectedFiles(paths: string[], targetDirectory: string) {
    return await this.runFileOperation('Move', paths, targetDirectory);
  }

  async deleteSelectedFiles(paths: string[]) {
    return await this.runFileOperation('Delete', paths);
  }

  async cancelBatch() {
    try {
      await invoke('calibrate_cancel');
    } catch {
      // ignore
    }

    try {
      // try a metrics cancel if backend supports it
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await invoke('run_metrics_cancel' as any);
    } catch {
      // ignore
    }
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

  async runMetrics() {
    if (this.metricsProgress) {
      toast.error('Metrics calculation is already running');
      return false;
    }

    const totalSessions = this.groupedNights.length;
    if (totalSessions === 0) {
      toast.error('No grouped sessions to compute metrics for');
      return false;
    }

    try {
      // Build a preview for metrics progress
      const steps = this.groupedNights.map((session) => ({
        id: `${session.uuid}:Metrics`,
        kind: 'Light' as const,
        label: 'Metrics',
        session_uuid: session.uuid,
        session_label: `${session.fingerprint.name} - ${session.fingerprint.filter}`,
        count: session.lights.length,
        completed_count: 0,
        skipped_count: 0,
        rejected_count: 0,
        status: 'Pending' as const,
        started_at: BigInt(Date.now()),
        ended_at: null as null,
        error: null as null
      }));

      const preview: CalibrationProgressMessage = {
        started_at: BigInt(Date.now()),
        finished_at: null,
        status: totalSessions === 0 ? 'Completed' : 'Running',
        current_step_id: null,
        steps
      };

      this.metricsProgress = preview;

      const channel = new Channel<CalibrationProgressMessage>();
      channel.onmessage = (message) => {
        if (this.metricsProgress) {
          this.metricsProgress = message;
        }
      };

      const updatedState = await invoke<FeState>('run_metrics', { channel });
      this.applyFeState(updatedState);
      void this.persistFeState();

      toast.success('Metrics calculated');
      return true;
    } catch (error) {
      this.metricsProgress = null;
      toast.error('Failed to calculate metrics', {
        description: error as string
      });
      return false;
    }
  }

  async runAllProcesses() {
    const totalFiles = Object.values(this.rawNights).flat().length;

    if (totalFiles === 0) {
      toast.error('No files to process');
      return false;
    }

    // Unified batch flow: grouping (if needed) -> calibrate -> metrics
    try {
      const needsGrouping = this.groupedNights.length === 0;

      if (needsGrouping) {
        // create a simple preview with a Group step
        const groupStep: CalibrationProgressStep = {
          id: 'Group:Frames',
          kind: 'Light' as const,
          label: 'Grouping frames',
          session_uuid: '',
          session_label: 'Grouping frames',
          count: totalFiles,
          completed_count: 0,
          skipped_count: 0,
          rejected_count: 0,
          status: 'Pending' as const,
          started_at: BigInt(Date.now()),
          ended_at: null,
          error: null
        };

        this.batchProgress = {
          started_at: BigInt(Date.now()),
          finished_at: null,
          status: 'Running',
          current_step_id: groupStep.id,
          steps: [groupStep]
        };

        const channel = new Channel<{ processed: number; total: number }>();
        channel.onmessage = (message) => {
          const bp = this.batchProgress;
          if (!bp) return;
          const step = bp.steps.find((s) => s.id === 'Group:Frames');
          if (!step) return;
          step.count = message.total;
          step.completed_count = message.processed;
          step.status =
            message.processed >= message.total ? ('Completed' as const) : ('Running' as const);
          if (step.status === 'Completed') {
            step.ended_at = BigInt(Date.now());
          }
          this.batchProgress = { ...bp };
        };

        try {
          const grouped = await invoke<AstroSession[]>('group_frames', { channel });
          this.groupedNights = grouped;
          this.normalizeActiveGroupedSession();
          if (!this.currentPreviewStillExists()) {
            this.currentPreviewFilePath = null;
          }
          void this.persistFeState();

          // mark grouping step as completed so it stays in table
          const completedGroupStep = this.batchProgress?.steps.find((s) => s.id === 'Group:Frames');
          if (completedGroupStep) {
            completedGroupStep.status = 'Completed' as const;
            completedGroupStep.ended_at = BigInt(Date.now());
          }
        } catch (error) {
          this.batchProgress = null;
          toast.error('Group frames step failed. Aborting run all processes.', {
            description: String(error)
          });
          return false;
        }
      } else {
        toast.info('Frames already grouped, skipping group step');
      }

      // Build calibration preview from grouped sessions
      const calPreview = buildCalibrationProgressPreview(this.groupedNights) ?? {
        started_at: BigInt(Date.now()),
        finished_at: null,
        status: 'Running' as const,
        current_step_id: null,
        steps: [] as CalibrationProgressStep[]
      };

      const metricsSteps = this.groupedNights.map((session) => ({
        id: `${session.uuid}:Metrics`,
        kind: 'Light' as const,
        label: 'Metrics',
        session_uuid: session.uuid,
        session_label: `${session.fingerprint.name} - ${session.fingerprint.filter}`,
        count: session.lights.length,
        completed_count: 0,
        skipped_count: 0,
        rejected_count: 0,
        status: 'Pending' as const,
        started_at: null as null,
        ended_at: null,
        error: null as null
      }));

      // Include grouping step if it was done
      const groupingStep = needsGrouping
        ? this.batchProgress?.steps.find((s) => s.id === 'Group:Frames')
        : null;
      const mergedSteps = [
        ...(groupingStep ? [groupingStep] : []),
        ...calPreview.steps,
        ...metricsSteps
      ];

      this.batchProgress = {
        started_at: BigInt(Date.now()),
        finished_at: null,
        status: mergedSteps.length === 0 ? 'Completed' : 'Running',
        current_step_id: mergedSteps.length > 0 ? mergedSteps[0].id : null,
        steps: mergedSteps
      };

      // Calibrate: invoke backend with channel to update steps in-place
      const request = buildCalibrateRequest(
        Object.values(this.rawNights).flat(),
        this.calibrationStorageMode,
        this.tempFolderPath
      );

      try {
        const channel = new Channel<CalibrationProgressMessage>();
        channel.onmessage = (message) => {
          const bp = this.batchProgress;
          if (!bp) return;
          bp.started_at = message.started_at;
          bp.finished_at = message.finished_at;
          bp.status = message.status;
          bp.current_step_id = message.current_step_id;

          for (const incoming of message.steps) {
            const target = bp.steps.find((s) => s.id === incoming.id);
            if (target) {
              target.count = incoming.count;
              target.status = incoming.status;
              target.completed_count = incoming.completed_count;
              target.skipped_count = incoming.skipped_count;
              target.rejected_count = incoming.rejected_count;
              target.started_at = incoming.started_at;
              target.ended_at = incoming.ended_at;
              target.error = incoming.error;
            }
          }

          this.batchProgress = { ...bp };
        };

        const updatedState = await invoke<FeState>('calibrate', { request, channel });
        this.applyFeState(updatedState);
        void this.persistFeState();
      } catch (error) {
        const errorMessage = String(error);
        this.batchProgress = null;
        if (errorMessage.includes('Calibration canceled')) {
          toast.info('Calibration canceled');
          return false;
        }
        toast.error('Calibrate frames step failed. Aborting run all processes.', {
          description: errorMessage
        });
        return false;
      }

      // Metrics
      try {
        const channel = new Channel<CalibrationProgressMessage>();
        channel.onmessage = (message) => {
          const bp = this.batchProgress;
          if (!bp) return;
          bp.started_at = message.started_at;
          bp.finished_at = message.finished_at;
          bp.status = message.status;
          bp.current_step_id = message.current_step_id;

          for (const incoming of message.steps) {
            const target = bp.steps.find(
              (s) => s.id === incoming.id || s.id === `${incoming.session_uuid}:Metrics`
            );
            if (target) {
              target.count = incoming.count;
              target.status = incoming.status;
              target.completed_count = incoming.completed_count;
              target.skipped_count = incoming.skipped_count;
              target.rejected_count = incoming.rejected_count;
              target.started_at = incoming.started_at;
              target.ended_at = incoming.ended_at;
              target.error = incoming.error;
            }
          }

          this.batchProgress = { ...bp };
        };

        const updatedState = await invoke<FeState>('run_metrics', { channel });
        this.applyFeState(updatedState);
        void this.persistFeState();
      } catch (error) {
        this.batchProgress = null;
        toast.error('Metrics computation step failed. Aborting run all processes.', {
          description: String(error)
        });
        return false;
      }

      toast.success('All processes completed successfully!');
      return true;
    } finally {
      // keep batchProgress open for user inspection
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
