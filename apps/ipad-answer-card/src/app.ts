import { answeredCount, clearAnswer, createExercise, createExerciseFromConfig, setAnswer, setQuestionNote, toggleImportant, toggleOption, toggleReview, toggleUnknown, toggleUncertainOption, toggleWholeUncertain } from "./domain";
import { getExercise, getScrollPosition, listExercises, persistenceKind, removeExercise, saveExercise, saveScrollPosition, stageRecovery, verifyStoredExercise } from "./storage";
import { parseConfig, parseEmbeddedExercise, parseImport, toConfigPayload, toCsv, toExportPayload } from "./format";
import { ANSWERS, BOOLEAN_OPTIONS, isAnswerValueEmpty, type AnswerValue, type Exercise, type Question } from "./types";
import { offerFile } from "./transfer";
import "./styles.css";

type View = "home" | "create" | "exercise" | "restore";
type SaveState = "idle" | "saving" | "saved" | "error";

interface AppState {
  view: View;
  exercises: Exercise[];
  current: Exercise | null;
  editingCompleted: boolean;
  filterUnanswered: boolean;
  filterSnapshot: Set<string>;
  uncertainOpen: Set<string>;
  saveState: SaveState;
  saveError: string;
  notice: { text: string; kind: "success" | "error" | "info" } | null;
}

const rootElement = document.querySelector<HTMLDivElement>("#app");
if (!rootElement) throw new Error("应用容器不存在。");
const root = rootElement;
const state: AppState = { view: "home", exercises: [], current: null, editingCompleted: false, filterUnanswered: false, filterSnapshot: new Set(), uncertainOpen: new Set(), saveState: "idle", saveError: "", notice: null };

let saveChain: Promise<void> | null = null;
let pendingSnapshot: Exercise | null = null;
let persistedRevision: number | undefined;
let scrollTimer = 0;
const dirtyQuestions = new Set<string>();

function escapeHtml(value: string): string { return value.replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character] ?? character); }
function statusLabel(exercise: Exercise): string { return exercise.status === "completed" ? "已完成" : "进行中"; }
function noticeHtml(): string {
  const warning = persistenceKind() === "memory" && (state.current || state.exercises.length) ? `<div class="notice error" role="alert">此查看器不允许本地保存，请先导出作答再退出。</div>` : "";
  return warning + (state.notice ? `<div class="notice ${state.notice.kind === "error" ? "error" : state.notice.kind === "success" ? "success" : ""}" role="status">${escapeHtml(state.notice.text)}</div>` : "");
}
function layout(content: string, title: string): string { return `<main class="app-shell"><header class="topbar"><h1>${escapeHtml(title)}</h1></header><div id="notices">${noticeHtml()}</div>${content}</main>`; }

function renderHome(): void {
  const cards = state.exercises.length ? state.exercises.map((exercise) => {
    const answered = answeredCount(exercise); const numbers = exercise.questions.map((question) => question.number); const range = `${Math.min(...numbers)}—${Math.max(...numbers)}`;
    return `<article class="exercise-card"><header><div><div class="exercise-title">${escapeHtml(exercise.name)}</div><div class="exercise-meta">第 ${range} 题 · ${answered}/${exercise.questionCount} 已答 · ${escapeHtml(exercise.paperId)}</div></div><span class="status ${exercise.status === "completed" ? "completed" : ""}">${statusLabel(exercise)}</span></header><div class="button-row"><button class="primary small" data-action="open-exercise" data-id="${exercise.id}">${exercise.status === "completed" ? "查看导出" : "继续答题"}</button><button class="danger small" data-action="delete-exercise" data-id="${exercise.id}">删除</button></div></article>`;
  }).join("") : `<div class="card"><p class="muted">还没有练习。可手动创建，或导入由“答题助手”生成的公开答题卡配置。</p></div>`;
  root.innerHTML = layout(`<section class="stack"><div class="home-actions"><h2>我的练习</h2><div class="button-row"><button class="secondary small" data-action="import-config">导入答题卡</button><button class="secondary small" data-action="import-json">导入备份</button><button class="secondary small" data-action="paste-restore">粘贴恢复</button><button class="primary small" data-action="new-exercise">新建练习</button><input id="import-config-file" class="screen-reader" type="file" accept="application/json,.json" /><input id="import-file" class="screen-reader" type="file" accept="application/json,.json" /></div></div><div class="exercise-list">${cards}</div></section>`, "答题记录");
}

