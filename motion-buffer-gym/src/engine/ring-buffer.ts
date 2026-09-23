import { isWithinBuffer } from "./time";
import type { DirectionEvent, Numpad } from "./types";

export interface RingState {
  readonly entries: readonly DirectionEvent[];
  readonly lastDirection: Numpad;
  readonly capacity: number;
}

export interface PushResult {
  readonly state: RingState;
  readonly recorded: boolean;
}

export function createRing(capacity = 64): RingState {
  if (capacity < 1) throw new Error("Ring capacity must be at least 1");
  return { entries: [], lastDirection: 5, capacity };
}

export function pushChange(state: RingState, direction: Numpad, time: number): PushResult {
  if (state.lastDirection === direction) {
    return { state, recorded: false };
  }
  const appended = state.entries.concat({ direction, time });
  const entries =
    appended.length > state.capacity ? appended.slice(appended.length - state.capacity) : appended;
  return {
    state: { entries, lastDirection: direction, capacity: state.capacity },
    recorded: true,
  };
}

export function pruneRing(state: RingState, now: number, bufferFrames: number): RingState {
  let dropped = false;
  const fresh: DirectionEvent[] = [];
  for (const entry of state.entries) {
    if (isWithinBuffer(now, entry.time, bufferFrames)) fresh.push(entry);
    else dropped = true;
  }
  const entries = fresh.length > state.capacity ? fresh.slice(fresh.length - state.capacity) : fresh;
  if (entries.length !== fresh.length) dropped = true;
  if (!dropped) return state;
  return { entries, lastDirection: state.lastDirection, capacity: state.capacity };
}
