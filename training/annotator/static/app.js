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
  selectedBoxIds: new Set(),
  hoverBoxId: null,
  isDraggingHandle: false,
  dragHandleType: null, // "p1", "p2", "move"
  dragBoxId: null,
  dragStartMouse: null,
  dragOriginalBox: null,
  dragOriginalBoxes: new Map(),
  globalStarTrailing: false,
  globalCloud: false,
  isClean: true,
  isDirty: false,
  isSaving: false,
  isLoading: false,
  loadSequenceId: 0,
  activeAbortController: null,

  // AI & Class State
  classes: ["satellite_streak", "airplane", "cloud", "obstruction", "star_trail", "unfocused_star"],
  availableModels: [],
  selectedModel: "",
  aiConfidence: 0.25,
  aiAppend: true,

  // Settings & Mark
  isFavorite: false,
  filterFavorites: false,
  filterUntagged: false,
  fileSortMode: "name_asc",
  showGrid: false,
  showCutPreview: false,
  lineThickness: 16,
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
  unfocused_star: "#38b2ac",
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

  // Filter marked / favorites toggle
  const chkFilterFav = document.getElementById("chk-filter-favorites");
  if (chkFilterFav) {
    chkFilterFav.checked = state.filterFavorites;
    chkFilterFav.addEventListener("change", (e) => {
      state.filterFavorites = e.target.checked;
      renderFileList();
      if (state.filterFavorites && state.currentFile && !state.currentFile.favorite) {
        const visible = getVisibleFileIndices();
        if (visible.length > 0 && !visible.includes(state.currentIndex)) {
          loadFile(visible[0]);
        }
      }
    });
  }

  // Toggle favorite / mark frame button
  const btnToggleFav = document.getElementById("btn-toggle-favorite");
  if (btnToggleFav) {
    btnToggleFav.addEventListener("click", toggleFavoriteCurrentFile);
  }

  // File sorting dropdown
  const selFileSort = document.getElementById("select-file-sort");
  if (selFileSort) {
    selFileSort.value = state.fileSortMode;
    selFileSort.addEventListener("change", (e) => {
      state.fileSortMode = e.target.value;
      renderFileList();
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
      state.isDirty = true;
      updateCleanStatus();
    });
  }

  const chkGlobal = document.getElementById("chk-global-star-trail");
  if (chkGlobal) {
    chkGlobal.addEventListener("change", (e) => {
      state.globalStarTrailing = e.target.checked;
      state.isDirty = true;
      updateCleanStatus();
    });
  }

  const chkClean = document.getElementById("chk-clean-sky");
  if (chkClean) {
    chkClean.addEventListener("change", (e) => {
      state.isClean = e.target.checked;
      state.isDirty = true;
      if (state.isClean) {
        state.boxes = [];
        state.selectedBoxIds.clear();
        state.selectedBoxId = null;
        state.globalStarTrailing = false;
        state.globalCloud = false;
        if (chkGlobal) chkGlobal.checked = false;
        if (chkGlobalCloud) chkGlobalCloud.checked = false;
        render();
        renderAnnotationCards();
      }
    });
  }

  const chkGrid = document.getElementById("chk-grid");
  if (chkGrid) {
    chkGrid.addEventListener("change", (e) => {
      state.showGrid = e.target.checked;
      render();
    });
  }

  const chkCutPreview = document.getElementById("chk-cut-preview");
  if (chkCutPreview) {
    chkCutPreview.addEventListener("change", (e) => {
      state.showCutPreview = e.target.checked;
      render();
    });
  }

  const sliderLineThick = document.getElementById("slider-line-thickness");
  const valLineThick = document.getElementById("line-thickness-val");
  if (sliderLineThick) {
    sliderLineThick.addEventListener("input", (e) => {
      const v = parseInt(e.target.value, 10) || 16;
      state.lineThickness = v;
      if (valLineThick) valLineThick.innerText = `${v}px`;
      for (const id of state.selectedBoxIds) {
        const b = state.boxes.find((x) => x.id === id);
        if (b && b.type === "line") {
          b.thickness = v;
          state.isDirty = true;
        }
      }
      render();
      renderAnnotationCards();
    });
  }

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

  // Batch Selection Toolbar
  const btnSelectAll = document.getElementById("btn-select-all");
  if (btnSelectAll) btnSelectAll.addEventListener("click", selectAll);

  const btnDeselectAll = document.getElementById("btn-deselect-all");
  if (btnDeselectAll) btnDeselectAll.addEventListener("click", deselectAll);

  const btnDelSelected = document.getElementById("btn-delete-selected");
  if (btnDelSelected) btnDelSelected.addEventListener("click", deleteSelected);

  const selByClass = document.getElementById("select-by-class");
  if (selByClass) {
    selByClass.addEventListener("change", (e) => {
      selectByClass(e.target.value);
    });
  }

  // AI Auto-Label Controls
  const selAiModel = document.getElementById("select-ai-model");
  if (selAiModel) {
    selAiModel.addEventListener("change", (e) => {
      state.selectedModel = e.target.value;
    });
  }

  const sliderAiConf = document.getElementById("slider-ai-conf");
  const valAiConf = document.getElementById("ai-conf-val");
  if (sliderAiConf) {
    sliderAiConf.addEventListener("input", (e) => {
      const v = parseFloat(e.target.value);
      state.aiConfidence = v;
      if (valAiConf) valAiConf.innerText = `${Math.round(v * 100)}%`;
    });
  }

  const chkAiAppend = document.getElementById("chk-ai-append");
  if (chkAiAppend) {
    chkAiAppend.addEventListener("change", (e) => {
      state.aiAppend = e.target.checked;
    });
  }

  const btnRefreshModels = document.getElementById("btn-refresh-models");
  if (btnRefreshModels) btnRefreshModels.addEventListener("click", loadAvailableModels);

  const btnRunAi = document.getElementById("btn-run-ai");
  if (btnRunAi) btnRunAi.addEventListener("click", predictCurrentImage);

  // Dataset Health Modal Controls
  const btnOpenAnalyzer = document.getElementById("btn-open-analyzer");
  if (btnOpenAnalyzer) btnOpenAnalyzer.addEventListener("click", openAnalyzerModal);

  const btnCloseModal = document.getElementById("btn-close-modal");
  if (btnCloseModal) btnCloseModal.addEventListener("click", closeAnalyzerModal);

  const btnCloseFooter = document.getElementById("btn-modal-close-footer");
  if (btnCloseFooter) btnCloseFooter.addEventListener("click", closeAnalyzerModal);

  const btnRefreshStats = document.getElementById("btn-refresh-stats");
  if (btnRefreshStats) btnRefreshStats.addEventListener("click", loadDatasetStats);

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

  // Load dynamic classes and models
  loadClassesConfig();
  loadAvailableModels();

  // URL Hash navigation
  window.addEventListener("hashchange", () => {
    if (!window.location.hash || !state.files || state.files.length === 0) return;
    const hashName = decodeURIComponent(window.location.hash.replace(/^#/, "").trim());
    const found = state.files.findIndex((f) => f.name === hashName);
    if (found !== -1 && found !== state.currentIndex) {
      loadFile(found);
    }
  });

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
  if (state.selectedBoxIds && state.selectedBoxIds.size > 0) {
    batchChangeClass(cls);
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
  state.selectedBoxIds = new Set([newBox.id]);
  state.selectedBoxId = newBox.id;
  state.isDirty = true;
  updateCleanStatus();
  setStatus(`Marked entire frame as ${state.activeClass.replace("_", " ")}`);
  render();
  renderAnnotationCards();
}

// ----------------------------------------------------
// Multi-Selection and Batch Operations
// ----------------------------------------------------
function selectBox(id, multi = false) {
  if (multi) {
    if (state.selectedBoxIds.has(id)) {
      state.selectedBoxIds.delete(id);
    } else {
      state.selectedBoxIds.add(id);
    }
  } else {
    state.selectedBoxIds = new Set([id]);
  }

  state.selectedBoxId = state.selectedBoxIds.size === 1 ? [...state.selectedBoxIds][0] : null;

  const thickGroup = document.getElementById("line-thickness-group");
  const lblThick = document.getElementById("lbl-line-thickness");
  const slThick = document.getElementById("slider-line-thickness");
  const lvThick = document.getElementById("line-thickness-val");

  if (state.selectedBoxId) {
    const b = state.boxes.find((x) => x.id === state.selectedBoxId);
    if (b) {
      state.activeClass = b.label;
      document.querySelectorAll(".btn-class").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.class === b.label);
      });
      if (b.type === "line") {
        const thick = b.thickness || state.lineThickness || 16;
        b.thickness = thick;
        state.lineThickness = thick;
        if (slThick) slThick.value = thick;
        if (lvThick) lvThick.innerText = `${thick}px`;
        if (lblThick) lblThick.innerText = "Selected Line Width:";
        if (thickGroup) thickGroup.classList.add("selected-line");
      } else {
        if (lblThick) lblThick.innerText = "Line Width:";
        if (thickGroup) thickGroup.classList.remove("selected-line");
      }
    }
  } else {
    const selectedLines = [...state.selectedBoxIds]
      .map((id) => state.boxes.find((x) => x.id === id))
      .filter((x) => x && x.type === "line");
    if (selectedLines.length > 0) {
      const thick = selectedLines[0].thickness || state.lineThickness || 16;
      if (slThick) slThick.value = thick;
      if (lvThick) lvThick.innerText = `${thick}px`;
      if (lblThick) lblThick.innerText = `Selected Lines (${selectedLines.length}) Width:`;
      if (thickGroup) thickGroup.classList.add("selected-line");
    } else {
      if (lblThick) lblThick.innerText = "Line Width:";
      if (thickGroup) thickGroup.classList.remove("selected-line");
    }
  }

  render();
  renderAnnotationCards();
}

function selectAll() {
  state.selectedBoxIds = new Set(state.boxes.map((b) => b.id));
  state.selectedBoxId = state.selectedBoxIds.size === 1 ? [...state.selectedBoxIds][0] : null;
  render();
  renderAnnotationCards();
  setStatus(`Selected all ${state.boxes.length} annotations.`);
}

function deselectAll() {
  state.selectedBoxIds.clear();
  state.selectedBoxId = null;
  state.hoverBoxId = null;
  const thickGroup = document.getElementById("line-thickness-group");
  const lblThick = document.getElementById("lbl-line-thickness");
  if (lblThick) lblThick.innerText = "Line Width:";
  if (thickGroup) thickGroup.classList.remove("selected-line");
  render();
  renderAnnotationCards();
}

