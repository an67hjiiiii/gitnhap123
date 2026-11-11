/** Không biến số đo chưa có thành 0. */
export function metric(value: number | null | undefined, suffix = ''): string {
  return value == null || !Number.isFinite(value) ? 'Chưa đo' : `${value}${suffix}`;
}
export function percent(value: number | null | undefined, digits = 0): string {
  return value == null || !Number.isFinite(value) ? 'Chưa đánh giá' : `${(value * 100).toFixed(digits)}%`;
}