function renderRestore(): void {
  root.innerHTML = layout(`<section class="card stack"><p>粘贴之前复制的完整 JSON，即可恢复答案与标记。内容不完整或试卷不匹配时会明确报错。</p><form id="restore-form" class="stack"><label for="restore-text">完整作答 JSON</label><textarea id="restore-text" class="restore-text" required spellcheck="false"></textarea><div class="button-row"><button class="primary" type="submit">恢复作答</button><button class="secondary" type="button" data-action="back-home">返回</button></div></form></section>`, "粘贴恢复");
}

function renderCreate(): void {
  root.innerHTML = layout(`<section class="card"><h2>新建练习</h2><form id="create-form" class="stack" novalidate><div class="form-grid"><div class="field"><label for="exercise-name">练习名称</label><input id="exercise-name" name="name" maxlength="100" required placeholder="例如：资料分析·第三套" /></div><div class="field"><label for="start-number">起始题号</label><input id="start-number" name="startNumber" type="number" min="1" max="9999" step="1" required value="1" /></div><div class="field"><label for="question-count">题目数量</label><input id="question-count" name="questionCount" type="number" min="1" max="500" step="1" required value="20" /></div></div><p class="muted">手动练习默认为四选一。通过答题助手配置导入单选、多选和判断题时，题型与选项按配置固定。</p><div class="button-row"><button class="primary" type="submit">开始记录</button><button class="secondary" type="button" data-action="back-home">返回</button></div></form></section>`, "新建练习");
}

function saveStateHtml(): string {
  if (state.saveState === "saving") return `<span class="save-status saving" role="status">保存中…</span>`;
  if (state.saveState === "error") return `<span class="save-status error" role="alert">保存失败：${escapeHtml(state.saveError)} <button class="secondary small" data-action="retry-save">重试</button> <button class="secondary small" data-action="reload-current">重新载入</button> <button class="secondary small" data-action="emergency-json">紧急导出</button></span>`;
  if (state.current?.savedRevision === state.current?.revision && state.current && persistenceKind() !== "memory") return `<span class="save-status saved" role="status">已保存</span>`;
  return `<span class="save-status" role="status">未保存</span>`;
}

function questionTypeLabel(question: Question): string { return question.type === "multiple" ? "多选" : question.type === "boolean" ? "判断" : "单选"; }
function answerLabel(question: Question, option: string): string { return question.type === "boolean" ? option : option; }
function isSelected(question: Question, option: string): boolean {
  if (question.type === "multiple") return Array.isArray(question.answer) && question.answer.includes(option);
  if (question.type === "boolean") return (option === BOOLEAN_OPTIONS[0] && question.answer === true) || (option === BOOLEAN_OPTIONS[1] && question.answer === false);
  return question.answer === option;
}
function answerButton(question: Question, option: string, disabled: boolean): string {
  const selected = isSelected(question, option); const value = question.type === "boolean" ? (option === BOOLEAN_OPTIONS[0] ? "true" : "false") : option;
  return `<button type="button" class="answer-button" data-action="answer" data-question-id="${question.id}" data-answer="${escapeHtml(value)}" aria-label="选择 ${escapeHtml(answerLabel(question, option))}" aria-pressed="${selected}" ${selected ? "data-selected=\"true\"" : ""} ${disabled ? "disabled" : ""}>${escapeHtml(option)}</button>`;
}

function uncertainButton(question: Question, option: string, disabled: boolean): string {
  const selected = question.uncertainOptions.includes(option);
  return `<button type="button" class="uncertain-option" data-action="uncertain-option" data-question-id="${question.id}" data-option="${escapeHtml(option)}" aria-label="标记 ${escapeHtml(option)} 为不确定" aria-pressed="${selected}" ${selected ? "data-selected=\"true\"" : ""} ${disabled ? "disabled" : ""}>${escapeHtml(option)}</button>`;
}

function uncertainMarker(question: Question, mark: "important" | "whole-uncertain" | "unknown", symbol: string, label: string, selected: boolean, disabled: boolean): string {
  return `<button type="button" class="uncertain-marker ${mark}" data-action="question-marker" data-question-id="${question.id}" data-mark="${mark}" aria-label="${label}" title="${label}" aria-pressed="${selected}" ${selected ? "data-selected=\"true\"" : ""} ${disabled ? "disabled" : ""}><span aria-hidden="true">${symbol}</span></button>`;
}

