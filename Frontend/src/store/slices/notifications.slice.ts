import { createSlice, nanoid, type PayloadAction } from "@reduxjs/toolkit";

export interface Toast { id: string; kind: "success" | "error" | "info"; message: string }
interface NotificationsState { toasts: Toast[]; unread: number }
const initialState: NotificationsState = { toasts: [], unread: 0 };

const notificationsSlice = createSlice({
  name: "notifications",
  initialState,
  reducers: {
    toastPushed: {
      reducer(state, a: PayloadAction<Toast>) { state.toasts.push(a.payload); },
      prepare(kind: Toast["kind"], message: string) { return { payload: { id: nanoid(), kind, message } }; },
    },
    toastDismissed(state, a: PayloadAction<string>) { state.toasts = state.toasts.filter((t) => t.id !== a.payload); },
    unreadCountSet(state, a: PayloadAction<number>) { state.unread = a.payload; },
  },
});
export const { toastPushed, toastDismissed, unreadCountSet } = notificationsSlice.actions;
export default notificationsSlice.reducer;
