"use strict";
const G = SpectraReferenceGeometry;
const data = JSON.parse(document.getElementById("data").textContent);
const evaluation = data.evaluation, reference = data.reference;
const corners = evaluation.physical_corners_pixels;
const $ = id => document.getElementById(id);
const canvas = $("view"), context = canvas.getContext("2d"), image = new Image();
const history = new G.History(), drafts = [null, null, null, null];
let current = 0, selection = null, gesture = null, preview = null, placement = null, spaceHeld = false;
let camera = { center: [0, 0], zoom: 1, width: canvas.width, height: canvas.height };
let unsaved = false;
const candidate = (side, id) => evaluation.sides[side].candidates.find(c => c.id === id);
const handlesFor = (side, line, span) => line ? span.map(t => G.atLine(corners, side, line, t).point) : null;
let state = {
  sides: G.copy(reference.sides),
  handles: reference.sides.map((s, i) => handlesFor(i, s.line_abc, s.valid_span_fraction)),
  initial: reference.sides.map((s, i) => {
    const c = candidate(i, s.candidate_id || s.basis_candidate_id);
    return c ? { id: c.id, line: G.copy(c.line_abc) } : null;
  }),
};
reference.sides = state.sides;

function bounds() {
  const r = canvas.getBoundingClientRect(), style = getComputedStyle(canvas);
  const left = parseFloat(style.borderLeftWidth), right = parseFloat(style.borderRightWidth);
  const top = parseFloat(style.borderTopWidth), bottom = parseFloat(style.borderBottomWidth);
  return { left: r.left + left, top: r.top + top, width: r.width - left - right, height: r.height - top - bottom };
}
function original(event, view = camera) { return G.clientToImage([event.clientX, event.clientY], bounds(), view); }
function error(message = "") { $("error").textContent = message; }
function mutate(action) {
  const before = G.copy(state);
  action();
  if (history.push(before, state, current)) unsaved = true;
  reference.sides = state.sides;
  loadControls(); draw();
}
function unconfirm(side) { if (side.status === "annotated") side.status = "unannotated"; }
function checkLine(line, side = current) {
  for (const t of state.sides[side].valid_span_fraction) G.atLine(corners, side, line, t);
}
function commitGeometry(points, line, definition = "manual", selectedCandidate = null) {
  checkLine(line);
  mutate(() => {
    const side = state.sides[current];
    const basis = side.candidate_id || side.basis_candidate_id || state.initial[current]?.id || null;
    unconfirm(side);
    Object.assign(side, { line_abc: G.copy(line), definition, candidate_id: selectedCandidate,
      basis_candidate_id: definition === "manual" ? basis : null });
    state.handles[current] = G.copy(points);
    drafts[current] = null;
  });
}
function chooseCandidate(id, reset = false) {
  if (!flushNumeric()) return;
  const c = reset ? state.initial[current] : candidate(current, id);
  if (!c) return;
  const line = G.copy(reset ? c.line : c.line_abc), cid = c.id;
  const points = handlesFor(current, line, state.sides[current].valid_span_fraction);
  checkLine(line);
  mutate(() => {
    if (!state.initial[current]) state.initial[current] = { id: cid, line: G.copy(line) };
    const side = state.sides[current];
    Object.assign(side, { line_abc: line, candidate_id: cid, basis_candidate_id: null, definition: "candidate", status: "unannotated" });
    state.handles[current] = points;
    drafts[current] = null;
  });
  selection = { side: current, endpoint: null }; draw();
}
function workflow(side) {
  if (side.status === "ambiguous") return "Ambiguous / uncertain - not confirmed.";
  if (side.status === "unannotatable") return "Unannotatable / absent - not confirmed.";
  if (!side.line_abc) return "Unannotated - choose a candidate or place a manual line.";
  if (side.status === "annotated") return "Confirmed / previously annotated status - verify provenance; not certified accuracy or independent validation.";
  return side.definition === "candidate" ? "Candidate selected - not independently verified. Review and explicitly confirm."
    : "Manual edit - review pending. Verify alignment and explicitly confirm.";
}
function setNumbers(line = state.sides[current].line_abc) {
  const span = state.sides[current].valid_span_fraction;
  $("span0").value = String(span[0]); $("span1").value = String(span[1]);
  for (const [id, t] of [["d0", span[0]], ["d1", span[1]]]) {
    $(id).value = line ? String(G.atLine(corners, current, line, t).distance) : "";
  }
}
function loadControls() {
  const side = state.sides[current];
  $("side").selectedIndex = current;
  $("candidate").replaceChildren(new Option("No candidate selected", ""));
  evaluation.sides[current].candidates.filter(c => c.line_abc).forEach(c => {
    $("candidate").add(new Option(`${c.id} | ${c.retention} | ${c.rejection_reasons.join(", ")}`, c.id));
  });
  $("candidate").value = side.candidate_id || "";
  $("status").value = side.status; $("sideNotes").value = side.notes || "";
  setNumbers();
  if (drafts[current]) for (const [key, value] of Object.entries(drafts[current].values)) $(key).value = value;
  $("reset").disabled = !state.initial[current];
  $("reset").textContent = "Reset initial candidate" + (state.initial[current] ? ` (${state.initial[current].id})` : " (none)");
  $("confirm").disabled = !side.line_abc;
}
function selectSide(index, focus = false) {
  flushNumeric(); // Invalid raw numerical drafts remain in drafts[index], never discarded.
  preview = null; placement = null; current = index;
  selection = state.sides[current].line_abc ? { side: current, endpoint: null } : null;
  loadControls();
  if (focus) focusAt(0.5); else draw();
  error(drafts[current] ? "Numerical draft retained. Fix it or explicitly discard it before exporting." : "");
}
function focusAt(t) {
  const points = state.handles[current];
  if (points) camera.center = points[0].map((v, i) => v + t * (points[1][i] - v));
  else {
    const { p, edge, normal } = G.axes(corners, current);
    camera.center = p.map((v, i) => v + t * edge[i] + 60 * normal[i]);
  }
  draw();
}
function stroke(points, color, width = 2, dash = []) {
  context.strokeStyle = color; context.lineWidth = width; context.setLineDash(dash);
  context.beginPath();
  points.forEach((p, i) => { const pixel = G.imageToCanvas(p, camera); if (!i) context.moveTo(...pixel); else context.lineTo(...pixel); });
  context.stroke(); context.setLineDash([]);
}
function paintLine(line, side, color, width = 2, dash = []) {
  if (!line) return;
  try { stroke([0, 1].map(t => G.atLine(corners, side, line, t).point), color, width, dash); } catch { /* Invalid drag preview is not committed. */ }
}
function draw() {
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.imageSmoothingEnabled = false;
  if (image.complete && image.naturalWidth) context.drawImage(image, camera.width / 2 - camera.center[0] * camera.zoom,
    camera.height / 2 - camera.center[1] * camera.zoom, image.width * camera.zoom, image.height * camera.zoom);
  stroke([...corners, corners[0]], "cyan");
  if ($("showCandidates").checked) evaluation.sides.forEach((s, i) => s.candidates.forEach(c => paintLine(c.line_abc, i, "magenta")));
  if ($("showReference").checked) state.sides.forEach((side, i) => {
    const dash = side.status === "annotated" ? [] : [6, 4];
    if (i === current) paintLine(side.line_abc, i, "white", 5, dash);
    paintLine(side.line_abc, i, "#18ef65", i === current ? 3 : 2, dash);
  });
  if (preview) paintLine(preview.line, current, "white", 2, [4, 4]);
  const points = preview?.points || state.handles[current];
  if (points && $("showReference").checked) points.forEach((point, index) => {
    const pixel = G.imageToCanvas(point, camera), radius = 7 * camera.width / bounds().width;
    context.beginPath(); context.arc(...pixel, radius, 0, Math.PI * 2);
    context.fillStyle = selection?.endpoint === index ? "white" : "#ffb84d"; context.fill();
    context.strokeStyle = "black"; context.lineWidth = 2; context.stroke();
    context.fillStyle = "white"; context.font = "14px system-ui"; context.fillText(String(index + 1), pixel[0] + radius + 3, pixel[1] - radius);
  });
  if (placement?.first) {
    const p = G.imageToCanvas(placement.first, camera); context.fillStyle = "white"; context.fillRect(p[0] - 3, p[1] - 3, 6, 6);
  }
  $("zoom").value = String(camera.zoom); $("zoomValue").textContent = `${camera.zoom.toFixed(2)}x`;
  $("workflow").textContent = `${state.sides[current].name}: ${workflow(state.sides[current])}`;
  $("undo").disabled = !history.past.length; $("redo").disabled = !history.future.length;
  const line = preview?.line || state.sides[current].line_abc;
  $("coordinates").textContent = line ? `${preview ? "PREVIEW" : "Stored"} a*x+b*y+c=0: ${JSON.stringify(line)}\nOriginal endpoints: ${JSON.stringify(points)}\nSelection: ${selection?.endpoint === null ? "entire line" : selection ? "endpoint " + (selection.endpoint + 1) : "none"}` : "No reference line. Place one manually without viewing detector candidates, or choose a candidate.";
  if (preview?.line && state.sides[current].line_abc) {
    try {
      const deltas = state.sides[current].valid_span_fraction.map(t => G.atLine(corners,current,preview.line,t).distance-G.atLine(corners,current,state.sides[current].line_abc,t).distance);
      $("coordinates").textContent += `\nChange from stored line at evaluation-span endpoints: ${JSON.stringify(deltas)} px (physical-side normal).`;
    } catch { /* Invalid preview remains visibly rejected by the error message. */ }
  }
  $("applied").textContent = JSON.stringify(state.sides[current], null, 2);
}
function readDraft(draft) {
  const v = draft.values, span = [Number(v.span0), Number(v.span1)];
  if (v.span0 === "" || v.span1 === "" || !span.every(Number.isFinite) || !(0 <= span[0] && span[0] < span[1] && span[1] <= 1)) throw Error("Span must satisfy 0 <= start < end <= 1.");
  if (draft.kind === "span" && state.sides[current].line_abc) {
    const line = G.copy(state.sides[current].line_abc);
    return { span, line, points: handlesFor(current, line, span) };
  }
  if (v.d0 === "" || v.d1 === "" || ![Number(v.d0), Number(v.d1)].every(Number.isFinite)) throw Error("Both finite offsets are required. Numerical draft retained.");
  return { span, ...G.fromOffsets(corners, current, span, [Number(v.d0), Number(v.d1)]) };
}
function numericInput(kind) {
  let actualKind = kind;
  if (kind === "span" && drafts[current]?.kind === "manual") actualKind = "manual";
  if (kind === "span") {
    const line = preview?.line || state.sides[current].line_abc;
    if (line) try {
      $("d0").value = String(G.atLine(corners, current, line, Number($("span0").value)).distance);
      $("d1").value = String(G.atLine(corners, current, line, Number($("span1").value)).distance);
    } catch { /* Preserve invalid input for correction. */ }
  }
  drafts[current] = { kind: actualKind, values: Object.fromEntries(["span0", "span1", "d0", "d1"].map(id => [id, $(id).value])) };
  try { preview = { ...readDraft(drafts[current]), kind: "numeric" }; error(); } catch (e) { preview = null; error(e.message); }
  draw();
}
function flushNumeric() {
  const draft = drafts[current];
  if (!draft) return true;
  try {
    const proposal = readDraft(draft); checkLine(proposal.line);
    mutate(() => {
      const side = state.sides[current]; unconfirm(side);
      if (draft.kind === "manual") {
        side.basis_candidate_id = side.candidate_id || side.basis_candidate_id || null;
        side.definition = "manual"; side.candidate_id = null;
      }
      side.line_abc = proposal.line; side.valid_span_fraction = proposal.span;
      state.handles[current] = proposal.points; drafts[current] = null;
    });
    preview = null; error(); draw(); return true;
  } catch (e) { error(e.message); return false; }
}
function hit(event) {
  if (!$("showReference").checked) return null;
  const pointer = [event.clientX, event.clientY], box = bounds();
  const points = state.handles[current];
  if (points) for (let i = 0; i < 2; i++) {
    const p = G.imageToClient(points[i], box, camera);
    if (Math.hypot(p[0] - pointer[0], p[1] - pointer[1]) <= 11) return { side: current, endpoint: i };
  }
  const indices = [current, ...[0, 1, 2, 3].filter(i => i !== current)];
  for (const side of indices) {
    const line = state.sides[side].line_abc;
    if (!line) continue;
    const p = [0, 1].map(t => G.imageToClient(G.atLine(corners, side, line, t).point, box, camera));
    if (G.segmentDistance(pointer, ...p) <= 8) return { side, endpoint: null };
  }
  return null;
}
function cancelGesture() {
  if (gesture?.mode === "pan") camera = gesture.camera;
  gesture = null; preview = null; placement = null; draw();
}
canvas.addEventListener("pointerdown", event => {
  if (event.button !== 0 && event.button !== 1) return;
  if (!flushNumeric()) return;
  canvas.focus(); error();
  const pan = event.button === 1 || spaceHeld || $("panMode").checked;
  const pointer = original(event);
  if (placement && !pan) {
    if (!placement.first) { placement.first = pointer; draw(); return; }
    try { const points = [placement.first, pointer], line = G.fromPoints(...points); commitGeometry(points, line); placement = null; preview = null; selection = { side: current, endpoint: null }; draw(); } catch (e) { error(e.message); }
    return;
  }
  const selected = pan ? null : hit(event);
  if (selected && selected.side !== current) selectSide(selected.side);
  if (selected) selection = selected;
  else if (!pan) selection = null;
  gesture = { mode: selected ? "edit" : "pan", pointer: pointer, camera: G.copy(camera),
    points: selected ? G.copy(state.handles[current]) : null, line: selected ? G.copy(state.sides[current].line_abc) : null,
    endpoint: selected?.endpoint ?? null, factor: event.shiftKey || $("fine").checked ? 0.1 : 1, moved: false, valid: true };
  canvas.setPointerCapture(event.pointerId); draw();
});
function updateGesture(event) {
  const pointer = original(event, gesture?.camera || camera);
  if (gesture) {
    gesture.moved = gesture.moved || Math.hypot(...pointer.map((v, i) => v - gesture.pointer[i])) > 1e-10;
    if (gesture.mode === "pan") camera.center = gesture.camera.center.map((v, i) => v - pointer[i] + gesture.pointer[i]);
    else {
      const points = G.move(gesture.points, gesture.pointer, pointer, gesture.endpoint, gesture.factor);
      const delta = points[0].map((v, i) => v - gesture.points[0][i]);
      try {
        const line = gesture.endpoint === null ? [gesture.line[0], gesture.line[1], gesture.line[2] - gesture.line[0] * delta[0] - gesture.line[1] * delta[1]] : G.fromPoints(...points);
        preview = { points, line, kind: "drag" };
        checkLine(line); gesture.valid = true; error(); setNumbers(line);
      } catch (e) { gesture.valid = false; preview = { points, line: null, kind: "drag" }; error(e.message); }
    }
    draw();
  } else if (placement?.first) {
    try { preview = { points: [placement.first, pointer], line: G.fromPoints(placement.first, pointer), kind: "placement" }; draw(); } catch { /* Coincident cursor before movement. */ }
  }
}
canvas.addEventListener("pointermove", event => {
  updateGesture(event);
  const { p, normal } = G.axes(corners, current), position = original(event);
  $("pointer").textContent = `Original x=${position[0].toFixed(4)}, y=${position[1].toFixed(4)} px; inward offset from physical side=${position.reduce((sum, v, i) => sum + (v - p[i]) * normal[i], 0).toFixed(4)} px`;
});
canvas.addEventListener("pointerup", event => {
  if (!gesture) return;
  updateGesture(event); // Include the final release coordinate, even without a final move event.
  const completed = gesture, proposal = preview;
  gesture = null; preview = null;
  if (completed.mode === "edit" && completed.moved && completed.valid && proposal) {
    try { commitGeometry(proposal.points, proposal.line); } catch (e) { error(e.message); }
  } else loadControls();
  if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
  draw();
});
canvas.addEventListener("pointercancel", cancelGesture);
canvas.addEventListener("lostpointercapture", () => { if (gesture) cancelGesture(); });
canvas.addEventListener("wheel", event => {
  event.preventDefault(); if (gesture) return;
  const p = original(event), pixel = G.imageToCanvas(p, camera);
  camera = G.zoomAt(camera, pixel, camera.zoom * Math.exp(-event.deltaY * (event.deltaMode === 1 ? 0.04 : 0.002)));
  draw();
}, { passive: false });
function restore(change) {
  if (!change) return;
  cancelGesture(); state = change.state; reference.sides = state.sides; current = change.side;
  selection = state.sides[current].line_abc ? { side: current, endpoint: null } : null;
  loadControls(); unsaved = true; error(); draw();
}
$("undo").onclick = () => { if (flushNumeric()) restore(history.undo()); };
$("redo").onclick = () => { if (!drafts.some(Boolean)) restore(history.redo()); };
document.addEventListener("keydown", event => {
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return;
  if (event.code === "Space") { event.preventDefault(); spaceHeld = true; }
  if (event.key === "Escape") { cancelGesture(); selection = null; loadControls(); draw(); }
  if ((event.ctrlKey || event.metaKey) && ["z", "y"].includes(event.key.toLowerCase())) {
    event.preventDefault(); (event.key.toLowerCase() === "y" || event.shiftKey ? $("redo") : $("undo")).click(); return;
  }
  const vector = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
  if (!vector || event.target !== canvas || gesture || placement || !flushNumeric()) return;
  event.preventDefault();
  if (selection && state.handles[current]) {
    try {
      const points = G.move(state.handles[current], [0, 0], vector, selection.endpoint, event.shiftKey || $("fine").checked ? 0.1 : 1);
      const line = selection.endpoint === null ? [state.sides[current].line_abc[0], state.sides[current].line_abc[1], state.sides[current].line_abc[2] - state.sides[current].line_abc[0] * vector[0] * (event.shiftKey || $("fine").checked ? 0.1 : 1) - state.sides[current].line_abc[1] * vector[1] * (event.shiftKey || $("fine").checked ? 0.1 : 1)] : G.fromPoints(...points);
      commitGeometry(points, line);
    } catch (e) { error(e.message); }
  } else { camera.center = camera.center.map((v, i) => v + vector[i] * 10 / camera.zoom); draw(); }
});
document.addEventListener("keyup", event => { if (event.code === "Space") spaceHeld = false; });
window.addEventListener("blur", () => { spaceHeld = false; if (gesture) cancelGesture(); });
$("candidate").onchange = () => { if ($("candidate").value) chooseCandidate($("candidate").value); };
$("side").onchange = () => selectSide($("side").selectedIndex, true);
$("reset").onclick = () => chooseCandidate(null, true);
$("confirm").onclick = () => {
  if (!flushNumeric() || gesture || placement || !state.sides[current].line_abc) return;
  mutate(() => { state.sides[current].status = "annotated"; }); error();
};
$("status").onchange = () => {
  const status = $("status").value;
  if (status === "annotated") { loadControls(); return; }
  mutate(() => { state.sides[current].status = status; });
};
$("sideNotes").onchange = () => { const notes = $("sideNotes").value; mutate(() => { state.sides[current].notes = notes; }); };
$("place").onclick = () => { if (!flushNumeric()) return; placement = { first: null }; selection = null; error("Click two points on the intended reference line. Escape cancels."); canvas.focus(); };
$("clear").onclick = () => mutate(() => {
  Object.assign(state.sides[current], { line_abc: null, definition: null, candidate_id: null, basis_candidate_id: null, status: "unannotated" });
  state.handles[current] = null; drafts[current] = null; selection = null; preview = null;
});
for (const id of ["d0", "d1", "span0", "span1"]) {
  $(id).oninput = () => numericInput(id.startsWith("span") ? "span" : "manual");
  $(id).onchange = flushNumeric;
}
$("apply").onclick = flushNumeric;
$("discardDraft").onclick = () => { drafts[current] = null; preview = null; loadControls(); error(); draw(); };
$("zoom").oninput = () => { if (!gesture) { camera = G.zoomAt(camera, [camera.width / 2, camera.height / 2], Number($("zoom").value)); draw(); } };
for (const id of ["showCandidates", "showReference"]) $(id).onchange = draw;
$("start").onclick = () => focusAt(0); $("middle").onclick = () => focusAt(0.5); $("end").onclick = () => focusAt(1);
$("download").onclick = () => {
  if (gesture || placement) { error("Finish or cancel the current gesture before exporting."); return; }
  if (!flushNumeric() || drafts.some(Boolean)) { error("Fix or explicitly discard the retained numerical drafts before exporting."); return; }
  if (!$("annotationId").value.trim()) { error("Provide an operator annotation identifier."); return; }
  reference.sides = G.copy(state.sides);
  reference.annotation_id = $("annotationId").value.trim(); reference.layout_status = $("layout").value;
  reference.operator_notes = $("notes").value; reference.annotated_at_utc = new Date().toISOString();
  reference.annotation_version = crypto.randomUUID();
  const blob = new Blob([JSON.stringify(reference, null, 2) + "\n"], { type: "application/json" });
  const url = URL.createObjectURL(blob), anchor = document.createElement("a");
  anchor.href = url; anchor.download = `spectra-reference-${reference.annotation_version}.json`; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 3000); unsaved = false; error();
};
for (const id of ["annotationId", "notes", "layout"]) $(id).addEventListener("input", () => { unsaved = true; });
window.addEventListener("beforeunload", event => { if (unsaved || drafts.some(Boolean) || gesture || placement) { event.preventDefault(); event.returnValue = ""; } });
$("annotationId").value = reference.annotation_id; $("layout").value = reference.layout_status;
$("notes").value = reference.operator_notes; $("provenance").textContent = JSON.stringify(reference.provenance, null, 2);
image.onload = () => { loadControls(); focusAt(0.5); };
image.src = data.image;
