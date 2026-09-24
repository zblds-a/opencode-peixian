// 浏览器同源示例。csrfToken 取当前登录响应，不硬编码、不写日志。
export async function api(path, {method = "GET", body, csrfToken} = {}) {
  const headers = body === undefined ? {} : {"Content-Type": "application/json"};
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch("/api/console/v1" + path, {
    method, credentials: "same-origin", headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) throw Object.assign(new Error(value.message || value.detail?.message || "请求未完成"), {status: response.status, detail: value});
  return value;
}
// client_request_id 在用户明确发送时生成并保存，网络重试沿用同一个值。
export function submitMessage(sid, text, fileIds, requestId, csrfToken) {
  return api(`/sessions/${encodeURIComponent(sid)}/messages`, {method:"POST", csrfToken,
    body:{text, agent_id:"theft-assistant", mode:"standard", file_ids:fileIds,
      skill_ids:[], plugin_ids:[], client_request_id:requestId}});
}
// option_id 仅用于 UI 稳定身份；提交协议仍是 label 二维数组。
export function replyQuestion(question, answers, csrfToken) {
  return api(`/questions/${encodeURIComponent(question.id)}/reply`, {method:"POST", csrfToken,
    body:{answers, question_version:question.question_version}});
}
export function getSource(sid,rid,evidenceId) {
  return api(`/sessions/${encodeURIComponent(sid)}/runs/${encodeURIComponent(rid)}/sources/${encodeURIComponent(evidenceId)}`);
}
