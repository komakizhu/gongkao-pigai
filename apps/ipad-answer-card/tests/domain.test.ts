import { describe, expect, it } from "vitest";
import { answeredCount, clearAnswer, createExercise, createExerciseFromConfig, migrateStoredExercise, setAnswer, toggleOption, toggleReview, toggleUncertainOption, validateCreateInput } from "../src/domain";
import { parseConfig, parseImport, toConfigPayload, toCsv, toExportPayload } from "../src/format";

describe("exercise domain", () => {
  it("creates stable unanswered questions and validates ranges", () => {
    const exercise = createExercise({ name: "专项", startNumber: 41, questionCount: 3 });
    expect(exercise.questions.map((question) => question.number)).toEqual([41, 42, 43]);
    expect(exercise.questions.every((question) => question.answer === null)).toBe(true);
    expect(exercise.questions.every((question) => question.uncertainOptions.length === 0)).toBe(true);
    expect(new Set(exercise.questions.map((question) => question.id)).size).toBe(3);
    expect(validateCreateInput({ name: "", startNumber: 1, questionCount: 1 })).toContain("名称");
    expect(validateCreateInput({ name: "x", startNumber: 0, questionCount: 1 })).toContain("起始");
  });

  it("changes only the requested question and repeated answers remain selected", () => {
    const exercise = createExercise({ name: "专项", startNumber: 41, questionCount: 3 });
    const q43 = exercise.questions[2].id;
    const selected = setAnswer(exercise, q43, "B");
    const changed = setAnswer(selected, q43, "D");
    expect(answeredCount(changed)).toBe(1);
    expect(changed.questions[2].answer).toBe("D");
    expect(changed.questions[0].answer).toBeNull();
    expect(setAnswer(changed, q43, "D").questions[2].answer).toBe("D");
    expect(clearAnswer(changed, q43).questions[2].answer).toBeNull();
    expect(toggleReview(changed, q43).questions[2].review).toBe(true);
  });

  it("round trips JSON and exports every question to CSV", () => {
    const exercise = createExercise({ name: "导出,测试", startNumber: 41, questionCount: 3 });
    const changed = toggleUncertainOption(setAnswer(exercise, exercise.questions[1].id, "C"), exercise.questions[1].id, "A");
    const restored = parseImport(JSON.stringify(toExportPayload(changed)));
    expect(restored.questions.map((question) => question.number)).toEqual([41, 42, 43]);
    expect(restored.questions[1].answer).toBe("C");
    expect(restored.questions[1].uncertainOptions).toEqual(["A"]);
    expect(restored.id).not.toBe(changed.id);
    const csv = toCsv(changed);
    expect(csv.startsWith("\uFEFFschema_version,paper_id,paper_version")).toBe(true);
    expect(csv.split("\r\n")).toHaveLength(5);
    expect(csv).toContain(",42,single,C,true,false,A");
  });

  it("rejects malformed backups without partial parsing", () => {
    expect(() => parseImport("{}")) .toThrow();
    const exercise = createExercise({ name: "专项", startNumber: 1, questionCount: 2 });
    const payload = toExportPayload(exercise) as unknown as Record<string, unknown>;
    const nested = payload.exercise as typeof exercise;
    nested.questions[1].number = 99;
    expect(() => parseImport(JSON.stringify(payload))).toThrow("题号");
  });

  it("rejects invalid uncertain options without accepting a partial backup", () => {
    const exercise = createExercise({ name: "标记校验", startNumber: 1, questionCount: 1 });
    const payload = toExportPayload(exercise) as unknown as Record<string, unknown>;
    const nested = payload.exercise as typeof exercise;
    delete (nested.questions[0] as unknown as Record<string, unknown>).uncertainOptions;
    expect(parseImport(JSON.stringify(payload)).questions[0].uncertainOptions).toEqual([]);

    (nested.questions[0] as unknown as Record<string, unknown>).uncertainOptions = ["Z"];
    expect(() => parseImport(JSON.stringify(payload))).toThrow("不确定选项");

    (nested.questions[0] as unknown as Record<string, unknown>).uncertainOptions = "A";
    expect(() => parseImport(JSON.stringify(payload))).toThrow("不确定选项");
  });

  it("handles multiple selection and boolean false independently from unanswered", () => {
    const exercise = createExerciseFromConfig({ schemaVersion: 2, type: "answer-recorder-config", paperId: "paper", paperVersion: "v1", name: "三类", questions: [
      { questionId: "q1", number: 1, type: "multiple", options: ["A", "B", "C", "D"] },
      { questionId: "q2", number: 2, type: "boolean", options: ["对", "错"] },
    ] });
    const multi = toggleOption(exercise, exercise.questions[0].id, "A");
    const multiAgain = toggleOption(multi, exercise.questions[0].id, "C");
    const bool = setAnswer(multiAgain, exercise.questions[1].id, false);
    expect(bool.questions[0].answer).toEqual(["A", "C"]);
    expect(bool.questions[1].answer).toBe(false);
    expect(answeredCount(bool)).toBe(2);
    expect(toggleOption(bool, bool.questions[0].id, "A").questions[0].answer).toEqual(["C"]);
    const marked = toggleUncertainOption(toggleUncertainOption(bool, bool.questions[0].id, "D"), bool.questions[1].id, "错");
    const restored = parseImport(JSON.stringify(toExportPayload(marked)));
    expect(restored.questions[0].answer).toEqual(["A", "C"]);
    expect(restored.questions[0].uncertainOptions).toEqual(["D"]);
    expect(restored.questions[1].answer).toBe(false);
    expect(restored.questions[1].uncertainOptions).toEqual(["错"]);
    const csv = toCsv(marked);
    expect(csv).toContain("multiple,A|C,true,false,D");
    expect(csv).toContain("boolean,false,true,false,错");
  });

  it("migrates legacy multiple and boolean answers without dropping false", () => {
    const migrated = migrateStoredExercise({
      id: "legacy-exercise",
      name: "旧记录",
      startNumber: 1,
      questions: [
        { id: "q1", questionId: "q1", number: 1, type: "multiple", options: ["A", "B", "C", "D"], answer: ["A", "C"], review: false },
        { id: "q2", questionId: "q2", number: 2, type: "boolean", options: ["对", "错"], answer: false, review: true },
      ],
    });
    expect(migrated.questions[0].answer).toEqual(["A", "C"]);
    expect(migrated.questions[1].answer).toBe(false);
    expect(migrated.questions[0].uncertainOptions).toEqual([]);
    expect(migrated.questions[1].uncertainOptions).toEqual([]);
  });

  it("toggles independent uncertain options in question order", () => {
    const exercise = createExercise({ name: "不确定", startNumber: 1, questionCount: 1 });
    const questionId = exercise.questions[0].id;
    const marked = toggleUncertainOption(toggleUncertainOption(exercise, questionId, "C"), questionId, "A");
    expect(marked.questions[0].answer).toBeNull();
    expect(marked.questions[0].uncertainOptions).toEqual(["A", "C"]);
    const withAnswer = setAnswer(marked, questionId, "A");
    expect(withAnswer.questions[0].uncertainOptions).toEqual(["A", "C"]);
    const cleared = clearAnswer(withAnswer, questionId);
    expect(cleared.questions[0].uncertainOptions).toEqual(["A", "C"]);
    expect(toggleUncertainOption(cleared, questionId, "A").questions[0].uncertainOptions).toEqual(["C"]);
  });

  it("keeps reference-answer fields out of public config and serializes typed CSV", () => {
    const exercise = createExerciseFromConfig({ schemaVersion: 2, type: "answer-recorder-config", paperId: "paper", paperVersion: "v2", name: "公开", questions: [
      { questionId: "q1", number: 1, type: "multiple", options: ["A", "B", "C", "D"] },
      { questionId: "q2", number: 2, type: "boolean", options: ["对", "错"] },
    ] });
    const answered = setAnswer(toggleOption(exercise, exercise.questions[0].id, "C"), exercise.questions[1].id, false);
    const config = toConfigPayload(answered);
    expect(JSON.stringify(config)).not.toContain("referenceAnswer");
    expect(JSON.stringify(config)).not.toContain("uncertainOptions");
    expect(parseConfig(JSON.stringify(config)).questions).toHaveLength(2);
    const csv = toCsv(answered);
    expect(csv).toContain("question_type,answer,answered,review_flag,uncertain_options");
    expect(csv).toContain("multiple,C,true,false,");
    expect(csv).toContain("boolean,false,true,false,");
  });

  it("rejects reference answers accidentally placed in a public config", () => {
    const bad = { schemaVersion: 2, type: "answer-recorder-config", paperId: "p", paperVersion: "1", name: "坏配置", questions: [{ questionId: "q", number: 1, type: "single", options: ["A", "B"], referenceAnswer: "A" }] };
    expect(() => parseConfig(JSON.stringify(bad))).toThrow("私有答案");
  });
});