function selectByClass(cls) {
  if (!cls) return;
  state.selectedBoxIds = new Set(state.boxes.filter((b) => b.label === cls).map((b) => b.id));
  state.selectedBoxId = state.selectedBoxIds.size === 1 ? [...state.selectedBoxIds][0] : null;
  render();
  renderAnnotationCards();
  setStatus(`Selected ${state.selectedBoxIds.size} annotation(s) of class '${cls}'.`);
}

function batchChangeClass(newClass) {
  if (!state.selectedBoxIds || state.selectedBoxIds.size === 0) return;
  let count = 0;
  for (const b of state.boxes) {
    if (state.selectedBoxIds.has(b.id)) {
      b.label = newClass;
      count++;
    }
  }
  state.activeClass = newClass;
  state.isDirty = true;
  document.querySelectorAll(".btn-class").forEach((b) => {
    b.classList.toggle("active", b.dataset.class === newClass);
  });
  render();
  renderAnnotationCards();
  setStatus(`Batch updated ${count} annotation(s) to '${newClass}'.`);
}

function deleteSelected() {
  if (!state.selectedBoxIds || state.selectedBoxIds.size === 0) return;
  const count = state.selectedBoxIds.size;
  state.boxes = state.boxes.filter((b) => !state.selectedBoxIds.has(b.id));
  state.selectedBoxIds.clear();
  state.selectedBoxId = null;
  state.hoverBoxId = null;
  state.isDirty = true;
  updateCleanStatus();
  render();
  renderAnnotationCards();
  setStatus(`Deleted ${count} annotation(s).`);
}

function renderAnnotationCards() {
  const badge = document.getElementById("annotation-count-badge");
  if (badge) badge.innerText = state.boxes.length;

  const selPill = document.getElementById("selection-count-badge");
  if (selPill) {
    const selCount = state.selectedBoxIds.size;
    selPill.innerText = `${selCount} selected`;
    selPill.style.display = selCount > 0 ? "inline-block" : "none";
  }

  const relabelBox = document.getElementById("batch-relabel-container");
  if (relabelBox) {
    relabelBox.classList.toggle("hidden", state.selectedBoxIds.size === 0);
  }

  const emptyEl = document.getElementById("annotation-list-empty");
  if (emptyEl) {
    emptyEl.style.display = state.boxes.length === 0 ? "block" : "none";
  }

  const list = document.getElementById("annotation-cards");
  if (!list) return;
  list.innerHTML = "";

  state.boxes.forEach((b, idx) => {
    const li = document.createElement("li");
    li.className = "annotation-card";
    li.dataset.id = b.id;
    if (state.selectedBoxIds.has(b.id)) li.classList.add("selected");
    if (state.hoverBoxId === b.id) li.classList.add("hovered");

    const col = CLASS_COLORS[b.label] || "#4299e1";
    li.style.borderLeftColor = col;

    const left = document.createElement("div");
    left.className = "card-left";

    const labelRow = document.createElement("div");
    labelRow.className = "card-label-row";

    const labelSpan = document.createElement("span");
    labelSpan.className = "card-label";
    labelSpan.style.color = col;
    labelSpan.innerText = `${idx + 1}. ${b.label.replace(/_/g, " ")}`;
    labelRow.appendChild(labelSpan);

    if (b.confidence !== undefined && b.confidence !== null) {
      const confSpan = document.createElement("span");
      confSpan.className = "card-conf";
      confSpan.innerText = `${Math.round(b.confidence * 100)}% AI`;
      labelRow.appendChild(confSpan);
    }
    left.appendChild(labelRow);

    const metaSpan = document.createElement("span");
    metaSpan.className = "card-meta";
    if (b.type === "polygon" && b.points) {
      metaSpan.innerText = `⬡ Poly (${b.points.length} pts)`;
    } else if (b.type === "line") {
      const len = Math.round(Math.hypot((b.x2 || 0) - (b.x1 || 0), (b.y2 || 0) - (b.y1 || 0)));
      metaSpan.innerText = `╱ Streak (${len}px, w:${b.thickness || 16})`;
    } else {
      metaSpan.innerText = `▢ Box (${Math.round(b.width)}×${Math.round(b.height)})`;
    }
    left.appendChild(metaSpan);
    li.appendChild(left);

    const btnDel = document.createElement("button");
    btnDel.className = "btn-card-del";
    btnDel.innerHTML = "✕";
    btnDel.title = "Delete annotation";
    btnDel.addEventListener("click", (e) => {
      e.stopPropagation();
      state.boxes = state.boxes.filter((x) => x.id !== b.id);
      state.selectedBoxIds.delete(b.id);
      if (state.selectedBoxId === b.id) state.selectedBoxId = null;
      state.isDirty = true;
      updateCleanStatus();
      render();
      renderAnnotationCards();
    });
    li.appendChild(btnDel);

    li.addEventListener("click", (e) => {
      const isMulti = e.ctrlKey || e.metaKey || e.shiftKey;
      selectBox(b.id, isMulti);
    });

    li.addEventListener("mouseenter", () => {
      state.hoverBoxId = b.id;
      render();
    });

    li.addEventListener("mouseleave", () => {
      if (state.hoverBoxId === b.id) {
        state.hoverBoxId = null;
        render();
      }
    });

    list.appendChild(li);
  });
}

// ----------------------------------------------------
// Dynamic Classes & Models Configuration
// ----------------------------------------------------
async function loadClassesConfig() {
  try {
    const res = await fetch("/api/classes");
    if (!res.ok) return;
    const data = await res.json();
    if (data.classes && data.classes.length > 0) {
      state.classes = data.classes;
      if (data.colors) {
        Object.assign(CLASS_COLORS, data.colors);
      }
      renderClassButtons();
      renderBatchRelabelButtons();
      renderSelectByClassDropdown();
    }
  } catch (err) {
    console.warn("Failed to load /api/classes:", err);
  }
}

function renderClassButtons() {
  const container = document.getElementById("class-buttons");
  if (!container) return;
  container.innerHTML = "";
  state.classes.forEach((cls, idx) => {
    const key = idx + 1;
    const btn = document.createElement("button");
    btn.className = "btn-class" + (cls === state.activeClass ? " active" : "");
    btn.dataset.class = cls;
    btn.dataset.key = key <= 9 ? String(key) : "";
    const prettyName = cls.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    btn.innerText = key <= 9 ? `[${key}] ${prettyName}` : prettyName;
    btn.style.borderBottomColor = CLASS_COLORS[cls] || "#555";
    btn.addEventListener("click", () => setActiveClass(cls));
    container.appendChild(btn);
  });
}

function renderBatchRelabelButtons() {
  const container = document.getElementById("batch-relabel-buttons");
  if (!container) return;
  container.innerHTML = "";
  state.classes.forEach((cls, idx) => {
    const key = idx + 1;
    const btn = document.createElement("button");
    btn.className = "btn-pill";
    btn.title = `Change selected to ${cls} [${key}]`;
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.backgroundColor = CLASS_COLORS[cls] || "#555";
    btn.appendChild(dot);
    const prettyName = cls.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    btn.appendChild(document.createTextNode(key <= 9 ? `[${key}] ${prettyName}` : prettyName));
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      batchChangeClass(cls);
    });
    container.appendChild(btn);
  });
}

function renderSelectByClassDropdown() {
  const sel = document.getElementById("select-by-class");
  if (!sel) return;
  sel.innerHTML = '<option value="">-- Filter/Select Class --</option>';
  state.classes.forEach((cls) => {
    const opt = document.createElement("option");
    opt.value = cls;
    const prettyName = cls.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    opt.textContent = prettyName;
    sel.appendChild(opt);
  });
}

async function loadAvailableModels() {
  const sel = document.getElementById("select-ai-model");
  const btnRun = document.getElementById("btn-run-ai");
  if (!sel) return;

  function updatePredictBtnText() {
    if (!btnRun) return;
    const cur = state.availableModels.find((m) => m.full_path === sel.value);
    if (cur && cur.type === "cnn") {
      btnRun.innerText = "⚡ Predict with CNN (Y)";
      btnRun.title = "Run CNN tile classification and adjacent square merging [Y]";
    } else {
      btnRun.innerText = "⚡ Predict with YOLO (Y)";
      btnRun.title = "Run YOLO segmentation on current frame [Y]";
    }
  }

  sel.innerHTML = '<option value="">Loading models...</option>';
  try {
    const res = await fetch("/api/models");
    if (!res.ok) throw new Error("Failed to fetch models");
    const data = await res.json();
    state.availableModels = data.models || [];
    sel.innerHTML = "";
    if (state.availableModels.length === 0) {
      sel.innerHTML = '<option value="">No models found</option>';
      return;
    }
    state.availableModels.forEach((m, idx) => {
      const opt = document.createElement("option");
      opt.value = m.full_path;
      const tag = m.type === "yolo-seg" ? "[YOLO-Seg]" : "[CNN]";
      opt.textContent = `${tag} ${m.name} (${m.size_mb} MB)`;
      if (idx === 0) opt.selected = true;
      sel.appendChild(opt);
    });
    state.selectedModel = sel.value;

    sel.onchange = () => {
      state.selectedModel = sel.value;
      updatePredictBtnText();
    };
    updatePredictBtnText();
  } catch (err) {
    sel.innerHTML = `<option value="">Error loading models: ${err.message}</option>`;
  }
}

