import * as THREE from "three";
import { OrbitControls } from "/static/vendor/three/OrbitControls.js";

const COLORS = { L: "#3b82f6", R: "#f97316", C: "#e5e7eb" };

const $ = (id) => document.getElementById(id);
const sections = ["capture", "processing", "preview", "saved", "failed"];

let current = null; // { id, preview, file }
let viewer = null;

function show(name) {
  for (const s of sections) $(s).hidden = s !== name;
}

function sideColor(name) {
  if (name.includes(".L")) return COLORS.L;
  if (name.includes(".R")) return COLORS.R;
  return COLORS.C;
}

function fail(message) {
  $("error-text").textContent = message;
  show("failed");
}

async function refreshModelNote() {
  try {
    const status = await (await fetch("/api/status")).json();
    $("model-note").textContent = status.model_loaded
      ? ""
      : "The model loads with the first photo, which takes a few extra seconds.";
    return status.model_loaded;
  } catch {
    return true;
  }
}

async function submit(file) {
  if (!file) return;
  const loaded = await refreshModelNote();
  $("processing-text").textContent = loaded
    ? "Estimating pose…"
    : "Loading the model and estimating pose…";
  show("processing");

  const form = new FormData();
  form.append("photo", file);
  let response;
  try {
    response = await fetch("/api/poses", { method: "POST", body: form });
  } catch (e) {
    fail(`Could not reach manikin: ${e.message}`);
    return;
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    fail(body.error || `Request failed (${response.status})`);
    return;
  }
  current = { id: body.id, preview: body.preview, file };
  $("pose-name").value = "";
  showPreview();
}

async function showPreview() {
  const { preview, file } = current;
  show("preview");
  selectTab("photo");

  const warnings = $("warnings");
  warnings.replaceChildren(
    ...preview.warnings.map((w) => Object.assign(document.createElement("li"), { textContent: w })),
  );

  await drawOverlay(file, preview);
  if (viewer) viewer.dispose();
  viewer = createViewer($("view-3d"), preview);
}

async function drawOverlay(file, preview) {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const canvas = $("overlay");
  const maxWidth = 1280;
  const scale = Math.min(1, maxWidth / bitmap.width);
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

  // Joint pixels refer to the upright photo the server decoded.
  const k = canvas.width / preview.image_size[0];
  const pt = (name) => preview.image_points[name].map((v) => v * k);
  const width = Math.max(2, canvas.width / 200);
  ctx.lineCap = "round";
  ctx.lineWidth = width;
  for (const [a, b] of preview.edges) {
    ctx.strokeStyle = sideColor(a + b);
    ctx.beginPath();
    ctx.moveTo(...pt(a));
    ctx.lineTo(...pt(b));
    ctx.stroke();
  }
  for (const name of Object.keys(preview.image_points)) {
    const [x, y] = pt(name);
    ctx.fillStyle = sideColor(name);
    ctx.beginPath();
    ctx.arc(x, y, width * 1.3, 0, Math.PI * 2);
    ctx.fill();
  }
}

// Pose joints use Blender axes (Z up, subject facing -Y); three.js uses Y up.
function toThree([x, y, z]) {
  return new THREE.Vector3(x, z, -y);
}

function createViewer(container, preview) {
  container.hidden = false; // Measure while visible; selectTab hides it again.
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  container.replaceChildren(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#0b0f19");
  scene.add(new THREE.HemisphereLight("#ffffff", "#334155", 2.5));

  const joints = Object.fromEntries(
    Object.entries(preview.joints).map(([name, p]) => [name, toThree(p)]),
  );
  const minY = Math.min(...Object.values(joints).map((p) => p.y));
  const grid = new THREE.GridHelper(3, 12, "#475569", "#1e293b");
  grid.position.y = minY;
  scene.add(grid);

  const materials = {};
  const material = (color) =>
    (materials[color] ??= new THREE.MeshStandardMaterial({ color, roughness: 0.6 }));
  const up = new THREE.Vector3(0, 1, 0);
  for (const [a, b] of preview.edges) {
    const start = joints[a];
    const end = joints[b];
    const length = start.distanceTo(end);
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, length, 10), material(sideColor(a + b)));
    mesh.position.copy(start).add(end).multiplyScalar(0.5);
    mesh.quaternion.setFromUnitVectors(up, end.clone().sub(start).normalize());
    scene.add(mesh);
  }
  const sphere = new THREE.SphereGeometry(0.03, 12, 8);
  for (const [name, p] of Object.entries(joints)) {
    const mesh = new THREE.Mesh(sphere, material(sideColor(name)));
    mesh.position.copy(p);
    scene.add(mesh);
  }

  const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 50);
  camera.position.set(0, 0.2, 3.2);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0.1, 0);
  controls.update();

  let frame = 0;
  const resize = () => {
    const { clientWidth: w, clientHeight: h } = container;
    if (w === 0 || h === 0) return;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  const loop = () => {
    frame = requestAnimationFrame(loop);
    if (!container.hidden) {
      resize();
      renderer.render(scene, camera);
    }
  };
  loop();

  return {
    dispose() {
      cancelAnimationFrame(frame);
      controls.dispose();
      renderer.dispose();
    },
  };
}

function selectTab(name) {
  $("tab-photo").setAttribute("aria-selected", String(name === "photo"));
  $("tab-3d").setAttribute("aria-selected", String(name === "3d"));
  $("view-photo").hidden = name !== "photo";
  $("view-3d").hidden = name !== "3d";
}

async function discard() {
  if (current) {
    fetch(`/api/poses/${current.id}`, { method: "DELETE" }).catch(() => {});
  }
  current = null;
  restart();
}

async function accept() {
  const button = $("accept");
  button.disabled = true;
  try {
    const response = await fetch(`/api/poses/${current.id}/accept`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("pose-name").value.trim() }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      fail(body.error || `Saving failed (${response.status})`);
      return;
    }
    current = null;
    $("saved-name").textContent = body.saved;
    show("saved");
  } catch (e) {
    fail(`Could not reach manikin: ${e.message}`);
  } finally {
    button.disabled = false;
  }
}

function restart() {
  for (const input of [$("camera-input"), $("file-input")]) input.value = "";
  show("capture");
  refreshModelNote();
}

$("camera-input").addEventListener("change", (e) => submit(e.target.files[0]));
$("file-input").addEventListener("change", (e) => submit(e.target.files[0]));
$("tab-photo").addEventListener("click", () => selectTab("photo"));
$("tab-3d").addEventListener("click", () => selectTab("3d"));
$("retake").addEventListener("click", discard);
$("accept").addEventListener("click", accept);
$("again").addEventListener("click", restart);
$("try-again").addEventListener("click", restart);

restart();