function questionRow(exercise: Exercise, questionId: string, disabled: boolean): string {
  const question = exercise.questions.find((item) => item.id === questionId); if (!question) return "";
  const many = question.options.length > 4;
  const uncertainOpen = state.uncertainOpen.has(question.id);
  const uncertainId = `uncertain-options-${question.id}`;
  const noteValue = escapeHtml(question.note ?? "");
  const markerToolbar = `<div class="question-markers" role="toolbar" aria-label="第 ${question.number} 题快捷标记" ${uncertainOpen ? "" : "hidden"}>${uncertainMarker(question, "important", "★", "标记本题重要", question.important, disabled)}${uncertainMarker(question, "whole-uncertain", "○", "整题不确定", question.wholeUncertain, disabled)}${uncertainMarker(question, "unknown", "?", "标记本题不会做", question.unknown, disabled)}</div>`;
  const expandedUncertain = `<div id="${uncertainId}" class="uncertain-options" role="group" aria-label="第 ${question.number} 题不确定选项" ${uncertainOpen ? "" : "hidden"}><div class="uncertain-choice-options">${question.options.map((option) => uncertainButton(question, option, disabled)).join("")}</div></div>`;
  return `<div class="question-row ${question.review ? "reviewing" : ""} ${uncertainOpen ? "markers-open" : ""}" data-question-id="${question.id}" data-option-count="${question.options.length}"><details class="number-menu"><summary aria-label="第 ${question.number} 题操作">${question.number}</summary><div class="menu"><button type="button" data-action="clear" data-question-id="${question.id}" ${disabled ? "disabled" : ""}>清空答案</button><button type="button" data-action="toggle-review" data-question-id="${question.id}" ${disabled ? "disabled" : ""}>${question.review ? "取消待复查" : "标记待复查"}</button><label class="note-label">备注<input class="question-note" data-action="note" data-question-id="${question.id}" type="text" maxlength="200" value="${noteValue}" placeholder="备注..." aria-label="第 ${question.number} 题备注" ${disabled ? "disabled" : ""} /></label></div></details><span class="question-type">${questionTypeLabel(question)}</span>${expandedUncertain}${markerToolbar}<div class="answer-options ${many ? "many" : ""}">${question.options.map((option) => answerButton(question, option, disabled)).join("")}</div><button type="button" class="uncertain-toggle" data-action="toggle-uncertain" data-question-id="${question.id}" aria-controls="${uncertainId}" aria-expanded="${uncertainOpen}">不确定 <span aria-hidden="true">${uncertainOpen ? "⌃" : "⌄"}</span></button></div>`;
}

function renderExercise(): void {
  const exercise = state.current; if (!exercise) return renderHome();
  const answered = answeredCount(exercise); const unanswered = exercise.questionCount - answered; const readOnly = exercise.status === "completed" && !state.editingCompleted;
  if (readOnly) {
    root.innerHTML = layout(`<section class="card stack"><div><p class="eyebrow">练习已完成</p><h2>${escapeHtml(exercise.name)}</h2></div><div class="summary-grid"><div class="summary-stat"><strong>${exercise.questionCount}</strong><span>总题数</span></div><div class="summary-stat"><strong>${answered}</strong><span>已答</span></div><div class="summary-stat"><strong>${unanswered}</strong><span>未答</span></div></div><div class="button-row"><button class="primary" data-action="save-local">保存</button><button class="secondary" data-action="export-json">导出.json</button><button class="secondary" data-action="export-csv">导出.csv</button><button class="secondary" data-action="continue-edit">继续修改</button><button class="secondary" data-action="back-home">返回列表</button></div>${saveStateHtml()}</section>`, exercise.name); return;
  }
  const visibleIds = state.filterUnanswered ? [...state.filterSnapshot] : exercise.questions.map((question) => question.id); const rows = visibleIds.map((id) => questionRow(exercise, id, false)).join(""); const empty = rows ? "" : `<div class="notice">当前筛选中没有未答题。你可以返回全部题目继续查看。</div>`;
  const headerQuestion = exercise.questions.find((question) => visibleIds.includes(question.id)) ?? exercise.questions[0]; const headerOptions = headerQuestion?.options ?? [...ANSWERS];
  root.innerHTML = layout(`<section class="card"><div class="answer-toolbar"><div class="answer-summary"><strong class="answered-count">${answered}/${exercise.questionCount} 已答</strong><span class="muted unanswered-count"> · ${unanswered} 未答</span>${saveStateHtml()}</div><div class="button-row answer-actions"><button class="primary small" data-action="save-local">保存</button><button class="secondary small" data-action="export-json">导出.json</button><button class="secondary small" data-action="export-csv">导出.csv</button><button class="secondary small" data-action="toggle-filter">${state.filterUnanswered ? "查看全部" : "查看未答"}</button></div></div><div class="answer-header"><span>题号</span><span>题型</span><div class="header-options">${headerOptions.map((option) => `<span>${escapeHtml(option)}</span>`).join("")}</div></div><div class="question-list" aria-label="题目列表" data-exercise-id="${exercise.id}" data-filter="${state.filterUnanswered}">${rows}${empty}</div></section>`, exercise.name);
  dirtyQuestions.clear();
  window.scrollTo(0, exercise.scrollTop ?? 0);
}