async function predictCurrentImage() {
  if (!state.currentFile) {
    alert("Please select and load a FITS image first.");
    return;
  }
  const sel = document.getElementById("select-ai-model");
  const modelPath = sel ? sel.value : state.selectedModel;
  if (!modelPath) {
    alert("Please select a trained model checkpoint (.pt or .onnx) first.");
    return;
  }

  const curModel = state.availableModels.find((m) => m.full_path === modelPath);
  const isCnn = curModel && curModel.type === "cnn";

  const statusEl = document.getElementById("ai-status");
  const btnRun = document.getElementById("btn-run-ai");
  if (statusEl) {
    statusEl.innerText = isCnn
      ? "Running CNN tile inference & merging..."
      : "Running YOLO segmentation...";
  }
  if (btnRun) {
    btnRun.disabled = true;
    btnRun.innerText = "⏳ Predicting...";
  }

  try {
    const payload = {
      path: state.currentFile.path,
      model_path: modelPath,
      conf: state.aiConfidence || 0.25,
      iou: 0.45,
      tile_size: 512,
      stride: 460,
      device: "auto",
      merge_adjacent: true,
    };
    const res = await fetch("/api/models/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Prediction request failed");
    }
    const data = await res.json();
    const newBoxes = data.boxes || [];

    if (!state.aiAppend) {
      state.boxes = newBoxes;
    } else {
      state.boxes.push(...newBoxes);
    }

    state.selectedBoxIds = new Set(newBoxes.map((b) => b.id));
    state.selectedBoxId = newBoxes.length === 1 ? newBoxes[0].id : null;
    if (newBoxes.length > 0) {
      state.isClean = false;
      const chkClean = document.getElementById("chk-clean-sky");
      if (chkClean) chkClean.checked = false;
    }
    state.isDirty = true;

    const kindLabel = isCnn ? "defect box(es)" : "mask(s)";
    if (statusEl) {
      statusEl.innerText = `Found ${data.count} ${kindLabel} in ${data.elapsed_sec}s`;
    }
    setStatus(
      `AI Auto-Label: ${data.count} ${kindLabel} generated using ${data.model} in ${data.elapsed_sec}s.`
    );
    render();
    renderAnnotationCards();
  } catch (err) {
    if (statusEl) statusEl.innerText = `Error: ${err.message}`;
    setStatus(`AI Prediction Error: ${err.message}`);
  } finally {
    if (btnRun) {
      btnRun.disabled = false;
      btnRun.innerText = isCnn ? "⚡ Predict with CNN (Y)" : "⚡ Predict with YOLO (Y)";
    }
  }
}

// ----------------------------------------------------
// Dataset Health & Pre-Analyzer Modal
// ----------------------------------------------------
function openAnalyzerModal() {
  const modal = document.getElementById("analyzer-modal");
  if (!modal) return;
  modal.classList.remove("hidden");
  loadDatasetStats();
}

function closeAnalyzerModal() {
  const modal = document.getElementById("analyzer-modal");
  if (modal) modal.classList.add("hidden");
}

async function loadDatasetStats() {
  const body = document.getElementById("analyzer-modal-body");
  if (!body) return;
  body.innerHTML = '<div class="loading-spinner">Analyzing directory...</div>';

  try {
    const res = await fetch(`/api/dataset/stats?dir_path=${encodeURIComponent(state.currentDir)}`);
    if (!res.ok) throw new Error("Failed to analyze dataset");
    const data = await res.json();
    renderAnalyzerStats(data);
  } catch (err) {
    body.innerHTML = `<div style="color: #fc8181; padding: 20px;">Error analyzing dataset: ${err.message}</div>`;
  }
}

function renderAnalyzerStats(data) {
  const body = document.getElementById("analyzer-modal-body");
  if (!body) return;

  const s = data.summary;
  const ch = data.class_health;
  const recs = data.recommendations;

  let html = `
    <div class="stats-summary-grid">
      <div class="stat-box">
        <div class="stat-val">${s.total_fits}</div>
        <div class="stat-label">Total Frames</div>
      </div>
      <div class="stat-box">
        <div class="stat-val" style="color: #48bb78;">${s.annotated_frames}</div>
        <div class="stat-label">Annotated (${Math.round((s.annotated_frames / Math.max(1, s.total_fits)) * 100)}%)</div>
      </div>
      <div class="stat-box">
        <div class="stat-val" style="color: #ed8936;">${s.unannotated_frames}</div>
        <div class="stat-label">Unannotated</div>
      </div>
      <div class="stat-box">
        <div class="stat-val">${s.total_annotations}</div>
        <div class="stat-label">Total Annotations</div>
      </div>
    </div>

    <h3 style="margin-top: 14px; margin-bottom: 6px; font-size: 13px;">Class Balance & Shape Distributions:</h3>
    <table class="stats-table">
      <thead>
        <tr>
          <th>Class</th>
          <th>Samples</th>
          <th>Share</th>
          <th>Frames</th>
          <th>Box</th>
          <th>Line</th>
          <th>Poly</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
  `;

  for (const [cls, info] of Object.entries(ch)) {
    const col = CLASS_COLORS[cls] || "#cbd5e0";
    const badgeClass = info.status === "healthy" ? "badge-healthy" : (info.status === "critical" ? "badge-critical" : "badge-low");
    const shapes = info.shapes || {};
    html += `
      <tr>
        <td style="font-weight: bold; color: ${col};">${cls}</td>
        <td>${info.count}</td>
        <td>${info.percent}%</td>
        <td>${info.frames}</td>
        <td>${shapes.box || 0}</td>
        <td>${shapes.line || 0}</td>
        <td>${shapes.polygon || 0}</td>
        <td><span class="${badgeClass}">${info.status.toUpperCase()}</span></td>
      </tr>
    `;
  }

  html += `
      </tbody>
    </table>
  `;

  if (recs && recs.length > 0) {
    html += `
      <div class="recs-box">
        <h3>⚠️ Recommendations & Deficits Detected:</h3>
        <ul>
    `;
    for (const r of recs) {
      html += `<li><strong>[${r.priority} Priority]</strong> ${r.message}</li>`;
    }
    html += `
        </ul>
      </div>
    `;
  }

  body.innerHTML = html;
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
      let initialIdx = 0;
      if (window.location.hash) {
        const hashName = decodeURIComponent(window.location.hash.replace(/^#/, "").trim());
        const found = state.files.findIndex((f) => f.name === hashName);
        if (found !== -1) initialIdx = found;
      }
      loadFile(initialIdx);
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
    if (state.filterUntagged && f.annotated) return;
    if (state.filterFavorites && !f.favorite) return;
    indices.push(idx);
  });

  const mode = state.fileSortMode || "name_asc";
  indices.sort((a, b) => {
    const fa = state.files[a];
    const fb = state.files[b];

    if (mode === "name_desc") {
      return fb.name.localeCompare(fa.name);
    }
    if (mode === "time_asc") {
      // Oldest classified first
      const ta = fa.annot_mtime || 0;
      const tb = fb.annot_mtime || 0;
      if (ta > 0 && tb > 0) {
        if (ta !== tb) return ta - tb;
      } else if (ta > 0) {
        return -1; // annotated files before unannotated
      } else if (tb > 0) {
        return 1;
      }
      return fa.name.localeCompare(fb.name);
    }
    if (mode === "time_desc") {
      // Newest classified first
      const ta = fa.annot_mtime || 0;
      const tb = fb.annot_mtime || 0;
      if (ta > 0 && tb > 0) {
        if (ta !== tb) return tb - ta;
      } else if (ta > 0) {
        return -1; // annotated files before unannotated
      } else if (tb > 0) {
        return 1;
      }
      return fa.name.localeCompare(fb.name);
    }

    // Default: name_asc
    return fa.name.localeCompare(fb.name);
  });

  return indices;
}

function renderFileList() {
  const list = document.getElementById("file-list");
  list.innerHTML = "";

  const visibleIndices = getVisibleFileIndices();
  const countEl = document.getElementById("file-count");
  if (countEl) {
    const isFiltered = state.filterUntagged || state.filterFavorites;
    countEl.innerText = isFiltered ? `${visibleIndices.length} / ${state.files.length}` : `${state.files.length}`;
  }

  visibleIndices.forEach((idx) => {
    const f = state.files[idx];
    const li = document.createElement("li");
    const nameSpan = document.createElement("span");
    nameSpan.className = "file-name";
    nameSpan.innerText = f.name;
    li.appendChild(nameSpan);

    const badges = document.createElement("span");
    badges.className = "file-badges";
    if (f.favorite) {
      const favBadge = document.createElement("span");
      favBadge.className = "badge-fav";
      favBadge.title = "Marked frame";
      favBadge.innerText = "⭐";
      badges.appendChild(favBadge);
    }
    if (f.annotated) {
      const annotBadge = document.createElement("span");
      annotBadge.className = "badge-annot";
      if (f.annot_mtime) {
        const d = new Date(f.annot_mtime * 1000);
        annotBadge.title = `Classified: ${d.toLocaleDateString()} ${d.toLocaleTimeString()}`;
      } else {
        annotBadge.title = "Annotated";
      }
      annotBadge.innerText = "✓";
      badges.appendChild(annotBadge);
    }
    li.appendChild(badges);

    if (f.annotated) li.classList.add("annotated");
    if (idx === state.currentIndex) li.classList.add("active");
    li.addEventListener("click", () => loadFile(idx));
    list.appendChild(li);
  });
}

async function toggleFavoriteCurrentFile() {
  if (!state.currentFile) return;
  state.isFavorite = !state.isFavorite;
  state.currentFile.favorite = state.isFavorite;

  updateFavoriteButtonUI();
  renderFileList();

  try {
    await fetch(`/api/favorite?path=${encodeURIComponent(state.currentFile.path)}&favorite=${state.isFavorite}`, {
      method: "POST"
    });
    setStatus(state.isFavorite ? `Marked ${state.currentFile.name} as favorite frame ⭐` : `Unmarked ${state.currentFile.name}`);
  } catch (err) {
    console.error("Failed to update favorite status:", err);
  }
}

function updateFavoriteButtonUI() {
  const btn = document.getElementById("btn-toggle-favorite");
  if (!btn) return;
  btn.classList.toggle("active", Boolean(state.isFavorite));
  btn.innerText = state.isFavorite ? "⭐ Marked Frame" : "☆ Mark Frame";
  btn.title = state.isFavorite ? "Unmark frame [K]" : "Star / Mark this frame for later review [K]";
}

