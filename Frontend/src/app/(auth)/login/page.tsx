import type { Metadata } from "next";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LoginForms } from "@/features/auth/login-forms";
import { GoogleButton } from "@/features/auth/google-button";
import { DemoButtons } from "@/features/demo/demo-buttons";

export const metadata: Metadata = { title: "Log in" };

export default function LoginPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h1" className="text-2xl">Welcome back</CardTitle>
        <CardDescription>Log in to sell, buy or manage the marketplace.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <GoogleButton />
        <LoginForms />
        <div className="relative py-1 text-center text-xs text-muted-foreground before:absolute before:left-0 before:top-1/2 before:h-px before:w-full before:bg-border">
          <span className="relative bg-card px-3">Just looking around?</span>
        </div>
        <DemoButtons layout="stack" />
      </CardContent>
    </Card>
  );
}
