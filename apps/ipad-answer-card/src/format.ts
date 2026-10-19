import { cloneImportedExercise, createExerciseFromConfig, migrateStoredExercise } from "./domain";
import type { AnswerValue, Exercise, ExerciseExport, PublicExerciseConfig, PublicQuestionConfig, Question, QuestionType } from "./types";
import { ANSWERS, BOOLEAN_OPTIONS, isAnswerValueEmpty } from "./types";

export function toExportPayload(exercise: Exercise, exportedAt = new Date().toISOString()): ExerciseExport { return { schemaVersion: 2, type: "answer-recorder-attempt", exportedAt, exercise: structuredClone(exercise) }; }

export function toConfigPayload(exercise: Exercise): PublicExerciseConfig {
  return { schemaVersion: 2, type: "answer-recorder-config", paperId: exercise.paperId, paperVersion: exercise.paperVersion, name: exercise.name, questions: exercise.questions.map((question) => ({ questionId: question.questionId, number: question.number, ...(question.section ? { section: question.section } : {}), type: question.type, options: [...question.options] })) };
}

function asRecord(value: unknown, label = "文件"): Record<string, unknown> { if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${label}必须是 JSON 对象。`); return value as Record<string, unknown>; }
function asString(value: unknown, label: string): string { if (typeof value !== "string") throw new Error(`${label}格式无效。`); return value; }
function asOptionalString(value: unknown, label: string): string | undefined { return value === undefined ? undefined : asString(value, label); }
function asOptionalBoolean(value: unknown, label: string): boolean | undefined { if (value === undefined) return undefined; if (typeof value !== "boolean") throw new Error(`${label}格式无效。`); return value; }
function asInt(value: unknown, label: string): number { if (typeof value !== "number" || !Number.isInteger(value)) throw new Error(`${label}格式无效。`); return value; }

function parseAnswer(value: unknown, type: QuestionType, options: string[], number: number): AnswerValue {
  if (value === null) return null;
  if (type === "single") { if (typeof value !== "string" || !options.includes(value)) throw new Error(`第 ${number} 题答案无效。`); return value; }
  if (type === "boolean") { if (typeof value !== "boolean") throw new Error(`第 ${number} 题判断答案无效。`); return value; }
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !options.includes(item))) throw new Error(`第 ${number} 题多选答案无效。`);
  const unique = [...new Set(value as string[])];
  return unique.length ? unique : null;
}

function parseUncertainOptions(value: unknown, options: string[], number: number): string[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !options.includes(item))) throw new Error(`第 ${number} 题不确定选项无效。`);
  return options.filter((option) => value.includes(option));
}

function parseQuestion(value: unknown, index: number): Question {
  const source = asRecord(value, `第 ${index + 1} 题`);
  const id = asString(source.id, `第 ${index + 1} 题本地身份`);
  const questionId = asString(source.questionId, `第 ${index + 1} 题稳定身份`);
  const number = asInt(source.number, `第 ${index + 1} 题题号`);
  const rawType = source.type;
  if (rawType !== "single" && rawType !== "multiple" && rawType !== "boolean") throw new Error(`第 ${number} 题题型无效。`);
  const type = rawType as QuestionType;
  const optionsValue = source.options;
  if (!Array.isArray(optionsValue) || optionsValue.some((item) => typeof item !== "string") || optionsValue.length < 2) throw new Error(`第 ${number} 题选项无效。`);
  const options = optionsValue.map(String);
  if (type === "boolean" && (options.length !== 2 || options[0] !== BOOLEAN_OPTIONS[0] || options[1] !== BOOLEAN_OPTIONS[1])) throw new Error(`第 ${number} 题判断选项无效。`);
  const answer = parseAnswer(source.answer, type, options, number);
  const uncertainOptions = parseUncertainOptions(source.uncertainOptions, options, number);
  if (typeof source.review !== "boolean") throw new Error(`第 ${number} 题复查标记无效。`);
  const wholeUncertain = asOptionalBoolean(source.wholeUncertain, `第 ${number} 题整题不确定标记`);
  return { id, questionId, number, section: asOptionalString(source.section, `第 ${number} 题分区`), type, options, answer, uncertainOptions, note: asOptionalString(source.note, `第 ${number} 题备注`) ?? "", important: asOptionalBoolean(source.important, `第 ${number} 题重要标记`) ?? false, wholeUncertain: wholeUncertain ?? (options.length > 0 && uncertainOptions.length === options.length), unknown: asOptionalBoolean(source.unknown, `第 ${number} 题不会做标记`) ?? false, review: source.review };
}

function parseV2Exercise(source: unknown): Exercise {
  const value = asRecord(source, "练习");
  const rawQuestions = value.questions;
  if (!Array.isArray(rawQuestions) || rawQuestions.length < 1 || rawQuestions.length > 500) throw new Error("备份中的题目数量无效。");
  const questions = rawQuestions.map(parseQuestion);
  const ids = new Set<string>(); const questionIds = new Set<string>();
  for (const question of questions) { if (ids.has(question.id) || questionIds.has(question.questionId)) throw new Error("备份中存在重复题目身份。"); ids.add(question.id); questionIds.add(question.questionId); }
  const name = asString(value.name, "练习名称").trim(); const startNumber = asInt(value.startNumber, "起始题号"); const count = asInt(value.questionCount, "题目数量");
  if (!name || name.length > 100 || startNumber < 1 || startNumber > 9999 || count !== questions.length || count < 1 || count > 500) throw new Error("备份中的练习范围无效。");
  const numbers = questions.map((question) => question.number);
  if (questions.every((question) => !question.section) && [...numbers].sort((a, b) => a - b).join(",") !== Array.from({ length: count }, (_, index) => startNumber + index).join(",")) throw new Error("备份中的题号范围无效。");
  if (value.status !== "active" && value.status !== "completed") throw new Error("备份中的练习状态无效。");
  return migrateStoredExercise({ ...value, id: asString(value.id, "练习身份"), paperId: asString(value.paperId, "试卷身份"), paperVersion: asString(value.paperVersion, "答案版本"), attemptId: asString(value.attemptId, "作答身份"), name, startNumber, questionCount: count, status: value.status, createdAt: asString(value.createdAt, "创建时间"), updatedAt: asString(value.updatedAt, "更新时间"), revision: asInt(value.revision, "修订号"), scrollTop: typeof value.scrollTop === "number" ? value.scrollTop : 0, questions });
}

function parseV1(value: Record<string, unknown>): Exercise {
  if (value.schemaVersion !== 1 || value.type !== "answer-recorder-exercise") throw new Error("不支持的备份版本或文件类型。");
  const source = asRecord(value.exercise, "旧版练习"); const name = asString(source.name, "练习名称").trim(); const startNumber = asInt(source.startNumber, "起始题号"); const questionCount = asInt(source.questionCount, "题目数量");
  if (!name || name.length > 100 || startNumber < 1 || questionCount < 1 || questionCount > 500 || startNumber + questionCount - 1 > 9999) throw new Error("旧版备份中的练习范围无效。");
  const values = source.questions; if (!Array.isArray(values) || values.length !== questionCount) throw new Error("旧版备份中的题目数量不匹配。");
  const questions = values.map((item, index) => { const old = asRecord(item, `第 ${index + 1} 题`); const number = asInt(old.number, `第 ${index + 1} 题题号`); const answer = old.answer; if (answer !== null && (typeof answer !== "string" || !ANSWERS.includes(answer))) throw new Error(`第 ${number} 题答案无效。`); if (typeof old.review !== "boolean") throw new Error(`第 ${number} 题复查标记无效。`); const id = asString(old.id, `第 ${number} 题身份`); return { id, questionId: id, number, type: "single" as const, options: [...ANSWERS], answer, uncertainOptions: [], note: "", important: false, wholeUncertain: false, unknown: false, review: old.review } satisfies Question; });
  return cloneImportedExercise(migrateStoredExercise({ ...source, questions, paperId: `legacy:${String(source.id)}`, paperVersion: "1", attemptId: `legacy-attempt:${String(source.id)}` }));
}

export function parseImport(text: string): Exercise {
  let value: unknown; try { value = JSON.parse(text); } catch { throw new Error("无法解析 JSON 文件。"); }
  const root = asRecord(value); if (root.schemaVersion === 1) return parseV1(root); if (root.schemaVersion === 2 && root.type === "answer-recorder-attempt") return cloneImportedExercise(parseV2Exercise(root.exercise)); throw new Error("不支持的备份版本或文件类型。");
}

/** Parse the snapshot embedded in a saved standalone HTML without changing its exercise identity. */
export function parseEmbeddedExercise(text: string): Exercise {
  let value: unknown; try { value = JSON.parse(text); } catch { throw new Error("保存的 HTML 状态不是有效 JSON。"); }
  const root = asRecord(value);
  if (root.schemaVersion !== 2 || root.type !== "answer-recorder-attempt") throw new Error("保存的 HTML 状态版本或文件类型不受支持。");
  return parseV2Exercise(root.exercise);
}

export function parseConfig(text: string): PublicExerciseConfig {
  let value: unknown; try { value = JSON.parse(text); } catch { throw new Error("无法解析答题卡配置 JSON。"); }
  const root = asRecord(value); if (root.schemaVersion !== 2 || root.type !== "answer-recorder-config") throw new Error("不支持的答题卡配置版本或文件类型。");
  const hasPrivateAnswerField = (record: Record<string, unknown>): boolean => Object.keys(record).some((key) => key === "answer" || key === "answers" || key.toLowerCase().includes("reference"));
  if (hasPrivateAnswerField(root)) throw new Error("公开答题卡配置不能包含参考答案。");
  if (!Array.isArray(root.questions)) throw new Error("答题卡配置缺少题目清单。");
  const questions = root.questions.map((raw, index) => { const q = asRecord(raw, `第 ${index + 1} 题配置`); if (hasPrivateAnswerField(q) || "source" in q) throw new Error("公开答题卡配置包含私有答案或来源字段。"); const type = q.type; if (type !== "single" && type !== "multiple" && type !== "boolean") throw new Error(`第 ${index + 1} 题题型无效。`); const options = q.options; if (!Array.isArray(options) || options.some((item) => typeof item !== "string")) throw new Error(`第 ${index + 1} 题选项无效。`); return { questionId: asString(q.questionId, `第 ${index + 1} 题身份`), number: asInt(q.number, `第 ${index + 1} 题题号`), section: asOptionalString(q.section, `第 ${index + 1} 题分区`), type, options: [...options] } satisfies PublicQuestionConfig; });
  const config = { schemaVersion: 2 as const, type: "answer-recorder-config" as const, paperId: asString(root.paperId, "试卷身份"), paperVersion: asString(root.paperVersion, "答案版本"), name: asString(root.name, "答题卡名称"), questions }; createExerciseFromConfig(config); return config;
}

function csvCell(value: string | number | boolean | null): string { let text = value === null ? "" : String(value); if (/^[=+\-@]/.test(text)) text = `'${text}`; if (/[",\r\n]/.test(text)) text = `"${text.replaceAll('"', '""')}"`; return text; }
function answerForCsv(answer: AnswerValue): string | null { if (answer === null) return null; if (Array.isArray(answer)) return [...answer].sort().join("|"); return String(answer); }

export function toCsv(exercise: Exercise): string {
  const header = ["schema_version", "paper_id", "paper_version", "attempt_id", "exercise_id", "exercise_name", "exercise_status", "question_id", "section", "question_number", "question_type", "answer", "answered", "review_flag", "uncertain_options", "note", "important_flag", "whole_uncertain_flag", "unknown_flag"];
  const rows = exercise.questions.map((question) => [2, exercise.paperId, exercise.paperVersion, exercise.attemptId, exercise.id, exercise.name, exercise.status, question.questionId, question.section ?? null, question.number, question.type, answerForCsv(question.answer), !isAnswerValueEmpty(question.answer), question.review, question.uncertainOptions.join("|"), question.note, question.important, question.wholeUncertain, question.unknown]);
  return "\uFEFF" + [header, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}