function patchExercise(list: HTMLElement): void {
  const exercise = state.current!;
  const answered = answeredCount(exercise);
  root.querySelector(".answered-count")!.textContent = `${answered}/${exercise.questionCount} 已答`;
  root.querySelector(".unanswered-count")!.textContent = ` · ${exercise.questionCount - answered} 未答`;
  const status = root.querySelector(".save-status");
  const statusHtml = saveStateHtml();
  if (status && status.outerHTML !== statusHtml) status.outerHTML = statusHtml;
  const notices = root.querySelector("#notices")!;
  const noticesHtml = noticeHtml();
  if (notices.innerHTML !== noticesHtml) notices.innerHTML = noticesHtml;
  for (const id of dirtyQuestions) {
    const question = exercise.questions.find((item) => item.id === id);
    const row = [...list.children].find((element) => (element as HTMLElement).dataset.questionId === id) as HTMLElement | undefined;
    if (!question || !row) continue;
    const open = state.uncertainOpen.has(id);
    row.classList.toggle("reviewing", question.review);
    row.classList.toggle("markers-open", open);
    row.querySelectorAll<HTMLElement>(".question-markers,.uncertain-options").forEach((element) => { element.hidden = !open; });
    const toggle = row.querySelector<HTMLButtonElement>(".uncertain-toggle")!;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.querySelector("span")!.textContent = open ? "⌃" : "⌄";
    row.querySelectorAll<HTMLButtonElement>(".answer-button,.uncertain-option,.uncertain-marker").forEach((button) => {
      const selected = button.dataset.action === "answer"
        ? isSelected(question, question.type === "boolean" ? (button.dataset.answer === "true" ? BOOLEAN_OPTIONS[0] : BOOLEAN_OPTIONS[1]) : button.dataset.answer!)
        : button.dataset.action === "uncertain-option" ? question.uncertainOptions.includes(button.dataset.option!)
        : button.dataset.mark === "important" ? question.important : button.dataset.mark === "unknown" ? question.unknown : question.wholeUncertain;
      button.setAttribute("aria-pressed", String(selected));
      if (selected) button.dataset.selected = "true"; else delete button.dataset.selected;
    });
    const note = row.querySelector<HTMLInputElement>(".question-note")!;
    if (note !== document.activeElement && note.value !== (question.note ?? "")) note.value = question.note ?? "";
    row.querySelector<HTMLButtonElement>('[data-action="toggle-review"]')!.textContent = question.review ? "取消待复查" : "标记待复查";
  }
  dirtyQuestions.clear();
}

function render(): void {
  const list = root.querySelector<HTMLElement>(".question-list");
  // Keep touch targets, note focus and scroll position alive throughout input and background saves.
  if (state.view === "exercise" && state.current && list?.dataset.exerciseId === state.current.id && list.dataset.filter === String(state.filterUnanswered)) {
    patchExercise(list);
    return;
  }
  if (state.view === "home") renderHome(); else if (state.view === "create") renderCreate(); else if (state.view === "restore") renderRestore(); else renderExercise();
}
function setNotice(text: string, kind: "success" | "error" | "info"): void { state.notice = { text, kind }; render(); window.setTimeout(() => { if (state.notice?.text === text) { state.notice = null; render(); } }, 3600); }

