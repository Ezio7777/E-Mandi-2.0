import { api } from "./client";
import type { CreateRequirementInput, MatchDto, RequirementDto } from "@/types";

export const matchingApi = {
  requirements: () => api.get<RequirementDto[]>("/requirements"),
  createRequirement: (input: CreateRequirementInput) => api.post<RequirementDto>("/requirements", input),
  matches: (requirementId?: string) => api.get<MatchDto[]>("/matches", { requirementId }),
};
