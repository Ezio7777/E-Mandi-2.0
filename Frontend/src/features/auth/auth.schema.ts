import { z } from "zod";

export const loginSchema = z.object({
  email: z.string().min(1, "Enter your email").email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});
export type LoginValues = z.infer<typeof loginSchema>;

export const phoneSchema = z.object({
  phone: z.string().regex(/^(\+91)?[6-9]\d{9}$/, "Enter a valid 10-digit Indian mobile number"),
});
export const otpSchema = z.object({ code: z.string().regex(/^\d{6}$/, "Enter the 6-digit code") });
