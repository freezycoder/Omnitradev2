import { describe, expect, it } from "vitest";
import { CHARACTERS } from "./characters";
import { evaluateMotions, type Evaluation } from "./matcher";
import { MOTION_IDS, MOTION_STEPS, windowsFor, type MotionWindows } from "./motions";
import { FRAME_MS } from "./time";
import type { DirectionEvent, Facing, MotionId, Numpad } from "./types";

const windows: MotionWindows = {
  qcf: [12, 12],
  dp: [8, 8],
  hcf: [12, 12, 12, 12],
};

const wideWindows: MotionWindows = {
  qcf: [30, 30],
  dp: [30, 30],
  hcf: [30, 30, 30, 30],
};

const now = 10_000;

function events(spec: ReadonlyArray<readonly [Numpad, number]>): DirectionEvent[] {
  return spec.map(([direction, framesAgo]) => ({
    direction,
    time: now - framesAgo * FRAME_MS,
  }));
}

function judge(
  entries: readonly DirectionEvent[],
  facing: Facing = "right",
  bufferFrames = 15,
  windowScale = 1,
  motionWindows: MotionWindows = windows,
): Evaluation {
  return evaluateMotions({
    entries,
    now,
    bufferFrames,
    facing,
    windows: motionWindows,
    windowScale,
  });
}

function expectMotion(
  entries: readonly DirectionEvent[],
  motion: MotionId | null,
  facing: Facing = "right",
  bufferFrames = 15,
  windowScale = 1,
  motionWindows: MotionWindows = windows,
): Evaluation {
  const result = judge(entries, facing, bufferFrames, windowScale, motionWindows);
  expect(result.motion).toBe(motion);
  return result;
}

describe("motion matcher", () => {
  it("matches quarter circle forward", () => {
    expectMotion(
      events([
        [2, 6],
        [3, 4],
        [6, 2],
      ]),
      "qcf",
    );
  });

  it("matches dragon punch", () => {
    expectMotion(
      events([
        [6, 6],
        [2, 4],
        [3, 2],
      ]),
      "dp",
    );
  });

  it("matches half circle forward", () => {
    expectMotion(
      events([
        [4, 10],
        [1, 8],
        [2, 6],
        [3, 4],
        [6, 2],
      ]),
      "hcf",
    );
  });

  it("fails when a required diagonal is skipped", () => {
    expectMotion(
      events([
        [2, 4],
        [6, 2],
      ]),
      null,
    );
  });

  it("fails when a wrong direction breaks the attempt", () => {
    expectMotion(
      events([
        [2, 8],
        [4, 6],
        [3, 4],
        [6, 2],
      ]),
      null,
    );
  });

  it("fails when a step exceeds its frame window", () => {
    expectMotion(
      events([
        [2, 16],
        [3, 14],
        [6, 1],
      ]),
      null,
      "right",
      30,
    );
  });

  it("accepts a step that lands on the frame window boundary", () => {
    expectMotion(
      events([
        [2, 14],
        [3, 2],
        [6, 1],
      ]),
      "qcf",
      "right",
      30,
    );
  });

  it("measures the gap from the previous required step when neutral sits between them", () => {
    expectMotion(
      events([
        [2, 14],
        [5, 13],
        [3, 1],
        [6, 0],
      ]),
      null,
      "right",
      30,
    );
  });

  it("fails when the first step is older than the buffer", () => {
    const sequence = events([
      [2, 16],
      [3, 2],
      [6, 1],
    ]);
    expectMotion(sequence, null, "right", 15, 1, wideWindows);
    expectMotion(sequence, "qcf", "right", 20, 1, wideWindows);
  });

  it("keeps a first step that is exactly bufferFrames old", () => {
    const sequence: DirectionEvent[] = [
      { direction: 2, time: now - 15 * FRAME_MS },
      { direction: 3, time: now - 2 * FRAME_MS },
      { direction: 6, time: now - FRAME_MS },
    ];
    expectMotion(sequence, "qcf", "right", 15, 1, wideWindows);
    const stale: DirectionEvent[] = [
      { direction: 2, time: now - 15 * FRAME_MS - 1 },
      sequence[1]!,
      sequence[2]!,
    ];
    expectMotion(stale, null, "right", 15, 1, wideWindows);
  });

  it("mirrors quarter circle forward when facing left", () => {
    const physical = events([
      [2, 6],
      [1, 4],
      [4, 2],
    ]);
    expectMotion(physical, "qcf", "left");
    expectMotion(physical, null, "right");
  });

  it("prefers half circle forward over quarter circle forward when both complete", () => {
    const result = expectMotion(
      events([
        [4, 10],
        [1, 8],
        [2, 6],
        [3, 4],
        [6, 2],
      ]),
      "hcf",
    );
    expect(result.matched).toEqual(expect.arrayContaining(["hcf", "qcf"]));
    expect(result.matched).not.toContain("dp");
  });

  it("allows neutral between required steps", () => {
    expectMotion(
      events([
        [2, 8],
        [5, 6],
        [3, 4],
        [5, 2],
        [6, 1],
      ]),
      "qcf",
    );
  });

  it("applies the window scale to per-step gaps", () => {
    const sequence = events([
      [2, 9],
      [3, 2],
      [6, 1],
    ]);
    expectMotion(sequence, null, "right", 30, 0.5);
    expectMotion(sequence, "qcf", "right", 30, 1);
  });

  it("does not re-match a later suffix after a broken attempt unless a new attempt starts", () => {
    expectMotion(
      events([
        [2, 8],
        [6, 6],
        [3, 4],
        [6, 2],
      ]),
      null,
    );
  });
});

describe("character fixtures", () => {
  it("gives each fighter a buffer and a window for every motion step", () => {
    expect(CHARACTERS.map((character) => character.name)).toEqual(["Kite", "Vesper", "Bulwark"]);
    const kite = CHARACTERS[0]!;
    const vesper = CHARACTERS[1]!;
    const bulwark = CHARACTERS[2]!;
    expect(kite.bufferFrames).toBe(15);
    expect(vesper.bufferFrames).toBeLessThan(kite.bufferFrames);
    expect(bulwark.bufferFrames).toBeGreaterThan(kite.bufferFrames);
    expect(vesper.windows.dp[0]).toBeLessThan(kite.windows.dp[0]);
    expect(bulwark.windows.hcf[0]).toBeGreaterThan(kite.windows.hcf[0]);

    for (const character of CHARACTERS) {
      expect(character.bufferFrames).toBeGreaterThan(0);
      for (const id of MOTION_IDS) {
        expect(windowsFor(character.windows, id)).toHaveLength(MOTION_STEPS[id].length - 1);
      }
    }
  });
});
