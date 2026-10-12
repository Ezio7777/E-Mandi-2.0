import { api } from "./client";
import type { Grade, PriceSuggestionDto } from "@/types";

export const pricingApi = {
  suggest: (crop: string, grade: Grade, location: string) =>
    api.get<PriceSuggestionDto>("/pricing/suggest", { crop, grade, location }),
};
