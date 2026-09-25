// Minimalist FITS Annotator Frontend Logic
const state = {
  currentDir: "../test_fits",
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

  // Box Drawing & Selection
  isDrawing: false,
  drawStartX: 0,
  drawStartY: 0,
  activeClass: "satellite_streak",
  boxes: [],
  selectedBoxId: null,
  globalStarTrailing: false,
  isClean: true,

  // Settings
  showGrid: false,
  shadowsClipping: -2.8,
  targetBg: 0.25,
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
  document.getElementById("btn-save").addEventListener("click", saveAnnotations);
  document.getElementById("btn-reset-view").addEventListener("click", resetView);

  // Class Buttons
  document.querySelectorAll(".btn-class").forEach((btn) => {
    btn.addEventListener("click", () => {
      setActiveClass(btn.dataset.class);
    });
  });

  // Toggles
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
      chkGlobal.checked = false;
      render();
    }
  });

  const chkGrid = document.getElementById("chk-grid");
  chkGrid.addEventListener("change", (e) => {
    state.showGrid = e.target.checked;
    render();
  });

  // Stretch Slider
  const slider = document.getElementById("slider-stretch");
  slider.addEventListener("input", (e) => {
    state.shadowsClipping = parseFloat(e.target.value);
    document.getElementById("stretch-val").innerText = state.shadowsClipping.toFixed(1);
  });
  slider.addEventListener("change", () => {
    if (state.currentFile) loadFilePreview(state.currentFile);
  });

  // Canvas Mouse Events
  canvas.addEventListener("mousedown", onMouseDown);
  canvas.addEventListener("mousemove", onMouseMove);
  canvas.addEventListener("mouseup", onMouseUp);
  canvas.addEventListener("wheel", onWheel, { passive: false });

  // Global Hotkeys
  window.addEventListener("keydown", onKeyDown);

  // Initial load
  loadDirectory();
}

