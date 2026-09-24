const labels: Record<string, string> = {
 pending: "等待处理", queued: "等待执行", running: "执行中", completed: "已完成", failed: "未完成", cancelled: "已取消", cancelling: "停止处理中", reconciling: "正在核对", accepted: "已受理", pending_dispatch: "等待投递", dispatching: "正在投递", generating: "正在生成", stopping: "正在停止", waiting_permission: "等待操作确认", waiting_question: "等待补充信息", waiting_input: "待你确认", empty: "暂无有效资料", partial: "资料不完整", complete: "资料已取得", unavailable: "资料暂不可用", finished: "执行结束",
}
export function executionLabel(value: string): string { return labels[value] ?? "状态待确认" }
