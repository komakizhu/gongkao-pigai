import type { AnswerValue, Exercise, PublicExerciseConfig, Question, QuestionType } from "./types";
import { ANSWERS, BOOLEAN_OPTIONS, isAnswerValueEmpty } from "./types";
import { newId } from "./id";

export interface CreateExerciseInput {
  name: string;
  startNumber: number;
  questionCount: number;
}

export function validateCreateInput(input: CreateExerciseInput): string | null {
  const name = input.name.trim();
  if (!name) return "请输入练习名称。";
  if (name.length > 100) return "练习名称不能超过 100 个字符。";
  if (!Number.isInteger(input.startNumber) || input.startNumber < 1 || input.startNumber > 9999) return "起始题号必须是 1—9999 的整数。";
  if (!Number.isInteger(input.questionCount) || input.questionCount < 1 || input.questionCount > 500) return "题目数量必须是 1—500 的整数。";
  if (input.startNumber + input.questionCount - 1 > 9999) return "题号范围不能超过 9999。";
  return null;
}

function defaultQuestion(number: number, id: string, type: QuestionType = "single"): Question {
  return { id: newId(), questionId: id, number, type, options: type === "boolean" ? [...BOOLEAN_OPTIONS] : [...ANSWERS], answer: null, uncertainOptions: [], note: "", important: false, wholeUncertain: false, unknown: false, review: false };
}

function baseExercise(input: Omit<Exercise, "questions">, questions: Question[]): Exercise {
  return { ...input, questions, questionCount: questions.length };
}

export function createExercise(input: CreateExerciseInput, now = new Date().toISOString()): Exercise {
  const error = validateCreateInput(input);
  if (error) throw new Error(error);
  const id = newId();
  const questions = Array.from({ length: input.questionCount }, (_, index) => {
    const number = input.startNumber + index;
    return defaultQuestion(number, `${id}:q:${number}`);
  });
  return baseExercise({ id, paperId: `manual:${id}`, paperVersion: "1", attemptId: newId(), name: input.name.trim(), startNumber: input.startNumber, questionCount: input.questionCount, status: "active", createdAt: now, updatedAt: now, revision: 0, scrollTop: 0 }, questions);
}

function validConfigQuestion(item: PublicExerciseConfig["questions"][number]): Question {
  const options = [...item.options];
  if (!item.questionId.trim()) throw new Error("配置中存在空题目身份。");
  if (!Number.isInteger(item.number) || item.number < 1 || item.number > 9999) throw new Error("配置中的题号无效。");
  if (!["single", "multiple", "boolean"].includes(item.type)) throw new Error(`第 ${item.number} 题题型无效。`);
  if (item.type === "boolean") {
    if (options.length !== 2 || options[0] !== BOOLEAN_OPTIONS[0] || options[1] !== BOOLEAN_OPTIONS[1]) throw new Error(`第 ${item.number} 题判断选项必须是“对／错”。`);
  } else if (options.length < 2 || options.length > 12 || new Set(options).size !== options.length || options.some((option) => !option.trim())) {
    throw new Error(`第 ${item.number} 题选项范围无效。`);
  }
  return { id: newId(), questionId: item.questionId, number: item.number, ...(item.section ? { section: item.section } : {}), type: item.type, options, answer: null, uncertainOptions: [], note: "", important: false, wholeUncertain: false, unknown: false, review: false };
}

export function createExerciseFromConfig(config: PublicExerciseConfig, now = new Date().toISOString()): Exercise {
  if (config.schemaVersion !== 2 || config.type !== "answer-recorder-config") throw new Error("不支持的答题卡配置版本或文件类型。");
  if (!config.paperId || !config.paperVersion || !config.name.trim()) throw new Error("答题卡配置缺少试卷身份或名称。");
  if (!Array.isArray(config.questions) || config.questions.length < 1 || config.questions.length > 500) throw new Error("答题卡配置题目数量无效。");
  const ids = new Set<string>();
  const questions = config.questions.map((item) => {
    if (ids.has(item.questionId)) throw new Error("答题卡配置中存在重复题目身份。");
    ids.add(item.questionId);
    return validConfigQuestion(item);
  });
  const id = newId();
  const numbers = questions.map((question) => question.number);
  return baseExercise({ id, paperId: config.paperId, paperVersion: config.paperVersion, attemptId: newId(), name: config.name.trim(), startNumber: Math.min(...numbers), questionCount: questions.length, status: "active", createdAt: now, updatedAt: now, revision: 0, scrollTop: 0 }, questions);
}

function updateQuestion(exercise: Exercise, questionId: string, updater: (question: Question) => Question): Exercise {
  let found = false;
  const questions = exercise.questions.map((question) => {
    if (question.id !== questionId) return question;
    found = true;
    return updater(question);
  });
  return found ? { ...exercise, questions } : exercise;
}

export function setAnswer(exercise: Exercise, questionId: string, answer: AnswerValue): Exercise {
  return updateQuestion(exercise, questionId, (question) => {
    if (question.type === "single") return typeof answer === "string" && question.options.includes(answer) ? { ...question, answer } : question;
    if (question.type === "boolean") return typeof answer === "boolean" ? { ...question, answer } : question;
    if (!Array.isArray(answer)) return question;
    const values = [...new Set(answer)].filter((value) => question.options.includes(value));
    return { ...question, answer: values.length ? values : null };
  });
}

export function toggleOption(exercise: Exercise, questionId: string, option: string): Exercise {
  return updateQuestion(exercise, questionId, (question) => {
    if (question.type !== "multiple" || !question.options.includes(option)) return question;
    const selected = Array.isArray(question.answer) ? question.answer : [];
    const next = selected.includes(option) ? selected.filter((item) => item !== option) : [...selected, option];
    return { ...question, answer: next.length ? next : null };
  });
}