async function loadFile(index) {
  if (index < 0 || index >= state.files.length) return;

  // 1. If current file has unsaved changes, save it first before navigating away!
  if (state.isDirty && state.currentFile && state.currentFile !== state.files[index]) {
    await saveAnnotations(state.currentFile);
  }

  // 2. Abort any previous in-flight requests (both preview and annotations)
  if (state.activeAbortController) {
    state.activeAbortController.abort();
  }
  state.activeAbortController = new AbortController();
  const signal = state.activeAbortController.signal;

  // 3. Increment load sequence ID to guarantee out-of-order network responses are rejected
  state.loadSequenceId = (state.loadSequenceId || 0) + 1;
  const seq = state.loadSequenceId;

  // 4. Update file pointers & immediately clear old annotations
  state.currentIndex = index;
  state.currentFile = state.files[index];

  // Sync with URL Hash
  history.replaceState(null, "", "#" + encodeURIComponent(state.currentFile.name));

  state.isLoading = true;
  state.isDirty = false;
  state.selectedBoxIds.clear();
  state.selectedBoxId = null;
  state.hoverBoxId = null;
  state.polygonPoints = [];
  state.boxes = []; // Wipe immediately so previous file boxes never bleed over
  state.globalStarTrailing = false;
  state.globalCloud = false;
  state.isClean = true;
  state.isFavorite = Boolean(state.currentFile.favorite);
  updateFavoriteButtonUI();

  // Clear checkboxes in UI
  const chkGlobalStar = document.getElementById("chk-global-star-trail");
  if (chkGlobalStar) chkGlobalStar.checked = false;
  const chkGlobalCloud = document.getElementById("chk-global-cloud");
  if (chkGlobalCloud) chkGlobalCloud.checked = false;
  const chkClean = document.getElementById("chk-clean-sky");
  if (chkClean) chkClean.checked = true;

  renderFileList();
  renderAnnotationCards(); // Clean sidebar cards immediately upon switching files
  document.getElementById("current-filename").innerText = state.currentFile.name;
  setStatus(`Loading ${state.currentFile.name}...`);
  render();

  try {
    const targetFile = state.currentFile;
    // 5. Load preview and annotations concurrently for maximum speed
    await Promise.all([
      loadFilePreview(targetFile, seq, signal),
      loadAnnotations(targetFile, seq, signal),
    ]);

    if (seq === state.loadSequenceId) {
      state.isLoading = false;
      state.isDirty = false;
      state.selectedBoxIds.clear();
      state.selectedBoxId = null;
      state.hoverBoxId = null;
      resetView();
      setStatus(`Loaded ${targetFile.name}`);
      render();
      renderAnnotationCards(); // Render loaded cards in sidebar
    }
  } catch (err) {
    if (err.name === "AbortError" || seq !== state.loadSequenceId) {
      return;
    }
    state.isLoading = false;
    setStatus(`Error loading ${state.currentFile.name}: ${err.message}`);
  }
}

async function loadFilePreview(file, seq, signal) {
  try {
    const url = `/api/preview?path=${encodeURIComponent(file.path)}&shadows=${state.shadowsClipping}&target_bg=${state.targetBg}&mode=${state.stretchMode}&linked=${state.rgbLinked}`;
    const res = await fetch(url, { signal });
    if (!res.ok) throw new Error("Failed to load preview");

    if (seq !== state.loadSequenceId) return;

    const hOrigW = parseInt(res.headers.get("X-Original-Width") || "0", 10);
    const hOrigH = parseInt(res.headers.get("X-Original-Height") || "0", 10);
    const hScale = parseFloat(res.headers.get("X-Preview-Scale") || "0");

    const blob = await res.blob();
    if (seq !== state.loadSequenceId) return;

    await new Promise((resolve, reject) => {
      if (seq !== state.loadSequenceId) return resolve();
      const img = new Image();
      img.onload = () => {
        if (seq !== state.loadSequenceId) return resolve();
        state.image = img;
        state.imageLoaded = true;

        state.origWidth = hOrigW > 0 ? hOrigW : img.naturalWidth;
        state.origHeight = hOrigH > 0 ? hOrigH : img.naturalHeight;
        state.imageDimensions = { width: state.origWidth, height: state.origHeight };

        if (state.origWidth > 0 && img.naturalWidth > 0) {
          state.previewScale = img.naturalWidth / state.origWidth;
        } else if (hScale > 0) {
          state.previewScale = hScale;
        } else {
          state.previewScale = 1.0;
        }

        document.getElementById("image-dimensions").innerText = `(${state.origWidth} x ${state.origHeight})`;
        resolve();
      };
      img.onerror = () => reject(new Error("Image decoding failed"));
      img.src = URL.createObjectURL(blob);
    });
  } catch (err) {
    if (err.name !== "AbortError") throw err;
  }
}

async function loadAnnotations(file, seq, signal) {
  try {
    const res = await fetch(`/api/annotations?path=${encodeURIComponent(file.path)}`, { signal });
    if (!res.ok) throw new Error("Failed to load annotations");
    const data = await res.json();

    if (seq !== state.loadSequenceId) return;

    state.boxes = data.boxes || [];
    state.globalStarTrailing = data.global_star_trailing || false;
    state.globalCloud = data.global_cloud || false;
    state.isClean = data.is_clean !== undefined ? data.is_clean : (state.boxes.length === 0 && !state.globalStarTrailing && !state.globalCloud);
    state.isFavorite = Boolean(data.favorite !== undefined ? data.favorite : file.favorite);
    file.favorite = state.isFavorite;
    updateFavoriteButtonUI();

    const chkGlobalStar = document.getElementById("chk-global-star-trail");
    if (chkGlobalStar) chkGlobalStar.checked = state.globalStarTrailing;
    const chkGlobalCloud = document.getElementById("chk-global-cloud");
    if (chkGlobalCloud) chkGlobalCloud.checked = state.globalCloud;
    const chkClean = document.getElementById("chk-clean-sky");
    if (chkClean) chkClean.checked = state.isClean;

    updateCleanStatus();
  } catch (err) {
    if (err.name !== "AbortError") {
      state.boxes = [];
    }
  }
}

