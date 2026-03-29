// Shadows Midtones Highlights (SMH)
export type SMH = [number, number, number];

export class PreserveRatio {
  private shadows = $state<number>(0);
  private midtone = $state<number>(0);
  private highlights = $state<number>(0);

  // Tracks the relative percentage of the midtone
  private ratio: number;

  // 10000 allows for 4 decimal places of precision (e.g., 0.1234)
  private multiplier: number = 10000;

  constructor(initialValues: SMH) {
    [this.shadows, this.midtone, this.highlights] = initialValues;
    this.ratio = this.calculateRatio();
  }

  // Solves the JS floating point precision issue
  private fixFloat(value: number): number {
    return Math.round(value * this.multiplier) / this.multiplier;
  }

  private calculateRatio(): number {
    const delta = this.highlights - this.shadows;
    if (delta === 0) return 0.5; // Prevent division by zero if thumbs collide
    return (this.midtone - this.shadows) / delta;
  }

  private recalculateMidtone(): void {
    const delta = this.highlights - this.shadows;
    const exactMidtone = this.shadows + this.ratio * delta;
    this.midtone = this.fixFloat(exactMidtone);
  }

  // --- Action Methods ---

  public updateShadows(newVal: number): SMH {
    this.shadows = this.fixFloat(newVal);
    this.recalculateMidtone();
    return this.getState();
  }

  public updateHighlights(newVal: number): SMH {
    this.highlights = this.fixFloat(newVal);
    this.recalculateMidtone();
    return this.getState();
  }

  public updateMidtone(newVal: number): SMH {
    this.midtone = this.fixFloat(newVal);
    // Midtone moved independently, so we must record its new relative ratio
    this.ratio = this.calculateRatio();
    return this.getState();
  }

  public getState(): SMH {
    return [this.shadows, this.midtone, this.highlights];
  }

  public setState(newValues: SMH): void {
    [this.shadows, this.midtone, this.highlights] = newValues.map(this.fixFloat.bind(this));
    this.ratio = this.calculateRatio();
  }
}
