import { describe, expect, it } from "vitest";
import { createRing, pruneRing, pushChange } from "./ring-buffer";
import { FRAME_MS } from "./time";
import type { Numpad } from "./types";

describe("direction ring", () => {
  it("records direction changes and ignores holds", () => {
    const initial = createRing(8);
    const first = pushChange(initial, 2, 0);
    expect(first.recorded).toBe(true);
    expect(initial.entries).toEqual([]);
    expect(first.state.entries).toEqual([{ direction: 2, time: 0 }]);

    const hold = pushChange(first.state, 2, 5);
    expect(hold.recorded).toBe(false);
    expect(hold.state).toBe(first.state);

    const neutral = pushChange(createRing(8), 5, 0);
    expect(neutral.recorded).toBe(false);

    const changed = pushChange(first.state, 5, 12);
    expect(changed.recorded).toBe(true);
    expect(changed.state.entries.map((entry) => entry.direction)).toEqual([2, 5]);
  });

  it("caps the ring to its capacity", () => {
    let ring = createRing(3);
    const sequence: ReadonlyArray<readonly [Numpad, number]> = [
      [2, 0],
      [3, 1],
      [6, 2],
      [4, 3],
    ];
    for (const [direction, time] of sequence) {
      ring = pushChange(ring, direction, time).state;
    }
    expect(ring.entries.map((entry) => entry.direction)).toEqual([3, 6, 4]);
  });

  it("drops entries older than bufferFrames * (1000/60)", () => {
    let ring = createRing(8);
    ring = pushChange(ring, 2, 0).state;
    ring = pushChange(ring, 6, 10 * FRAME_MS).state;

    const kept = pruneRing(ring, 10 * FRAME_MS, 10);
    expect(kept.entries.map((entry) => entry.direction)).toEqual([2, 6]);

    const dropped = pruneRing(ring, 10 * FRAME_MS + 1, 10);
    expect(dropped.entries.map((entry) => entry.direction)).toEqual([6]);
    expect(dropped.lastDirection).toBe(6);
  });

  it("does not re-arm a held direction when old entries expire", () => {
    let ring = createRing(8);
    ring = pushChange(ring, 6, 0).state;
    ring = pruneRing(ring, 30 * FRAME_MS, 10);
    expect(ring.entries).toEqual([]);
    const again = pushChange(ring, 6, 30 * FRAME_MS);
    expect(again.recorded).toBe(false);
  });
});
