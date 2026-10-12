import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { UserDto, Role } from "@/types";

interface AuthState {
  user: UserDto | null;
  role: Role | null;
  status: "unknown" | "authenticated" | "unauthenticated";
}
const initialState: AuthState = { user: null, role: null, status: "unknown" };

/** UI snapshot only. The backend remains the source of truth for identity and permissions. */
const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    sessionLoaded(state, action: PayloadAction<UserDto>) {
      state.user = action.payload;
      state.role = action.payload.role;
      state.status = "authenticated";
    },
    sessionCleared(state) {
      state.user = null; state.role = null; state.status = "unauthenticated";
    },
    sessionExpired(state) {
      state.user = null; state.role = null; state.status = "unauthenticated";
    },
  },
});
export const { sessionLoaded, sessionCleared, sessionExpired } = authSlice.actions;
export default authSlice.reducer;
