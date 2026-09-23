import { assertNever } from "./types";
import type { MotionWindows } from "./motions";

export const CHARACTER_IDS = ["kite", "vesper", "bulwark"] as const;

export type CharacterId = (typeof CHARACTER_IDS)[number];

export interface CharacterFixture {
  readonly id: CharacterId;
  readonly name: string;
  readonly summary: string;
  readonly bufferFrames: number;
  readonly windows: MotionWindows;
}

const KITE: CharacterFixture = {
  id: "kite",
  name: "Kite",
  summary: "Balanced",
  bufferFrames: 15,
  windows: {
    qcf: [12, 12],
    dp: [8, 8],
    hcf: [12, 12, 12, 12],
  },
};

const VESPER: CharacterFixture = {
  id: "vesper",
  name: "Vesper",
  summary: "Strict execution",
  bufferFrames: 9,
  windows: {
    qcf: [8, 8],
    dp: [5, 4],
    hcf: [7, 7, 7, 7],
  },
};

const BULWARK: CharacterFixture = {
  id: "bulwark",
  name: "Bulwark",
  summary: "Lenient grappler",
  bufferFrames: 24,
  windows: {
    qcf: [16, 16],
    dp: [12, 12],
    hcf: [20, 20, 20, 20],
  },
};

export const CHARACTERS: readonly CharacterFixture[] = [KITE, VESPER, BULWARK];

export function characterById(id: CharacterId): CharacterFixture {
  switch (id) {
    case "kite":
      return KITE;
    case "vesper":
      return VESPER;
    case "bulwark":
      return BULWARK;
    default:
      return assertNever(id);
  }
}
