"use client";
import { useCallback, useRef, useState } from "react";
import { uploadsApi, uploadToS3 } from "@/lib/api";
import { MAX_IMAGES, validateFile } from "./upload.schema";
import type { SampleCrop } from "./sample-crops";

export type UploadStatus = "uploading" | "done" | "error";
export interface UploadItem {
  id: string;
  name: string;
  preview: string;
  status: UploadStatus;
  progress: number;
  objectKey?: string;
  error?: string;
  file?: File;
}

/**
 * presigned S3 flow: init → direct browser upload → confirm. Large files never pass through the API.
 * Items live in a ref mirrored to state, so side effects (starting uploads) never run inside a
 * state updater (React may invoke updaters twice in StrictMode).
 */
export function useImageUpload() {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const ref = useRef<UploadItem[]>([]);
  const aborts = useRef(new Map<string, AbortController>());

  const commit = useCallback((next: UploadItem[]) => { ref.current = next; setItems(next); }, []);
  const patch = useCallback((id: string, p: Partial<UploadItem>) => commit(ref.current.map((i) => (i.id === id ? { ...i, ...p } : i))), [commit]);

  const send = useCallback(async (id: string, file: File) => {
    const ctrl = new AbortController();
    aborts.current.set(id, ctrl);
    patch(id, { status: "uploading", progress: 0, error: undefined });
    try {
      const init = await uploadsApi.init(file.name, file.type, file.size);
      await uploadToS3(init, file, (progress) => patch(id, { progress }), ctrl.signal);
      const meta = await uploadsApi.confirm(init.objectKey);
      patch(id, { status: "done", progress: 100, objectKey: meta.objectKey });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      patch(id, { status: "error", error: e instanceof Error ? e.message : "Upload failed" });
    } finally {
      aborts.current.delete(id);
    }
  }, [patch]);

  const addFiles = useCallback((files: FileList | File[]) => {
    const list = Array.from(files);
    const problems: string[] = [];
    const room = MAX_IMAGES - ref.current.length;
    if (list.length > room) problems.push(`You can add up to ${MAX_IMAGES} photos.`);
    const added: UploadItem[] = [];
    for (const f of list.slice(0, Math.max(room, 0))) {
      const err = validateFile(f);
      if (err) { problems.push(err); continue; }
      added.push({ id: crypto.randomUUID(), name: f.name, preview: URL.createObjectURL(f), status: "uploading", progress: 0, file: f });
    }
    setErrors(problems);
    if (added.length === 0) return;
    commit([...ref.current, ...added]);
    for (const a of added) void send(a.id, a.file!);
  }, [commit, send]);

  const addSample = useCallback(async (s: SampleCrop) => {
    if (ref.current.length >= MAX_IMAGES) return;
    const id = crypto.randomUUID();
    setErrors([]);
    commit([...ref.current, { id, name: s.name, preview: s.src, status: "uploading", progress: 15 }]);
    // Realistic progress while the backend registers the sample (and can reuse cached grading by image hash).
    const tick = setInterval(() => {
      const it = ref.current.find((i) => i.id === id);
      if (it && it.status === "uploading" && it.progress < 85) patch(id, { progress: it.progress + 14 });
    }, 250);
    try {
      const meta = await uploadsApi.useSample(s.id);
      patch(id, { status: "done", progress: 100, objectKey: meta.objectKey });
    } catch (e) {
      patch(id, { status: "error", error: e instanceof Error ? e.message : "Could not load the sample" });
    } finally {
      clearInterval(tick);
    }
  }, [commit, patch]);

  const remove = useCallback((id: string) => {
    aborts.current.get(id)?.abort();
    commit(ref.current.filter((i) => i.id !== id));
  }, [commit]);

  const retry = useCallback((id: string) => {
    const it = ref.current.find((i) => i.id === id);
    if (it?.file) void send(id, it.file);
  }, [send]);

  const replace = useCallback((id: string, file: File) => {
    const err = validateFile(file);
    if (err) { setErrors([err]); return; }
    aborts.current.get(id)?.abort();
    patch(id, { name: file.name, preview: URL.createObjectURL(file), file });
    void send(id, file);
  }, [patch, send]);

  return {
    items, errors, addFiles, addSample, remove, retry, replace,
    ready: items.length > 0 && items.every((i) => i.status === "done"),
    keys: items.flatMap((i) => (i.objectKey ? [i.objectKey] : [])),
  };
}
