import { FollowScroll } from "./follow-scroll"

type Snapshot = { anchor?: Element; offset: number; top: number }
export type ChatScrollMeasure = { source: string; following: boolean; before: { scrollHeight: number; clientHeight: number; scrollTop: number }; after: { scrollHeight: number; clientHeight: number; scrollTop: number } }

// One owner for message scroll writes. Resize notifications run before paint, while
// queued requests cover Solid DOM updates that do not change the measured height.
export class ChatScroll {
  private snapshot: Snapshot = { offset: 0, top: 0 }
  private pending = false
  private disposed = false
  private writing = false
  private clearWriting = 0
  private content?: Element
  private questions?: Element
  private source = "mount"
  private readonly resize: ResizeObserver
  private readonly mutations: MutationObserver

  constructor(private readonly scroll: HTMLElement, private readonly follow: FollowScroll, private readonly pause: () => boolean, private readonly onFollow: () => void, private readonly onMeasure?: (value: ChatScrollMeasure) => void) {
    this.resize = new ResizeObserver(() => this.request("resize"))
    this.resize.observe(scroll)
    this.mutations = new MutationObserver(() => {
      this.observeContent()
      this.request("content-mount")
    })
    this.mutations.observe(scroll, { childList: true })
    this.observeContent()
    this.capture()
  }

  get programmatic() { return this.writing }

  request(source: string) {
    this.source = source
    if (this.pending || this.disposed) return
    this.pending = true
    queueMicrotask(() => {
      this.pending = false
      if (this.disposed) return
      this.reconcile()
    })
  }

  capture() {
    if (this.disposed) return
    const top = this.scroll.getBoundingClientRect().top
    const anchor = Array.from(this.scroll.querySelectorAll(".markdown > *, .message-author, .assistant-thinking, .conversation-questions .confirmation-card"))
      .find((element) => element.getBoundingClientRect().bottom > top + 1)
    this.snapshot = { anchor, offset: anchor ? anchor.getBoundingClientRect().top - top : 0, top: this.scroll.scrollTop }
  }

  dispose() {
    this.disposed = true
    this.resize.disconnect()
    this.mutations.disconnect()
    cancelAnimationFrame(this.clearWriting)
  }

  private observeContent() {
    const content = this.scroll.querySelector(".messages")
    const questions = this.scroll.querySelector(".conversation-questions")
    if (content !== this.content) {
      if (this.content) this.resize.unobserve(this.content)
      if (content) this.resize.observe(content)
      this.content = content ?? undefined
    }
    if (questions !== this.questions) {
      if (this.questions) this.resize.unobserve(this.questions)
      if (questions) this.resize.observe(questions)
      this.questions = questions ?? undefined
    }
  }

  private reconcile() {
    if (this.pause()) return
    const before = { scrollHeight: this.scroll.scrollHeight, clientHeight: this.scroll.clientHeight, scrollTop: this.scroll.scrollTop }
    const maximum = Math.max(0, this.scroll.scrollHeight - this.scroll.clientHeight)
    const anchor = this.snapshot.anchor
    const target = this.follow.following
      ? maximum
      : anchor && this.scroll.contains(anchor)
        ? this.snapshot.top + anchor.getBoundingClientRect().top - this.scroll.getBoundingClientRect().top - this.snapshot.offset
        : this.snapshot.top
    const next = Math.max(0, Math.min(maximum, target))
    if (Math.abs(this.scroll.scrollTop - next) > 0.5) {
      this.writing = true
      this.scroll.scrollTop = next
      cancelAnimationFrame(this.clearWriting)
      this.clearWriting = requestAnimationFrame(() => { this.writing = false })
    }
    this.capture()
    this.onFollow()
    this.onMeasure?.({ source: this.source, following: this.follow.following, before, after: { scrollHeight: this.scroll.scrollHeight, clientHeight: this.scroll.clientHeight, scrollTop: this.scroll.scrollTop } })
  }
}
