# Motion Buffer Gym

A self-contained browser gym for forward-relative fighting-game motions. It does not use a backend.

## Run

```bash
cd motion-buffer-gym
npm install
npm run dev
```

Open the local URL Vite prints.

## Test

```bash
npm test
```

## Controls

- Arrow keys or numpad `1`–`9`. `5` is neutral. The pad faces right:

```
7 8 9
4 5 6
1 2 3
```

- `J` punch, `K` kick. On-screen buttons send the same attacks.
- `F` or the facing control flips left and right.
- Gamepad: left stick and d-pad choose a direction. A held d-pad wins over the stick. Face buttons bottom and left are punch; right and top are kick. The header pill shows whether the last input came from the keyboard or a gamepad.

## Motions and windows

Motions are written in forward-relative numpad. Facing left mirrors forward and back before matching (`6↔4`, `3↔1`, `9↔7`). `2`, `5`, and `8` stay put.

- QCF: `2 → 3 → 6`
- DP: `6 → 2 → 3`
- HCF: `4 → 1 → 2 → 3 → 6`

The ring stores direction changes, not a sample every frame. Each entry keeps the numpad direction and a `performance.now()` timestamp. A held direction does not add another entry. Entries older than `bufferFrames * (1000/60)` milliseconds are dropped, and the ring is capped.

On punch or kick, every motion is checked against the directions still inside the buffer. Each step after the first must land within that step's frame window, measured from the previous required step. The window scale multiplies the active character's fixture windows. Neutral between steps is allowed and does not use a step. Any other direction that is not the next required step breaks that attempt. Required diagonals are not skipped. If more than one motion completes, the longest one is chosen, so HCF beats QCF.

Kite, Vesper, and Bulwark each load their own buffer length and step windows into the sliders. Later slider edits stay on the live session until you switch character again.
