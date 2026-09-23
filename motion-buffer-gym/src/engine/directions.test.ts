import { describe, expect, it } from "vitest";
import { arrowsToNumpad, vectorToNumpad } from "./directions";

describe("numpad vectors", () => {
  it("maps stick quadrants and the deadzone", () => {
    expect(vectorToNumpad(0, 0, 0.45)).toBe(5);
    expect(vectorToNumpad(1, 0, 0.45)).toBe(6);
    expect(vectorToNumpad(-1, 0, 0.45)).toBe(4);
    expect(vectorToNumpad(0, 1, 0.45)).toBe(8);
    expect(vectorToNumpad(0, -1, 0.45)).toBe(2);
    expect(vectorToNumpad(1, -1, 0.45)).toBe(3);
    expect(vectorToNumpad(-1, -1, 0.45)).toBe(1);
    expect(vectorToNumpad(1, 1, 0.45)).toBe(9);
    expect(vectorToNumpad(-1, 1, 0.45)).toBe(7);
    expect(vectorToNumpad(0.2, -0.9, 0.45)).toBe(2);
    expect(vectorToNumpad(0.2, 0.2, 0.45)).toBe(5);
  });

  it("cancels opposing arrows and builds diagonals", () => {
    expect(arrowsToNumpad({ up: false, down: true, left: false, right: true })).toBe(3);
    expect(arrowsToNumpad({ up: false, down: true, left: true, right: true })).toBe(2);
    expect(arrowsToNumpad({ up: true, down: true, left: true, right: false })).toBe(4);
    expect(arrowsToNumpad({ up: false, down: false, left: false, right: false })).toBe(5);
  });
});
