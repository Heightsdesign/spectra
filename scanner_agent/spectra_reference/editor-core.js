/* Original-pixel geometry shared by the offline editor and deterministic Node tests. */
(function (root) {
  "use strict";
  const copy = value => structuredClone(value);
  function axes(corners, side) {
    const p = corners[side], q = corners[(side + 1) % 4];
    const edge = [q[0] - p[0], q[1] - p[1]], length = Math.hypot(...edge);
    return { p, edge, normal: [-edge[1] / length, edge[0] / length] };
  }
  function fromPoints(p, q) {
    if (![...p, ...q].every(Number.isFinite)) throw Error("Finite original-pixel endpoints required.");
    const a = p[1] - q[1], b = q[0] - p[0], c = p[0] * q[1] - q[0] * p[1];
    const length = Math.hypot(a, b);
    if (length < 1e-8) throw Error("The two handles must remain distinct.");
    return [a / length, b / length, c / length];
  }
  function atLine(corners, side, line, fraction) {
    const { p, edge, normal } = axes(corners, side);
    const origin = p.map((v, i) => v + fraction * edge[i]);
    const denominator = line[0] * normal[0] + line[1] * normal[1];
    if (!line.every(Number.isFinite) || Math.abs(denominator) / Math.hypot(line[0], line[1]) < 0.1) {
      throw Error("Line orientation is incompatible with this side. No approximation was saved.");
    }
    const distance = -(line[0] * origin[0] + line[1] * origin[1] + line[2]) / denominator;
    if (!Number.isFinite(distance)) throw Error("Invalid side line.");
    return { point: origin.map((v, i) => v + distance * normal[i]), distance };
  }
  function fromOffsets(corners, side, span, distances) {
    const { p, edge, normal } = axes(corners, side);
    const points = span.map((t, k) => p.map((v, i) => v + t * edge[i] + distances[k] * normal[i]));
    return { points, line: fromPoints(...points) };
  }
  function imageToCanvas(point, camera) {
    return point.map((v, i) => (v - camera.center[i]) * camera.zoom + [camera.width, camera.height][i] / 2);
  }
  function canvasToImage(point, camera) {
    return point.map((v, i) => camera.center[i] + (v - [camera.width, camera.height][i] / 2) / camera.zoom);
  }
  function clientToImage(point, bounds, camera) {
    return canvasToImage([(point[0] - bounds.left) * camera.width / bounds.width,
      (point[1] - bounds.top) * camera.height / bounds.height], camera);
  }
  function imageToClient(point, bounds, camera) {
    const pixel = imageToCanvas(point, camera);
    return [bounds.left + pixel[0] * bounds.width / camera.width,
      bounds.top + pixel[1] * bounds.height / camera.height];
  }
  function zoomAt(camera, canvasPoint, requested) {
    const anchor = canvasToImage(canvasPoint, camera), zoom = Math.max(0.25, Math.min(16, requested));
    return { ...camera, zoom, center: anchor.map((v, i) => v - (canvasPoint[i] - [camera.width, camera.height][i] / 2) / zoom) };
  }
  function move(points, start, pointer, endpoint = null, factor = 1) {
    const delta = pointer.map((v, i) => (v - start[i]) * factor);
    return points.map((p, index) => p.map((v, i) => endpoint === null || endpoint === index ? v + delta[i] : v));
  }
  function segmentDistance(point, a, b) {
    const edge = b.map((v, i) => v - a[i]), squared = edge[0] ** 2 + edge[1] ** 2;
    const t = squared ? Math.max(0, Math.min(1, ((point[0] - a[0]) * edge[0] + (point[1] - a[1]) * edge[1]) / squared)) : 0;
    return Math.hypot(point[0] - a[0] - t * edge[0], point[1] - a[1] - t * edge[1]);
  }
  class History {
    constructor(limit = 200) { this.limit = limit; this.past = []; this.future = []; }
    push(before, after, side) {
      if (JSON.stringify(before) === JSON.stringify(after)) return false;
      this.past.push({ before: copy(before), after: copy(after), side });
      if (this.past.length > this.limit) this.past.shift();
      this.future = []; return true;
    }
    undo() { const item = this.past.pop(); if (!item) return null; this.future.push(item); return { state: copy(item.before), side: item.side }; }
    redo() { const item = this.future.pop(); if (!item) return null; this.past.push(item); return { state: copy(item.after), side: item.side }; }
  }
  const api = { copy, axes, fromPoints, atLine, fromOffsets, imageToCanvas, canvasToImage,
    clientToImage, imageToClient, zoomAt, move, segmentDistance, History };
  root.SpectraReferenceGeometry = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
