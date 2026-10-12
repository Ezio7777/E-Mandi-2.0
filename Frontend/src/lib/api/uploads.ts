import { api } from "./client";
import type { ImageDto, UploadInitDto } from "@/types";

export const uploadsApi = {
  init: (fileName: string, contentType: string, size: number) =>
    api.post<UploadInitDto>("/uploads/init", { fileName, contentType, size }),
  confirm: (objectKey: string) => api.post<ImageDto>("/uploads/confirm", { objectKey }),
  /** Registers a bundled demo image. Backend can cache grading by image hash. */
  useSample: (sampleId: string) => api.post<ImageDto>("/uploads/sample", { sampleId }),
};

/** Direct browser → S3 upload with progress. Large files never touch the API server. */
export function uploadToS3(
  init: UploadInitDto,
  file: File,
  onProgress: (pct: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const isPost = Boolean(init.fields);
    xhr.open(isPost ? "POST" : "PUT", init.uploadUrl);
    if (!isPost) xhr.setRequestHeader("Content-Type", file.type);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`Upload failed (${xhr.status})`)));
    xhr.onerror = () => reject(new Error("Upload failed. Check your connection."));
    signal?.addEventListener("abort", () => { xhr.abort(); reject(new DOMException("Aborted", "AbortError")); });
    if (isPost) {
      const form = new FormData();
      Object.entries(init.fields ?? {}).forEach(([k, v]) => form.append(k, v));
      form.append("file", file);
      xhr.send(form);
    } else {
      xhr.send(file);
    }
  });
}
