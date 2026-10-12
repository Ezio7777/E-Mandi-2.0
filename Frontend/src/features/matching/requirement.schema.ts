import { z } from "zod";

export const requirementSchema = z.object({
  crop: z.string().trim().min(2, "Enter the crop you need"),
  quantityKg: z.coerce.number({ invalid_type_error: "Enter a number" }).positive("Quantity must be more than 0"),
  desiredGrade: z.enum(["A", "B", "C"]),
  destination: z.string().trim().min(2, "Enter the delivery location"),
  deliveryDate: z.string().min(1, "Choose a delivery date").refine((d) => new Date(d) >= new Date(new Date().toDateString()), "Delivery date can't be in the past"),
  maxBudget: z.coerce.number({ invalid_type_error: "Enter a number" }).positive("Budget must be more than 0"),
});
export type RequirementValues = z.infer<typeof requirementSchema>;
