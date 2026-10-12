"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { authApi } from "@/lib/api";
import { setAccessToken } from "@/lib/api/client";
import { queryKeys } from "@/lib/query/keys";
import { useAppDispatch } from "@/store/hooks";
import { sessionCleared, sessionLoaded } from "@/store/slices/auth.slice";
import { demoEnded, demoStarted } from "@/store/slices/demo.slice";
import { tourReset } from "@/store/slices/tour.slice";
import { resolveNext } from "@/utils/safe-redirect";
import type { AuthSessionDto, Role } from "@/types";

/** Non-sensitive hint cookie for the Next middleware (the API cookie may live on another origin). */
const setHint = (on: boolean) => {
  document.cookie = `emandi_session=${on ? "1" : ""}; path=/; SameSite=Lax; ${on ? "max-age=604800" : "max-age=0"}`;
};

export function useSession() {
  const dispatch = useAppDispatch();
  return useQuery({
    queryKey: queryKeys.session,
    queryFn: async () => {
      try {
        const user = await authApi.me();
        setHint(true);
        dispatch(sessionLoaded(user));
        return user;
      } catch (e) {
        setHint(false);
        dispatch(sessionCleared());
        throw e;
      }
    },
    retry: false,
    staleTime: 60_000,
  });
}

function useSessionSuccess() {
  const dispatch = useAppDispatch();
  const router = useRouter();
  const qc = useQueryClient();
  return (s: AuthSessionDto, demo = false) => {
    if (s.accessToken) setAccessToken(s.accessToken);
    setHint(true);
    dispatch(sessionLoaded(s.user));
    if (demo || s.user.isDemo) dispatch(demoStarted(s.user.role)); else dispatch(demoEnded());
    qc.setQueryData(queryKeys.session, s.user);
    router.replace(resolveNext(new URLSearchParams(window.location.search).get("next"), s.user.role));
  };
}

export const useLogin = () => {
  const ok = useSessionSuccess();
  return useMutation({ mutationFn: (v: { email: string; password: string }) => authApi.login(v.email, v.password), onSuccess: (s) => ok(s) });
};
export const useRequestOtp = () => useMutation({ mutationFn: (phone: string) => authApi.requestOtp(phone) });
export const useVerifyOtp = () => {
  const ok = useSessionSuccess();
  return useMutation({ mutationFn: (v: { phone: string; code: string }) => authApi.verifyOtp(v.phone, v.code), onSuccess: (s) => ok(s) });
};
export const useGoogleLogin = () => {
  const ok = useSessionSuccess();
  return useMutation({ mutationFn: (credential: string) => authApi.google(credential), onSuccess: (s) => ok(s) });
};
export const useDemoLogin = () => {
  const ok = useSessionSuccess();
  return useMutation({ mutationFn: (role: Role) => authApi.demo(role), onSuccess: (s) => ok(s, true) });
};
export const useLogout = () => {
  const dispatch = useAppDispatch();
  const router = useRouter();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => authApi.logout(),
    onSettled: () => {
      setAccessToken(null);
      setHint(false);
      dispatch(sessionCleared());
      dispatch(demoEnded());
      dispatch(tourReset());
      qc.clear();
      router.replace("/login");
    },
  });
};
