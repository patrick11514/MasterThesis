import type { CalibrateRequest } from './types/CalibrateRequest';
import type { CalibrationStorageMode } from './types/CalibrationStorageMode';
import type { File } from './types/File';

const getFileNameParts = (filePath: string) => {
  const lastSlashIndex = Math.max(filePath.lastIndexOf('/'), filePath.lastIndexOf('\\'));
  const directory = lastSlashIndex >= 0 ? filePath.slice(0, lastSlashIndex) : '';
  const fileName = filePath.slice(lastSlashIndex + 1);
  const extensionIndex = fileName.lastIndexOf('.');

  if (extensionIndex < 0) {
    return {
      directory,
      calibratedName: `${fileName}_cal`
    };
  }

  return {
    directory,
    calibratedName: `${fileName.slice(0, extensionIndex)}_cal${fileName.slice(extensionIndex)}`
  };
};

export const resolveCalibratedPath = (
  sourcePath: string,
  storageMode: CalibrationStorageMode,
  tempFolderPath: string
) => {
  const { directory, calibratedName } = getFileNameParts(sourcePath);

  if (storageMode === 'TempFolder') {
    const normalizedTempFolder = tempFolderPath.replace(/[\\/]+$/, '');
    const separator = normalizedTempFolder.includes('\\') ? '\\' : '/';
    return `${normalizedTempFolder}${separator}${calibratedName}`;
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
        calibrated_path: resolveCalibratedPath(file.path, storageMode, tempFolderPath)
      }))
  };
};
