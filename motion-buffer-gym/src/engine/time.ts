export const FRAME_MS = 1000 / 60;

export function isWithinBuffer(now: number, time: number, bufferFrames: number): boolean {
  return now - time <= bufferFrames * FRAME_MS + 1e-6;
}

export function isWithinGap(previousTime: number, nextTime: number, maxFrames: number): boolean {
  return nextTime - previousTime <= maxFrames * FRAME_MS + 1e-6;
}

export function formatFrames(frames: number): string {
  const rounded = Math.round(frames * 100) / 100;
  return `${rounded}f`;
}
