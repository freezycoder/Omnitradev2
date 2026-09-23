import { assertNever, type Facing, type Numpad } from "./types";

const MIRROR: Record<Numpad, Numpad> = {
  1: 3,
  2: 2,
  3: 1,
  4: 6,
  5: 5,
  6: 4,
  7: 9,
  8: 8,
  9: 7,
};

export function toForwardRelative(direction: Numpad, facing: Facing): Numpad {
  switch (facing) {
    case "right":
      return direction;
    case "left":
      return MIRROR[direction];
    default:
      return assertNever(facing);
  }
}
