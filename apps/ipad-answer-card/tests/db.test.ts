import "fake-indexeddb/auto";
import { afterEach, describe, expect, it } from "vitest";
import { clearDatabaseForTests, getScrollPosition, listExercises, saveExercise, saveScrollPosition } from "../src/db";
import { createExercise, createExerciseFromConfig, setAnswer, toggleUncertainOption } from "../src/domain";
import type { Exercise } from "../src/types";

describe("IndexedDB persistence", () => {
  afterEach(async () => { await clearDatabaseForTests(); });

  it("preserves sections and an explicitly cleared whole-question mark on reopening", async () => {
    const exercise = createExerciseFromConfig({ schemaVersion: 2, type: "answer-recorder-config", paperId: "sections", paperVersion: "1", name: "恢复字段", questions: [{ questionId: "section:q1", section: "常识判断", number: 1, type: "single", options: ["A", "B"] }] });
    exercise.questions[0].uncertainOptions = ["A", "B"];
    exercise.questions[0].wholeUncertain = false;
    await saveExercise(exercise);
    const [restored] = await listExercises();
    expect(restored.questions).toEqual(exercise.questions);
  });

  it("restores the latest snapshot with question identities intact", async () => {
    const exercise = createExercise({ name: "持久化", startNumber: 41, questionCount: 2 });
    await saveExercise(exercise);
    const changed = toggleUncertainOption(setAnswer(exercise, exercise.questions[1].id, "D"), exercise.questions[1].id, "A");
    await saveExercise(changed);
    const restored = await listExercises();
    expect(restored).toHaveLength(1);
    expect(restored[0].questions[1].number).toBe(42);
    expect(restored[0].questions[1].answer).toBe("D");
    expect(restored[0].questions[1].uncertainOptions).toEqual(["A"]);
  });

  it("migrates old stored records with typed answers and no uncertain field", async () => {
    const legacy = {
      id: "legacy-db",
      name: "旧数据库",
      startNumber: 1,
      questions: [
        { id: "legacy-q1", questionId: "legacy-q1", number: 1, type: "multiple", options: ["A", "B", "C", "D"], answer: ["C", "A"], review: false },
        { id: "legacy-q2", questionId: "legacy-q2", number: 2, type: "boolean", options: ["对", "错"], answer: false, review: false },
      ],
    } as unknown as Exercise;
    await saveExercise(legacy);
    const restored = await listExercises();
    expect(restored[0].questions[0].answer).toEqual(["A", "C"]);
    expect(restored[0].questions[0].uncertainOptions).toEqual([]);
    expect(restored[0].questions[1].answer).toBe(false);
  });

  it("keeps scroll auxiliary state out of answer revisions and rejects stale writers", async () => {
    const exercise = createExercise({ name: "时序", startNumber: 1, questionCount: 1 });
    await saveExercise(exercise);
    const first = setAnswer(exercise, exercise.questions[0].id, "B");
    const second = setAnswer({ ...first, revision: 2 }, first.questions[0].id, "C");
    await saveExercise(second, 0);
    await saveScrollPosition(exercise.id, 480);
    expect(await getScrollPosition(exercise.id)).toBe(480);
    await expect(saveExercise({ ...second, revision: 3 }, 0)).rejects.toThrow("其他页面");
    const restored = await listExercises();
    expect(restored[0].questions[0].answer).toBe("C");
    expect(restored[0].revision).toBe(2);
  });
});
