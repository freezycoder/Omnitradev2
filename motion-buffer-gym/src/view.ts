import { CHARACTERS, type CharacterId } from "./engine/characters";
import { toForwardRelative } from "./engine/facing";
import { buttonName, MOTION_IDS, MOTION_STEPS, motionName, windowsFor } from "./engine/motions";
import { formatFrames, FRAME_MS } from "./engine/time";
import { assertNever, type DirectionEvent, type Facing, type InputSource, type Numpad } from "./engine/types";
import type { TimelineItem } from "./model";

export interface ViewState {
  readonly characterId: CharacterId;
  readonly bufferFrames: number;
  readonly windowScale: number;
  readonly facing: Facing;
  readonly held: Numpad;
  readonly entries: readonly DirectionEvent[];
  readonly timeline: readonly TimelineItem[];
  readonly source: InputSource;
  readonly padConnected: boolean;
  readonly origin: number;
}

export interface GymHandlers {
  readonly onCharacter: (id: CharacterId) => void;
  readonly onBufferFrames: (frames: number) => void;
  readonly onWindowScale: (scale: number) => void;
  readonly onFacing: () => void;
  readonly onPunch: () => void;
  readonly onKick: () => void;
  readonly onHoldDirection: (direction: Numpad) => void;
  readonly onReleaseDirection: () => void;
}

const PAD_DIRECTIONS: readonly Numpad[] = [7, 8, 9, 4, 5, 6, 1, 2, 3];

export function mountGym(handlers: GymHandlers): { paint: (state: ViewState) => void } {
  const root = must("app");
  root.innerHTML = `
    <div class="app">
      <header class="top">
        <div>
          <p class="kicker">Combo gym</p>
          <h1>Motion Buffer</h1>
        </div>
        <div class="top-actions">
          <div id="input-source" data-source="keyboard">
            <span class="source-dot"></span>
            <span id="input-source-label">Keyboard</span>
            <span id="pad-status">No pad</span>
          </div>
          <button id="facing-toggle" type="button">Facing right</button>
        </div>
      </header>
      <div class="layout">
        <section class="play panel">
          <div id="direction-stage">
            <div id="direction-ring" aria-hidden="true"></div>
            <div id="numpad"></div>
          </div>
          <p id="held-direction"></p>
          <div id="buffer-sequence"></div>
          <p id="facing-note"></p>
          <ul id="motion-legend"></ul>
          <div class="attacks">
            <button id="punch" type="button">Punch <kbd>J</kbd></button>
            <button id="kick" type="button">Kick <kbd>K</kbd></button>
          </div>
          <p class="hint">Arrows or numpad 1–9. 5 is neutral. F flips facing. Gamepad: left stick or d-pad, face buttons bottom/left punch and right/top kick.</p>
        </section>
        <section class="timeline-panel panel">
          <div class="timeline-head">
            <h2>Timeline</h2>
            <p>Inputs and button judgments. Newest stays in view.</p>
          </div>
          <div id="timeline" role="log" aria-live="polite"></div>
        </section>
      </div>
      <section id="fixture-panel" class="panel">
        <div id="characters"></div>
        <div class="sliders">
          <label class="slider" for="buffer-slider">
            <span>Buffer length <strong id="buffer-value"></strong></span>
            <input id="buffer-slider" type="range" min="4" max="40" step="1" value="15" />
          </label>
          <label class="slider" for="scale-slider">
            <span>Step window scale <strong id="scale-value"></strong></span>
            <input id="scale-slider" type="range" min="0.25" max="2" step="0.05" value="1" />
          </label>
        </div>
        <div>
          <p class="section-label">Effective step windows</p>
          <div id="effective-windows"></div>
        </div>
      </section>
    </div>
  `;

  const numpad = must("numpad");
  for (const direction of PAD_DIRECTIONS) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "dir";
    cell.dataset.direction = String(direction);
    cell.tabIndex = -1;
    cell.textContent = String(direction);
    cell.setAttribute("aria-label", `Direction ${direction}`);
    cell.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      handlers.onHoldDirection(direction);
    });
    cell.addEventListener("pointerenter", (event) => {
      if (event.buttons !== 1) return;
      handlers.onHoldDirection(direction);
    });
    numpad.append(cell);
  }

  window.addEventListener("pointerup", () => handlers.onReleaseDirection());
  window.addEventListener("pointercancel", () => handlers.onReleaseDirection());

  const characters = must("characters");
  for (const character of CHARACTERS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "character";
    button.dataset.character = character.id;
    button.addEventListener("click", () => handlers.onCharacter(character.id));

    const name = document.createElement("span");
    name.className = "character-name";
    name.textContent = character.name;
    const summary = document.createElement("span");
    summary.className = "character-summary";
    summary.textContent = character.summary;
    const meta = document.createElement("span");
    meta.className = "character-meta";
    meta.textContent = `Fixture ${character.bufferFrames}f`;
    button.append(name, summary, meta);
    characters.append(button);
  }

  const legend = must("motion-legend");
  for (const id of MOTION_IDS) {
    const item = document.createElement("li");
    const name = document.createElement("strong");
    name.textContent = motionName(id);
    item.append(name, document.createTextNode(` ${MOTION_STEPS[id].join(" → ")}`));
    legend.append(item);
  }

  must<HTMLButtonElement>("facing-toggle").addEventListener("click", () => handlers.onFacing());
  must<HTMLButtonElement>("punch").addEventListener("click", () => handlers.onPunch());
  must<HTMLButtonElement>("kick").addEventListener("click", () => handlers.onKick());
  must<HTMLInputElement>("buffer-slider").addEventListener("input", (event) => {
    const target = event.currentTarget;
    if (!(target instanceof HTMLInputElement)) return;
    handlers.onBufferFrames(Math.round(Number(target.value)));
  });
  must<HTMLInputElement>("scale-slider").addEventListener("input", (event) => {
    const target = event.currentTarget;
    if (!(target instanceof HTMLInputElement)) return;
    handlers.onWindowScale(Math.round(Number(target.value) * 100) / 100);
  });

  return {
    paint(state) {
      paintFacing(state.facing);
      paintSource(state.source, state.padConnected);
      paintHeld(state.held, state.entries);
      paintSequence(state.entries);
      paintCharacters(state.characterId);
      paintSliders(state);
      paintWindows(state);
      paintTimeline(state);
      must("facing-note").textContent = facingNote(state.facing);
    },
  };
}

