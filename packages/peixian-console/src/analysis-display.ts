const names = ["涉赌案件资料整理", "盗窃案件时空资料核对"]
const capabilityNames: Record<string, string> = {
  周边警情: "地点周边警情列表",
  周边抓拍汇总: "地点周边人员抓拍统计",
  人员轨迹: "人员指定时段轨迹明细",
  夜间来源记录: "人员夜间抓拍记录",
  跨小区来源记录: "人员跨小区活动汇总",
  预警概况: "人员预警类型概览",
  近七天预警明细: "人员近七天预警记录",
  档案与最近抓拍: "人员基础档案与最近十条抓拍",
}
export function displayName(value = "") {
  if (capabilityNames[value]) return capabilityNames[value]
  for (const name of names) if ([name, name + "（合成演示）", name + "（代码核对演示）"].includes(value)) return name
  return value
}
