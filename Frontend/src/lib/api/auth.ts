import { api } from "./client";
import type { AuthSessionDto, Role, UserDto } from "@/types";

export const authApi = {
  login: (email: string, password: string) => api.post<AuthSessionDto>("/auth/login", { email, password }),
  requestOtp: (phone: string) => api.post<{ sent: boolean }>("/auth/otp/request", { phone }),
  verifyOtp: (phone: string, code: string) => api.post<AuthSessionDto>("/auth/otp/verify", { phone, code }),
  google: (credential: string) => api.post<AuthSessionDto>("/auth/google", { credential }),
  demo: (role: Role) => api.post<AuthSessionDto>("/auth/demo", { role }),
  logout: () => api.post<void>("/auth/logout"),
  me: () => api.get<UserDto>("/auth/me"),
};
