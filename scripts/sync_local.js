#!/usr/bin/env node

/**
 * sync_local.js - Sync raw astronomical images (FITS/TIFF) from local directory or remote Proxmox storage
 *
 * Scans local defect annotation files (.json) in the target directory (e.g. TRAINING_FILES
 * or test_fits), identifies which raw image frames are missing locally, locates them
 * in a local directory (localhost) or on a remote host (Proxmox over SSH), and copies/downloads them.
 *
 * Usage:
 *   node scripts/sync_local.js [target_folder] [source_folder] [options]
 *
 * Options:
 *   --local, -l          Search on local machine (localhost) instead of remote SSH
 *   --source-dir, -s <p> Source search directory (aliases: --src-dir, --dir, --remote-dir)
 *   --host <host>        SSH host alias or IP (default: proxmox; 'localhost'/'local' for local sync)
 *   --dry-run            Show missing and found files without transferring
 *   --help, -h           Show help message
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawn, spawnSync } = require('child_process');

// ANSI Color Helpers
const colors = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  red: '\x1b[31m',
};

function printHelp() {
  console.log(`
${colors.bold}${colors.cyan}AstroGrader Image Sync Tool${colors.reset}

${colors.bold}Usage:${colors.reset}
  node sync_local.js [target_dir] [source_dir] [options]
  ./sync_local.sh [source_or_target_dir] [options]

${colors.bold}Arguments:${colors.reset}
  target_dir           Local directory containing annotations (.json) and where images will be placed
                       (default: auto-detected, e.g. TRAINING_FILES or current directory)
  source_dir           Directory to search for raw image frames (.fits, .tif, etc.)
                       Can be a folder on this PC (localhost) or a remote directory path

${colors.bold}Options:${colors.reset}
  --local, -l          Search on this local machine (localhost) instead of remote SSH host
  --source-dir, -s <p> Source search directory for raw images (aliases: --src-dir, --dir, --remote-dir)
  --host <name>        SSH remote host (default: proxmox). Set to 'localhost' or 'local' for local sync
  --dry-run            Scan and locate files without downloading/copying
  --help, -h           Show this help message

${colors.bold}Examples:${colors.reset}
  # Sync from another folder on this machine (localhost):
  ./sync_local.sh /path/to/my/local/astro_images
  ./sync_local.sh --local --source-dir /media/external/ASTRO
  node scripts/sync_local.js TRAINING_FILES /mnt/data/fits

  # Sync from remote Proxmox storage over SSH:
  ./sync_local.sh
  ./sync_local.sh --host proxmox --remote-dir /mnt/HDD/ASTRO

  # Dry run (locate files without copying):
  ./sync_local.sh /path/to/local/astro_images --dry-run
`);
}

function expandHome(p) {
  if (!p) return p;
  if (p === '~') return os.homedir();
  if (p.startsWith('~/') || p.startsWith('~\\')) {
    return path.join(os.homedir(), p.slice(2));
  }
  return p;
}

// Parse command line arguments
const args = process.argv.slice(2);
let targetDirArg = null;
let remoteHost = process.env.REMOTE_HOST || 'proxmox';
let sourceDir = process.env.LOCAL_DIR || process.env.SOURCE_DIR || process.env.SRC_DIR || process.env.REMOTE_DIR || '/mnt/HDD/ASTRO';
let isDryRun = false;
let isLocalFlag = Boolean(process.env.LOCAL_DIR);
let hostExplicitlySet = Boolean(process.env.REMOTE_HOST);
let sourceDirExplicitlySet = Boolean(process.env.LOCAL_DIR || process.env.SOURCE_DIR || process.env.SRC_DIR || process.env.REMOTE_DIR);

const positionalArgs = [];

for (let i = 0; i < args.length; i++) {
  const arg = args[i];
  if (arg === '--help' || arg === '-h') {
    printHelp();
    process.exit(0);
  } else if (arg === '--dry-run') {
    isDryRun = true;
  } else if (arg === '--local' || arg === '-l' || arg === '--localhost') {
    isLocalFlag = true;
  } else if (arg === '--host') {
    remoteHost = args[++i];
    hostExplicitlySet = true;
  } else if (arg.startsWith('--host=')) {
    remoteHost = arg.slice(7);
    hostExplicitlySet = true;
  } else if (arg === '--source-dir' || arg === '--src-dir' || arg === '--remote-dir' || arg === '--dir' || arg === '-s') {
    sourceDir = expandHome(args[++i]);
    sourceDirExplicitlySet = true;
  } else if (arg.startsWith('--source-dir=')) {
    sourceDir = expandHome(arg.slice(13));
    sourceDirExplicitlySet = true;
  } else if (arg.startsWith('--src-dir=')) {
    sourceDir = expandHome(arg.slice(10));
    sourceDirExplicitlySet = true;
  } else if (arg.startsWith('--remote-dir=')) {
    sourceDir = expandHome(arg.slice(13));
    sourceDirExplicitlySet = true;
  } else if (arg.startsWith('--dir=')) {
    sourceDir = expandHome(arg.slice(6));
    sourceDirExplicitlySet = true;
  } else if (arg === '--target-dir' || arg === '-t') {
    targetDirArg = expandHome(args[++i]);
  } else if (arg.startsWith('--target-dir=')) {
    targetDirArg = expandHome(arg.slice(13));
  } else if (!arg.startsWith('-')) {
    positionalArgs.push(expandHome(arg));
  }
}

// Check if directory has annotation files
function dirHasAnnotations(dirPath) {
  try {
    const resolved = path.resolve(process.cwd(), dirPath);
    if (!fs.existsSync(resolved) || !fs.statSync(resolved).isDirectory()) return false;
    const files = fs.readdirSync(resolved);
    return files.some(f => f.endsWith('.json') && !f.includes('package') && !f.includes('history') && !f.includes('config') && f !== 'tsconfig.json');
  } catch (e) {
    return false;
  }
}

// Map positional arguments
if (positionalArgs.length >= 2) {
  if (!targetDirArg) targetDirArg = positionalArgs[0];
  if (!sourceDirExplicitlySet) {
    sourceDir = positionalArgs[1];
    sourceDirExplicitlySet = true;
  }
} else if (positionalArgs.length === 1) {
  const p = positionalArgs[0];
  if (targetDirArg) {
    if (!sourceDirExplicitlySet) {
      sourceDir = p;
      sourceDirExplicitlySet = true;
    }
  } else {
    if (dirHasAnnotations(p)) {
      targetDirArg = p;
    } else {
      sourceDir = p;
      sourceDirExplicitlySet = true;
    }
  }
}

// Resolve target local directory (where annotations live and missing files will be placed)
function resolveTargetDirectory(arg) {
  if (arg) {
    const resolved = path.resolve(process.cwd(), arg);
    if (fs.existsSync(resolved) && fs.statSync(resolved).isDirectory()) {
      return resolved;
    }
    console.error(`${colors.red}Error: Specified target directory does not exist: ${resolved}${colors.reset}`);
    process.exit(1);
  }

  // Auto-detection:
  // If current working directory has .json annotations, use cwd
  const cwdFiles = fs.readdirSync(process.cwd());
  if (cwdFiles.some(f => f.endsWith('.json') && f !== 'package.json' && f !== 'tsconfig.json')) {
    return process.cwd();
  }

  // Check common project folders relative to cwd
  const candidates = ['TRAINING_FILES', 'test_fits', '../TRAINING_FILES'];
  for (const cand of candidates) {
    const p = path.resolve(process.cwd(), cand);
    if (fs.existsSync(p) && fs.statSync(p).isDirectory()) {
      return p;
    }
  }

  return process.cwd();
}

const targetDir = resolveTargetDirectory(targetDirArg);

// Determine local vs remote mode
const resolvedSourceDir = path.resolve(process.cwd(), sourceDir);
let isSourceDirLocal = false;
try {
  isSourceDirLocal = fs.existsSync(resolvedSourceDir) && fs.statSync(resolvedSourceDir).isDirectory();
} catch (e) {
  isSourceDirLocal = false;
}

let isLocal = false;
if (isLocalFlag) {
  isLocal = true;
} else if (hostExplicitlySet) {
  const h = (remoteHost || '').toLowerCase();
  isLocal = ['localhost', 'local', '127.0.0.1', '::1', 'none', ''].includes(h);
} else {
  // If host wasn't explicitly specified, and sourceDir exists locally on this machine, use local mode!
  if (sourceDirExplicitlySet && isSourceDirLocal) {
    isLocal = true;
  } else {
    isLocal = false;
  }
}

if (isLocal) {
  if (!isSourceDirLocal) {
    console.error(`${colors.red}${colors.bold}Error: Local source directory does not exist or is not a directory:${colors.reset} ${resolvedSourceDir}`);
    console.error(`${colors.dim}Please specify an existing directory on this PC: ./sync_local.sh <folder_path> or --source-dir <folder_path>${colors.reset}`);
    process.exit(1);
  }
  sourceDir = resolvedSourceDir;
}

console.log(`${colors.bold}${colors.cyan}=== AstroGrader Image Sync Tool ===${colors.reset}`);
console.log(`${colors.dim}Target directory:${colors.reset}   ${colors.bold}${targetDir}${colors.reset}`);
if (isLocal) {
  console.log(`${colors.dim}Sync Mode:${colors.reset}          ${colors.bold}${colors.green}Local machine (localhost)${colors.reset}`);
  console.log(`${colors.dim}Source directory:${colors.reset}   ${colors.bold}${sourceDir}${colors.reset}`);
} else {
  console.log(`${colors.dim}Sync Mode:${colors.reset}          ${colors.bold}${colors.blue}Remote SSH (${remoteHost})${colors.reset}`);
  console.log(`${colors.dim}Remote search dir:${colors.reset} ${colors.bold}${sourceDir}${colors.reset}`);
}
if (isDryRun) {
  console.log(`${colors.yellow}${colors.bold}[DRY RUN MODE]${colors.reset} No files will be transferred.`);
}
console.log('');

// Image file extensions to check
const IMAGE_EXTENSIONS = ['.fits', '.fit', '.FITS', '.FIT', '.tif', '.tiff', '.TIF', '.TIFF', '.fts', '.FTS'];

// Find all annotation files
const allFiles = fs.readdirSync(targetDir);
const jsonFiles = allFiles.filter(f => f.endsWith('.json') && !f.includes('package') && !f.includes('history') && !f.includes('config'));

if (jsonFiles.length === 0) {
  console.log(`${colors.yellow}No annotation .json files found in ${targetDir}${colors.reset}`);
  process.exit(0);
}

const missingImages = [];
const presentImages = [];

for (const jsonFile of jsonFiles) {
  const jsonPath = path.join(targetDir, jsonFile);
  let expectedFilename = null;

  try {
    const content = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
    if (content.file_name && typeof content.file_name === 'string') {
      expectedFilename = content.file_name;
    }
  } catch (err) {
    // If not valid JSON, fallback to stem
  }

  const baseStem = path.basename(jsonFile, '.json');

  // Check if expectedFilename exists
  let foundLocal = false;
  let localFilename = null;

  if (expectedFilename) {
    const expectedPath = path.join(targetDir, expectedFilename);
    if (fs.existsSync(expectedPath) && fs.statSync(expectedPath).size > 0) {
      foundLocal = true;
      localFilename = expectedFilename;
    }
  }

  // If not found yet, check any matching image extension with baseStem
  if (!foundLocal) {
    for (const ext of IMAGE_EXTENSIONS) {
      const candidateName = baseStem + ext;
      const candidatePath = path.join(targetDir, candidateName);
      if (fs.existsSync(candidatePath) && fs.statSync(candidatePath).size > 0) {
        foundLocal = true;
        localFilename = candidateName;
        break;
      }
    }
  }

  if (foundLocal) {
    presentImages.push(localFilename);
  } else {
    // Target to search for
    const targetName = expectedFilename || (baseStem + '.fits');
    missingImages.push({
      targetName,
      baseStem,
      jsonFile,
    });
  }
}

console.log(`${colors.dim}Total annotations:${colors.reset}       ${colors.bold}${jsonFiles.length}${colors.reset}`);
console.log(`${colors.green}Already present in target:${colors.reset} ${colors.bold}${presentImages.length}${colors.reset}`);
console.log(`${colors.yellow}Missing from target:${colors.reset}     ${colors.bold}${missingImages.length}${colors.reset}`);

if (missingImages.length === 0) {
  console.log(`\n${colors.green}${colors.bold}✔ All corresponding image frames already exist in target directory! Nothing to sync.${colors.reset}\n`);
  process.exit(0);
}

console.log('');
if (missingImages.length <= 10) {
  console.log(`${colors.dim}Missing files needed:${colors.reset}`);
  missingImages.forEach(m => console.log(`  - ${colors.yellow}${m.targetName}${colors.reset}`));
} else {
  console.log(`${colors.dim}Missing files sample (first 10 of ${missingImages.length}):${colors.reset}`);
  missingImages.slice(0, 10).forEach(m => console.log(`  - ${colors.yellow}${m.targetName}${colors.reset}`));
  console.log(`  ${colors.dim}... and ${missingImages.length - 10} more${colors.reset}`);
}
console.log('');

// Setup persistent SSH ControlMaster socket only when connecting to a remote host
const controlSocketPath = `/tmp/ssh_mux_astro_${process.pid}_%h_%p_%r`;
const sshControlArgs = [
  '-o', 'ControlMaster=auto',
  '-o', `ControlPath=${controlSocketPath}`,
  '-o', 'ControlPersist=10m',
  '-o', 'ConnectTimeout=15',
];

function cleanupSocket() {
  if (isLocal) return;
  try {
    spawnSync('ssh', ['-O', 'exit', '-o', `ControlPath=${controlSocketPath}`, remoteHost], {
      stdio: 'ignore',
    });
  } catch (e) {}
}

if (!isLocal) {
  process.on('exit', cleanupSocket);
  process.on('SIGINT', () => {
    cleanupSocket();
    process.exit(130);
  });
}

// Local search function
async function searchLocalFiles(rootDir, missingList) {
  return new Promise((resolve) => {
    const targets = new Set();
    const stems = new Map();

    for (const m of missingList) {
      targets.add(m.targetName);
      const stem = path.parse(m.targetName).name.toLowerCase();
      stems.set(stem, m.targetName);
      if (m.baseStem) {
        stems.set(m.baseStem.toLowerCase(), m.targetName);
      }
    }

    const totalTargets = targets.size;
    const results = new Map();
    const stack = [rootDir];
    const visitedDirs = new Set();
    let scannedDirs = 0;

    function checkLocalFile(fileName, fullPath) {
      if (targets.has(fileName)) {
        results.set(fileName, fullPath);
        targets.delete(fileName);
        return;
      }
      const stem = path.parse(fileName).name.toLowerCase();
      if (stems.has(stem)) {
        const orig = stems.get(stem);
        if (targets.has(orig)) {
          results.set(orig, fullPath);
          targets.delete(orig);
        }
      }
    }

    while (stack.length > 0 && targets.size > 0) {
      const currentDir = stack.pop();

      try {
        const real = fs.realpathSync(currentDir);
        if (visitedDirs.has(real)) continue;
        visitedDirs.add(real);
      } catch (e) {
        continue;
      }

      scannedDirs++;
      if (scannedDirs % 50 === 0) {
        process.stderr.write(`\rSearching local storage... found ${results.size}/${totalTargets} files (scanned ${scannedDirs} directories)`);
      }

      let entries;
      try {
        entries = fs.readdirSync(currentDir, { withFileTypes: true });
      } catch (e) {
        continue;
      }

      for (const entry of entries) {
        const fullPath = path.join(currentDir, entry.name);

        if (entry.isDirectory()) {
          stack.push(fullPath);
        } else if (entry.isSymbolicLink()) {
          try {
            const targetStat = fs.statSync(fullPath);
            if (targetStat.isDirectory()) {
              stack.push(fullPath);
            } else if (targetStat.isFile()) {
              checkLocalFile(entry.name, fullPath);
            }
          } catch (e) {}
        } else if (entry.isFile()) {
          checkLocalFile(entry.name, fullPath);
        }

        if (targets.size === 0) break;
      }
    }

    process.stderr.write(`\rSearch completed! Found ${results.size}/${totalTargets} files in ${scannedDirs} directories.\n`);
    resolve(results);
  });
}

// Remote Python script to locate target files on remote host (e.g. Proxmox)
const remoteFinderScript = `
import sys, os

targets = set()
stems = {}

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    targets.add(line)
    stem = os.path.splitext(line)[0].lower()
    stems[stem] = line

if not targets:
    sys.exit(0)

total_targets = len(targets)
root_dir = sys.argv[1] if len(sys.argv) > 1 else "/mnt/HDD/ASTRO"
if not os.path.isdir(root_dir):
    sys.stderr.write(f"ERROR: Directory not found on remote: {root_dir}\\n")
    sys.exit(1)

found = {}
scanned_dirs = 0

for root, dirs, files in os.walk(root_dir, followlinks=True):
    scanned_dirs += 1
    if scanned_dirs % 50 == 0:
        sys.stderr.write(f"\\rSearching Proxmox storage... found {len(found)}/{total_targets} files (scanned {scanned_dirs} directories)")
        sys.stderr.flush()

    for f in files:
        if f in targets:
            found[f] = os.path.join(root, f)
            targets.discard(f)
            if not targets:
                break
        else:
            stem = os.path.splitext(f)[0].lower()
            if stem in stems and stems[stem] in targets:
                orig = stems[stem]
                found[orig] = os.path.join(root, f)
                targets.discard(orig)
                if not targets:
                    break
    if not targets:
        break

sys.stderr.write(f"\\rSearch completed! Found {len(found)}/{total_targets} files in {scanned_dirs} directories.\\n")
sys.stderr.flush()

for target, full_path in found.items():
    print(f"{target}\\t{full_path}")
`;

// Query remote host via SSH
async function searchRemoteFiles() {
  return new Promise((resolve, reject) => {
    const inputLines = missingImages.map(m => m.targetName).join('\n') + '\n';

    const b64Script = Buffer.from(remoteFinderScript).toString('base64');
    const remotePyCommand = `if command -v find_astro_files.py >/dev/null 2>&1; then find_astro_files.py --dir ${JSON.stringify(sourceDir)}; elif [ -f ~/find_astro_files.py ]; then python3 ~/find_astro_files.py --dir ${JSON.stringify(sourceDir)}; else python3 -c "import base64; exec(base64.b64decode('${b64Script}').decode('utf-8'))" ${JSON.stringify(sourceDir)}; fi`;

    const sshCmdArgs = [
      ...sshControlArgs,
      remoteHost,
      remotePyCommand,
    ];

    const child = spawn('ssh', sshCmdArgs, {
      stdio: ['pipe', 'pipe', 'inherit'],
    });

    let stdoutData = '';

    child.stdout.on('data', chunk => {
      stdoutData += chunk.toString();
    });

    child.stdin.write(inputLines);
    child.stdin.end();

    child.on('error', err => reject(err));
    child.on('close', code => {
      if (code !== 0) {
        return reject(new Error(`SSH search process exited with code ${code}`));
      }

      const results = new Map();
      const lines = stdoutData.trim().split('\n');
      for (const line of lines) {
        if (!line.includes('\t')) continue;
        const [target, remotePath] = line.split('\t');
        if (target && remotePath) {
          results.set(target.trim(), remotePath.trim());
        }
      }
      resolve(results);
    });
  });
}

async function run() {
  if (isLocal) {
    console.log(`${colors.cyan}Searching local directory ${sourceDir}...${colors.reset}\n`);
  } else {
    console.log(`${colors.cyan}Connecting to ${remoteHost} and searching ${sourceDir}...${colors.reset}`);
    console.log(`${colors.dim}(If prompted, enter SSH password once to authenticate)${colors.reset}\n`);
  }

  let foundMap;
  try {
    if (isLocal) {
      foundMap = await searchLocalFiles(sourceDir, missingImages);
    } else {
      foundMap = await searchRemoteFiles();
    }
  } catch (err) {
    if (isLocal) {
      console.error(`\n${colors.red}${colors.bold}Error searching local directory ${sourceDir}:${colors.reset}`, err.message);
    } else {
      console.error(`\n${colors.red}${colors.bold}Error connecting to ${remoteHost}:${colors.reset}`, err.message);
    }
    process.exit(1);
  }

  const foundList = [];
  const notFoundList = [];

  for (const item of missingImages) {
    if (foundMap.has(item.targetName)) {
      foundList.push({
        targetName: item.targetName,
        remotePath: foundMap.get(item.targetName),
      });
    } else {
      notFoundList.push(item);
    }
  }

  const locationLabel = isLocal ? 'locally' : `on ${remoteHost}`;
  console.log(`\n${colors.bold}--- Search Results ---${colors.reset}`);
  console.log(`${colors.green}Found ${locationLabel}:${colors.reset}     ${colors.bold}${foundList.length}${colors.reset} / ${missingImages.length}`);
  if (notFoundList.length > 0) {
    console.log(`${colors.red}Not found ${locationLabel}:${colors.reset} ${colors.bold}${notFoundList.length}${colors.reset}`);
    if (notFoundList.length <= 10) {
      notFoundList.forEach(m => console.log(`  ${colors.dim}x ${m.targetName}${colors.reset}`));
    } else {
      notFoundList.slice(0, 5).forEach(m => console.log(`  ${colors.dim}x ${m.targetName}${colors.reset}`));
      console.log(`  ${colors.dim}... and ${notFoundList.length - 5} more not found${colors.reset}`);
    }
  }

  if (foundList.length === 0) {
    console.log(`\n${colors.yellow}No missing files could be found under ${sourceDir} ${locationLabel}.${colors.reset}`);
    process.exit(0);
  }

  if (isDryRun) {
    console.log(`\n${colors.yellow}${colors.bold}[DRY RUN] Found ${foundList.length} files. Exiting without transfer.${colors.reset}\n`);
    process.exit(0);
  }

  const actionVerb = isLocal ? 'Copying' : 'Transferring';
  console.log(`\n${colors.bold}${colors.cyan}${actionVerb} ${foundList.length} files via rsync to ${targetDir}...${colors.reset}\n`);

  const filePaths = foundList.map(f => f.remotePath);
  const BATCH_SIZE = 20;
  let completed = 0;

  for (let i = 0; i < filePaths.length; i += BATCH_SIZE) {
    const batch = filePaths.slice(i, i + BATCH_SIZE);
    const batchNum = Math.floor(i / BATCH_SIZE) + 1;
    const totalBatches = Math.ceil(filePaths.length / BATCH_SIZE);

    const transferWord = isLocal ? 'Copying' : 'Downloading';
    console.log(`${colors.cyan}[Batch ${batchNum}/${totalBatches}] ${transferWord} ${batch.length} files...${colors.reset}`);

    let rsyncArgs;
    if (isLocal) {
      rsyncArgs = [
        '-avP',
        ...batch,
        `${targetDir}/`,
      ];
    } else {
      const remoteArgs = batch.map(p => `${remoteHost}:${p}`);
      rsyncArgs = [
        '-avP',
        '-s',
        '-e', `ssh -o ControlPath=${controlSocketPath}`,
        ...remoteArgs,
        `${targetDir}/`,
      ];
    }

    const rsyncCode = await new Promise(resolve => {
      const child = spawn('rsync', rsyncArgs, {
        stdio: 'inherit',
      });
      child.on('close', code => resolve(code));
      child.on('error', err => {
        console.error(`${colors.red}rsync error:${colors.reset}`, err.message);
        resolve(1);
      });
    });

    if (rsyncCode !== 0) {
      console.warn(`${colors.yellow}Warning: rsync batch exited with code ${rsyncCode}. Continuing with remaining batches...${colors.reset}`);
    } else {
      completed += batch.length;
    }
  }

  console.log(`\n${colors.green}${colors.bold}✔ Transfer completed! Successfully synced ${completed} / ${foundList.length} files.${colors.reset}\n`);
}

run().catch(err => {
  console.error(`\n${colors.red}${colors.bold}Unexpected Error:${colors.reset}`, err);
  process.exit(1);
});
