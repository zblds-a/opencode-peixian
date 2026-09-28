import { marked } from "marked"

export type StreamProjection = { text: string; pendingTable: boolean; pendingSource: boolean }

// A cumulative snapshot may arrive in any packet boundaries. Keep the raw tail here;
// Completed rows stay stable; the current row may expose safe cells while source
// anchors remain buffered until their short labels and targets are complete.
export class MarkdownStreamBuffer {
  private raw = ""

  reset(text = "") { this.raw = text }
  append(chunk: string) { this.raw += chunk }

  project(finished = false, interrupted = false): StreamProjection {
    const lines = this.raw.match(/[^\n]*\n|[^\n]+$/g) ?? []
    const partial = lines.at(-1)?.endsWith("\n") ? "" : lines.pop() ?? ""
    let text = ""
    let header = ""
    let table: { header: string; separator: string; sourceColumns: number[]; columns: number } | undefined
    let fence = ""
    let blocked = false

    const accept = (line: string) => {
      const body = line.replace(/\r?\n$/, "")
      const marker = body.match(/^ {0,3}(`{3,}|~{3,})/)?.[1] ?? ""
      if (fence) {
        text += line
        if (marker && marker[0] === fence[0] && marker.length >= fence.length) fence = ""
        return
      }
      if (marker) { fence = marker; text += line; return }
      if (header) {
        const candidate = marked.lexer(header + line).find((token) => token.type === "table")
        if (candidate?.type === "table") {
          const headings = splitTableCells(header.replace(/\r?\n$/, ""))
          table = { header, separator: line, columns: headings.length, sourceColumns: headings.flatMap((heading, index) => /来源/.test(heading) ? [index] : []) }
          text += header + line
          header = ""
          return
        }
        text += header
        header = ""
      }
      if (table) {
        if (hasStructuralPipe(body)) {
          if (unfinishedSourceStart(line) >= 0) { blocked = true; return }
          const candidate = marked.lexer(table.header + table.separator + line).find((token) => token.type === "table")
          if (candidate?.type === "table" && candidate.rows.length === 1) { text += line; return }
        }
        table = undefined
      }
      if (hasStructuralPipe(body)) { header = line; return }
      text += line
    }

    for (const line of lines) {
      if (blocked) break
      accept(line)
    }
    let draftTable = false
    if (finished && !interrupted && !blocked) {
      if (partial) accept(partial)
      if (header) text += header
    } else if (table?.sourceColumns.length && !interrupted && !blocked && !fence && hasStructuralPipe(partial)) {
      const currentTable = table
      const cells = splitTableCells(partial)
      if (cells.length <= currentTable.columns && currentTable.columns > 0) {
        const visible = Array.from({ length: currentTable.columns }, (_, index) => {
          const cell = cells[index] ?? ""
          if (currentTable.sourceColumns.includes(index)) {
            return [...cell.matchAll(/\[来源\d+\]\(#source-[A-Za-z0-9-]+\)/g)]
              .map((match) => match[0]).join("、") || " "
          }
          const sourceStart = unfinishedSourceStart(cell)
          return sourceStart < 0 ? cell : cell.slice(0, sourceStart)
        })
        const row = `| ${visible.join(" | ")} |\n`
        const candidate = marked.lexer(currentTable.header + currentTable.separator + row).find((token) => token.type === "table")
        if (candidate?.type === "table" && candidate.rows.length === 1) {
          text += row
          draftTable = true
        }
      }
    } else if (!header && !table && !fence && !blocked && !finished) {
      // A complete sentence can appear while the current line is still growing.
      // Holding the rest also prevents a table header from flashing as a paragraph.
      const sourceStart = unfinishedSourceStart(partial)
      const safe = sourceStart < 0 ? partial : partial.slice(0, sourceStart)
      if (!hasStructuralPipe(safe)) {
        const ends = [...safe.matchAll(/[。！？.!?](?:\s|$)/g)]
        const last = ends.at(-1)
        if (last?.index !== undefined) text += safe.slice(0, last.index + last[0].length)
      }
    }
    const sourceStart = unfinishedSourceStart(text)
    return {
      text: sourceStart < 0 ? text : text.slice(0, sourceStart),
      pendingTable: !finished && (Boolean(header) || !draftTable && !fence && hasStructuralPipe(partial)),
      pendingSource: blocked || sourceStart >= 0 || unfinishedSourceStart(partial) >= 0,
    }
  }
}

// Split only structural pipes, leaving escaped pipes and inline code intact.
function splitTableCells(line: string) {
  const cells: string[] = []
  let start = 0
  let code = 0
  for (let index = 0; index < line.length; index++) {
    if (line[index] === "\\") { index++; continue }
    if (line[index] === "`") {
      let end = index + 1
      while (line[end] === "`") end++
      const width = end - index
      if (!code) code = width
      else if (code === width) code = 0
      index = end - 1
      continue
    }
    if (line[index] !== "|" || code) continue
    cells.push(line.slice(start, index))
    start = index + 1
  }
  cells.push(line.slice(start))
  if (!cells[0].trim()) cells.shift()
  if (cells.length > 1 && !cells.at(-1)?.trim()) cells.pop()
  return cells
}

function hasStructuralPipe(text: string) {
  let code = 0
  for (let i = 0; i < text.length; i++) {
    if (text[i] === "\\") { i++; continue }
    if (text[i] === "`") {
      let end = i + 1
      while (text[end] === "`") end++
      const width = end - i
      if (!code) code = width
      else if (code === width) code = 0
      i = end - 1
      continue
    }
    if (text[i] === "|" && !code) return true
  }
  return false
}

// Return the first unfinished source anchor, without hiding unrelated bracketed prose.
function unfinishedSourceStart(text: string) {
  for (let start = text.indexOf("["); start >= 0; start = text.indexOf("[", start + 1)) {
    let position = start
    const literal = (expected: string) => {
      for (const character of expected) {
        if (position === text.length) return "pending"
        if (text[position++] !== character) return "other"
      }
      return "match"
    }
    const prefix = literal("[来源")
    if (prefix === "pending") return start
    if (prefix !== "match") continue
    const digits = position
    while (/\d/.test(text[position] ?? "")) position++
    if (position === text.length) return start
    if (position === digits) continue
    const target = literal("](#source-")
    if (target === "pending") return start
    if (target !== "match") continue
    const id = position
    while (/[A-Za-z0-9-]/.test(text[position] ?? "")) position++
    if (position === text.length) return start
    if (position === id || text[position] !== ")") continue
    start = position
  }
  return -1
}