/** Normalize marked options to the question's original option order. */
export function normalizeOptionList(value: unknown, options: string[]): string[] {
  if (!Array.isArray(value)) return [];
  const selected = new Set(value.filter((item): item is string => typeof item === "string" && options.includes(item)));
  return options.filter((option) => selected.has(option));
}

export function toggleUncertainOption(exercise: Exercise, questionId: string, option: string): Exercise {
  return updateQuestion(exercise, questionId, (question) => {
    if (!question.options.includes(option)) return question;
    const selected = Array.isArray(question.uncertainOptions) ? question.uncertainOptions : [];
    const next = selected.includes(option) ? selected.filter((item) => item !== option) : [...selected, option];
    const uncertainOptions = normalizeOptionList(next, question.options);
    return { ...question, uncertainOptions };
  });
}

export function toggleWholeUncertain(exercise: Exercise, questionId: string): Exercise {
  return updateQuestion(exercise, questionId, (question) => ({ ...question, wholeUncertain: !question.wholeUncertain }));
}

export function setQuestionNote(exercise: Exercise, questionId: string, note: string): Exercise {
  return updateQuestion(exercise, questionId, (question) => ({ ...question, note: note.slice(0, 200) }));
}

export function toggleImportant(exercise: Exercise, questionId: string): Exercise {
  return updateQuestion(exercise, questionId, (question) => ({ ...question, important: !question.important }));
}

export function toggleUnknown(exercise: Exercise, questionId: string): Exercise {
  return updateQuestion(exercise, questionId, (question) => ({ ...question, unknown: !question.unknown }));
}

export function clearAnswer(exercise: Exercise, questionId: string): Exercise { return updateQuestion(exercise, questionId, (question) => ({ ...question, answer: null })); }
export function toggleReview(exercise: Exercise, questionId: string): Exercise { return updateQuestion(exercise, questionId, (question) => ({ ...question, review: !question.review })); }
export function answeredCount(exercise: Exercise): number { return exercise.questions.filter((question) => !isAnswerValueEmpty(question.answer)).length; }

export function cloneImportedExercise(source: Exercise, now = new Date().toISOString()): Exercise {
  return { ...structuredClone(source), id: newId(), attemptId: newId(), name: `${source.name}（副本）`, status: "active", createdAt: now, updatedAt: now, revision: 0, scrollTop: 0, questions: source.questions.map((question) => ({ ...question, id: newId() })) };
}

/** Convert records written by the v1 web app without dropping answers. */
export function migrateStoredExercise(value: unknown): Exercise {
  if (!value || typeof value !== "object") throw new Error("本地练习记录无效。");
  const source = value as Partial<Exercise> & { questions?: unknown[] };
  if (!Array.isArray(source.questions)) throw new Error("本地练习缺少题目。");
  const id = typeof source.id === "string" ? source.id : newId();
  const name = typeof source.name === "string" ? source.name : "未命名练习";
  const startNumber = typeof source.startNumber === "number" && Number.isInteger(source.startNumber) ? source.startNumber : 1;
  const questions = source.questions.map((raw, index) => {
    const old = raw as Partial<Question>;
    const number = typeof old.number === "number" && Number.isInteger(old.number) ? old.number : startNumber + index;
    const type = old.type === "multiple" || old.type === "boolean" ? old.type : "single";
    const options = Array.isArray(old.options) && old.options.every((item) => typeof item === "string") ? [...old.options] : type === "boolean" ? [...BOOLEAN_OPTIONS] : [...ANSWERS];
    const answer = old.answer === null || old.answer === undefined
      ? null
      : type === "boolean"
        ? typeof old.answer === "boolean" ? old.answer : null
        : type === "multiple"
          ? (() => { const values = normalizeOptionList(old.answer, options); return values.length ? values : null; })()
          : typeof old.answer === "string" ? old.answer : null;
    const uncertainOptions = normalizeOptionList(old.uncertainOptions, options);
    return { id: typeof old.id === "string" ? old.id : newId(), questionId: typeof old.questionId === "string" ? old.questionId : `legacy:${id}:q:${number}`, number, ...(typeof old.section === "string" ? { section: old.section } : {}), type, options, answer, uncertainOptions, note: typeof old.note === "string" ? old.note.slice(0, 200) : "", important: old.important === true, wholeUncertain: typeof old.wholeUncertain === "boolean" ? old.wholeUncertain : (options.length > 0 && uncertainOptions.length === options.length), unknown: old.unknown === true, review: old.review === true } satisfies Question;
  });
  const now = new Date().toISOString();
  const revision = typeof source.revision === "number" && Number.isInteger(source.revision) && source.revision >= 0 ? source.revision : 0;
  return { id, paperId: typeof source.paperId === "string" ? source.paperId : `legacy:${id}`, paperVersion: typeof source.paperVersion === "string" ? source.paperVersion : "1", attemptId: typeof source.attemptId === "string" ? source.attemptId : `legacy-attempt:${id}`, name, startNumber, questionCount: questions.length, status: source.status === "completed" ? "completed" : "active", createdAt: typeof source.createdAt === "string" ? source.createdAt : now, updatedAt: typeof source.updatedAt === "string" ? source.updatedAt : now, revision, scrollTop: typeof source.scrollTop === "number" && source.scrollTop >= 0 ? source.scrollTop : 0, questions, ...(typeof source.savedRevision === "number" && Number.isInteger(source.savedRevision) && source.savedRevision >= 0 && source.savedRevision <= revision ? { savedRevision: source.savedRevision } : {}) };
}
