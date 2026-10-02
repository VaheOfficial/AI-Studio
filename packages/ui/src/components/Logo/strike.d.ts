export interface StrikeOptions {
  /** The logo's pieces and its view box (see logoParts.ts). */
  logo: { width: number; height: number; parts: { region: string; cx: number; cy: number; d: string }[] }
  /** The mark's width in CSS pixels. Read every frame. */
  size: () => number
  /** Where the mark sits on the canvas; its middle by default. Read every frame. */
  center?: () => { x: number; y: number }
  /** Called each time the sequence has played through to the end (the mark whole again after shattering). */
  onRound?: () => void
}

export interface Strike {
  /** Stops the show and dims the mark, or starts it again. */
  rest(on: boolean): void
  /** Ends the show at the next moment the mark is whole and calls `done`; the mark then stays, at rest. */
  finish(done: () => void): void
  /**
   * The way out, for a page lying over another: the mark dashes to `to` and lands with a blow that tears the
   * ground (painted by the canvas in `ground` from now on) open from that point. Call it once the show has finished.
   */
  exit(options: { to: { x: number; y: number; size: number }; ground: string; onLand?: () => void; onDone?: () => void }): void
  /** Draws the moment `ms` into the sequence, with no clock running. */
  seek(ms: number): void
  destroy(): void
}

/** The loading sequence, drawn on `canvas`: the logo builds itself and then hunts, is cut, darts and shatters. */
export function createStrike(canvas: HTMLCanvasElement, options: StrikeOptions): Strike
