#!/usr/bin/env node

/**
 * sync_local.js - Sync raw astronomical images (FITS/TIFF) from remote Proxmox storage
 *
 * Scans local defect annotation files (.json / .txt) in the target directory (e.g. TRAINING_FILES
 * or test_fits), identifies which raw image frames are missing locally, connects to Proxmox over SSH,
 * locates them inside /mnt/HDD/ASTRO, and downloads them using rsync.
 *
 * Usage:
 *   node scripts/sync_local.js [target_folder] [options]
 *
 * Options:
 *   --host <host>        SSH host alias or IP (default: proxmox)
 *   --remote-dir <path>  Remote search directory (default: /mnt/HDD/ASTRO)
 *   --dry-run            Show missing and remote-found files without transferring
 *   --help, -h           Show help message
 */

const fs = require('fs');
const path = require('path');
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
${colors.bold}${colors.cyan}AstroGrader Remote FITS Sync Tool${colors.reset}

${colors.bold}Usage:${colors.reset}
  node sync_local.js [target_dir] [options]
  ./sync_local.sh [target_dir] [options]

${colors.bold}Arguments:${colors.reset}
  target_dir           Local directory containing annotations (default: TRAINING_FILES or .)

${colors.bold}Options:${colors.reset}
  --host <name>        SSH remote host from ~/.ssh/config or IP (default: proxmox)
  --remote-dir <path>  Remote search directory on Proxmox (default: /mnt/HDD/ASTRO)
  --dry-run            Scan and locate files without downloading
  --help, -h           Show this help message

${colors.bold}Examples:${colors.reset}
  node scripts/sync_local.js
  node scripts/sync_local.js TRAINING_FILES
  node scripts/sync_local.js test_fits --dry-run
  node scripts/sync_local.js --host proxmox --remote-dir /mnt/HDD/ASTRO
`);
}

// Parse command line arguments
const args = process.argv.slice(2);
let targetDirArg = null;
let remoteHost = process.env.REMOTE_HOST || 'proxmox';
let remoteDir = process.env.REMOTE_DIR || '/mnt/HDD/ASTRO';
let isDryRun = false;

for (let i = 0; i < args.length; i++) {
  const arg = args[i];
  if (arg === '--help' || arg === '-h') {
    printHelp();
    process.exit(0);
  } else if (arg === '--dry-run') {
    isDryRun = true;
  } else if (arg === '--host') {
    remoteHost = args[++i];
  } else if (arg === '--remote-dir') {
    remoteDir = args[++i];
  } else if (!arg.startsWith('-') && !targetDirArg) {
    targetDirArg = arg;
  }
}

// Resolve target local directory
function resolveTargetDirectory(arg) {
  if (arg) {
    const resolved = path.resolve(process.cwd(), arg);
    if (fs.existsSync(resolved) && fs.statSync(resolved).isDirectory()) {
      return resolved;
    }
    console.error(`${colors.red}Error: Specified directory does not exist: ${resolved}${colors.reset}`);
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
console.log(`${colors.bold}${colors.cyan}=== AstroGrader Local Sync Tool ===${colors.reset}`);
console.log(`${colors.dim}Target directory:${colors.reset} ${colors.bold}${targetDir}${colors.reset}`);
console.log(`${colors.dim}Remote host:${colors.reset}      ${colors.bold}${remoteHost}${colors.reset}`);
console.log(`${colors.dim}Remote search dir:${colors.reset} ${colors.bold}${remoteDir}${colors.reset}`);
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
console.log(`${colors.green}Already present locally:${colors.reset} ${colors.bold}${presentImages.length}${colors.reset}`);
console.log(`${colors.yellow}Missing locally:${colors.reset}         ${colors.bold}${missingImages.length}${colors.reset}`);

if (missingImages.length === 0) {
  console.log(`\n${colors.green}${colors.bold}✔ All corresponding image frames already exist locally! Nothing to sync.${colors.reset}\n`);
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

// Setup persistent SSH ControlMaster socket
const controlSocketPath = `/tmp/ssh_mux_astro_${process.pid}_%h_%p_%r`;
const sshControlArgs = [
  '-o', 'ControlMaster=auto',
  '-o', `ControlPath=${controlSocketPath}`,
  '-o', 'ControlPersist=10m',
  '-o', 'ConnectTimeout=15',
];

// Clean up socket on process exit
function cleanupSocket() {
  try {
    spawnSync('ssh', ['-O', 'exit', '-o', `ControlPath=${controlSocketPath}`, remoteHost], {
      stdio: 'ignore',
    });
  } catch (e) {}
}
process.on('exit', cleanupSocket);
process.on('SIGINT', () => {
  cleanupSocket();
  process.exit(130);
});

// Build remote python script to locate target files on Proxmox
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
        sys.stderr.write(f"\rSearching Proxmox storage... found {len(found)}/{total_targets} files (scanned {scanned_dirs} directories)")
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

sys.stderr.write(f"\rSearch completed! Found {len(found)}/{total_targets} files in {scanned_dirs} directories.\n")
sys.stderr.flush()

for target, full_path in found.items():
    print(f"{target}\\t{full_path}")
`;