function paintFacing(facing: Facing): void {
  const button = must<HTMLButtonElement>("facing-toggle");
  switch (facing) {
    case "right":
      button.textContent = "Facing right";
      button.setAttribute("aria-pressed", "false");
      return;
    case "left":
      button.textContent = "Facing left";
      button.setAttribute("aria-pressed", "true");
      return;
    default:
      assertNever(facing);
  }
}

function facingNote(facing: Facing): string {
  switch (facing) {
    case "right":
      return "Forward is 6. Motions are matched on this numpad.";
    case "left":
      return "Forward is 4. The matcher mirrors 6↔4, 3↔1, and 9↔7.";
    default:
      return assertNever(facing);
  }
}

function paintSource(source: InputSource, padConnected: boolean): void {
  const chip = must("input-source");
  chip.dataset.source = source;
  must("input-source-label").textContent = sourceLabel(source);
  must("pad-status").textContent = padConnected ? "Pad connected" : "No pad";
}

function sourceLabel(source: InputSource): string {
  switch (source) {
    case "keyboard":
      return "Keyboard";
    case "gamepad":
      return "Gamepad";
    default:
      return assertNever(source);
  }
}

function paintHeld(held: Numpad, entries: readonly DirectionEvent[]): void {
  const present = new Set(entries.map((entry) => entry.direction));
  for (const direction of PAD_DIRECTIONS) {
    const cell = document.querySelector<HTMLButtonElement>(`[data-direction="${direction}"]`);
    if (!cell) continue;
    cell.classList.toggle("is-held", direction === held);
    cell.classList.toggle("in-buffer", present.has(direction));
  }
  must("held-direction").textContent = `Held ${held}`;
  paintRing(entries);
}

function paintRing(entries: readonly DirectionEvent[]): void {
  const ring = must("direction-ring");
  ring.replaceChildren();
  const visible = entries.slice(-16);
  const count = visible.length;
  visible.forEach((entry, index) => {
    const token = document.createElement("span");
    token.className = "token";
    if (index === count - 1) token.classList.add("is-newest");
    token.textContent = String(entry.direction);
    const age = count - 1 - index;
    const angle = -Math.PI / 2 - (count === 1 ? 0 : (age / count) * Math.PI * 2);
    const radius = 40;
    token.style.left = `${50 + Math.cos(angle) * radius}%`;
    token.style.top = `${50 + Math.sin(angle) * radius}%`;
    token.style.opacity = String(0.4 + (0.6 * (index + 1)) / count);
    ring.append(token);
  });
}

function paintSequence(entries: readonly DirectionEvent[]): void {
  const sequence = must("buffer-sequence");
  sequence.replaceChildren();
  const label = document.createElement("span");
  label.className = "sequence-label";
  label.textContent = "Ring";
  sequence.append(label);
  if (entries.length === 0) {
    const empty = document.createElement("span");
    empty.className = "sequence-empty";
    empty.textContent = "empty";
    sequence.append(empty);
    return;
  }
  entries.forEach((entry, index) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    if (index === entries.length - 1) chip.classList.add("is-newest");
    chip.textContent = String(entry.direction);
    sequence.append(chip);
  });
}

