export type QuestionType = "single" | "multiple" | "boolean";
export type Choice = string;
export type Answer = Choice;
export type AnswerValue = Choice | Choice[] | boolean | null;
export type ExerciseStatus = "active" | "completed";

export interface Question {
  id: string;
  questionId: string;
  number: number;
  section?: string;
  type: QuestionType;
  options: string[];
  answer: AnswerValue;
  uncertainOptions: string[];
  note: string;
  important: boolean;
  wholeUncertain: boolean;
  unknown: boolean;
  review: boolean;
}

export interface Exercise {
  id: string;
  paperId: string;
  paperVersion: string;
  attemptId: string;
  name: string;
  startNumber: number;
  questionCount: number;
  status: ExerciseStatus;
  createdAt: string;
  updatedAt: string;
  /** Answer/status revision only. Scroll position is stored separately. */
  revision: number;
  /** Last revision explicitly saved and read back successfully; background recovery is separate. */
  savedRevision?: number;
  /** Kept for v1 display/compatibility; new code reads the auxiliary view-state store. */
  scrollTop: number;
  questions: Question[];
}

export interface PublicQuestionConfig {
  questionId: string;
  number: number;
  section?: string;
  type: QuestionType;
  options: string[];
}

export interface PublicExerciseConfig {
  schemaVersion: 2;
  type: "answer-recorder-config";
  paperId: string;
  paperVersion: string;
  name: string;
  questions: PublicQuestionConfig[];
}

export interface ExerciseExport {
  schemaVersion: 2;
  type: "answer-recorder-attempt";
  exportedAt: string;
  exercise: Exercise;
}

export const ANSWERS: Choice[] = ["A", "B", "C", "D"];
export const BOOLEAN_OPTIONS = ["对", "错"] as const;

export function isAnswerValueEmpty(answer: AnswerValue): boolean {
  return answer === null || (Array.isArray(answer) && answer.length === 0);
}
