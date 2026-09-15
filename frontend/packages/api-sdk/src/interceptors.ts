/**
 * 13.9.2 拦截器语义的纯函数构件（可单测）：
 * - backoffDelay：429 退避延迟计算（Retry-After 秒优先，无头按 1s * 2^attempt）；
 * - parseRetryAfter：Retry-After 头解析（秒数或 HTTP 日期）；
 * - createSingleFlight：401 刷新单飞（并发调用共享同一 inflight promise）。
 */

/** 429 退避延迟（毫秒）：有 Retry-After（秒）按头值，无头按 1s * 2^attempt。 */
export function backoffDelay(attempt: number, retryAfterSeconds?: number | null): number {
  if (retryAfterSeconds != null) {
    return Math.max(0, retryAfterSeconds) * 1000;
  }
  const exp = Math.min(Math.max(Math.trunc(attempt), 0), 16);
  return 1000 * 2 ** exp;
}

/** 解析 Retry-After 头为秒数；支持秒数与 HTTP 日期两种格式，非法/缺失返回 null。 */
export function parseRetryAfter(header: string | null): number | null {
  if (!header) return null;
  const trimmed = header.trim();
  if (trimmed === "") return null;
  const seconds = Number(trimmed);
  if (Number.isFinite(seconds)) return Math.max(0, seconds);
  const at = Date.parse(trimmed);
  if (Number.isNaN(at)) return null;
  return Math.max(0, (at - Date.now()) / 1000);
}

/** 刷新单飞：并发调用共享同一 inflight promise（同一结果），落定后复位允许再次触发。 */
export function createSingleFlight<A extends unknown[], R>(
  fn: (...args: A) => Promise<R>,
): (...args: A) => Promise<R> {
  let inflight: Promise<R> | null = null;
  return (...args: A) => {
    if (!inflight) {
      inflight = fn(...args).finally(() => {
        inflight = null;
      });
    }
    return inflight;
  };
}
