"use client";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useLogin, useRequestOtp, useVerifyOtp } from "@/services/auth";
import { useT } from "@/lib/i18n";
import { cn } from "@/utils/cn";
import { loginSchema, otpSchema, phoneSchema, type LoginValues } from "./auth.schema";

function Field({ id, label, error, children }: { id: string; label: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error && <p id={`${id}-error`} role="alert" className="text-sm text-danger">{error}</p>}
    </div>
  );
}

function EmailForm() {
  const { t } = useT();
  const login = useLogin();
  const { register, handleSubmit, formState: { errors } } = useForm<LoginValues>({ resolver: zodResolver(loginSchema) });
  return (
    <form onSubmit={handleSubmit((v) => login.mutate(v))} className="space-y-4" noValidate>
      <Field id="email" label={t("auth.email")} error={errors.email?.message}>
        <Input id="email" type="email" autoComplete="email" inputMode="email" aria-invalid={!!errors.email} aria-describedby={errors.email ? "email-error" : undefined} {...register("email")} />
      </Field>
      <Field id="password" label={t("auth.password")} error={errors.password?.message}>
        <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!errors.password} {...register("password")} />
      </Field>
      {login.isError && <p role="alert" className="text-sm text-danger">{login.error.message}</p>}
      <Button type="submit" className="w-full" loading={login.isPending}>{t("auth.login")}</Button>
    </form>
  );
}

function OtpForm() {
  const { t } = useT();
  const [phone, setPhone] = useState<string | null>(null);
  const request = useRequestOtp();
  const verify = useVerifyOtp();
  const phoneForm = useForm<{ phone: string }>({ resolver: zodResolver(phoneSchema) });
  const otpForm = useForm<{ code: string }>({ resolver: zodResolver(otpSchema) });

  if (!phone) {
    return (
      <form onSubmit={phoneForm.handleSubmit((v) => request.mutate(v.phone, { onSuccess: () => setPhone(v.phone) }))} className="space-y-4" noValidate>
        <Field id="phone" label={t("auth.phone")} error={phoneForm.formState.errors.phone?.message}>
          <Input id="phone" type="tel" inputMode="numeric" autoComplete="tel-national" placeholder="98765 43210" {...phoneForm.register("phone")} />
        </Field>
        {request.isError && <p role="alert" className="text-sm text-danger">{request.error.message}</p>}
        <Button type="submit" className="w-full" loading={request.isPending}>{t("auth.sendOtp")}</Button>
      </form>
    );
  }
  return (
    <form onSubmit={otpForm.handleSubmit((v) => verify.mutate({ phone, code: v.code }))} className="space-y-4" noValidate>
      <p className="text-sm text-muted-foreground">We sent a 6-digit code to {phone}.</p>
      <Field id="code" label={t("auth.otp")} error={otpForm.formState.errors.code?.message}>
        <Input id="code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} className="tracking-[0.4em]" {...otpForm.register("code")} />
      </Field>
      {verify.isError && <p role="alert" className="text-sm text-danger">{verify.error.message}</p>}
      <div className="flex gap-2">
        <Button type="button" variant="outline" onClick={() => setPhone(null)}>Change number</Button>
        <Button type="submit" className="flex-1" loading={verify.isPending}>{t("auth.verify")}</Button>
      </div>
    </form>
  );
}

export function LoginForms() {
  const [tab, setTab] = useState<"email" | "phone">("email");
  return (
    <div>
      <div role="tablist" aria-label="Login method" className="mb-5 grid grid-cols-2 rounded-lg bg-muted p-1">
        {(["email", "phone"] as const).map((k) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn("min-h-touch rounded-md text-sm font-medium transition-[background-color,color,box-shadow] duration-200", tab === k ? "bg-background shadow-sm" : "text-muted-foreground")}
          >
            {k === "email" ? "Email" : "Phone OTP"}
          </button>
        ))}
      </div>
      <div role="tabpanel">{tab === "email" ? <EmailForm /> : <OtpForm />}</div>
    </div>
  );
}
