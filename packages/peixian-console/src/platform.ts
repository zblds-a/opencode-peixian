export type Platform = { name: string; short_name: string; description: string }

export const defaultPlatform: Platform = {
  name: "沛警智枢",
  short_name: "沛警",
  description: "沛县公安智能研判平台",
}

export function platformMetadata(value: Partial<Platform> | null): Platform {
  const generic = { name: "Agent 工作台", short_name: "AI", description: "你的智能助手与工具空间" }
  return Object.fromEntries(
    Object.entries(defaultPlatform).map(([key, fallback]) => {
      const supplied = value?.[key as keyof Platform]
      return [key, typeof supplied === "string" && supplied.trim() && supplied.trim() !== generic[key as keyof Platform] ? supplied.trim() : fallback]
    }),
  ) as Platform
}
