import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

const api = vi.hoisted(() => ({
  init: vi.fn(),
  confirm: vi.fn(),
  useSample: vi.fn(),
  uploadToS3: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  uploadsApi: { init: api.init, confirm: api.confirm, useSample: api.useSample },
  uploadToS3: api.uploadToS3,
}));

import { useImageUpload } from "./use-image-upload";
import { SAMPLE_CROPS } from "./sample-crops";

const jpeg = (name = "tomato.jpg") => new File([new Uint8Array(100)], name, { type: "image/jpeg" });

beforeEach(() => {
  vi.clearAllMocks();
  URL.createObjectURL = vi.fn(() => "blob:preview");
  api.init.mockResolvedValue({ uploadUrl: "https://s3.test/put", objectKey: "uploads/a.jpg" });
  api.uploadToS3.mockImplementation(async (_i: unknown, _f: File, onProgress: (n: number) => void) => onProgress(100));
  api.confirm.mockResolvedValue({ id: "img1", objectKey: "uploads/a.jpg", url: "https://cdn.test/a.jpg" });
});

describe("useImageUpload", () => {
  it("runs init → S3 upload → confirm and exposes the object key", async () => {
    const { result } = renderHook(() => useImageUpload());
    act(() => result.current.addFiles([jpeg()]));
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(api.init).toHaveBeenCalledWith("tomato.jpg", "image/jpeg", 100);
    expect(api.confirm).toHaveBeenCalledWith("uploads/a.jpg");
    expect(result.current.keys).toEqual(["uploads/a.jpg"]);
  });

  it("uploads each file exactly once", async () => {
    const { result } = renderHook(() => useImageUpload());
    act(() => result.current.addFiles([jpeg("a.jpg"), jpeg("b.jpg")]));
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(api.init).toHaveBeenCalledTimes(2);
    expect(api.uploadToS3).toHaveBeenCalledTimes(2);
  });

  it("rejects unsupported files without calling the API", () => {
    const { result } = renderHook(() => useImageUpload());
    act(() => result.current.addFiles([new File(["x"], "doc.pdf", { type: "application/pdf" })]));
    expect(result.current.items).toHaveLength(0);
    expect(result.current.errors[0]).toMatch(/JPG, PNG or WebP/);
    expect(api.init).not.toHaveBeenCalled();
  });

  it("caps the list at 5 photos", async () => {
    const { result } = renderHook(() => useImageUpload());
    act(() => result.current.addFiles(Array.from({ length: 7 }, (_, i) => jpeg(`p${i}.jpg`))));
    expect(result.current.items).toHaveLength(5);
    expect(result.current.errors.join(" ")).toMatch(/up to 5/);
    await waitFor(() => expect(result.current.ready).toBe(true));
  });

  it("marks an item as failed when the S3 upload fails, and can retry", async () => {
    api.uploadToS3.mockRejectedValueOnce(new Error("Upload failed (403)"));
    const { result } = renderHook(() => useImageUpload());
    act(() => result.current.addFiles([jpeg()]));
    await waitFor(() => expect(result.current.items[0]?.status).toBe("error"));
    expect(result.current.items[0]?.error).toBe("Upload failed (403)");
    expect(result.current.ready).toBe(false);

    act(() => result.current.retry(result.current.items[0]!.id));
    await waitFor(() => expect(result.current.ready).toBe(true));
  });

  it("removes an item", async () => {
    const { result } = renderHook(() => useImageUpload());
    act(() => result.current.addFiles([jpeg()]));
    await waitFor(() => expect(result.current.ready).toBe(true));
    act(() => result.current.remove(result.current.items[0]!.id));
    expect(result.current.items).toHaveLength(0);
  });

  it("registers a sample crop through the backend and returns its key", async () => {
    api.useSample.mockResolvedValue({ id: "s1", objectKey: "samples/tomato.jpg", url: "/demo-crops/tomato.svg" });
    const { result } = renderHook(() => useImageUpload());
    await act(async () => { await result.current.addSample(SAMPLE_CROPS[0]); });
    expect(api.useSample).toHaveBeenCalledWith("tomato");
    expect(result.current.keys).toEqual(["samples/tomato.jpg"]);
    expect(api.init).not.toHaveBeenCalled();
  });
});