function mutateCurrent(mutator: (exercise: Exercise) => Exercise): Exercise | null {
  if (!state.current) return null;
  const updated = mutator(state.current);
  if (updated === state.current) return state.current;
  updated.questions.forEach((question, index) => { if (question !== state.current!.questions[index]) dirtyQuestions.add(question.id); });
  state.current = { ...updated, updatedAt: new Date().toISOString(), revision: state.current.revision + 1 };
  state.saveState = "idle";
  return state.current;
}

async function runSaveLoop(): Promise<void> {
  while (pendingSnapshot) {
    const snapshot = pendingSnapshot; pendingSnapshot = null;
    try {
      await saveExercise(snapshot, persistedRevision);
      persistedRevision = snapshot.revision;
      // Background recovery never confirms that the user has explicitly saved this revision.
    } catch (error) {
      pendingSnapshot ??= snapshot;
      state.saveState = "error"; state.saveError = error instanceof Error ? error.message : "请重试。"; render();
      throw error;
    }
  }
}

function queueSave(snapshot: Exercise): Promise<void> {
  try { stageRecovery(snapshot); }
  catch (error) { state.saveState = "error"; state.saveError = error instanceof Error ? error.message : "恢复记录写入失败。"; render(); return Promise.resolve(); }
  pendingSnapshot = { ...snapshot }; state.saveError = ""; render();
  if (!saveChain) saveChain = runSaveLoop().finally(() => { saveChain = null; });
  return saveChain.catch(() => undefined);
}

function serializeEmbeddedJson(value: unknown): string {
  return JSON.stringify(value).replaceAll("<", "\\u003c").replaceAll("\u2028", "\\u2028").replaceAll("\u2029", "\\u2029");
}

function syncEmbeddedState(exercise: Exercise): void {
  if (!document.getElementById(EMBEDDED_CONFIG_ID) && !document.getElementById(EMBEDDED_STATE_ID)) return;
  let element = document.getElementById(EMBEDDED_STATE_ID);
  if (!element) { element = document.createElement("script"); element.id = EMBEDDED_STATE_ID; element.setAttribute("type", "application/json"); document.body.prepend(element); }
  element.textContent = serializeEmbeddedJson(toExportPayload(exercise));
}

async function saveCurrentLocally(): Promise<void> {
  if (!state.current) return;
  try {
    const id = state.current.id;
    while (state.current?.id === id) {
      const snapshot = { ...state.current, savedRevision: state.current.revision };
      state.saveState = "saving";
      await queueSave(snapshot);
      if (state.saveError) return;
      await verifyStoredExercise(snapshot);
      if (state.current?.id !== id) return;
      if (state.current.revision !== snapshot.revision) continue;
      state.current = { ...state.current, savedRevision: snapshot.savedRevision };
      state.saveState = "saved"; state.saveError = ""; render(); return;
    }
  } catch (error) {
    state.saveState = "error";
    state.saveError = error instanceof Error ? error.message : "本地记录未写入，请导出作答后再退出。";
    render();
  }
}

