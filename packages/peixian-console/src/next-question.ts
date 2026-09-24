import type { Pending } from "./BusinessConfirmations"
import type { PersonTableAnswer } from "./trusted-v2"

export type NextQuestion = NonNullable<PersonTableAnswer["next_question"]>

export const STOP_FOLLOWUP_TEXT = "不再追问，请基于已取得资料直接作答。"

export function nextQuestionRequest(question: NextQuestion, sid: string): Pending {
  return {
    id: question.id,
    sessionID: sid,
    questions: [{
      header: question.header || "下一步分析",
      question: question.question || "请选择下一步，选择后才会查询。",
      options: (question.options ?? []).map((option) => ({
        label: option.label,
        description: option.description,
      })),
      custom: question.custom !== false,
      // Follow-up selections become a user message, so this form can retain every checked choice.
      multiple: true,
    }],
  }
}

export function nextQuestionAction(
  question: NextQuestion,
  answers: string[][],
): { send: string } | { draft: string } {
  const selected = (answers[0] ?? []).map((item) => item.trim()).filter(Boolean)
  if (!selected.length) throw new Error("请选择下一步。")
  const text = selected.join("；")
  const draft = selected.some((label) => {
    const option = (question.options ?? []).find((item) => item.label === label)
    return option && option.send === false
  })
  if (draft) return { draft: text }
  return { send: text }
}
