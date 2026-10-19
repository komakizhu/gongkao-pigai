import { migrateStoredExercise } from "./domain";
import type { Exercise } from "./types";

const DB_NAME = "ipad-answer-recorder";
const DB_VERSION = 2;
const STORE = "exercises";
const VIEW_STORE = "viewState";

export class RevisionConflictError extends Error {}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" });
      if (!db.objectStoreNames.contains(VIEW_STORE)) db.createObjectStore(VIEW_STORE, { keyPath: "id" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("无法打开本地数据库。"));
  });
}

function closeAfter<T>(db: IDBDatabase, promise: Promise<T>): Promise<T> {
  return promise.finally(() => db.close());
}

export async function listExercises(): Promise<Exercise[]> {
  const db = await openDb();
  return closeAfter(db, new Promise<Exercise[]>((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const request = tx.objectStore(STORE).getAll();
    request.onsuccess = () => {
      try { resolve((request.result as unknown[]).map(migrateStoredExercise).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))); } catch (error) { reject(error); }
    };
    request.onerror = () => reject(request.error ?? new Error("无法读取本地练习。"));
  }));
}

export async function getExercise(id: string): Promise<Exercise | undefined> {
  const db = await openDb();
  return closeAfter(db, new Promise<Exercise | undefined>((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly"); const request = tx.objectStore(STORE).get(id);
    request.onsuccess = () => { try { resolve(request.result ? migrateStoredExercise(request.result) : undefined); } catch (error) { reject(error); } };
    request.onerror = () => reject(request.error ?? new Error("无法读取本地练习。"));
  }));
}

export function saveExercise(exercise: Exercise, expectedRevision?: number): Promise<void> {
  return openDb().then((db) => closeAfter(db, new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite"); const store = tx.objectStore(STORE); const read = store.get(exercise.id); let failed = false;
    const fail = (error: Error) => { if (failed) return; failed = true; try { tx.abort(); } catch { /* transaction already closed */ } reject(error); };
    read.onerror = () => fail(read.error ?? new Error("本地保存失败。"));
    read.onsuccess = () => {
      const existing = read.result as Exercise | undefined;
      if (expectedRevision !== undefined && (!existing || existing.revision !== expectedRevision)) { fail(new RevisionConflictError("练习在其他页面中发生了变化，请重新载入后再保存。")); return; }
      try { store.put(structuredClone(exercise)); } catch (error) { fail(error instanceof Error ? error : new Error("本地保存失败。")); }
    };
    tx.onerror = () => fail(tx.error ?? new Error("本地保存失败。"));
    tx.onabort = () => { if (!failed) { failed = true; reject(tx.error ?? new Error("本地保存失败。")); } };
    tx.oncomplete = () => { if (!failed) { failed = true; resolve(); } };
  })));
}

export async function saveScrollPosition(id: string, scrollTop: number): Promise<void> {
  const db = await openDb();
  return closeAfter(db, new Promise<void>((resolve, reject) => {
    const tx = db.transaction(VIEW_STORE, "readwrite"); tx.objectStore(VIEW_STORE).put({ id, scrollTop: Math.max(0, scrollTop), updatedAt: new Date().toISOString() });
    tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error ?? new Error("滚动位置保存失败。")); tx.onabort = () => reject(tx.error ?? new Error("滚动位置保存失败。"));
  }));
}

export async function getScrollPosition(id: string): Promise<number> {
  const db = await openDb();
  return closeAfter(db, new Promise<number>((resolve, reject) => {
    const tx = db.transaction(VIEW_STORE, "readonly"); const request = tx.objectStore(VIEW_STORE).get(id);
    request.onsuccess = () => resolve(typeof request.result?.scrollTop === "number" ? request.result.scrollTop : 0);
    request.onerror = () => reject(request.error ?? new Error("无法读取滚动位置。"));
  }));
}

export async function removeExercise(id: string): Promise<void> {
  const db = await openDb();
  return closeAfter(db, new Promise<void>((resolve, reject) => {
    const tx = db.transaction([STORE, VIEW_STORE], "readwrite"); tx.objectStore(STORE).delete(id); tx.objectStore(VIEW_STORE).delete(id);
    tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error ?? new Error("删除练习失败。")); tx.onabort = () => reject(tx.error ?? new Error("删除练习失败。"));
  }));
}

export async function clearDatabaseForTests(): Promise<void> {
  const db = await openDb();
  return closeAfter(db, new Promise<void>((resolve, reject) => {
    const tx = db.transaction([STORE, VIEW_STORE], "readwrite"); tx.objectStore(STORE).clear(); tx.objectStore(VIEW_STORE).clear();
    tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error ?? new Error("清理本地数据库失败。")); tx.onabort = () => reject(tx.error ?? new Error("清理本地数据库失败。"));
  }));
}