function exportCurrent(kind: "json" | "csv", emergency = false): void {
  if (!state.current) return;
  const payload = kind === "json" ? JSON.stringify(toExportPayload(state.current), null, 2) : toCsv(state.current); const safeName = state.current.name.replace(/[\\/:*?"<>|]/g, "_").slice(0, 60) || "答题记录";
  offerFile({ filename: `${safeName}.${kind}`, content: payload, mime: kind === "json" ? "application/json" : "text/csv", summary: `${state.current.questionCount} 题 · ${answeredCount(state.current)} 已答${emergency ? " · 紧急导出" : ""}` });
}

async function openExercise(id: string): Promise<void> {
  const found = state.exercises.find((exercise) => exercise.id === id); if (!found) return;
  state.current = structuredClone(found); persistedRevision = found.revision; state.view = "exercise"; state.editingCompleted = false; state.filterUnanswered = false; state.filterSnapshot = new Set(); state.uncertainOpen = new Set(); state.saveState = "saved"; state.saveError = "";
  try { state.current.scrollTop = await getScrollPosition(found.id); } catch { /* auxiliary state is optional */ }
  render();
}
async function refreshHome(): Promise<void> { state.exercises = await listExercises(); state.view = "home"; state.current = null; state.editingCompleted = false; state.uncertainOpen = new Set(); persistedRevision = undefined; render(); }

const EMBEDDED_CONFIG_ID = "answer-recorder-config";
const EMBEDDED_STATE_ID = "answer-recorder-state";

async function importEmbeddedConfig(): Promise<void> {
  const element = document.getElementById(EMBEDDED_CONFIG_ID);
  const stateElement = document.getElementById(EMBEDDED_STATE_ID);
  const serializedState = stateElement?.textContent?.trim() ?? "";
  if (serializedState) {
    const embeddedExercise = parseEmbeddedExercise(serializedState);
    if (element) {
      const serializedConfig = element.textContent?.trim() ?? "";
      if (!serializedConfig) throw new Error("答题卡配置为空，无法恢复保存的作答。");
      const config = parseConfig(serializedConfig);
      assertMatchingPaper(embeddedExercise, config);
    }
    const existing = await getExercise(embeddedExercise.id);
    if (existing && existing.attemptId !== embeddedExercise.attemptId) throw new Error("保存文件的作答身份与本地记录冲突，请先导出当前记录。");
    // Reopening an older HTML must never roll a continued attempt back.
    if (!existing || embeddedExercise.revision > existing.revision) await saveExercise(embeddedExercise, existing?.revision);
    syncEmbeddedState(existing && existing.revision >= embeddedExercise.revision ? existing : embeddedExercise);
    return;
  }
  if (!element) return;
  const serialized = element.textContent?.trim() ?? "";
  if (!serialized) return;
  const config = parseConfig(serialized);
  const existing = (await listExercises()).find((exercise) => exercise.paperId === config.paperId && exercise.paperVersion === config.paperVersion);
  const current = existing ?? createExerciseFromConfig(config);
  if (!existing) await saveExercise(current);
  syncEmbeddedState(current);
}

function assertMatchingPaper(exercise: Exercise, config: ReturnType<typeof parseConfig>): void {
  // Display names and local IDs can change on import; stable paper/question identities cannot.
  const identity = (value: ReturnType<typeof toConfigPayload>) => JSON.stringify([value.paperId, value.paperVersion, value.questions.map((q) => [q.questionId, q.number, q.section ?? "", q.type, q.options]).sort((a, b) => String(a[0]).localeCompare(String(b[0])))]);
  if (identity(toConfigPayload(exercise)) !== identity(config)) throw new Error("保存的作答与当前答题卡不匹配，已停止恢复以避免串题。");
}

async function restoreText(form: HTMLFormElement): Promise<void> {
  try {
    const restored = parseEmbeddedExercise(form.querySelector<HTMLTextAreaElement>("textarea")!.value);
    const configElement = document.getElementById(EMBEDDED_CONFIG_ID);
    if (configElement?.textContent) assertMatchingPaper(restored, parseConfig(configElement.textContent));
    const existing = await getExercise(restored.id);
    if (existing && (existing.attemptId !== restored.attemptId || existing.revision > restored.revision)) throw new Error("本地已有更新或不同的记录，未用旧 JSON 覆盖。请返回列表查看最新作答。");
    await saveExercise(restored, existing?.revision);
    await refreshHome();
    syncEmbeddedState(restored);
    await openExercise(restored.id);
  } catch (error) {
    const previous = form.querySelector<HTMLTextAreaElement>("textarea")!.value;
    state.view = "restore";
    state.notice = { text: error instanceof Error ? error.message : "恢复失败。", kind: "error" };
    render();
    root.querySelector<HTMLTextAreaElement>("#restore-text")!.value = previous;
  }
}

async function handleCreate(form: HTMLFormElement): Promise<void> {
  const data = new FormData(form); const input = { name: String(data.get("name") ?? ""), startNumber: Number(data.get("startNumber")), questionCount: Number(data.get("questionCount")) };
  try { const exercise = createExercise(input); await saveExercise(exercise); persistedRevision = exercise.revision; state.current = exercise; state.exercises = [exercise, ...state.exercises]; state.view = "exercise"; state.saveState = "saved"; state.filterUnanswered = false; state.uncertainOpen = new Set(); render(); } catch (error: unknown) { setNotice(error instanceof Error ? error.message : "无法创建练习。", "error"); }
}
async function handleImport(input: HTMLInputElement, configuration: boolean): Promise<void> {
  const file = input.files?.[0]; input.value = ""; if (!file) return;
  try {
    const imported = configuration ? createExerciseFromConfig(parseConfig(await file.text())) : parseImport(await file.text());
    await saveExercise(imported); await refreshHome(); setNotice(configuration ? `已导入“${imported.name}”答题卡。` : `已导入“${imported.name}”，原练习没有被覆盖。`, "success");
  } catch (error: unknown) { setNotice(error instanceof Error ? error.message : "导入失败，原有练习未改变。", "error"); }
}

root.addEventListener("submit", (event) => {
  const form = event.target as HTMLFormElement;
  if (form.id === "create-form") { event.preventDefault(); void handleCreate(form); }
  if (form.id === "restore-form") { event.preventDefault(); void restoreText(form); }
});
root.addEventListener("change", (event) => {
  const input = event.target as HTMLInputElement;
  if (input.id === "import-file") void handleImport(input, false);
  if (input.id === "import-config-file") void handleImport(input, true);
});
root.addEventListener("input", (event) => {
  const input = event.target as HTMLInputElement;
  if (input.dataset.action === "note") {
    if (!state.current || (state.current.status === "completed" && !state.editingCompleted)) return;
    const questionId = input.dataset.questionId;
    if (!questionId) return;
    const updated = mutateCurrent((exercise) => setQuestionNote(exercise, questionId, input.value));
    if (updated) void queueSave(updated);
  }
});
window.addEventListener("scroll", () => { if (state.view !== "exercise" || !state.current) return; state.current.scrollTop = window.scrollY; window.clearTimeout(scrollTimer); const id = state.current.id; const position = window.scrollY; scrollTimer = window.setTimeout(() => { void saveScrollPosition(id, position).catch(() => undefined); }, 350); }, { passive: true });

// A drag that began on a button must not become a delayed synthetic tap on release.
// Never prevent pointer movement: native document scrolling remains in charge.
let touchGesture: { id: number; x: number; y: number; dragged: boolean; endedAt: number } | undefined;
root.addEventListener("pointerdown", (event) => {
  if (event.pointerType !== "touch" && event.pointerType !== "pen") { touchGesture = undefined; return; }
  if (!(event.target as Element).closest("button,summary")) { touchGesture = undefined; return; }
  touchGesture = { id: event.pointerId, x: event.clientX, y: event.clientY, dragged: false, endedAt: performance.now() };
}, { passive: true });
window.addEventListener("pointermove", (event) => {
  if (!touchGesture || touchGesture.id !== event.pointerId) return;
  if (Math.hypot(event.clientX - touchGesture.x, event.clientY - touchGesture.y) > 10) touchGesture.dragged = true;
}, { passive: true });
for (const type of ["pointerup", "pointercancel"] as const) window.addEventListener(type, (event) => {
  if (!touchGesture || touchGesture.id !== event.pointerId) return;
  if (type === "pointercancel") touchGesture.dragged = true;
  touchGesture.endedAt = performance.now();
}, { passive: true });
root.addEventListener("click", (event) => {
  if (event.detail > 0 && touchGesture?.dragged && performance.now() - touchGesture.endedAt < 700) {
    event.preventDefault(); event.stopImmediatePropagation(); touchGesture = undefined;
  }
}, true);

root.addEventListener("click", (event) => {
  const target = event.target as HTMLElement; const actionElement = target.closest<HTMLElement>("[data-action]"); if (!actionElement) return; const action = actionElement.dataset.action; const id = actionElement.dataset.id;
  if (action === "new-exercise") { state.view = "create"; state.notice = null; render(); return; }
  if (action === "paste-restore") { state.view = "restore"; state.notice = null; render(); return; }
  if (action === "back-home") { void refreshHome(); return; }
  if (action === "open-exercise" && id) { void openExercise(id); return; }
  if (action === "delete-exercise" && id) { const exercise = state.exercises.find((item) => item.id === id); if (exercise && window.confirm(`确定删除“${exercise.name}”？删除后无法在网页中恢复，请先导出备份。`)) void removeExercise(id).then(() => refreshHome()); return; }
  if (action === "import-json") { root.querySelector<HTMLInputElement>("#import-file")?.click(); return; }
  if (action === "import-config") { root.querySelector<HTMLInputElement>("#import-config-file")?.click(); return; }
  if (!state.current) return;
  if (action === "answer") {
    if (state.current.status === "completed" && !state.editingCompleted) return;
    const questionId = actionElement.dataset.questionId; const question = state.current.questions.find((item) => item.id === questionId); if (!questionId || !question) return;
    const raw = actionElement.dataset.answer ?? ""; let updated: Exercise;
    if (question.type === "multiple") updated = mutateCurrent((exercise) => toggleOption(exercise, questionId, raw)) ?? state.current;
    else { const answer: AnswerValue = question.type === "boolean" ? raw === "true" : raw; updated = mutateCurrent((exercise) => setAnswer(exercise, questionId, answer)) ?? state.current; }
    void queueSave(updated); return;
  }
  if (action === "toggle-uncertain") {
    const questionId = actionElement.dataset.questionId; if (!questionId) return;
    if (state.uncertainOpen.has(questionId)) state.uncertainOpen.delete(questionId); else state.uncertainOpen.add(questionId);
    dirtyQuestions.add(questionId);
    render(); return;
  }
  if (action === "uncertain-option") {
    if (state.current.status === "completed" && !state.editingCompleted) return;
    const questionId = actionElement.dataset.questionId; const option = actionElement.dataset.option;
    if (!questionId || !option) return;
    const updated = mutateCurrent((exercise) => toggleUncertainOption(exercise, questionId, option));
    if (updated) void queueSave(updated);
    return;
  }
  if (action === "question-marker") {
    if (state.current.status === "completed" && !state.editingCompleted) return;
    const questionId = actionElement.dataset.questionId; const mark = actionElement.dataset.mark;
    if (!questionId) return;
    const updated = mark === "important"
      ? mutateCurrent((exercise) => toggleImportant(exercise, questionId))
      : mark === "whole-uncertain"
        ? mutateCurrent((exercise) => toggleWholeUncertain(exercise, questionId))
        : mark === "unknown"
          ? mutateCurrent((exercise) => toggleUnknown(exercise, questionId))
          : null;
    if (updated) void queueSave(updated);
    return;
  }
  if (action === "clear" || action === "toggle-review") { if (state.current.status === "completed" && !state.editingCompleted) return; const questionId = actionElement.dataset.questionId; if (!questionId) return; actionElement.closest<HTMLDetailsElement>("details")!.open = false; const updated = mutateCurrent((exercise) => action === "clear" ? clearAnswer(exercise, questionId) : toggleReview(exercise, questionId)); if (updated) void queueSave(updated); return; }
  if (action === "toggle-filter") { if (state.filterUnanswered) state.filterUnanswered = false; else { state.filterSnapshot = new Set(state.current.questions.filter((question) => isAnswerValueEmpty(question.answer)).map((question) => question.id)); state.filterUnanswered = true; } render(); return; }
  if (action === "save-local") { void saveCurrentLocally(); return; }
  if (action === "continue-edit") { state.uncertainOpen = new Set(); const updated = mutateCurrent((exercise) => ({ ...exercise, status: "active" })); state.editingCompleted = true; if (updated) void queueSave(structuredClone(updated)); return; }
  if (action === "export-json" || action === "export-csv") { void exportCurrent(action === "export-json" ? "json" : "csv"); return; }
  if (action === "emergency-json") { void exportCurrent("json", true); return; }
  if (action === "reload-current") {
    const currentId = state.current.id;
    void getExercise(currentId).then((loaded) => {
      if (!loaded) { setNotice("本地记录已不存在，当前内存答案仍可通过紧急 JSON 导出。", "error"); return; }
      pendingSnapshot = null; state.current = loaded; persistedRevision = loaded.revision; state.uncertainOpen = new Set(); state.saveState = "saved"; state.saveError = ""; loaded.questions.forEach((question) => dirtyQuestions.add(question.id)); render();
    }).catch((error: unknown) => setNotice(error instanceof Error ? error.message : "重新载入失败。", "error"));
    return;
  }
  if (action === "retry-save") { void saveCurrentLocally(); }
});


export async function boot(): Promise<void> {
  try {
    await importEmbeddedConfig();
    state.exercises = await listExercises();
    render();
  } catch (error: unknown) {
    state.notice = { text: error instanceof Error ? error.message : "无法读取本地练习。", kind: "error" };
    render();
  }
}
