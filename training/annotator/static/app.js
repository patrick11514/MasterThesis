// Minimalist FITS Annotator Frontend Logic with Polygon & Streak Line Support
const state = {
  currentDir: "../TRAINING_FILES",
  files: [],
  currentIndex: -1,
  currentFile: null,
  image: null,
  imageLoaded: false,
  origWidth: 0,
  origHeight: 0,
  previewScale: 1.0,

  // Pan and Zoom
  zoom: 1.0,
  panX: 0,
  panY: 0,
  isPanning: false,
  panStartX: 0,
  panStartY: 0,

  // Drawing Tools: 'box', 'polygon', 'line'
  activeTool: "box",
  isDrawing: false,
  drawStartX: 0,
  drawStartY: 0,
  currentDrawEnd: null,
  polygonPoints: [], // [{x, y}, ...]
  cursorPt: null,
  activeClass: "satellite_streak",
  boxes: [],
  selectedBoxId: null,
  isDraggingHandle: false,
  dragHandleType: null, // "p1", "p2", "move"
  dragBoxId: null,
  dragStartMouse: null,
  dragOriginalBox: null,
  globalStarTrailing: false,
  globalCloud: false,
  isClean: true,

  // Settings
  filterUntagged: false,
  showGrid: false,
  shadowsClipping: -2.8,
  targetBg: 0.25,
  stretchMode: "stf",
  rgbLinked: false,
};

const CLASS_COLORS = {
  satellite_streak: "#e53e3e",
  airplane: "#ed8936",
  cloud: "#4299e1",
  obstruction: "#9f7aea",
  star_trail: "#ecc94b",
};

const canvas = document.getElementById("viewport");
const ctx = canvas.getContext("2d");
const container = document.getElementById("canvas-container");

function init() {
  window.addEventListener("resize", resizeCanvas);
  resizeCanvas();

  // Directory loading
  document.getElementById("btn-load-dir").addEventListener("click", loadDirectory);
  document.getElementById("dir-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadDirectory();
  });

  // Navigation
  document.getElementById("btn-prev").addEventListener("click", prevFile);
  document.getElementById("btn-next").addEventListener("click", nextFile);
  const btnNextUntagged = document.getElementById("btn-next-untagged");
  if (btnNextUntagged) {
    btnNextUntagged.addEventListener("click", nextUntaggedFile);
  }
  document.getElementById("btn-save").addEventListener("click", saveAnnotations);
  const btnClearLabels = document.getElementById("btn-clear-labels");
  if (btnClearLabels) {
    btnClearLabels.addEventListener("click", clearAnnotations);
  }

  // Filter untagged toggle
  const chkFilterUntagged = document.getElementById("chk-filter-untagged");
  if (chkFilterUntagged) {
    chkFilterUntagged.checked = state.filterUntagged;
    chkFilterUntagged.addEventListener("change", (e) => {
      state.filterUntagged = e.target.checked;
      renderFileList();
      // If current file is annotated and filter turned on, jump to next untagged
      if (state.filterUntagged && state.currentFile && state.currentFile.annotated) {
        nextUntaggedFile();
      }
    });
  }

  // Tool buttons (Box, Polygon, Streak Line)
  document.querySelectorAll("#tool-buttons .btn-tool").forEach((btn) => {
    btn.addEventListener("click", () => {
      setTool(btn.dataset.tool);
    });
  });

  // Full Frame button
  const btnFull = document.getElementById("btn-full-frame");
  if (btnFull) {
    btnFull.addEventListener("click", selectFullFrame);
  }

  // Zoom / View buttons
  const btnZoomIn = document.getElementById("btn-zoom-in");
  const btnZoomOut = document.getElementById("btn-zoom-out");
  const btnZoom100 = document.getElementById("btn-zoom-100");
  const btnCenterView = document.getElementById("btn-center-view");
  if (btnZoomIn) btnZoomIn.addEventListener("click", zoomIn);
  if (btnZoomOut) btnZoomOut.addEventListener("click", zoomOut);
  if (btnZoom100) btnZoom100.addEventListener("click", zoom100);
  if (btnCenterView) btnCenterView.addEventListener("click", resetView);

  // Class Buttons
  document.querySelectorAll(".btn-class").forEach((btn) => {
    btn.addEventListener("click", () => {
      setActiveClass(btn.dataset.class);
    });
  });

  // Toggles
  const chkGlobalCloud = document.getElementById("chk-global-cloud");
  if (chkGlobalCloud) {
    chkGlobalCloud.addEventListener("change", (e) => {
      state.globalCloud = e.target.checked;
      updateCleanStatus();
    });
  }

  const chkGlobal = document.getElementById("chk-global-star-trail");
  chkGlobal.addEventListener("change", (e) => {
    state.globalStarTrailing = e.target.checked;
    updateCleanStatus();
  });

  const chkClean = document.getElementById("chk-clean-sky");
  chkClean.addEventListener("change", (e) => {
    state.isClean = e.target.checked;
    if (state.isClean) {
      state.boxes = [];
      state.globalStarTrailing = false;
      state.globalCloud = false;
      chkGlobal.checked = false;
      if (chkGlobalCloud) chkGlobalCloud.checked = false;
      render();
    }
  });

  const chkGrid = document.getElementById("chk-grid");
  chkGrid.addEventListener("change", (e) => {
    state.showGrid = e.target.checked;
    render();
  });

  // Stretch Mode Buttons
  document.querySelectorAll("#stretch-modes .btn-mode").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.stretchMode = btn.dataset.mode;
      document.querySelectorAll("#stretch-modes .btn-mode").forEach((b) => {
        b.classList.toggle("active", b.dataset.mode === state.stretchMode);
      });
      if (state.currentFile) loadFilePreview(state.currentFile);
    });
  });

  // Stretch Sliders
  const sliderBright = document.getElementById("slider-brightness");
  sliderBright.addEventListener("input", (e) => {
    state.targetBg = parseFloat(e.target.value);
    document.getElementById("brightness-val").innerText = `${Math.round(state.targetBg * 100)}%`;
  });
  sliderBright.addEventListener("change", () => {
    if (state.currentFile) loadFilePreview(state.currentFile);
  });

  const sliderShadows = document.getElementById("slider-shadows");
  sliderShadows.addEventListener("input", (e) => {
    state.shadowsClipping = parseFloat(e.target.value);
    document.getElementById("shadows-val").innerText = state.shadowsClipping.toFixed(1);
  });
  sliderShadows.addEventListener("change", () => {
    if (state.currentFile) loadFilePreview(state.currentFile);
  });

  const chkLinked = document.getElementById("chk-linked-rgb");
  chkLinked.checked = state.rgbLinked;
  chkLinked.addEventListener("change", (e) => {
    state.rgbLinked = e.target.checked;
    if (state.currentFile) loadFilePreview(state.currentFile);
  });

  // Reset STF
  document.getElementById("btn-reset-stretch").addEventListener("click", () => {
    state.targetBg = 0.25;
    state.shadowsClipping = -2.8;
    state.stretchMode = "stf";
    state.rgbLinked = false;
    chkLinked.checked = false;
    sliderBright.value = "0.25";
    sliderShadows.value = "-2.8";
    document.getElementById("brightness-val").innerText = "25%";
    document.getElementById("shadows-val").innerText = "-2.8";
    document.querySelectorAll("#stretch-modes .btn-mode").forEach((b) => {
      b.classList.toggle("active", b.dataset.mode === "stf");
    });
    if (state.currentFile) loadFilePreview(state.currentFile);
  });

  // Canvas Mouse Events
  canvas.addEventListener("mousedown", onMouseDown);
  canvas.addEventListener("mousemove", onMouseMove);
  canvas.addEventListener("mouseup", onMouseUp);
  canvas.addEventListener("dblclick", onDoubleClick);
  canvas.addEventListener("wheel", onWheel, { passive: false });

  // Global Hotkeys
  window.addEventListener("keydown", onKeyDown);

  // Set initial tool
  setTool("box");

  // Initial load
  loadDirectory();
}

