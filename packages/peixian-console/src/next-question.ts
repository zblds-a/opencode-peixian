import type { Pending } from "./BusinessConfirmations"
import type { PersonTableAnswer } from "./trusted-v2"

export type NextQuestion = NonNullable<PersonTableAnswer["next_question"]>

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
    }],
  }
}

export function nextQuestionAction(
  question: NextQuestion,
  answers: string[][],
): { send: string } | { draft: string } {
  const text = answers[0]?.[0]?.trim() ?? ""
  if (!text) throw new Error("请选择下一步。")
  const option = (question.options ?? []).find((item) => item.label === text)
  if (option && option.send === false) return { draft: text }
  return { send: text }
}