async function saveAnnotations(explicitFile = null) {
  const targetFile = explicitFile || state.currentFile;
  if (!targetFile) return;

  // If loading and not dirty, skip
  if (state.isLoading && !state.isDirty) return;

  // Snapshot everything synchronously right now!
  const fileToSave = targetFile;
  const filePath = fileToSave.path;
  const fileName = fileToSave.name;
  const payload = {
    file_name: fileName,
    width: state.origWidth,
    height: state.origHeight,
    global_star_trailing: state.globalStarTrailing,
    global_cloud: state.globalCloud,
    is_clean: state.isClean,
    favorite: state.isFavorite,
    boxes: JSON.parse(JSON.stringify(state.boxes)),
  };

  state.isSaving = true;
  setStatus(`Saving annotations for ${fileName}...`);
  try {
    const res = await fetch(`/api/annotations?path=${encodeURIComponent(filePath)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("Failed to save");

    const resData = await res.json().catch(() => ({}));
    fileToSave.annotated = true;
    fileToSave.annot_mtime = resData.annot_mtime || (Date.now() / 1000);
    renderFileList();

    if (state.currentFile && state.currentFile.path === filePath) {
      state.isDirty = false;
      setStatus(`Saved annotations (${payload.boxes.length} items) for ${fileName}`);
    }
  } catch (err) {
    if (err.name !== "AbortError") {
      setStatus(`Error saving ${fileName}: ${err.message}`);
    }
  } finally {
    state.isSaving = false;
  }
}

async function clearAnnotations() {
  if (!state.currentFile) return;
  if (!confirm(`Are you sure you want to clear all annotations for ${state.currentFile.name}?`)) {
    return;
  }
  const fileToClear = state.currentFile;
  setStatus("Clearing annotations...");
  try {
    const res = await fetch(`/api/annotations?path=${encodeURIComponent(fileToClear.path)}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error("Failed to delete annotations");

    state.boxes = [];
    state.selectedBoxIds.clear();
    state.selectedBoxId = null;
    state.hoverBoxId = null;
    state.globalStarTrailing = false;
    state.globalCloud = false;
    state.isClean = true;
    state.isDirty = false;

    const chkGlobalStar = document.getElementById("chk-global-star-trail");
    if (chkGlobalStar) chkGlobalStar.checked = false;
    const chkGlobalCloud = document.getElementById("chk-global-cloud");
    if (chkGlobalCloud) chkGlobalCloud.checked = false;
    const chkClean = document.getElementById("chk-clean-sky");
    if (chkClean) chkClean.checked = true;

    fileToClear.annotated = false;
    fileToClear.annot_mtime = 0;
    renderFileList();
    render();
    renderAnnotationCards();
    setStatus(`Cleared all annotations for ${fileToClear.name}`);
  } catch (err) {
    setStatus("Error clearing annotations: " + err.message);
  }
}

async function prevFile() {
  const visible = getVisibleFileIndices();
  if (visible.length === 0) return;
  const currentPos = visible.indexOf(state.currentIndex);
  if (currentPos > 0) {
    await loadFile(visible[currentPos - 1]);
  } else if (currentPos === -1 && visible.length > 0) {
    const preceding = visible.filter((i) => i < state.currentIndex);
    if (preceding.length > 0) {
      await loadFile(preceding[preceding.length - 1]);
    }
  }
}

async function nextFile() {
  const visible = getVisibleFileIndices();
  if (visible.length === 0) return;
  const currentPos = visible.indexOf(state.currentIndex);
  if (currentPos >= 0 && currentPos < visible.length - 1) {
    await loadFile(visible[currentPos + 1]);
  } else if (currentPos === -1) {
    const following = visible.filter((i) => i > state.currentIndex);
    if (following.length > 0) {
      await loadFile(following[0]);
    } else if (visible.length > 0) {
      await loadFile(visible[0]);
    }
  }
}

async function nextUntaggedFile() {
  if (state.isDirty && state.currentFile) {
    await saveAnnotations(state.currentFile);
  }
  for (let i = state.currentIndex + 1; i < state.files.length; i++) {
    if (!state.files[i].annotated) {
      await loadFile(i);
      return;
    }
  }
  for (let i = 0; i <= state.currentIndex; i++) {
    if (!state.files[i].annotated) {
      await loadFile(i);
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

function lineIntersectsTile(x1, y1, x2, y2, tx, ty, tsize) {
  const INSIDE = 0, LEFT = 1, RIGHT = 2, BOTTOM = 4, TOP = 8;
  function computeCode(x, y) {
    let code = INSIDE;
    if (x < tx) code |= LEFT;
    else if (x > tx + tsize) code |= RIGHT;
    if (y < ty) code |= BOTTOM;
    else if (y > ty + tsize) code |= TOP;
    return code;
  }
  let c1 = computeCode(x1, y1);
  let c2 = computeCode(x2, y2);
  while (true) {
    if ((c1 | c2) === 0) return true;
    if ((c1 & c2) !== 0) return false;
    let codeOut = c1 !== 0 ? c1 : c2;
    let x = 0, y = 0;
    if (codeOut & TOP) {
      x = x1 + (x2 - x1) * (ty + tsize - y1) / (y2 - y1);
      y = ty + tsize;
    } else if (codeOut & BOTTOM) {
      x = x1 + (x2 - x1) * (ty - y1) / (y2 - y1);
      y = ty;
    } else if (codeOut & RIGHT) {
      y = y1 + (y2 - y1) * (tx + tsize - x1) / (x2 - x1);
      x = tx + tsize;
    } else if (codeOut & LEFT) {
      y = y1 + (y2 - y1) * (tx - x1) / (x2 - x1);
      x = tx;
    }
    if (codeOut === c1) {
      x1 = x; y1 = y;
      c1 = computeCode(x1, y1);
    } else {
      x2 = x; y2 = y;
      c2 = computeCode(x2, y2);
    }
  }
}

function itemIntersectsTile(item, tx, ty, tsize) {
  if (item.type === "polygon" && item.points && item.points.length >= 3) {
    // 1. Any vertex inside
    for (let p of item.points) {
      if (p[0] >= tx && p[0] <= tx + tsize && p[1] >= ty && p[1] <= ty + tsize) return true;
    }
    // 2. Tile points inside polygon
    const testPoints = [
      [tx, ty], [tx + tsize, ty], [tx + tsize, ty + tsize], [tx, ty + tsize],
      [tx + tsize / 2, ty + tsize / 2]
    ];
    for (let tp of testPoints) {
      if (pointInPolygon(tp[0], tp[1], item.points)) return true;
    }
    // 3. Edges intersect
    const n = item.points.length;
    for (let i = 0; i < n; i++) {
      const p1 = item.points[i];
      const p2 = item.points[(i + 1) % n];
      if (lineIntersectsTile(p1[0], p1[1], p2[0], p2[1], tx, ty, tsize)) return true;
    }
    return false;
  }
  if (item.type === "line") {
    const x1 = item.x1 !== undefined ? item.x1 : item.x;
    const y1 = item.y1 !== undefined ? item.y1 : item.y;
    const x2 = item.x2 !== undefined ? item.x2 : item.x + item.width;
    const y2 = item.y2 !== undefined ? item.y2 : item.y + item.height;
    const thick = (item.thickness !== undefined ? item.thickness : state.lineThickness) || 16;
    const buf = thick / 2.0;
    return lineIntersectsTile(x1, y1, x2, y2, tx - buf, ty - buf, tsize + buf * 2);
  }
  // Box
  return !(
    item.x + item.width <= tx ||
    item.x >= tx + tsize ||
    item.y + item.height <= ty ||
    item.y >= ty + tsize
  );
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

  // Handle detection radius in image coordinates (at least 15px on screen or 14 image px)
  const handleRadius = Math.max(14, 16 / (state.zoom * state.previewScale));

  const d1 = Math.hypot(x - x1, y - y1);
  const d2 = Math.hypot(x - x2, y - y2);

  // Endpoint handles take absolute priority over segment body
  if (d1 <= handleRadius || d2 <= handleRadius) {
    return d1 <= d2 ? "p1" : "p2";
  }

  // Check if near the segment itself for body move
  const thick = line.thickness || state.lineThickness || 16;
  const segThreshold = Math.max(handleRadius, thick / 2 + 6);
  const d = distToSegment(x, y, x1, y1, x2, y2);
  if (d <= segThreshold) {
    return "move";
  }
  return null;
}

function findBoxHandleAt(x, y, box, allowBodyMove = false) {
  const x1 = box.x;
  const y1 = box.y;
  const x2 = box.x + box.width;
  const y2 = box.y + box.height;

  const radius = Math.max(12, 14 / (state.zoom * state.previewScale));

  // 1. Corners (priority over edges)
  if (Math.hypot(x - x1, y - y1) <= radius) return "tl";
  if (Math.hypot(x - x2, y - y1) <= radius) return "tr";
  if (Math.hypot(x - x2, y - y2) <= radius) return "br";
  if (Math.hypot(x - x1, y - y2) <= radius) return "bl";

  // 2. Edges
  if (Math.abs(y - y1) <= radius && x >= x1 - radius && x <= x2 + radius) return "t";
  if (Math.abs(y - y2) <= radius && x >= x1 - radius && x <= x2 + radius) return "b";
  if (Math.abs(x - x1) <= radius && y >= y1 - radius && y <= y2 + radius) return "l";
  if (Math.abs(x - x2) <= radius && y >= y1 - radius && y <= y2 + radius) return "r";

  // 3. Top-left label badge area
  const fontSize = Math.max(10, Math.min(14, 12 / state.zoom));
  const badgeH = (fontSize + 6) / (state.zoom * state.previewScale);
  const badgeW = Math.max(60, box.width * 0.4);
  if (x >= x1 && x <= x1 + badgeW && y >= y1 - badgeH && y <= y1 + badgeH) {
    return "move";
  }

  // 4. Body interior (only if allowBodyMove is true, e.g. Alt held)
  if (allowBodyMove && x >= x1 && x <= x2 && y >= y1 && y <= y2) {
    return "move";
  }

  return null;
}

function findPolygonHandleAt(x, y, poly, allowBodyMove = false) {
  if (!poly.points || poly.points.length === 0) return null;
  const radius = Math.max(12, 14 / (state.zoom * state.previewScale));

  // 1. Check vertices
  for (let i = 0; i < poly.points.length; i++) {
    const [px, py] = poly.points[i];
    if (Math.hypot(x - px, y - py) <= radius) {
      return "vertex_" + i;
    }
  }

  // 2. Check edges for move
  const n = poly.points.length;
  for (let i = 0; i < n; i++) {
    const p1 = poly.points[i];
    const p2 = poly.points[(i + 1) % n];
    if (distToSegment(x, y, p1[0], p1[1], p2[0], p2[1]) <= radius) {
      return "move";
    }
  }

  // 3. Centroid label badge area
  const cX = poly.x + poly.width / 2;
  const cY = poly.y + poly.height / 2;
  if (Math.hypot(x - cX, y - cY) <= radius * 1.5) {
    return "move";
  }

  // 4. Body
  if (allowBodyMove && pointInPolygon(x, y, poly.points)) {
    return "move";
  }

  return null;
}

function updateCursor(x, y) {
  if (state.isPanning) {
    canvas.style.cursor = "grabbing";
    return;
  }
  if (state.isDraggingHandle || state.isDrawing) {
    return;
  }

  // 1. Check selected shape handles first
  const targetId = state.selectedBoxIds && state.selectedBoxIds.size === 1
    ? [...state.selectedBoxIds][0]
    : state.selectedBoxId;

  if (targetId) {
    const selBox = state.boxes.find((b) => b.id === targetId);
    if (selBox) {
      let handle = null;
      if (selBox.type === "line") {
        handle = findLineHandleAt(x, y, selBox);
      } else if (selBox.type === "polygon") {
        handle = findPolygonHandleAt(x, y, selBox, false);
      } else {
        handle = findBoxHandleAt(x, y, selBox, false);
      }

      if (handle) {
        switch (handle) {
          case "tl":
          case "br":
            canvas.style.cursor = "nwse-resize";
            return;
          case "tr":
          case "bl":
            canvas.style.cursor = "nesw-resize";
            return;
          case "t":
          case "b":
            canvas.style.cursor = "ns-resize";
            return;
          case "l":
          case "r":
            canvas.style.cursor = "ew-resize";
            return;
          case "p1":
          case "p2":
            canvas.style.cursor = "grab";
            return;
          case "move":
            canvas.style.cursor = "move";
            return;
          default:
            if (handle.startsWith("vertex_")) {
              canvas.style.cursor = "grab";
              return;
            }
        }
      }
    }
  }

  // 2. Check if hovering over endpoints of any line
  for (let i = state.boxes.length - 1; i >= 0; i--) {
    const b = state.boxes[i];
    if (b.type === "line") {
      const lh = findLineHandleAt(x, y, b);
      if (lh === "p1" || lh === "p2") {
        canvas.style.cursor = "grab";
        return;
      }
    } else if (b.type === "polygon") {
      const ph = findPolygonHandleAt(x, y, b, false);
      if (ph && ph.startsWith("vertex_")) {
        canvas.style.cursor = "grab";
        return;
      }
    }
  }

  // 3. Hovering over any shape body
  const hoverBox = findBoxAt(x, y);
  if (hoverBox) {
    canvas.style.cursor = "pointer";
    return;
  }

  canvas.style.cursor = "crosshair";
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
      const halfThick = (b.thickness || 16) / 2;
      const threshold = 16 / (state.zoom * state.previewScale);
      if (d <= Math.max(10, halfThick, threshold)) return b;
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
  state.selectedBoxIds = new Set([newPoly.id]);
  state.selectedBoxId = newPoly.id;
  state.polygonPoints = [];
  state.isDirty = true;
  updateCleanStatus();
  setStatus(`Created ${state.activeClass.replace("_", " ")} polygon (${newPoly.points.length} vertices)`);
  render();
  renderAnnotationCards();
}

function onMouseDown(e) {
  const rect = canvas.getBoundingClientRect();
  const mouseX = e.clientX - rect.left;
  const mouseY = e.clientY - rect.top;

  // Middle click, space key, or shift+click (without Alt/Ctrl) = Pan
  if (e.button === 1 || e.spaceKey || (e.button === 0 && e.shiftKey && !e.ctrlKey)) {
    state.isPanning = true;
    state.panStartX = mouseX - state.panX;
    state.panStartY = mouseY - state.panY;
    return;
  }

  // Left click
  if (e.button === 0) {
    const pt = screenToImage(mouseX, mouseY);
    const isCtrl = e.ctrlKey || e.metaKey;

    // 1. If a single item is selected and not Ctrl-clicking, check its handles/endpoints FIRST!
    if (state.selectedBoxIds && state.selectedBoxIds.size === 1 && !isCtrl) {
      const singleId = [...state.selectedBoxIds][0];
      const selBox = state.boxes.find((b) => b.id === singleId);
      if (selBox) {
        let handleType = null;
        if (selBox.type === "line") {
          handleType = findLineHandleAt(pt.x, pt.y, selBox);
        } else if (selBox.type === "polygon") {
          handleType = findPolygonHandleAt(pt.x, pt.y, selBox, e.altKey);
        } else {
          handleType = findBoxHandleAt(pt.x, pt.y, selBox, e.altKey);
        }

        if (handleType) {
          state.isDraggingHandle = true;
          state.dragHandleType = handleType;
          state.dragBoxId = selBox.id;
          state.dragStartMouse = { x: pt.x, y: pt.y };
          state.dragOriginalBox = JSON.parse(JSON.stringify(selBox));
          if (handleType === "move") {
            state.dragOriginalBoxes = new Map([[selBox.id, JSON.parse(JSON.stringify(selBox))]]);
          } else {
            state.dragOriginalBoxes = null;
          }
          return;
        }
      }
    }

    // 2. Check if clicking directly on an endpoint of ANY line or vertex of ANY polygon (even unselected)
    if (!isCtrl) {
      for (let i = state.boxes.length - 1; i >= 0; i--) {
        const b = state.boxes[i];
        if (b.type === "line") {
          const lh = findLineHandleAt(pt.x, pt.y, b);
          if (lh === "p1" || lh === "p2") {
            selectBox(b.id, false);
            state.isDraggingHandle = true;
            state.dragHandleType = lh;
            state.dragBoxId = b.id;
            state.dragStartMouse = { x: pt.x, y: pt.y };
            state.dragOriginalBox = JSON.parse(JSON.stringify(b));
            state.dragOriginalBoxes = null;
            return;
          }
        } else if (b.type === "polygon") {
          const ph = findPolygonHandleAt(pt.x, pt.y, b, false);
          if (ph && ph.startsWith("vertex_")) {
            selectBox(b.id, false);
            state.isDraggingHandle = true;
            state.dragHandleType = ph;
            state.dragBoxId = b.id;
            state.dragStartMouse = { x: pt.x, y: pt.y };
            state.dragOriginalBox = JSON.parse(JSON.stringify(b));
            state.dragOriginalBoxes = null;
            return;
          }
        }
      }
    }

    // 3. Check if clicking on an already-selected shape to drag-move ALL selected shapes (batch move)
    const clickedBox = findBoxAt(pt.x, pt.y);
    if (clickedBox && state.selectedBoxIds && state.selectedBoxIds.has(clickedBox.id) && !isCtrl) {
      state.isDraggingHandle = true;
      state.dragHandleType = "move";
      state.dragBoxId = clickedBox.id;
      state.dragStartMouse = { x: pt.x, y: pt.y };
      state.dragOriginalBoxes = new Map();
      for (const id of state.selectedBoxIds) {
        const b = state.boxes.find((x) => x.id === id);
        if (b) {
          state.dragOriginalBoxes.set(id, JSON.parse(JSON.stringify(b)));
        }
      }
      return;
    }

    // 4. POLYGON TOOL
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

      // If no points in progress yet and Alt/Ctrl is held, clicking shape selects it
      if (state.polygonPoints.length === 0 && (e.altKey || isCtrl)) {
        const clicked = findBoxAt(pt.x, pt.y);
        if (clicked) {
          selectBox(clicked.id, isCtrl);
          return;
        }
      }

      // Add vertex to polygon
      state.polygonPoints.push(pt);
      state.selectedBoxIds.clear();
      state.selectedBoxId = null;
      setStatus(`Polygon: ${state.polygonPoints.length} points placed. Click more, double-click or click first point to close.`);
      render();
      renderAnnotationCards();
      return;
    }

    // 5. BOX OR LINE TOOL
    state.isDrawing = true;
    state.drawStartX = pt.x;
    state.drawStartY = pt.y;
    state.currentDrawEnd = pt;
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

  // Batch Move Handling
  if (state.isDraggingHandle && state.dragHandleType === "move" && state.dragOriginalBoxes && state.dragOriginalBoxes.size > 0) {
    const dx = Math.round(pt.x - state.dragStartMouse.x);
    const dy = Math.round(pt.y - state.dragStartMouse.y);
    for (const [id, orig] of state.dragOriginalBoxes.entries()) {
      const b = state.boxes.find((x) => x.id === id);
      if (!b) continue;
      if (b.type === "polygon" && orig.points) {
        b.points = orig.points.map((p) => [Math.round(p[0] + dx), Math.round(p[1] + dy)]);
        const xs = b.points.map((p) => p[0]);
        const ys = b.points.map((p) => p[1]);
        b.x = Math.min(...xs);
        b.y = Math.min(...ys);
        b.width = Math.max(...xs) - b.x;
        b.height = Math.max(...ys) - b.y;
      } else if (b.type === "line") {
        b.x1 = Math.round(orig.x1 + dx);
        b.y1 = Math.round(orig.y1 + dy);
        b.x2 = Math.round(orig.x2 + dx);
        b.y2 = Math.round(orig.y2 + dy);
        b.x = Math.min(b.x1, b.x2);
        b.y = Math.min(b.y1, b.y2);
      } else {
        b.x = Math.round(orig.x + dx);
        b.y = Math.round(orig.y + dy);
      }
    }
    state.isDirty = true;
    render();
    return;
  }

  // Handle resizing / moving
  if (state.isDraggingHandle && state.dragBoxId && state.dragOriginalBox) {
    const box = state.boxes.find((b) => b.id === state.dragBoxId);
    if (box) {
      const orig = state.dragOriginalBox;
      const dx = pt.x - state.dragStartMouse.x;
      const dy = pt.y - state.dragStartMouse.y;

      if (box.type === "box") {
        let x1 = orig.x;
        let y1 = orig.y;
        let x2 = orig.x + orig.width;
        let y2 = orig.y + orig.height;

        switch (state.dragHandleType) {
          case "tl":
            x1 = Math.min(orig.x + dx, x2 - 5);
            y1 = Math.min(orig.y + dy, y2 - 5);
            break;
          case "tr":
            x2 = Math.max(orig.x + orig.width + dx, x1 + 5);
            y1 = Math.min(orig.y + dy, y2 - 5);
            break;
          case "br":
            x2 = Math.max(orig.x + orig.width + dx, x1 + 5);
            y2 = Math.max(orig.y + orig.height + dy, y1 + 5);
            break;
          case "bl":
            x1 = Math.min(orig.x + dx, x2 - 5);
            y2 = Math.max(orig.y + orig.height + dy, y1 + 5);
            break;
          case "t":
            y1 = Math.min(orig.y + dy, y2 - 5);
            break;
          case "b":
            y2 = Math.max(orig.y + orig.height + dy, y1 + 5);
            break;
          case "l":
            x1 = Math.min(orig.x + dx, x2 - 5);
            break;
          case "r":
            x2 = Math.max(orig.x + orig.width + dx, x1 + 5);
            break;
          case "move":
            const w = orig.width;
            const h = orig.height;
            x1 = Math.max(0, Math.min(state.origWidth - w, orig.x + dx));
            y1 = Math.max(0, Math.min(state.origHeight - h, orig.y + dy));
            x2 = x1 + w;
            y2 = y1 + h;
            break;
        }

        box.x = Math.round(x1);
        box.y = Math.round(y1);
        box.width = Math.round(x2 - x1);
        box.height = Math.round(y2 - y1);
      } else if (box.type === "polygon") {
        if (state.dragHandleType.startsWith("vertex_")) {
          const vIdx = parseInt(state.dragHandleType.replace("vertex_", ""), 10);
          if (!isNaN(vIdx) && vIdx >= 0 && vIdx < box.points.length) {
            box.points[vIdx] = [
              Math.round(orig.points[vIdx][0] + dx),
              Math.round(orig.points[vIdx][1] + dy),
            ];
          }
        } else if (state.dragHandleType === "move") {
          for (let i = 0; i < box.points.length; i++) {
            box.points[i] = [
              Math.round(orig.points[i][0] + dx),
              Math.round(orig.points[i][1] + dy),
            ];
          }
        }
        // Recalculate bounding box
        const xs = box.points.map((p) => p[0]);
        const ys = box.points.map((p) => p[1]);
        const minX = Math.min(...xs);
        const minY = Math.min(...ys);
        box.x = minX;
        box.y = minY;
        box.width = Math.max(Math.max(...xs) - minX, 4);
        box.height = Math.max(Math.max(...ys) - minY, 4);
      } else if (box.type === "line") {
        const origX1 = orig.x1 !== undefined ? orig.x1 : orig.x;
        const origY1 = orig.y1 !== undefined ? orig.y1 : orig.y;
        const origX2 = orig.x2 !== undefined ? orig.x2 : orig.x + orig.width;
        const origY2 = orig.y2 !== undefined ? orig.y2 : orig.y + orig.height;

        let x1 = origX1;
        let y1 = origY1;
        let x2 = origX2;
        let y2 = origY2;

        if (state.dragHandleType === "p1") {
          x1 = Math.round(origX1 + dx);
          y1 = Math.round(origY1 + dy);
        } else if (state.dragHandleType === "p2") {
          x2 = Math.round(origX2 + dx);
          y2 = Math.round(origY2 + dy);
        } else if (state.dragHandleType === "move") {
          x1 = Math.round(origX1 + dx);
          y1 = Math.round(origY1 + dy);
          x2 = Math.round(origX2 + dx);
          y2 = Math.round(origY2 + dy);
        }

        box.x1 = x1;
        box.y1 = y1;
        box.x2 = x2;
        box.y2 = y2;
        box.x = Math.min(x1, x2);
        box.y = Math.min(y1, y2);
        box.width = Math.max(Math.abs(x2 - x1), 2);
        box.height = Math.max(Math.abs(y2 - y1), 2);
      }

      state.isDirty = true;
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
    return;
  }

  // Hover detection and cursor update
  if (!state.isDrawing && !state.isDraggingHandle) {
    const hBox = findBoxAt(pt.x, pt.y);
    const hId = hBox ? hBox.id : null;
    if (hId !== state.hoverBoxId) {
      state.hoverBoxId = hId;
      render();
      document.querySelectorAll(".annotation-card").forEach((c) => {
        c.classList.toggle("hovered", c.dataset.id === hId);
      });
    }
  }

  // Update hover cursor
  updateCursor(pt.x, pt.y);
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
    if (state.dragOriginalBoxes) state.dragOriginalBoxes.clear();
    state.isDirty = true;
    render();
    renderAnnotationCards();
    return;
  }

  if (state.isDrawing) {
    state.isDrawing = false;
    const rect = canvas.getBoundingClientRect();
    const pt = screenToImage(e.clientX - rect.left, e.clientY - rect.top);
    const dragDist = Math.hypot(pt.x - state.drawStartX, pt.y - state.drawStartY);

    if (dragDist < 8) {
      // Click without drag: select object under click (or toggle with Ctrl/Cmd)
      const clicked = findBoxAt(pt.x, pt.y);
      const isMulti = e.ctrlKey || e.metaKey;
      if (clicked) {
        selectBox(clicked.id, isMulti);
      } else {
        if (!isMulti) {
          deselectAll();
        }
      }
    } else {
      // Dragged: create new annotation
      if (state.activeTool === "line") {
        const x1 = Math.round(state.drawStartX);
        const y1 = Math.round(state.drawStartY);
        const x2 = Math.round(pt.x);
        const y2 = Math.round(pt.y);
        const dist = Math.hypot(x2 - x1, y2 - y1);
        if (dist > 10) {
          const newLine = {
            id: "l_" + Date.now(),
            type: "line",
            label: state.activeClass,
            thickness: state.lineThickness || 16,
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
          selectBox(newLine.id, false);
          state.isDirty = true;
          updateCleanStatus();
        }
      } else if (state.activeTool === "box") {
        const x1 = Math.round(Math.min(state.drawStartX, pt.x));
        const y1 = Math.round(Math.min(state.drawStartY, pt.y));
        const x2 = Math.round(Math.max(state.drawStartX, pt.x));
        const y2 = Math.round(Math.max(state.drawStartY, pt.y));
        const w = x2 - x1;
        const h = y2 - y1;

        if (w > 6 && h > 6) {
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
          selectBox(newBox.id, false);
          state.isDirty = true;
          updateCleanStatus();
        }
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

  // Select All: Ctrl+A or Cmd+A
  if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A")) {
    e.preventDefault();
    selectAll();
    return;
  }

  // AI Auto-Label Hotkey: Y
  if (e.key === "y" || e.key === "Y") {
    predictCurrentImage();
    return;
  }

  // Mark / Favorite Frame Hotkey: K
  if (e.key === "k" || e.key === "K") {
    e.preventDefault();
    toggleFavoriteCurrentFile();
    return;
  }

  // Tool Selection Hotkeys
  if (e.key === "b" || e.key === "B") setTool("box");
  if (e.key === "p" || e.key === "P") setTool("polygon");
  if (e.key === "l" || e.key === "L") setTool("line");
  if (e.key === "f" || e.key === "F") selectFullFrame();

  // Class Selection & Batch Relabel Hotkeys: 1 - 9
  if (e.key >= "1" && e.key <= "9") {
    const idx = parseInt(e.key, 10) - 1;
    if (state.classes && idx < state.classes.length) {
      setActiveClass(state.classes[idx]);
      return;
    }
  }

  // Zoom hotkeys
  if (e.key === "+" || e.key === "=") zoomIn();
  if (e.key === "-") zoomOut();
  if (e.key === "0") resetView();

  // Navigation Hotkeys
  if (e.key === "a" || e.key === "A") {
    e.preventDefault();
    prevFile();
  }
  if (e.key === "d" || e.key === "D") {
    e.preventDefault();
    nextFile();
  }
  if (e.key === "w" || e.key === "W") {
    e.preventDefault();
    nextUntaggedFile();
  }
  if (e.key === "u" || e.key === "U") {
    state.filterUntagged = !state.filterUntagged;
    const chk = document.getElementById("chk-filter-untagged");
    if (chk) chk.checked = state.filterUntagged;
    renderFileList();
    if (state.filterUntagged && state.currentFile && state.currentFile.annotated) {
      nextUntaggedFile();
    }
  }
  // Hotkey for Cut Preview toggle
  if (e.key === "c" || e.key === "C") {
    state.showCutPreview = !state.showCutPreview;
    const chk = document.getElementById("chk-cut-preview");
    if (chk) chk.checked = state.showCutPreview;
    setStatus(state.showCutPreview ? "Tile Cut Preview enabled (highlighting 512x512 patches)." : "Tile Cut Preview disabled.");
    render();
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

  // Cancel polygon or deselect
  if (e.key === "Escape") {
    if (state.polygonPoints.length > 0) {
      state.polygonPoints = [];
      setStatus("Cancelled polygon shape.");
      render();
      return;
    }
    if (state.selectedBoxIds && state.selectedBoxIds.size > 0) {
      deselectAll();
      return;
    }
  }

  if (e.key === "Delete" || e.key === "Backspace") {
    if (state.polygonPoints.length > 0) {
      state.polygonPoints.pop();
      render();
      return;
    }
    if (state.selectedBoxIds && state.selectedBoxIds.size > 0) {
      deleteSelected();
      return;
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
  if (state.showGrid || state.showCutPreview) {
    const tileSize = 512 * state.previewScale;
    const stride = 460 * state.previewScale; // matches prep_dataset default stride
    const imgW = state.image.width;
    const imgH = state.image.height;

    // Draw Cut Preview (highlight tiles intersecting defects)
    if (state.showCutPreview && state.imageDimensions) {
      const origW = state.imageDimensions.width;
      const origH = state.imageDimensions.height;
      const origTileSize = 512;
      const origStride = 460;

      function getTileOffsets(dimSize, tSize, str) {
        if (dimSize <= tSize) return [0];
        const offsets = [];
        for (let o = 0; o <= dimSize - tSize; o += str) {
          offsets.push(o);
        }
        const lastOffset = dimSize - tSize;
        if (offsets[offsets.length - 1] !== lastOffset) {
          offsets.push(lastOffset);
        }
        return offsets;
      }

      const xOffsets = getTileOffsets(origW, origTileSize, origStride);
      const yOffsets = getTileOffsets(origH, origTileSize, origStride);

      for (let yStart of yOffsets) {
        for (let xStart of xOffsets) {

          let hasDefect = false;
          let matchedClasses = [];

          if (state.globalCloud) {
            hasDefect = true;
            matchedClasses.push("cloud");
          }
          if (state.globalStarTrailing) {
            hasDefect = true;
            matchedClasses.push("star_trail");
          }

          for (let b of state.boxes) {
            if (itemIntersectsTile(b, xStart, yStart, origTileSize)) {
              hasDefect = true;
              matchedClasses.push(b.label);
            }
          }

          const sX = xStart * state.previewScale;
          const sY = yStart * state.previewScale;
          const sW = origTileSize * state.previewScale;
          const sH = origTileSize * state.previewScale;

          if (hasDefect) {
            const firstCls = matchedClasses[0];
            const clsCol = CLASS_COLORS[firstCls] || "#e53e3e";
            ctx.fillStyle = hexToRgba(clsCol, 0.22);
            ctx.fillRect(sX, sY, sW, sH);

            ctx.strokeStyle = clsCol;
            ctx.lineWidth = 1.5 / state.zoom;
            ctx.strokeRect(sX, sY, sW, sH);
          } else {
            // Clean Sky tile outline
            ctx.strokeStyle = "rgba(72, 187, 120, 0.25)";
            ctx.lineWidth = 1 / state.zoom;
            ctx.strokeRect(sX, sY, sW, sH);
          }
        }
      }
    }

    if (state.showGrid) {
      ctx.strokeStyle = "rgba(255, 255, 255, 0.2)";
      ctx.lineWidth = 1 / state.zoom;
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
  }

  // Draw existing annotations (boxes, lines, polygons)
  state.boxes.forEach((b) => {
    const isSelected = state.selectedBoxIds ? state.selectedBoxIds.has(b.id) : (b.id === state.selectedBoxId);
    const isHovered = (b.id === state.hoverBoxId);
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
      ctx.fillStyle = isSelected ? "rgba(255, 255, 255, 0.32)" : (isHovered ? "rgba(99, 179, 237, 0.28)" : hexToRgba(col, 0.18));
      ctx.fill();

      // Hover glow outline
      if (isHovered) {
        ctx.save();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 3.5 / state.zoom;
        ctx.stroke();
        ctx.restore();
      }

      // Stroke
      ctx.strokeStyle = isSelected ? "#ffffff" : col;
      ctx.lineWidth = (isSelected ? 3.0 : (isHovered ? 2.5 : 1.8)) / state.zoom;
      ctx.stroke();

      // Vertices (draggable handles)
      const vr = (isSelected ? 4.5 : (isHovered ? 3.5 : 2.5)) / state.zoom;
      for (let i = 0; i < b.points.length; i++) {
        const vx = b.points[i][0] * state.previewScale;
        const vy = b.points[i][1] * state.previewScale;
        ctx.beginPath();
        ctx.arc(vx, vy, vr, 0, Math.PI * 2);
        ctx.fillStyle = isSelected ? "#ffffff" : col;
        ctx.fill();
        ctx.strokeStyle = isSelected ? "#000000" : "#ffffff";
        ctx.lineWidth = (isSelected ? 1.8 : 1.0) / state.zoom;
        ctx.stroke();
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
      const thick = (b.thickness !== undefined ? b.thickness : state.lineThickness) || 16;
      const renderThick = (thick * state.previewScale);

      // Draw semi-transparent buffer swath around line
      if (renderThick > 1) {
        ctx.save();
        ctx.strokeStyle = hexToRgba(col, isSelected ? 0.28 : (isHovered ? 0.24 : 0.16));
        ctx.lineWidth = renderThick;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(lx1, ly1);
        ctx.lineTo(lx2, ly2);
        ctx.stroke();
        ctx.restore();
      }

      // Hover glow for line
      if (isHovered) {
        ctx.save();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 4.5 / state.zoom;
        ctx.beginPath();
        ctx.moveTo(lx1, ly1);
        ctx.lineTo(lx2, ly2);
        ctx.stroke();
        ctx.restore();
      }

      ctx.strokeStyle = isSelected ? "#ffffff" : col;
      ctx.lineWidth = (isSelected ? 3.5 : (isHovered ? 2.8 : 2.0)) / state.zoom;
      ctx.beginPath();
      ctx.moveTo(lx1, ly1);
      ctx.lineTo(lx2, ly2);
      ctx.stroke();

      // Draw endpoint circles (draggable handles)
      const r = (isSelected ? 6.0 : (isHovered ? 4.5 : 3.0)) / state.zoom;
      ctx.fillStyle = isSelected ? "#ffffff" : col;
      ctx.strokeStyle = isSelected ? "#000000" : col;
      ctx.lineWidth = (isSelected ? 2.0 : 1.0) / state.zoom;

      ctx.beginPath();
      ctx.arc(lx1, ly1, r, 0, 2 * Math.PI);
      ctx.fill();
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(lx2, ly2, r, 0, 2 * Math.PI);
      ctx.fill();
      ctx.stroke();

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

      ctx.fillStyle = isSelected ? "rgba(255, 255, 255, 0.22)" : (isHovered ? "rgba(99, 179, 237, 0.22)" : hexToRgba(col, 0.12));
      ctx.fillRect(px, py, pw, ph);

      // Hover glow for box
      if (isHovered) {
        ctx.save();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 3.5 / state.zoom;
        ctx.strokeRect(px, py, pw, ph);
        ctx.restore();
      }

      ctx.strokeStyle = isSelected ? "#ffffff" : col;
      ctx.lineWidth = (isSelected ? 2.5 : (isHovered ? 2.0 : 1.5)) / state.zoom;
      ctx.strokeRect(px, py, pw, ph);

      ctx.fillStyle = col;
      ctx.fillRect(px, py - fontSize - 2, textW + 6, fontSize + 4);
      ctx.fillStyle = "#ffffff";
      ctx.fillText(labelText, px + 3, py - 2);

      // Draw 8 resize handles if selected
      if (isSelected) {
        const hs = Math.max(6, 8 / state.zoom);
        const half = hs / 2;
        const handles = [
          { x: px, y: py },                         // tl
          { x: px + pw / 2, y: py },                // t
          { x: px + pw, y: py },                    // tr
          { x: px + pw, y: py + ph / 2 },           // r
          { x: px + pw, y: py + ph },               // br
          { x: px + pw / 2, y: py + ph },           // b
          { x: px, y: py + ph },                    // bl
          { x: px, y: py + ph / 2 },                // l
        ];

        ctx.fillStyle = "#ffffff";
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = 1.5 / state.zoom;
        for (const h of handles) {
          ctx.fillRect(h.x - half, h.y - half, hs, hs);
          ctx.strokeRect(h.x - half, h.y - half, hs, hs);
        }
      }
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

  // Render Selection Cut PIP Preview
  updateSelectionPreview();
}

function updateSelectionPreview() {
  const pipContainer = document.getElementById("cut-preview-pip");
  const pipCanvas = document.getElementById("pip-canvas");
  const pipTitle = document.getElementById("pip-title");
  const pipInfo = document.getElementById("pip-info");

  if (!pipContainer || !pipCanvas || !state.imageLoaded || !state.image) {
    if (pipContainer) pipContainer.classList.add("hidden");
    return;
  }

  // Determine which item to preview
  let targetItem = null;

  if (state.isDrawing && state.currentDrawEnd) {
    if (state.activeTool === "line") {
      const x1 = Math.round(state.drawStartX);
      const y1 = Math.round(state.drawStartY);
      const x2 = Math.round(state.currentDrawEnd.x);
      const y2 = Math.round(state.currentDrawEnd.y);
      targetItem = {
        type: "line",
        label: state.activeClass,
        thickness: state.lineThickness || 16,
        x1, y1, x2, y2,
        x: Math.min(x1, x2),
        y: Math.min(y1, y2),
        width: Math.abs(x2 - x1),
        height: Math.abs(y2 - y1),
      };
    } else if (state.activeTool === "box") {
      const x1 = Math.round(Math.min(state.drawStartX, state.currentDrawEnd.x));
      const y1 = Math.round(Math.min(state.drawStartY, state.currentDrawEnd.y));
      const x2 = Math.round(Math.max(state.drawStartX, state.currentDrawEnd.x));
      const y2 = Math.round(Math.max(state.drawStartY, state.currentDrawEnd.y));
      targetItem = {
        type: "box",
        label: state.activeClass,
        x: x1,
        y: y1,
        width: Math.max(x2 - x1, 4),
        height: Math.max(y2 - y1, 4),
      };
    }
  } else if (state.activeTool === "polygon" && state.polygonPoints.length >= 2) {
    const allPts = state.cursorPt ? [...state.polygonPoints, state.cursorPt] : state.polygonPoints;
    const xs = allPts.map((p) => p.x);
    const ys = allPts.map((p) => p.y);
    const minX = Math.min(...xs);
    const minY = Math.min(...ys);
    targetItem = {
      type: "polygon",
      label: state.activeClass,
      x: minX,
      y: minY,
      width: Math.max(Math.max(...xs) - minX, 4),
      height: Math.max(Math.max(...ys) - minY, 4),
      points: allPts.map((p) => [p.x, p.y]),
    };
  } else if (state.selectedBoxId) {
    targetItem = state.boxes.find((b) => b.id === state.selectedBoxId);
  }

  if (!targetItem) {
    pipContainer.classList.add("hidden");
    return;
  }

  pipContainer.classList.remove("hidden");

  const pipCtx = pipCanvas.getContext("2d");
  const pw = pipCanvas.width;
  const ph = pipCanvas.height;

  pipCtx.fillStyle = "#0d1117";
  pipCtx.fillRect(0, 0, pw, ph);

  // Compute crop bounding box in original image space
  let cropX = targetItem.x;
  let cropY = targetItem.y;
  let cropW = Math.max(targetItem.width, 4);
  let cropH = Math.max(targetItem.height, 4);

  let title = "Selection Preview";
  let meta = `${Math.round(cropW)}x${Math.round(cropH)} px`;

  if (targetItem.type === "line") {
    const x1 = targetItem.x1 !== undefined ? targetItem.x1 : targetItem.x;
    const y1 = targetItem.y1 !== undefined ? targetItem.y1 : targetItem.y;
    const x2 = targetItem.x2 !== undefined ? targetItem.x2 : targetItem.x + targetItem.width;
    const y2 = targetItem.y2 !== undefined ? targetItem.y2 : targetItem.y + targetItem.height;
    const thick = targetItem.thickness || state.lineThickness || 16;
    const pad = Math.max(thick * 0.8, 16);
    cropX = Math.min(x1, x2) - pad;
    cropY = Math.min(y1, y2) - pad;
    cropW = Math.abs(x2 - x1) + pad * 2;
    cropH = Math.abs(y2 - y1) + pad * 2;
    const len = Math.hypot(x2 - x1, y2 - y1);
    title = `Streak (${thick}px width)`;
    meta = `L: ${Math.round(len)}px`;
  } else if (targetItem.type === "polygon") {
    const pad = 12;
    cropX = targetItem.x - pad;
    cropY = targetItem.y - pad;
    cropW = targetItem.width + pad * 2;
    cropH = targetItem.height + pad * 2;
    title = `Polygon Cut`;
    meta = `${Math.round(targetItem.width)}x${Math.round(targetItem.height)} px`;
  } else {
    title = `Box Cut (${targetItem.label.replace("_", " ")})`;
    meta = `${Math.round(cropW)}x${Math.round(cropH)} px`;
  }

  if (pipTitle) pipTitle.innerText = title;
  if (pipInfo) pipInfo.innerText = meta;

  // Convert crop rect to preview image bitmap coordinates
  const sx = Math.max(0, cropX * state.previewScale);
  const sy = Math.max(0, cropY * state.previewScale);
  const sw = Math.min(state.image.width - sx, cropW * state.previewScale);
  const sh = Math.min(state.image.height - sy, cropH * state.previewScale);

  if (sw <= 1 || sh <= 1) return;

  // Fit within PIP canvas with aspect ratio preserved
  const padding = 8;
  const availW = pw - padding * 2;
  const availH = ph - padding * 2;
  const fitZoom = Math.min(availW / sw, availH / sh);
  const zoom = Math.min(fitZoom, 8.0);

  const dw = sw * zoom;
  const dh = sh * zoom;
  const dx = (pw - dw) / 2;
  const dy = (ph - dh) / 2;

  pipCtx.imageSmoothingEnabled = zoom < 2.0;

  pipCtx.fillStyle = "#161b22";
  pipCtx.fillRect(dx, dy, dw, dh);

  // Draw cropped image region
  pipCtx.drawImage(state.image, sx, sy, sw, sh, dx, dy, dw, dh);

  // Helper coordinate mapper to pip canvas space
  const toPipX = (origX) => dx + (origX * state.previewScale - sx) * zoom;
  const toPipY = (origY) => dy + (origY * state.previewScale - sy) * zoom;

  const col = CLASS_COLORS[targetItem.label] || "#4299e1";

  // Overlay shape outline / swath
  if (targetItem.type === "line") {
    const x1 = targetItem.x1 !== undefined ? targetItem.x1 : targetItem.x;
    const y1 = targetItem.y1 !== undefined ? targetItem.y1 : targetItem.y;
    const x2 = targetItem.x2 !== undefined ? targetItem.x2 : targetItem.x + targetItem.width;
    const y2 = targetItem.y2 !== undefined ? targetItem.y2 : targetItem.y + targetItem.height;
    const thick = targetItem.thickness || state.lineThickness || 16;
    const pipThick = thick * state.previewScale * zoom;

    pipCtx.save();
    // Swath highlight
    pipCtx.strokeStyle = hexToRgba(col, 0.35);
    pipCtx.lineWidth = Math.max(2, pipThick);
    pipCtx.lineCap = "round";
    pipCtx.beginPath();
    pipCtx.moveTo(toPipX(x1), toPipY(y1));
    pipCtx.lineTo(toPipX(x2), toPipY(y2));
    pipCtx.stroke();

    // Centerline
    pipCtx.strokeStyle = "#ffffff";
    pipCtx.lineWidth = 1.2;
    pipCtx.beginPath();
    pipCtx.moveTo(toPipX(x1), toPipY(y1));
    pipCtx.lineTo(toPipX(x2), toPipY(y2));
    pipCtx.stroke();
    pipCtx.restore();
  } else if (targetItem.type === "polygon" && targetItem.points && targetItem.points.length >= 2) {
    pipCtx.save();
    pipCtx.strokeStyle = col;
    pipCtx.lineWidth = 1.5;
    pipCtx.beginPath();
    const p0 = targetItem.points[0];
    pipCtx.moveTo(toPipX(p0[0]), toPipY(p0[1]));
    for (let i = 1; i < targetItem.points.length; i++) {
      pipCtx.lineTo(toPipX(targetItem.points[i][0]), toPipY(targetItem.points[i][1]));
    }
    pipCtx.closePath();
    pipCtx.fillStyle = hexToRgba(col, 0.2);
    pipCtx.fill();
    pipCtx.stroke();
    pipCtx.restore();
  } else {
    // Box
    const bx = toPipX(targetItem.x);
    const by = toPipY(targetItem.y);
    const bw = targetItem.width * state.previewScale * zoom;
    const bh = targetItem.height * state.previewScale * zoom;

    pipCtx.strokeStyle = col;
    pipCtx.lineWidth = 1.5;
    pipCtx.strokeRect(bx, by, bw, bh);
  }

  // Draw fine 1px outer frame
  pipCtx.strokeStyle = "rgba(255, 255, 255, 0.15)";
  pipCtx.lineWidth = 1;
  pipCtx.strokeRect(dx, dy, dw, dh);
}

window.onload = init;