function resizeCanvas() {
  canvas.width = container.clientWidth;
  canvas.height = container.clientHeight;
  render();
}

function setTool(tool) {
  // If leaving polygon tool with points in progress, cancel them
  if (state.activeTool === "polygon" && tool !== "polygon") {
    state.polygonPoints = [];
  }
  state.activeTool = tool;
  document.querySelectorAll("#tool-buttons .btn-tool").forEach((b) => {
    b.classList.toggle("active", b.dataset.tool === tool);
  });

  if (tool === "polygon") {
    setStatus("Tool: Polygon / Freeform Shape | Click N points on canvas to draw shape. Double-click or click start point to close. Esc to cancel.");
  } else if (tool === "line") {
    setStatus("Tool: Streak Line | Click and drag along straight satellite or airplane streak.");
  } else {
    setStatus("Tool: Box | Click and drag rectangle to outline defect area.");
  }
  render();
}

function setActiveClass(cls) {
  state.activeClass = cls;
  document.querySelectorAll(".btn-class").forEach((b) => {
    b.classList.toggle("active", b.dataset.class === cls);
  });
  if (state.selectedBoxId) {
    const b = state.boxes.find((x) => x.id === state.selectedBoxId);
    if (b) {
      b.label = cls;
      render();
    }
  }
}

function selectFullFrame() {
  if (!state.imageLoaded || !state.currentFile) return;
  const newBox = {
    id: "full_" + Date.now(),
    type: "box",
    label: state.activeClass,
    x: 0,
    y: 0,
    width: state.origWidth,
    height: state.origHeight,
  };
  state.boxes.push(newBox);
  state.selectedBoxId = newBox.id;
  updateCleanStatus();
  setStatus(`Marked entire frame as ${state.activeClass.replace("_", " ")}`);
  render();
}

function zoomIn() {
  zoomBy(1.25);
}

function zoomOut() {
  zoomBy(0.8);
}

function zoom100() {
  if (!state.imageLoaded) return;
  state.zoom = 1.0;
  state.panX = (canvas.width - state.image.width) / 2;
  state.panY = (canvas.height - state.image.height) / 2;
  updateZoomDisplay();
  render();
}

function zoomBy(factor) {
  if (!state.imageLoaded) return;
  const newZoom = Math.max(0.05, Math.min(20.0, state.zoom * factor));
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;
  state.panX = cx - (cx - state.panX) * (newZoom / state.zoom);
  state.panY = cy - (cy - state.panY) * (newZoom / state.zoom);
  state.zoom = newZoom;
  updateZoomDisplay();
  render();
}

function updateZoomDisplay() {
  const el = document.getElementById("zoom-level-text");
  if (el) el.innerText = `${Math.round(state.zoom * 100)}%`;
}

