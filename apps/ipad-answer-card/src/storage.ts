import * as database from "./db";
import { parseEmbeddedExercise, toExportPayload } from "./format";
import type { Exercise } from "./types";

const PREFIX = "answer-recorder:recovery:";
const memory = new Map<string, Exercise>();
let databaseAvailable = false;
let cacheAvailable = false;

export function persistenceKind(): "database" | "cache" | "memory" {
  return databaseAvailable ? "database" : cacheAvailable ? "cache" : "memory";
}

function cachedExercises(): Exercise[] {
  const values: Exercise[] = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key?.startsWith(PREFIX)) continue;
      const text = localStorage.getItem(key);
      try { if (text) values.push(parseEmbeddedExercise(text)); } catch { /* Keep the original invalid entry intact. */ }
    }
  } catch { /* Some file viewers deny browser storage. */ }
  return values;
}

/** Write during the input event, before an asynchronous database write or page close. */
export function stageRecovery(exercise: Exercise): void {
  let current: Exercise | undefined;
  try {
    const text = localStorage.getItem(PREFIX + exercise.id);
    if (text) current = parseEmbeddedExercise(text);
  } catch { /* Unavailable or invalid cache must not prevent the database fallback. */ }
  if (current && (current.revision > exercise.revision || (current.revision === exercise.revision && current.updatedAt !== exercise.updatedAt))) {
    throw new database.RevisionConflictError("其他页面已有更新的作答；当前答案仍在页面中，请先导出再重新载入。");
  }
  memory.set(exercise.id, structuredClone(exercise));
  try {
    const text = JSON.stringify(toExportPayload(exercise));
    localStorage.setItem(PREFIX + exercise.id, text);
    cacheAvailable = localStorage.getItem(PREFIX + exercise.id) === text;
  } catch { cacheAvailable = false; }
}

export async function listExercises(): Promise<Exercise[]> {
  let stored: Exercise[] = [];
  try { stored = await database.listExercises(); databaseAvailable = true; } catch { databaseAvailable = false; }
  const merged = new Map(stored.map((item) => [item.id, item]));
  for (const item of [...cachedExercises(), ...memory.values()]) {
    const previous = merged.get(item.id);
    if (!previous || item.revision > previous.revision) merged.set(item.id, item);
  }
  // Complete interrupted database writes before exposing their recovered revisions for editing.
  for (const item of merged.values()) {
    const previous = stored.find((entry) => entry.id === item.id);
    if (databaseAvailable && (!previous || item.revision > previous.revision)) {
      try { await database.saveExercise(item, previous?.revision); }
      catch (error) { if (error instanceof database.RevisionConflictError) throw error; databaseAvailable = false; }
    }
    stageRecovery(item);
  }
  return [...merged.values()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export async function getExercise(id: string): Promise<Exercise | undefined> {
  return (await listExercises()).find((item) => item.id === id);
}

export async function saveExercise(exercise: Exercise, expectedRevision?: number): Promise<void> {
  // A pending write may be older than the next queued input; do not roll its recovery record back.
  const staged = memory.get(exercise.id);
  if (!staged || staged.revision < exercise.revision || (staged.revision === exercise.revision && staged.updatedAt !== exercise.updatedAt)) stageRecovery(exercise);
  try { await database.saveExercise(exercise, expectedRevision); databaseAvailable = true; }
  catch (error) { if (error instanceof database.RevisionConflictError) throw error; databaseAvailable = false; }
}

/** Read back actual persistent storage, never the in-memory recovery map. */
export async function verifyStoredExercise(exercise: Exercise): Promise<void> {
  // Scroll is stored separately and may change while the answer transaction is pending.
  const matches = (stored: Exercise | undefined) => stored && JSON.stringify({ ...stored, scrollTop: 0 }) === JSON.stringify({ ...exercise, scrollTop: 0 });
  try {
    if (matches(await database.getExercise(exercise.id))) { databaseAvailable = true; return; }
  } catch { databaseAvailable = false; }
  try {
    const text = localStorage.getItem(PREFIX + exercise.id);
    if (text && matches(parseEmbeddedExercise(text))) { cacheAvailable = true; return; }
  } catch { cacheAvailable = false; }
  throw new Error("此查看器未能保存当前作答，请先导出 JSON 再退出。");
}

export async function removeExercise(id: string): Promise<void> {
  try { await database.removeExercise(id); } catch (error) { if (databaseAvailable) throw error; }
  // Do not silently claim deletion if a persistent recovery record could not be removed.
  try { localStorage.removeItem(PREFIX + id); } catch (error) { if (cacheAvailable) throw error; }
  memory.delete(id);
}

export async function getScrollPosition(id: string): Promise<number> {
  try { return await database.getScrollPosition(id); } catch { return memory.get(id)?.scrollTop ?? 0; }
}

export async function saveScrollPosition(id: string, value: number): Promise<void> {
  try { await database.saveScrollPosition(id, value); } catch { /* Answer persistence does not depend on scroll state. */ }
}
