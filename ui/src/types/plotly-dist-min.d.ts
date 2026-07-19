// plotly.js-dist-min ships no types; declare the small surface we use.
declare module 'plotly.js-dist-min' {
  export function react(
    el: HTMLElement,
    data: unknown[],
    layout?: Record<string, unknown>,
    config?: Record<string, unknown>,
  ): Promise<void>
  export function purge(el: HTMLElement): void
  export const Plots: { resize(el: HTMLElement): void }
}
