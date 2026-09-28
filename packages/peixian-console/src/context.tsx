import { createContext, useContext } from "solid-js"
import type { Accessor } from "solid-js"
import type { Capability, User } from "./types"
import type { Change, LiveNotice, Resource } from "./events"
export type ConsoleContext = {
  user: Accessor<User>
  capabilities: Accessor<Capability[]>
  can: (capability: Capability) => boolean
  notify: (message: string, kind?: "success" | "error") => void
  refreshUser: () => Promise<void>
  invalidate: (resources: Resource[]) => void
  changed: Accessor<number>
  subscribe: (resource: Resource, callback: (change: Change) => void) => () => void
  subscribeLive?: (callback: (notice: LiveNotice) => void) => () => void
}
export const Context = createContext<ConsoleContext>()
export function useConsole() {
  const value = useContext(Context)
  if (!value) throw new Error("Console context is missing")
  return value
}
