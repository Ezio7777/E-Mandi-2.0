"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { gradingApi, pricingApi } from "@/lib/api";
import { queryKeys } from "@/lib/query/keys";
import { useRealtime } from "@/hooks/use-realtime";
import type { Grade, GradingJobDto } from "@/types";

export const useStartGrading = () =>
  useMutation({ mutationFn: (v: { imageKeys: string[]; cropName: string }) => gradingApi.start(v.imageKeys, v.cropName) });

/** Polls until ready; a websocket push (if the backend sends one) short-circuits the wait. */
export function useGradingJob(jobId: string | null) {
  const qc = useQueryClient();
  useRealtime<GradingJobDto>(jobId ? `/ws/grading/${jobId}` : null, (job) => qc.setQueryData(queryKeys.grading.job(job.jobId), job), Boolean(jobId));
  return useQuery({
    queryKey: queryKeys.grading.job(jobId ?? ""),
    queryFn: () => gradingApi.job(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (q) => (q.state.data?.status === "ready" || q.state.data?.status === "failed" ? false : 1200),
  });
}

export const usePriceSuggestion = (crop: string, grade: Grade | undefined, location: string) =>
  useQuery({
    queryKey: queryKeys.pricing(crop, grade ?? "", location),
    queryFn: () => pricingApi.suggest(crop, grade!, location),
    enabled: Boolean(crop && grade && location),
  });
