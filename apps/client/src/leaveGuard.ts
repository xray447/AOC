/**
 * UI-10：页面级「有未保存改动」拦截。
 *
 * 当前工程用的是 `<BrowserRouter>` + `<Routes>`（不是 data router），`useBlocker` 用不了，
 * 所以这里留一个极简注册表：页面（目前只有设置页）在脏状态下注册确认函数，侧栏导航与
 * 关窗口前调用 `confirmLeave()`；没有注册时直接放行。
 */
type LeaveGuard = () => Promise<boolean>;

let guard: LeaveGuard | null = null;

export function setLeaveGuard(next: LeaveGuard | null): void {
  guard = next;
}

export function hasLeaveGuard(): boolean {
  return guard !== null;
}

/** 返回 true 表示可以离开（无未保存改动，或用户确认放弃）。 */
export async function confirmLeave(): Promise<boolean> {
  if (!guard) return true;
  return guard();
}