async function loadDirectory() {
  const dir = document.getElementById("dir-input").value.trim();
  setStatus("Loading files...");
  try {
    const res = await fetch(`/api/files?dir_path=${encodeURIComponent(dir)}`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    state.currentDir = data.directory;
    state.files = data.files;
    document.getElementById("file-count").innerText = state.files.length;

    renderFileList();
    if (state.files.length > 0) {
      loadFile(0);
    } else {
      setStatus("No FITS files found in directory.");
    }
  } catch (err) {
    setStatus("Error: " + err.message);
  }
}

function getVisibleFileIndices() {
  const indices = [];
  state.files.forEach((f, idx) => {
    if (!state.filterUntagged || !f.annotated) {
      indices.push(idx);
    }
  });
  return indices;
}

function renderFileList() {
  const list = document.getElementById("file-list");
  list.innerHTML = "";

  const untaggedCount = state.files.filter((f) => !f.annotated).length;
  const countEl = document.getElementById("file-count");
  if (countEl) {
    countEl.innerText = state.filterUntagged ? `${untaggedCount} / ${state.files.length}` : `${state.files.length}`;
  }

  state.files.forEach((f, idx) => {
    if (state.filterUntagged && f.annotated) {
      return;
    }
    const li = document.createElement("li");
    li.innerText = f.name;
    if (f.annotated) li.classList.add("annotated");
    if (idx === state.currentIndex) li.classList.add("active");
    li.addEventListener("click", () => loadFile(idx));
    list.appendChild(li);
  });
}

async function loadFile(index) {
  if (index < 0 || index >= state.files.length) return;
  state.currentIndex = index;
  state.currentFile = state.files[index];
  state.polygonPoints = [];
  renderFileList();

  document.getElementById("current-filename").innerText = state.currentFile.name;
  setStatus(`Loading ${state.currentFile.name}...`);

  await loadFilePreview(state.currentFile);
  await loadAnnotations(state.currentFile);
  resetView();
}

async function loadFilePreview(file) {
  try {
    const url = `/api/preview?path=${encodeURIComponent(file.path)}&shadows=${state.shadowsClipping}&target_bg=${state.targetBg}&mode=${state.stretchMode}&linked=${state.rgbLinked}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to load preview");

    state.origWidth = parseInt(res.headers.get("X-Original-Width") || "0", 10);
    state.origHeight = parseInt(res.headers.get("X-Original-Height") || "0", 10);
    state.previewScale = parseFloat(res.headers.get("X-Preview-Scale") || "1.0");

    document.getElementById("image-dimensions").innerText = `(${state.origWidth} x ${state.origHeight})`;

    const blob = await res.blob();
    const img = new Image();
    img.onload = () => {
      state.image = img;
      state.imageLoaded = true;
      setStatus(`Loaded ${file.name}`);
      render();
    };
    img.src = URL.createObjectURL(blob);
  } catch (err) {
    setStatus("Error loading image: " + err.message);
  }
}

async function loadAnnotations(file) {
  try {
    const res = await fetch(`/api/annotations?path=${encodeURIComponent(file.path)}`);
    const data = await res.json();
    state.boxes = data.boxes || [];
    state.globalStarTrailing = data.global_star_trailing || false;
    state.globalCloud = data.global_cloud || false;
    state.isClean = data.is_clean !== undefined ? data.is_clean : (state.boxes.length === 0 && !state.globalStarTrailing && !state.globalCloud);

    document.getElementById("chk-global-star-trail").checked = state.globalStarTrailing;
    const chkGlobalCloud = document.getElementById("chk-global-cloud");
    if (chkGlobalCloud) chkGlobalCloud.checked = state.globalCloud;
    document.getElementById("chk-clean-sky").checked = state.isClean;
    updateCleanStatus();
    render();
  } catch (err) {
    state.boxes = [];
  }
}

async function saveAnnotations() {
  if (!state.currentFile) return;
  setStatus("Saving annotations...");
  try {
    const payload = {
      file_name: state.currentFile.name,
      width: state.origWidth,
      height: state.origHeight,
      global_star_trailing: state.globalStarTrailing,
      global_cloud: state.globalCloud,
      is_clean: state.isClean,
      boxes: state.boxes,
    };
    const res = await fetch(`/api/annotations?path=${encodeURIComponent(state.currentFile.path)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("Failed to save");
    state.currentFile.annotated = true;
    renderFileList();
    setStatus(`Saved annotations (${state.boxes.length} items) for ${state.currentFile.name}`);
  } catch (err) {
    setStatus("Error saving: " + err.message);
  }
}

async function clearAnnotations() {
  if (!state.currentFile) return;
  if (!confirm(`Are you sure you want to clear all annotations for ${state.currentFile.name}?`)) {
    return;
  }
  setStatus("Clearing annotations...");
  try {
    const res = await fetch(`/api/annotations?path=${encodeURIComponent(state.currentFile.path)}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error("Failed to delete annotations");

    state.boxes = [];
    state.globalStarTrailing = false;
    state.globalCloud = false;
    state.isClean = true;
    state.selectedBoxId = null;

    const chkGlobalStar = document.getElementById("chk-global-star-trail");
    if (chkGlobalStar) chkGlobalStar.checked = false;
    const chkGlobalCloud = document.getElementById("chk-global-cloud");
    if (chkGlobalCloud) chkGlobalCloud.checked = false;
    const chkClean = document.getElementById("chk-clean-sky");
    if (chkClean) chkClean.checked = true;

    state.currentFile.annotated = false;
    renderFileList();
    render();
    setStatus(`Cleared all annotations for ${state.currentFile.name}`);
  } catch (err) {
    setStatus("Error clearing annotations: " + err.message);
  }
}

function prevFile() {
  const visible = getVisibleFileIndices();
  if (visible.length === 0) return;
  const currentPos = visible.indexOf(state.currentIndex);
  if (currentPos > 0) {
    saveAnnotations();
    loadFile(visible[currentPos - 1]);
  } else if (currentPos === -1 && visible.length > 0) {
    const preceding = visible.filter((i) => i < state.currentIndex);
    if (preceding.length > 0) {
      saveAnnotations();
      loadFile(preceding[preceding.length - 1]);
    }
  }
}

function nextFile() {
  const visible = getVisibleFileIndices();
  if (visible.length === 0) return;
  const currentPos = visible.indexOf(state.currentIndex);
  if (currentPos >= 0 && currentPos < visible.length - 1) {
    saveAnnotations();
    loadFile(visible[currentPos + 1]);
  } else if (currentPos === -1) {
    const following = visible.filter((i) => i > state.currentIndex);
    if (following.length > 0) {
      saveAnnotations();
      loadFile(following[0]);
    } else if (visible.length > 0) {
      saveAnnotations();
      loadFile(visible[0]);
    }
  }
}

function nextUntaggedFile() {
  saveAnnotations();
  for (let i = state.currentIndex + 1; i < state.files.length; i++) {
    if (!state.files[i].annotated) {
      loadFile(i);
      return;
    }
  }
  for (let i = 0; i <= state.currentIndex; i++) {
    if (!state.files[i].annotated) {
      loadFile(i);
      return;
    }
  }
  setStatus("All files in directory are annotated!");
}

function resetView() {
  if (!state.imageLoaded || !state.image) return;
  const padding = 20;
  const availW = canvas.width - padding * 2;
  const availH = canvas.height - padding * 2;

  const scaleX = availW / state.image.width;
  const scaleY = availH / state.image.height;
  state.zoom = Math.min(scaleX, scaleY, 1.0);

  state.panX = (canvas.width - state.image.width * state.zoom) / 2;
  state.panY = (canvas.height - state.image.height * state.zoom) / 2;
  updateZoomDisplay();
  render();
}

function updateCleanStatus() {
  if (state.boxes.length > 0 || state.globalStarTrailing || state.globalCloud) {
    state.isClean = false;
  } else {
    state.isClean = true;
  }
  document.getElementById("chk-clean-sky").checked = state.isClean;
  document.getElementById("box-count").innerText = `Annotations: ${state.boxes.length}`;
}

// Canvas Coordinate Helpers
function screenToImage(screenX, screenY) {
  if (!state.imageLoaded) return { x: 0, y: 0 };
  const previewX = (screenX - state.panX) / state.zoom;
  const previewY = (screenY - state.panY) / state.zoom;
  const origX = previewX / state.previewScale;
  const origY = previewY / state.previewScale;
  return { x: origX, y: origY };
}

function imageToScreen(origX, origY) {
  const previewX = origX * state.previewScale;
  const previewY = origY * state.previewScale;
  const screenX = previewX * state.zoom + state.panX;
  const screenY = previewY * state.zoom + state.panY;
  return { x: screenX, y: screenY };
}

function hexToRgba(hex, alpha) {
  let c = hex.replace("#", "");
  if (c.length === 3) c = c.split("").map((x) => x + x).join("");
  const r = parseInt(c.substring(0, 2), 16) || 0;
  const g = parseInt(c.substring(2, 4), 16) || 0;
  const b = parseInt(c.substring(4, 6), 16) || 0;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function pointInPolygon(x, y, points) {
  let inside = false;
  const n = points.length;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = points[i][0], yi = points[i][1];
    const xj = points[j][0], yj = points[j][1];
    const intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function distToSegment(px, py, x1, y1, x2, y2) {
  const l2 = (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1);
  if (l2 === 0) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * (x2 - x1)), py - (y1 + t * (y2 - y1)));
}

function findLineHandleAt(x, y, line) {
  const x1 = line.x1 !== undefined ? line.x1 : line.x;
  const y1 = line.y1 !== undefined ? line.y1 : line.y;
  const x2 = line.x2 !== undefined ? line.x2 : line.x + line.width;
  const y2 = line.y2 !== undefined ? line.y2 : line.y + line.height;

  // Handle detection radius in image coordinates
  const handleRadius = Math.max(12, 14 / (state.zoom * state.previewScale));

  if (Math.hypot(x - x1, y - y1) <= handleRadius) {
    return "p1";
  }
  if (Math.hypot(x - x2, y - y2) <= handleRadius) {
    return "p2";
  }
  // Check if near the segment itself
  const d = distToSegment(x, y, x1, y1, x2, y2);
  if (d <= Math.max(8, 12 / (state.zoom * state.previewScale))) {
    return "move";
  }
  return null;
}

function findBoxAt(x, y) {
  for (let i = state.boxes.length - 1; i >= 0; i--) {
    const b = state.boxes[i];
    if (b.type === "polygon" && b.points && b.points.length >= 3) {
      if (pointInPolygon(x, y, b.points)) return b;
    } else if (b.type === "line") {
      const x1 = b.x1 !== undefined ? b.x1 : b.x;
      const y1 = b.y1 !== undefined ? b.y1 : b.y;
      const x2 = b.x2 !== undefined ? b.x2 : b.x + b.width;
      const y2 = b.y2 !== undefined ? b.y2 : b.y + b.height;
      const d = distToSegment(x, y, x1, y1, x2, y2);
      const threshold = 16 / (state.zoom * state.previewScale);
      if (d <= Math.max(10, threshold)) return b;
    } else {
      if (x >= b.x && x <= b.x + b.width && y >= b.y && y <= b.y + b.height) {
        return b;
      }
    }
  }
  return null;
}

function closeAndCommitPolygon() {
  if (state.polygonPoints.length < 3) {
    state.polygonPoints = [];
    render();
    return;
  }
  const xs = state.polygonPoints.map((p) => p.x);
  const ys = state.polygonPoints.map((p) => p.y);
  const minX = Math.round(Math.min(...xs));
  const minY = Math.round(Math.min(...ys));
  const maxX = Math.round(Math.max(...xs));
  const maxY = Math.round(Math.max(...ys));

  const newPoly = {
    id: "poly_" + Date.now(),
    type: "polygon",
    label: state.activeClass,
    x: minX,
    y: minY,
    width: Math.max(maxX - minX, 4),
    height: Math.max(maxY - minY, 4),
    points: state.polygonPoints.map((p) => [Math.round(p.x), Math.round(p.y)]),
  };

  state.boxes.push(newPoly);
  state.selectedBoxId = newPoly.id;
  state.polygonPoints = [];
  updateCleanStatus();
  setStatus(`Created ${state.activeClass.replace("_", " ")} polygon (${newPoly.points.length} vertices)`);
  render();
}

function onMouseDown(e) {
  const rect = canvas.getBoundingClientRect();
  const mouseX = e.clientX - rect.left;
  const mouseY = e.clientY - rect.top;

  // Middle click, space key, or shift+click = Pan
  if (e.button === 1 || e.spaceKey || (e.button === 0 && e.shiftKey)) {
    state.isPanning = true;
    state.panStartX = mouseX - state.panX;
    state.panStartY = mouseY - state.panY;
    return;
  }

  // Left click
  if (e.button === 0) {
    const pt = screenToImage(mouseX, mouseY);

    // If an item is already selected and it's a line, check if user is grabbing a handle or body
    if (state.selectedBoxId && !e.altKey) {
      const selBox = state.boxes.find((b) => b.id === state.selectedBoxId);
      if (selBox && selBox.type === "line") {
        const handleType = findLineHandleAt(pt.x, pt.y, selBox);
        if (handleType) {
          state.isDraggingHandle = true;
          state.dragHandleType = handleType;
          state.dragBoxId = selBox.id;
          state.dragStartMouse = { x: pt.x, y: pt.y };
          state.dragOriginalBox = { ...selBox };
          return;
        }
      }
    }

    // --- POLYGON TOOL ---
    if (state.activeTool === "polygon") {
      // Check if clicking near first point to close
      if (state.polygonPoints.length >= 3) {
        const startScreen = imageToScreen(state.polygonPoints[0].x, state.polygonPoints[0].y);
        const dist = Math.hypot(mouseX - startScreen.x, mouseY - startScreen.y);
        if (dist < 15) {
          closeAndCommitPolygon();
          return;
        }
      }

      // If no points in progress yet, check if clicking existing item to select
      if (state.polygonPoints.length === 0) {
        const clicked = findBoxAt(pt.x, pt.y);
        if (clicked && !e.altKey) {
          state.selectedBoxId = clicked.id;
          setActiveClass(clicked.label);
          render();
          return;
        }
      }

      // Add vertex to polygon
      state.polygonPoints.push(pt);
      state.selectedBoxId = null;
      setStatus(`Polygon: ${state.polygonPoints.length} points placed. Click more, double-click or click first point to close.`);
      render();
      return;
    }

    // --- BOX OR LINE TOOL ---
    const clickedBox = findBoxAt(pt.x, pt.y);
    if (clickedBox && !e.altKey) {
      state.selectedBoxId = clickedBox.id;
      setActiveClass(clickedBox.label);

      // If clicked a line, immediately check if handle/body was grabbed
      if (clickedBox.type === "line") {
        const handleType = findLineHandleAt(pt.x, pt.y, clickedBox);
        if (handleType) {
          state.isDraggingHandle = true;
          state.dragHandleType = handleType;
          state.dragBoxId = clickedBox.id;
          state.dragStartMouse = { x: pt.x, y: pt.y };
          state.dragOriginalBox = { ...clickedBox };
        }
      }

      render();
      return;
    }

    // Start drawing
    state.selectedBoxId = null;
    state.isDrawing = true;
    state.drawStartX = pt.x;
    state.drawStartY = pt.y;
  }
}

function onMouseMove(e) {
  const rect = canvas.getBoundingClientRect();
  const mouseX = e.clientX - rect.left;
  const mouseY = e.clientY - rect.top;

  const pt = screenToImage(mouseX, mouseY);
  state.cursorPt = pt;
  document.getElementById("cursor-pos").innerText = `X: ${Math.round(pt.x)}, Y: ${Math.round(pt.y)}`;

  if (state.isPanning) {
    state.panX = mouseX - state.panStartX;
    state.panY = mouseY - state.panStartY;
    render();
    return;
  }

  // Handle line endpoint/move dragging
  if (state.isDraggingHandle && state.dragBoxId) {
    const box = state.boxes.find((b) => b.id === state.dragBoxId);
    if (box && box.type === "line" && state.dragOriginalBox) {
      const orig = state.dragOriginalBox;
      const dx = pt.x - state.dragStartMouse.x;
      const dy = pt.y - state.dragStartMouse.y;

      let x1 = orig.x1 !== undefined ? orig.x1 : orig.x;
      let y1 = orig.y1 !== undefined ? orig.y1 : orig.y;
      let x2 = orig.x2 !== undefined ? orig.x2 : orig.x + orig.width;
      let y2 = orig.y2 !== undefined ? orig.y2 : orig.y + orig.height;

      if (state.dragHandleType === "p1") {
        x1 = Math.round(orig.x1 + dx);
        y1 = Math.round(orig.y1 + dy);
      } else if (state.dragHandleType === "p2") {
        x2 = Math.round(orig.x2 + dx);
        y2 = Math.round(orig.y2 + dy);
      } else if (state.dragHandleType === "move") {
        x1 = Math.round(orig.x1 + dx);
        y1 = Math.round(orig.y1 + dy);
        x2 = Math.round(orig.x2 + dx);
        y2 = Math.round(orig.y2 + dy);
      }

      box.x1 = x1;
      box.y1 = y1;
      box.x2 = x2;
      box.y2 = y2;
      box.x = Math.min(x1, x2);
      box.y = Math.min(y1, y2);
      box.width = Math.abs(x2 - x1);
      box.height = Math.abs(y2 - y1);

      render();
      return;
    }
  }

  if (state.activeTool === "polygon" && state.polygonPoints.length > 0) {
    render();
    return;
  }

  if (state.isDrawing) {
    state.currentDrawEnd = pt;
    render();
  }
}

function onMouseUp(e) {
  if (state.isPanning) {
    state.isPanning = false;
    return;
  }

  if (state.isDraggingHandle) {
    state.isDraggingHandle = false;
    state.dragHandleType = null;
    state.dragBoxId = null;
    state.dragStartMouse = null;
    state.dragOriginalBox = null;
    render();
    return;
  }

  if (state.isDrawing) {
    state.isDrawing = false;
    const rect = canvas.getBoundingClientRect();
    const pt = screenToImage(e.clientX - rect.left, e.clientY - rect.top);

    if (state.activeTool === "line") {
      const x1 = Math.round(state.drawStartX);
      const y1 = Math.round(state.drawStartY);
      const x2 = Math.round(pt.x);
      const y2 = Math.round(pt.y);
      const dist = Math.hypot(x2 - x1, y2 - y1);
      if (dist > 15) {
        const newLine = {
          id: "l_" + Date.now(),
          type: "line",
          label: state.activeClass,
          x: Math.min(x1, x2),
          y: Math.min(y1, y2),
          width: Math.abs(x2 - x1),
          height: Math.abs(y2 - y1),
          x1: x1,
          y1: y1,
          x2: x2,
          y2: y2,
        };
        state.boxes.push(newLine);
        state.selectedBoxId = newLine.id;
        updateCleanStatus();
      }
    } else if (state.activeTool === "box") {
      const x1 = Math.round(Math.min(state.drawStartX, pt.x));
      const y1 = Math.round(Math.min(state.drawStartY, pt.y));
      const x2 = Math.round(Math.max(state.drawStartX, pt.x));
      const y2 = Math.round(Math.max(state.drawStartY, pt.y));
      const w = x2 - x1;
      const h = y2 - y1;

      if (w > 10 && h > 10) {
        const newBox = {
          id: "b_" + Date.now(),
          type: "box",
          label: state.activeClass,
          x: x1,
          y: y1,
          width: w,
          height: h,
        };
        state.boxes.push(newBox);
        state.selectedBoxId = newBox.id;
        updateCleanStatus();
      }
    }
    state.currentDrawEnd = null;
    render();
  }
}

function onDoubleClick(e) {
  if (state.activeTool === "polygon" && state.polygonPoints.length >= 3) {
    closeAndCommitPolygon();
  }
}

function onWheel(e) {
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const mouseX = e.clientX - rect.left;
  const mouseY = e.clientY - rect.top;

  const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
  const newZoom = Math.max(0.05, Math.min(20.0, state.zoom * zoomFactor));

  // Zoom centered on cursor
  state.panX = mouseX - (mouseX - state.panX) * (newZoom / state.zoom);
  state.panY = mouseY - (mouseY - state.panY) * (newZoom / state.zoom);
  state.zoom = newZoom;

  updateZoomDisplay();
  render();
}

function onKeyDown(e) {
  if (e.target.tagName === "INPUT") return;

  // Tool Selection Hotkeys
  if (e.key === "b" || e.key === "B") setTool("box");
  if (e.key === "p" || e.key === "P") setTool("polygon");
  if (e.key === "l" || e.key === "L") setTool("line");
  if (e.key === "f" || e.key === "F") selectFullFrame();

  // Class Selection Hotkeys
  if (e.key === "1") setActiveClass("satellite_streak");
  if (e.key === "2") setActiveClass("airplane");
  if (e.key === "3") setActiveClass("cloud");
  if (e.key === "4") setActiveClass("obstruction");
  if (e.key === "5") setActiveClass("star_trail");

  // Zoom hotkeys
  if (e.key === "+" || e.key === "=") zoomIn();
  if (e.key === "-") zoomOut();
  if (e.key === "0") resetView();

  // Navigation Hotkeys
  if (e.key === "a" || e.key === "A") prevFile();
  if (e.key === "d" || e.key === "D") nextFile();
  if (e.key === "w" || e.key === "W") nextUntaggedFile();
  if (e.key === "u" || e.key === "U") {
    state.filterUntagged = !state.filterUntagged;
    const chk = document.getElementById("chk-filter-untagged");
    if (chk) chk.checked = state.filterUntagged;
    renderFileList();
    if (state.filterUntagged && state.currentFile && state.currentFile.annotated) {
      nextUntaggedFile();
    }
  }
  if (e.key === "s" || e.key === "S") {
    e.preventDefault();
    saveAnnotations();
  }

  // Polygon Commit
  if (e.key === "Enter") {
    if (state.activeTool === "polygon" && state.polygonPoints.length >= 3) {
      closeAndCommitPolygon();
    }
  }

  // Cancel polygon or delete
  if (e.key === "Escape") {
    if (state.polygonPoints.length > 0) {
      state.polygonPoints = [];
      setStatus("Cancelled polygon shape.");
      render();
    }
  }

  if (e.key === "Delete" || e.key === "Backspace") {
    if (state.polygonPoints.length > 0) {
      state.polygonPoints.pop();
      render();
      return;
    }
    if (state.selectedBoxId) {
      state.boxes = state.boxes.filter((b) => b.id !== state.selectedBoxId);
      state.selectedBoxId = null;
      updateCleanStatus();
      render();
    }
  }
}

function setStatus(msg) {
  document.getElementById("status-text").innerText = msg;
}

// Rendering
function render() {
  ctx.fillStyle = "#111111";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (!state.imageLoaded || !state.image) return;

  ctx.save();
  ctx.translate(state.panX, state.panY);
  ctx.scale(state.zoom, state.zoom);

  // Draw image
  ctx.drawImage(state.image, 0, 0);

  // Draw 512x512 tile grid if toggled
  if (state.showGrid) {
    ctx.strokeStyle = "rgba(255, 255, 255, 0.2)";
    ctx.lineWidth = 1 / state.zoom;
    const tileSize = 512 * state.previewScale;
    for (let gx = 0; gx < state.image.width; gx += tileSize) {
      ctx.beginPath();
      ctx.moveTo(gx, 0);
      ctx.lineTo(gx, state.image.height);
      ctx.stroke();
    }
    for (let gy = 0; gy < state.image.height; gy += tileSize) {
      ctx.beginPath();
      ctx.moveTo(0, gy);
      ctx.lineTo(state.image.width, gy);
      ctx.stroke();
    }
  }

  // Draw existing annotations (boxes, lines, polygons)
  state.boxes.forEach((b) => {
    const isSelected = b.id === state.selectedBoxId;
    const col = CLASS_COLORS[b.label] || "#4299e1";
    const fontSize = Math.max(10, Math.min(14, 12 / state.zoom));
    ctx.font = `${fontSize}px monospace`;
    const labelText = b.label.replace("_", " ");
    const textW = ctx.measureText(labelText).width;

    // --- POLYGON ---
    if (b.type === "polygon" && b.points && b.points.length >= 3) {
      ctx.beginPath();
      const p0 = { x: b.points[0][0] * state.previewScale, y: b.points[0][1] * state.previewScale };
      ctx.moveTo(p0.x, p0.y);
      for (let i = 1; i < b.points.length; i++) {
        ctx.lineTo(b.points[i][0] * state.previewScale, b.points[i][1] * state.previewScale);
      }
      ctx.closePath();

      // Semi-transparent fill
      ctx.fillStyle = isSelected ? "rgba(255, 255, 255, 0.28)" : hexToRgba(col, 0.18);
      ctx.fill();

      // Stroke
      ctx.strokeStyle = col;
      ctx.lineWidth = (isSelected ? 3.0 : 1.8) / state.zoom;
      ctx.stroke();

      // Vertices
      const vr = (isSelected ? 3.5 : 2.5) / state.zoom;
      ctx.fillStyle = col;
      for (let i = 0; i < b.points.length; i++) {
        ctx.beginPath();
        ctx.arc(b.points[i][0] * state.previewScale, b.points[i][1] * state.previewScale, vr, 0, Math.PI * 2);
        ctx.fill();
      }

      // Centroid label badge
      const cX = (b.x + b.width / 2) * state.previewScale;
      const cY = (b.y + b.height / 2) * state.previewScale;
      ctx.fillStyle = col;
      ctx.fillRect(cX - textW / 2 - 3, cY - fontSize / 2 - 2, textW + 6, fontSize + 4);
      ctx.fillStyle = "#ffffff";
      ctx.fillText(labelText, cX - textW / 2, cY + fontSize / 2 - 3);

    // --- STREAK LINE ---
    } else if (b.type === "line") {
      const lx1 = (b.x1 !== undefined ? b.x1 : b.x) * state.previewScale;
      const ly1 = (b.y1 !== undefined ? b.y1 : b.y) * state.previewScale;
      const lx2 = (b.x2 !== undefined ? b.x2 : b.x + b.width) * state.previewScale;
      const ly2 = (b.y2 !== undefined ? b.y2 : b.y + b.height) * state.previewScale;

      ctx.strokeStyle = col;
      ctx.lineWidth = (isSelected ? 3.5 : 2.0) / state.zoom;
      ctx.beginPath();
      ctx.moveTo(lx1, ly1);
      ctx.lineTo(lx2, ly2);
      ctx.stroke();

      // Draw endpoint circles (draggable handles)
      const r = (isSelected ? 6.0 : 3.0) / state.zoom;
      ctx.fillStyle = isSelected ? "#ffffff" : col;
      ctx.strokeStyle = col;
      ctx.lineWidth = (isSelected ? 2.0 : 1.0) / state.zoom;

      ctx.beginPath();
      ctx.arc(lx1, ly1, r, 0, 2 * Math.PI);
      ctx.fill();
      if (isSelected) ctx.stroke();

      ctx.beginPath();
      ctx.arc(lx2, ly2, r, 0, 2 * Math.PI);
      ctx.fill();
      if (isSelected) ctx.stroke();

      const midX = (lx1 + lx2) / 2;
      const midY = (ly1 + ly2) / 2;
      ctx.fillStyle = col;
      ctx.fillRect(midX - textW / 2 - 3, midY - fontSize / 2 - 2, textW + 6, fontSize + 4);
      ctx.fillStyle = "#ffffff";
      ctx.fillText(labelText, midX - textW / 2, midY + fontSize / 2 - 3);

    // --- BOX ---
    } else {
      const px = b.x * state.previewScale;
      const py = b.y * state.previewScale;
      const pw = b.width * state.previewScale;
      const ph = b.height * state.previewScale;

      ctx.fillStyle = isSelected ? "rgba(255, 255, 255, 0.18)" : hexToRgba(col, 0.12);
      ctx.fillRect(px, py, pw, ph);

      ctx.strokeStyle = col;
      ctx.lineWidth = (isSelected ? 2.5 : 1.5) / state.zoom;
      ctx.strokeRect(px, py, pw, ph);

      ctx.fillStyle = col;
      ctx.fillRect(px, py - fontSize - 2, textW + 6, fontSize + 4);
      ctx.fillStyle = "#ffffff";
      ctx.fillText(labelText, px + 3, py - 2);
    }
  });

  // Draw in-progress Polygon
  if (state.activeTool === "polygon" && state.polygonPoints.length > 0) {
    const col = CLASS_COLORS[state.activeClass] || "#4299e1";
    ctx.strokeStyle = col;
    ctx.lineWidth = 2.0 / state.zoom;

    // Draw lines between placed vertices
    ctx.beginPath();
    const p0 = { x: state.polygonPoints[0].x * state.previewScale, y: state.polygonPoints[0].y * state.previewScale };
    ctx.moveTo(p0.x, p0.y);
    for (let i = 1; i < state.polygonPoints.length; i++) {
      ctx.lineTo(state.polygonPoints[i].x * state.previewScale, state.polygonPoints[i].y * state.previewScale);
    }

    // Dashed line to current mouse position
    if (state.cursorPt) {
      ctx.stroke();
      ctx.beginPath();
      const lastP = state.polygonPoints[state.polygonPoints.length - 1];
      ctx.moveTo(lastP.x * state.previewScale, lastP.y * state.previewScale);
      ctx.lineTo(state.cursorPt.x * state.previewScale, state.cursorPt.y * state.previewScale);
      ctx.setLineDash([4 / state.zoom, 4 / state.zoom]);
      ctx.stroke();
      ctx.setLineDash([]);
    } else {
      ctx.stroke();
    }

    // Draw placed vertices
    const vr = 4.0 / state.zoom;
    for (let i = 0; i < state.polygonPoints.length; i++) {
      ctx.fillStyle = i === 0 ? "#48bb78" : col; // First point highlighted in green
      ctx.beginPath();
      ctx.arc(state.polygonPoints[i].x * state.previewScale, state.polygonPoints[i].y * state.previewScale, vr, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1 / state.zoom;
      ctx.stroke();
    }

    // Check if cursor is close to start point (indicating close action)
    if (state.polygonPoints.length >= 3 && state.cursorPt) {
      const dStart = Math.hypot(
        (state.cursorPt.x - state.polygonPoints[0].x) * state.previewScale,
        (state.cursorPt.y - state.polygonPoints[0].y) * state.previewScale
      );
      if (dStart < 15) {
        ctx.strokeStyle = "#48bb78";
        ctx.lineWidth = 2.5 / state.zoom;
        ctx.beginPath();
        ctx.arc(p0.x, p0.y, 8 / state.zoom, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
  }

  // Draw in-progress Box or Line
  if (state.isDrawing && state.currentDrawEnd) {
    ctx.strokeStyle = CLASS_COLORS[state.activeClass] || "#ffffff";
    ctx.lineWidth = 1.5 / state.zoom;
    ctx.setLineDash([4 / state.zoom, 4 / state.zoom]);

    if (state.activeTool === "line") {
      const lx1 = state.drawStartX * state.previewScale;
      const ly1 = state.drawStartY * state.previewScale;
      const lx2 = state.currentDrawEnd.x * state.previewScale;
      const ly2 = state.currentDrawEnd.y * state.previewScale;
      ctx.beginPath();
      ctx.moveTo(lx1, ly1);
      ctx.lineTo(lx2, ly2);
      ctx.stroke();
    } else if (state.activeTool === "box") {
      const x1 = Math.min(state.drawStartX, state.currentDrawEnd.x) * state.previewScale;
      const y1 = Math.min(state.drawStartY, state.currentDrawEnd.y) * state.previewScale;
      const w = Math.abs(state.currentDrawEnd.x - state.drawStartX) * state.previewScale;
      const h = Math.abs(state.currentDrawEnd.y - state.drawStartY) * state.previewScale;
      ctx.strokeRect(x1, y1, w, h);
    }

    ctx.setLineDash([]);
  }

  ctx.restore();
}

window.onload = init;
