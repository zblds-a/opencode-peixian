import type { Pending } from "./BusinessConfirmations"
import type { Run } from "./types"

const LABELS: Record<string, { title: string; question: string }> = {
  person_identity: { title: "核对对象", question: "请提供本次要核对的一名人员身份号码。" },
  lon: { title: "查询位置", question: "请提供已确认位置的经度。" },
  lat: { title: "查询位置", question: "请提供已确认位置的纬度。" },
  radius_m: { title: "查询范围", question: "请提供查询半径，单位为米。" },
  start: { title: "开始时间", question: "请提供开始时间，格式为 YYYY-MM-DD HH:mm:ss。" },
  end: { title: "结束时间", question: "请提供结束时间，格式为 YYYY-MM-DD HH:mm:ss。" },
  page: { title: "页码", question: "请说明要查询第几页；不会自动翻页。" },
  page_size: { title: "每页数量", question: "请说明每页查询多少条。" },
  source: { title: "来源记录", question: "请提供要继续核对的来源记录编号。不会自动选择第一条。" },
  supported_scope: { title: "查询范围限制", question: "当前警情接口不能按“近期”或“仅盗窃”筛选。是否同意改用上游默认覆盖范围？" },
}

export function clarificationRequest(run: Run, sid: string): Pending {
  const clarification = run.clarification!
  return { id: clarification.id, sessionID: sid, questions: clarification.missing.map((field) => ({
    header: LABELS[field]?.title ?? "补充信息",
    question: LABELS[field]?.question ?? "请补充本次查询所需的信息。",
    options: field === "supported_scope" ? [{ label: "同意使用上游默认覆盖范围", description: "仍按已确认的坐标、半径和页码查询；不附加近期或警情类别过滤。" }] : [],
    custom: field !== "supported_scope",
  })) }
}

export function clarificationAnswer(fields: string[], answers: string[][]): string {
  if (fields.length !== answers.length) throw new Error("请回答全部问题。")
  const parts = fields.map((field, index) => {
    const value = answers[index]?.[0]?.trim() ?? ""
    if (!value) throw new Error("请回答全部问题。")
    if (field === "supported_scope") {
      if (value !== "同意使用上游默认覆盖范围") throw new Error("请明确是否同意使用上游默认覆盖范围。")
      return value
    }
    if (field === "person_identity" && !/^\d{17}[\dXx]$/.test(value)) throw new Error("请填写一名人员的完整身份号码。")
    if (["start", "end"].includes(field) && !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)) throw new Error("时间请填写为 YYYY-MM-DD HH:mm:ss。")
    if (["lon", "lat"].includes(field) && !/^-?\d+(?:\.\d+)?$/.test(value)) throw new Error("经纬度请填写数字。")
    if (["radius_m", "page", "page_size"].includes(field) && !/^[1-9]\d*$/.test(value)) throw new Error("半径、页码和每页数量请填写正整数。")
    if (field === "page") return `第${value}页`
    if (field === "page_size") return `每页${value}条`
    return ({lon:"经度",lat:"纬度",radius_m:"半径",start:"开始时间",end:"结束时间",person_identity:"人员",source:"来源记录编号"} as Record<string,string>)[field] + "：" + value + (field === "radius_m" ? " 米" : "")
  })
  return parts.join("；")
}