console.log(`${colors.cyan}Connecting to ${remoteHost} and searching ${remoteDir}...${colors.reset}`);
console.log(`${colors.dim}(If prompted, enter SSH password once to authenticate)${colors.reset}\n`);

// Query remote host via SSH
async function searchRemoteFiles() {
  return new Promise((resolve, reject) => {
    const inputLines = missingImages.map(m => m.targetName).join('\n') + '\n';

    // Check if remote has find_astro_files.py installed in PATH or ~/find_astro_files.py, else use inline base64 python
    const b64Script = Buffer.from(remoteFinderScript).toString('base64');
    const remotePyCommand = `if command -v find_astro_files.py >/dev/null 2>&1; then find_astro_files.py --dir ${JSON.stringify(remoteDir)}; elif [ -f ~/find_astro_files.py ]; then python3 ~/find_astro_files.py --dir ${JSON.stringify(remoteDir)}; else python3 -c "import base64; exec(base64.b64decode('${b64Script}').decode('utf-8'))" ${JSON.stringify(remoteDir)}; fi`;

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
  let foundMap;
  try {
    foundMap = await searchRemoteFiles();
  } catch (err) {
    console.error(`\n${colors.red}${colors.bold}Error connecting to ${remoteHost}:${colors.reset}`, err.message);
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

  console.log(`\n${colors.bold}--- Search Results ---${colors.reset}`);
  console.log(`${colors.green}Found on Proxmox:${colors.reset}     ${colors.bold}${foundList.length}${colors.reset} / ${missingImages.length}`);
  if (notFoundList.length > 0) {
    console.log(`${colors.red}Not found on Proxmox:${colors.reset} ${colors.bold}${notFoundList.length}${colors.reset}`);
    if (notFoundList.length <= 10) {
      notFoundList.forEach(m => console.log(`  ${colors.dim}x ${m.targetName}${colors.reset}`));
    } else {
      notFoundList.slice(0, 5).forEach(m => console.log(`  ${colors.dim}x ${m.targetName}${colors.reset}`));
      console.log(`  ${colors.dim}... and ${notFoundList.length - 5} more not found${colors.reset}`);
    }
  }

  if (foundList.length === 0) {
    console.log(`\n${colors.yellow}No missing files could be found under ${remoteDir} on ${remoteHost}.${colors.reset}`);
    process.exit(0);
  }

  if (isDryRun) {
    console.log(`\n${colors.yellow}${colors.bold}[DRY RUN] Found ${foundList.length} files. Exiting without transfer.${colors.reset}\n`);
    process.exit(0);
  }

  console.log(`\n${colors.bold}${colors.cyan}Transferring ${foundList.length} files via rsync to ${targetDir}...${colors.reset}\n`);

  // Batch transfer using rsync
  // Since files might come from different subdirectories in /mnt/HDD/ASTRO,
  // we can transfer each batch cleanly.
  const remotePaths = foundList.map(f => f.remotePath);

  // Group into batches of 20 files to avoid command length limits
  const BATCH_SIZE = 20;
  let completed = 0;

  for (let i = 0; i < remotePaths.length; i += BATCH_SIZE) {
    const batch = remotePaths.slice(i, i + BATCH_SIZE);
    const batchNum = Math.floor(i / BATCH_SIZE) + 1;
    const totalBatches = Math.ceil(remotePaths.length / BATCH_SIZE);

    console.log(`${colors.cyan}[Batch ${batchNum}/${totalBatches}] Downloading ${batch.length} files...${colors.reset}`);

    // Each remote file as a separate remote argument (without extra literal quotes, using -s for safe spaces)
    const remoteArgs = batch.map(p => `${remoteHost}:${p}`);
    const rsyncArgs = [
      '-avP',
      '-s',
      '-e', `ssh -o ControlPath=${controlSocketPath}`,
      ...remoteArgs,
      `${targetDir}/`,
    ];

    const rsyncCode = await new Promise(resolve => {
      const child = spawn('rsync', rsyncArgs, {
        stdio: 'inherit',
      });
      child.on('close', code => resolve(code));
      child.on('error', () => resolve(1));
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
