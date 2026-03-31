// Shadows Midtones Highlights (SMH)
export type SMH = [number, number, number];

export class PreserveRatio {
  private shadows = $state<number>(0);
  private midtone = $state<number>(0);
  private highlights = $state<number>(0);

  // Tracks the relative percentage of the midtone
  private ratio: number;

  constructor(initialValues: SMH) {
    [this.shadows, this.midtone, this.highlights] = initialValues;
    this.ratio = this.calculateRatio();
  }

  private calculateRatio(): number {
    const delta = this.highlights - this.shadows;
    if (delta === 0) return 0.5; // Prevent division by zero if thumbs collide
    return (this.midtone - this.shadows) / delta;
  }

  private recalculateMidtone(): void {
    const delta = this.highlights - this.shadows;
    const exactMidtone = this.shadows + this.ratio * delta;
    this.midtone = exactMidtone;
  }

  // --- Action Methods ---

  public updateShadows(newVal: number): SMH {
    this.shadows = newVal;
    this.recalculateMidtone();
    return this.getState();
  }

  public updateHighlights(newVal: number): SMH {
    this.highlights = newVal;
    this.recalculateMidtone();
    return this.getState();
  }

  public updateMidtone(newVal: number): SMH {
    this.midtone = newVal;
    // Midtone moved independently, so we must record its new relative ratio
    this.ratio = this.calculateRatio();
    return this.getState();
  }

  public getState(): SMH {
    return [this.shadows, this.midtone, this.highlights];
  }

  public setState(newValues: SMH): void {
    [this.shadows, this.midtone, this.highlights] = newValues;
    this.ratio = this.calculateRatio();
  }
}
