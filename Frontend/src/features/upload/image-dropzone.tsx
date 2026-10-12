"use client";
import { useRef, useState } from "react";
import { Camera, ImagePlus, RefreshCw, RotateCcw, Trash2, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/cn";
import { ACCEPTED, MAX_IMAGES } from "./upload.schema";
import { SAMPLE_CROPS } from "./sample-crops";
import type { useImageUpload } from "./use-image-upload";

type Upload = ReturnType<typeof useImageUpload>;

export function ImageDropzone({ upload }: { upload: Upload }) {
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const camRef = useRef<HTMLInputElement>(null);
  const full = upload.items.length >= MAX_IMAGES;

  return (
    <div className="space-y-4" data-tour="upload-zone">
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); if (!full) upload.addFiles(e.dataTransfer.files); }}
        className={cn("flex flex-col items-center gap-3 rounded-xl border-2 border-dashed p-6 text-center transition-colors sm:p-8", drag ? "border-primary bg-primary-soft" : "border-input", full && "opacity-60")}
      >
        <UploadCloud className="h-9 w-9 text-primary" aria-hidden />
        <div>
          <p className="font-medium">Drag photos here</p>
          <p className="text-sm text-muted-foreground">Up to {MAX_IMAGES} photos. JPG, PNG or WebP.</p>
        </div>
        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
          <Button type="button" variant="outline" disabled={full} onClick={() => fileRef.current?.click()}><ImagePlus /> Choose photos</Button>
          <Button type="button" variant="outline" disabled={full} onClick={() => camRef.current?.click()}><Camera /> Use camera</Button>
        </div>
        <input ref={fileRef} type="file" accept={ACCEPTED.join(",")} multiple hidden onChange={(e) => { if (e.target.files) upload.addFiles(e.target.files); e.target.value = ""; }} />
        <input ref={camRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { if (e.target.files) upload.addFiles(e.target.files); e.target.value = ""; }} />
      </div>

      <div>
        <p className="mb-2 text-sm font-medium">Try with sample crop</p>
        <div className="grid grid-cols-4 gap-2">
          {SAMPLE_CROPS.map((s) => (
            <button key={s.id} type="button" disabled={full} onClick={() => upload.addSample(s)}
              className="group overflow-hidden rounded-lg border bg-card text-xs font-medium hover:border-primary disabled:opacity-50">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={s.src} alt="" className="aspect-square w-full object-cover" />
              <span className="block truncate px-1 py-1.5">{s.name}</span>
            </button>
          ))}
        </div>
      </div>

      {upload.errors.length > 0 && (
        <ul role="alert" className="space-y-1 text-sm text-danger">{upload.errors.map((e) => <li key={e}>{e}</li>)}</ul>
      )}

      {upload.items.length > 0 && (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {upload.items.map((it) => (
            <li key={it.id} className="overflow-hidden rounded-lg border bg-card">
              <div className="relative aspect-[4/3] bg-muted">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={it.preview} alt={`Preview of ${it.name}`} className="h-full w-full object-cover" />
                {it.status === "uploading" && (
                  <div className="absolute inset-x-0 bottom-0 bg-background/80 p-2">
                    <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={it.progress} aria-valuemin={0} aria-valuemax={100} aria-label={`Uploading ${it.name}`}>
                      <div className="h-full bg-primary transition-all" style={{ width: `${it.progress}%` }} />
                    </div>
                  </div>
                )}
              </div>
              <div className="flex items-center justify-between gap-1 p-2">
                <span className={cn("truncate text-xs", it.status === "error" ? "text-danger" : "text-muted-foreground")}>
                  {it.status === "error" ? it.error : it.status === "done" ? "Uploaded" : `${it.progress}%`}
                </span>
                <div className="flex shrink-0">
                  {it.status === "error" && it.file && <Button type="button" size="icon" variant="ghost" className="h-9 w-9 min-h-0 min-w-0" onClick={() => upload.retry(it.id)} aria-label="Retry upload"><RotateCcw /></Button>}
                  {it.file && (
                    <label className="inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-md hover:bg-accent" aria-label={`Replace ${it.name}`}>
                      <RefreshCw className="h-4 w-4" />
                      <input type="file" accept={ACCEPTED.join(",")} hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.replace(it.id, f); e.target.value = ""; }} />
                    </label>
                  )}
                  <Button type="button" size="icon" variant="ghost" className="h-9 w-9 min-h-0 min-w-0" onClick={() => upload.remove(it.id)} aria-label={`Remove ${it.name}`}><Trash2 /></Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
