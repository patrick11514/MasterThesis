import type { AstroSession } from './types/AstroSession';
import type { CalibrateRequest } from './types/CalibrateRequest';
import type { CalibrationProgressMessage } from './types/CalibrationProgressMessage';
import type { CalibrationProgressStep } from './types/CalibrationProgressStep';
import type { CalibrationRunStatus } from './types/CalibrationRunStatus';
import type { CalibrationStepKind } from './types/CalibrationStepKind';
import type { CalibrationStepStatus } from './types/CalibrationStepStatus';
import type { CalibrationStorageMode } from './types/CalibrationStorageMode';
import type { File } from './types/File';
import type { MasterOrFrames } from './types/MasterOrFrames';

const getFileNameParts = (filePath: string) => {
  const lastSlashIndex = Math.max(filePath.lastIndexOf('/'), filePath.lastIndexOf('\\'));
  const directory = lastSlashIndex >= 0 ? filePath.slice(0, lastSlashIndex) : '';
  const fileName = filePath.slice(lastSlashIndex + 1);
  const extensionIndex = fileName.lastIndexOf('.');

  if (extensionIndex < 0) {
    return {
      directory,
      fileName,
      calibratedName: `${fileName}_cal`
    };
  }

  return {
    directory,
    fileName: fileName.slice(0, extensionIndex),
    calibratedName: `${fileName.slice(0, extensionIndex)}_cal${fileName.slice(extensionIndex)}`
  };
};

export const resolveCalibratedPath = (
  sourcePath: string,
  uuid: string,
  storageMode: CalibrationStorageMode,
  tempFolderPath: string
) => {
  const { directory, fileName, calibratedName } = getFileNameParts(sourcePath);

  if (storageMode === 'TempFolder') {
    const normalizedTempFolder = tempFolderPath.replace(/[\\/]+$/, '');
    const separator = normalizedTempFolder.includes('\\') ? '\\' : '/';
    const hash = uuid.split('-')[0];
    const extension = sourcePath.includes('.') ? sourcePath.slice(sourcePath.lastIndexOf('.')) : '';
    return `${normalizedTempFolder}${separator}${fileName}_${hash}${extension}`;
  }

  if (!directory) {
    return calibratedName;
  }

  const separator = directory.includes('\\') ? '\\' : '/';
  return `${directory}${separator}${calibratedName}`;
};

export const buildCalibrateRequest = (
  files: File[],
  storageMode: CalibrationStorageMode,
  tempFolderPath: string
): CalibrateRequest => {
  return {
    storage_mode: storageMode,
    temp_folder_path: tempFolderPath,
    targets: files
      .filter((file) => file.type === 'Light')
      .map((file) => ({
        source_path: file.path,
        calibrated_path: resolveCalibratedPath(file.path, file.uuid, storageMode, tempFolderPath)
      }))
  };
};

const kindLabel = (kind: CalibrationStepKind) => {
  switch (kind) {
    case 'Dark':
      return 'Stacking dark frames';
    case 'Flat':
      return 'Stacking flat frames';
    case 'Bias':
      return 'Stacking bias frames';
    case 'Light':
      return 'Calibrating light frames';
  }
};

const sessionLabel = (session: AstroSession) => {
  if (!session.fingerprint.name) {
    return 'Unnamed session';
  }

  return `${session.fingerprint.name} - ${session.fingerprint.filter} - ${session.fingerprint.exposure.toFixed(2)}s - gain ${session.fingerprint.gain.toFixed(2)} - ${session.fingerprint.temperature.toFixed(1)}C`;
};

const collectFrames = (slot: MasterOrFrames) => {
  if (!('Frames' in slot)) {
    return null;
  }

  return slot.Frames.length > 0 ? slot.Frames : null;
};

const framesSignature = (frames: File[]) => {
  const ids = frames.map((f) => f.uuid).sort();
  return ids.join(',');
};

export const buildCalibrationProgressPreview = (
  sessions: AstroSession[]
): CalibrationProgressMessage | null => {
  const steps: CalibrationProgressStep[] = [];
  const masterSignatures = new Set<string>();

  for (const session of sessions) {
    const label = sessionLabel(session);

    const slots: Array<[CalibrationStepKind, MasterOrFrames | File[]]> = [
      ['Dark', session.darks],
      ['Flat', session.flats],
      ['Bias', session.biases]
    ];

    for (const [kind, slot] of slots) {
      const frames = Array.isArray(slot) ? slot : collectFrames(slot);
      if (!frames || frames.length === 0) {
        continue;
      }

      const sig = framesSignature(frames);
      const key = `${kind}:${sig}`;
      if (masterSignatures.has(key)) {
        continue;
      }
      masterSignatures.add(key);

      steps.push({
        id: `${session.uuid}:${kind}`,
        kind,
        label: kindLabel(kind),
        session_uuid: session.uuid,
        session_label: label,
        count: frames.length,
        completed_count: 0,
        status: 'Pending' as CalibrationStepStatus,
        started_at: null,
        ended_at: null,
        error: null
      });
    }
  }

  for (const session of sessions) {
    const label = sessionLabel(session);

    if (session.lights.length > 0) {
      const kind = 'Light';
      steps.push({
        id: `${session.uuid}:${kind}`,
        kind,
        label: kindLabel(kind),
        session_uuid: session.uuid,
        session_label: label,
        count: session.lights.length,
        completed_count: 0,
        status: 'Pending' as CalibrationStepStatus,
        started_at: null,
        ended_at: null,
        error: null
      });
    }
  }

  if (steps.length === 0) {
    return null;
  }

  return {
    started_at: BigInt(Date.now()),
    finished_at: null,
    status: 'Running' as CalibrationRunStatus,
    current_step_id: null,
    steps
  };
};
