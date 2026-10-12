import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { Role } from "@/types";

interface DemoState { active: boolean; role: Role | null }
const initialState: DemoState = { active: false, role: null };

const demoSlice = createSlice({
  name: "demo",
  initialState,
  reducers: {
    demoStarted(state, a: PayloadAction<Role>) { state.active = true; state.role = a.payload; },
    demoEnded(state) { state.active = false; state.role = null; },
  },
});
export const { demoStarted, demoEnded } = demoSlice.actions;
export default demoSlice.reducer;