function resizeCanvas() {
  canvas.width = container.clientWidth;
  canvas.height = container.clientHeight;
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

function renderFileList() {
  const list = document.getElementById("file-list");
  list.innerHTML = "";
  state.files.forEach((f, idx) => {
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
  renderFileList();

  document.getElementById("current-filename").innerText = state.currentFile.name;
  setStatus(`Loading ${state.currentFile.name}...`);

  await loadFilePreview(state.currentFile);
  await loadAnnotations(state.currentFile);
  resetView();
}

async function loadFilePreview(file) {
  try {
    const url = `/api/preview?path=${encodeURIComponent(file.path)}&shadows=${state.shadowsClipping}&target_bg=${state.targetBg}`;
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
    state.isClean = data.is_clean !== undefined ? data.is_clean : state.boxes.length === 0;

    document.getElementById("chk-global-star-trail").checked = state.globalStarTrailing;
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
    setStatus(`Saved annotations (${state.boxes.length} boxes) for ${state.currentFile.name}`);
  } catch (err) {
    setStatus("Error saving: " + err.message);
  }
}

function prevFile() {
  if (state.currentIndex > 0) {
    saveAnnotations();
    loadFile(state.currentIndex - 1);
  }
}

function nextFile() {
  if (state.currentIndex < state.files.length - 1) {
    saveAnnotations();
    loadFile(state.currentIndex + 1);
  }
}

function resetView() {
  if (!state.imageLoaded) return;
  const padding = 20;
  const availW = canvas.width - padding * 2;
  const availH = canvas.height - padding * 2;

  const scaleX = availW / state.image.width;
  const scaleY = availH / state.image.height;
  state.zoom = Math.min(scaleX, scaleY, 1.0);

  state.panX = (canvas.width - state.image.width * state.zoom) / 2;
  state.panY = (canvas.height - state.image.height * state.zoom) / 2;
  render();
}

function updateCleanStatus() {
  if (state.boxes.length > 0 || state.globalStarTrailing) {
    state.isClean = false;
  } else {
    state.isClean = true;
  }
  document.getElementById("chk-clean-sky").checked = state.isClean;
  document.getElementById("box-count").innerText = `Boxes: ${state.boxes.length}`;
}

// Canvas Coordinate Helpers
function screenToImage(screenX, screenY) {
  if (!state.imageLoaded) return { x: 0, y: 0 };
  const previewX = (screenX - state.panX) / state.zoom;
  const previewY = (screenY - state.panY) / state.zoom;
  // Convert from preview pixel space to full original image pixel space
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

function onMouseDown(e) {
  const rect = canvas.getBoundingClientRect();
  const mouseX = e.clientX - rect.left;
  const mouseY = e.clientY - rect.top;

  // Middle click or Space+click = Pan
  if (e.button === 1 || e.spaceKey || (e.button === 0 && e.shiftKey)) {
    state.isPanning = true;
    state.panStartX = mouseX - state.panX;
    state.panStartY = mouseY - state.panY;
    return;
  }

  // Left click: Check if clicked inside existing box
  if (e.button === 0) {
    const pt = screenToImage(mouseX, mouseY);
    const clickedBox = findBoxAt(pt.x, pt.y);
    if (clickedBox && !e.altKey) {
      state.selectedBoxId = clickedBox.id;
      setActiveClass(clickedBox.label);
      render();
      return;
    }

    // Start drawing new box
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
  document.getElementById("cursor-pos").innerText = `X: ${Math.round(pt.x)}, Y: ${Math.round(pt.y)}`;

  if (state.isPanning) {
    state.panX = mouseX - state.panStartX;
    state.panY = mouseY - state.panStartY;
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

  if (state.isDrawing) {
    state.isDrawing = false;
    const rect = canvas.getBoundingClientRect();
    const pt = screenToImage(e.clientX - rect.left, e.clientY - rect.top);

    const x1 = Math.min(state.drawStartX, pt.x);
    const y1 = Math.min(state.drawStartY, pt.y);
    const x2 = Math.max(state.drawStartX, pt.x);
    const y2 = Math.max(state.drawStartY, pt.y);
    const w = x2 - x1;
    const h = y2 - y1;

    // Minimum box size to avoid accidental single clicks
    if (w > 10 && h > 10) {
      const newBox = {
        id: "b_" + Date.now(),
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
    state.currentDrawEnd = null;
    render();
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

  render();
}

function findBoxAt(x, y) {
  for (let i = state.boxes.length - 1; i >= 0; i--) {
    const b = state.boxes[i];
    if (x >= b.x && x <= b.x + b.width && y >= b.y && y <= b.y + b.height) {
      return b;
    }
  }
  return null;
}

function onKeyDown(e) {
  // Ignore inputs inside text box
  if (e.target.tagName === "INPUT") return;

  if (e.key === "1") setActiveClass("satellite_streak");
  if (e.key === "2") setActiveClass("airplane");
  if (e.key === "3") setActiveClass("cloud");
  if (e.key === "4") setActiveClass("obstruction");
  if (e.key === "5") setActiveClass("star_trail");

  if (e.key === "a" || e.key === "A") prevFile();
  if (e.key === "d" || e.key === "D") nextFile();
  if (e.key === "s" || e.key === "S") {
    e.preventDefault();
    saveAnnotations();
  }

  if (e.key === "Delete" || e.key === "Backspace") {
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

  // Draw existing bounding boxes
  state.boxes.forEach((b) => {
    const isSelected = b.id === state.selectedBoxId;
    const col = CLASS_COLORS[b.label] || "#4299e1";

    const px = b.x * state.previewScale;
    const py = b.y * state.previewScale;
    const pw = b.width * state.previewScale;
    const ph = b.height * state.previewScale;

    // Fill
    ctx.fillStyle = isSelected ? "rgba(255, 255, 255, 0.15)" : "rgba(0, 0, 0, 0.05)";
    ctx.fillRect(px, py, pw, ph);

    // Border
    ctx.strokeStyle = col;
    ctx.lineWidth = (isSelected ? 2.5 : 1.5) / state.zoom;
    ctx.strokeRect(px, py, pw, ph);

    // Label tag
    ctx.fillStyle = col;
    const fontSize = Math.max(10, Math.min(14, 12 / state.zoom));
    ctx.font = `${fontSize}px monospace`;
    const labelText = b.label.replace("_", " ");
    const textW = ctx.measureText(labelText).width;
    ctx.fillRect(px, py - fontSize - 2, textW + 6, fontSize + 4);

    ctx.fillStyle = "#ffffff";
    ctx.fillText(labelText, px + 3, py - 2);
  });

  // Draw in-progress box
  if (state.isDrawing && state.currentDrawEnd) {
    const x1 = Math.min(state.drawStartX, state.currentDrawEnd.x) * state.previewScale;
    const y1 = Math.min(state.drawStartY, state.currentDrawEnd.y) * state.previewScale;
    const w = Math.abs(state.currentDrawEnd.x - state.drawStartX) * state.previewScale;
    const h = Math.abs(state.currentDrawEnd.y - state.drawStartY) * state.previewScale;

    ctx.strokeStyle = CLASS_COLORS[state.activeClass] || "#ffffff";
    ctx.lineWidth = 1.5 / state.zoom;
    ctx.setLineDash([4 / state.zoom, 4 / state.zoom]);
    ctx.strokeRect(x1, y1, w, h);
    ctx.setLineDash([]);
  }

  ctx.restore();
}

window.onload = init;
