import type { Metadata } from "next";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DemoButtons } from "@/features/demo/demo-buttons";

export const metadata: Metadata = { title: "Explore the demo" };

export default function DemoPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h1" className="text-2xl">Explore E-Mandi</CardTitle>
        <CardDescription>Pick a role. No sign-up. You&apos;ll land on a guided tour using real, seeded data.</CardDescription>
      </CardHeader>
      <CardContent><DemoButtons layout="stack" /></CardContent>
    </Card>
  );
}
