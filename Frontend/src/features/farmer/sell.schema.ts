import { z } from "zod";

export const cropSchema = z.object({ crop: z.string().trim().min(2, "Enter the crop name") });
export const quantitySchema = z.object({
  quantityKg: z.coerce.number({ invalid_type_error: "Enter a number" }).positive("Quantity must be more than 0").max(100000, "Maximum 1,00,000 kg per listing"),
});
export const locationSchema = z.object({ location: z.string().trim().min(2, "Enter your village, town or district") });
export const priceSchema = z.object({ pricePerKg: z.coerce.number({ invalid_type_error: "Enter a price" }).positive("Price must be more than 0").max(10000) });