function paintCharacters(active: CharacterId): void {
  for (const character of CHARACTERS) {
    const button = document.querySelector<HTMLButtonElement>(`[data-character="${character.id}"]`);
    if (!button) continue;
    const selected = character.id === active;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  }
}

function paintSliders(state: ViewState): void {
  setRange(must<HTMLInputElement>("buffer-slider"), state.bufferFrames);
  setRange(must<HTMLInputElement>("scale-slider"), state.windowScale);
  must("buffer-value").textContent = `${state.bufferFrames}f`;
  must("scale-value").textContent = `${state.windowScale.toFixed(2)}×`;
}

function paintWindows(state: ViewState): void {
  const character = CHARACTERS.find((candidate) => candidate.id === state.characterId);
  if (!character) return;
  const root = must("effective-windows");
  root.replaceChildren();
  for (const id of MOTION_IDS) {
    const steps = MOTION_STEPS[id];
    const gaps = windowsFor(character.windows, id);
    const row = document.createElement("p");
    row.className = "window-row";
    const name = document.createElement("strong");
    name.textContent = motionName(id);
    const detail = gaps
      .map((gap, index) => `${steps[index]}→${steps[index + 1]} ${formatFrames(gap * state.windowScale)}`)
      .join(" · ");
    row.append(name, document.createTextNode(` ${detail}`));
    root.append(row);
  }
}

function paintTimeline(state: ViewState): void {
  const timeline = must("timeline");
  timeline.replaceChildren();
  if (state.timeline.length === 0) {
    const empty = document.createElement("p");
    empty.className = "timeline-empty";
    empty.textContent = "Change direction, then press punch or kick.";
    timeline.append(empty);
    return;
  }
  for (const item of state.timeline) {
    timeline.append(paintTimelineItem(item, state.origin));
  }
  timeline.scrollTop = timeline.scrollHeight;
}

function paintTimelineItem(item: TimelineItem, origin: number): HTMLElement {
  switch (item.kind) {
    case "direction":
      return paintDirectionItem(item, origin);
    case "judgment":
      return paintJudgmentItem(item, origin);
    default:
      return assertNever(item);
  }
}

function paintDirectionItem(item: Extract<TimelineItem, { kind: "direction" }>, origin: number): HTMLElement {
  const row = document.createElement("article");
  row.className = "event direction";
  row.append(stamp(item.time, origin), pill("Input", "input"), textLine(String(item.direction)));
  return row;
}

function paintJudgmentItem(item: Extract<TimelineItem, { kind: "judgment" }>, origin: number): HTMLElement {
  const matched = item.motion !== null;
  const row = document.createElement("article");
  row.className = matched ? "event judgment match" : "event judgment fail";
  row.dataset.outcome = matched ? "match" : "fail";
  if (item.motion) row.dataset.motion = item.motion;
  const title = document.createElement("p");
  title.className = "event-title";
  const motion = document.createElement("strong");
  motion.textContent = item.motion ? motionName(item.motion) : "No motion";
  title.append(motion, document.createTextNode(` · ${buttonName(item.button)}`));
  const body = document.createElement("div");
  body.className = "event-body";
  body.append(title, textLine(formatConsidered(item)));
  row.append(stamp(item.time, origin), pill(matched ? "Match" : "Fail", matched ? "match" : "fail"), body);
  return row;
}

function formatConsidered(item: Extract<TimelineItem, { kind: "judgment" }>): string {
  const physical = item.considered.map((direction) => String(direction)).join(" ") || "—";
  switch (item.facing) {
    case "right":
      return physical;
    case "left": {
      const forward =
        item.considered.map((direction) => String(toForwardRelative(direction, item.facing))).join(" ") || "—";
      return `${physical} → ${forward}`;
    }
    default:
      return assertNever(item.facing);
  }
}

function stamp(time: number, origin: number): HTMLElement {
  const node = document.createElement("span");
  node.className = "stamp";
  node.textContent = `${Math.round((time - origin) / FRAME_MS)}f`;
  return node;
}

function pill(label: string, tone: "input" | "match" | "fail"): HTMLElement {
  const node = document.createElement("span");
  node.className = `pill ${tone}`;
  node.textContent = label;
  return node;
}

function textLine(value: string): HTMLElement {
  const node = document.createElement("p");
  node.className = "event-text";
  node.textContent = value;
  return node;
}

function setRange(input: HTMLInputElement, value: number): void {
  if (Number(input.value) !== value) input.value = String(value);
}

function must<T extends HTMLElement = HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing #${id}`);
  return node as T;
}
