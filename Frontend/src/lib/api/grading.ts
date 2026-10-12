import { api } from "./client";
import type { GradingJobDto } from "@/types";

export const gradingApi = {
  start: (imageKeys: string[], cropName: string) => api.post<{ jobId: string }>("/grading", { imageKeys, cropName }),
  job: (jobId: string) => api.get<GradingJobDto>(`/grading/${jobId}`),
  queue: () => api.get<GradingJobDto[]>("/admin/grading"),
};
