// Follow the answer only while the reader has not expressed an upward scroll intent.
// Content growth and browser scroll anchoring never change this state by themselves.
export class FollowScroll {
  following = true
  private intent: "up" | "down" | "drag" | undefined
  private until = 0
  private pointer = false

  wheel(deltaY: number, now: number) {
    this.intent = deltaY < 0 ? "up" : "down"
    this.until = now + 250
    if (deltaY < 0) this.following = false
  }

  key(key: string, now: number) {
    if (["ArrowUp", "PageUp", "Home"].includes(key)) this.wheel(-1, now)
    if (["ArrowDown", "PageDown", "End"].includes(key)) this.wheel(1, now)
  }

  pointerDown() { this.pointer = true; this.intent = "drag" }
  pointerUp() { this.pointer = false; this.intent = undefined }
  pause() { this.following = false; this.intent = undefined }
  resume() { this.following = true; this.intent = undefined }

  scroll(distanceFromBottom: number, programmatic: boolean, now: number) {
    if (programmatic || !this.intent || !this.pointer && now > this.until) return this.following
    if (this.intent === "up") this.following = false
    else this.following = distanceFromBottom < 24
    if (!this.pointer) this.intent = undefined
    return this.following
  }
}
