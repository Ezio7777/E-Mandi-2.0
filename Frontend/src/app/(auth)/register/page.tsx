import type { Metadata } from "next";
import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "Create account" };

export default function RegisterPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h1" className="text-2xl">Create your account</CardTitle>
        <CardDescription>Registration opens once the backend registration endpoint is connected. Use Google, phone OTP or the demo in the meantime.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 sm:flex-row">
        <Button asChild className="flex-1"><Link href="/login">Log in</Link></Button>
        <Button asChild variant="outline" className="flex-1"><Link href="/demo">Explore demo</Link></Button>
      </CardContent>
    </Card>
  );
}
