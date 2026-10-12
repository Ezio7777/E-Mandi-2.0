"use client";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useCreateRequirement } from "@/services/orders";
import { MatchList } from "./match-list";
import { requirementSchema, type RequirementValues } from "./requirement.schema";

export function RequirementForm() {
  const create = useCreateRequirement();
  const [createdId, setCreatedId] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors } } = useForm<RequirementValues>({ resolver: zodResolver(requirementSchema), defaultValues: { desiredGrade: "A" } });
  const E = ({ n }: { n: keyof RequirementValues }) => (errors[n] ? <p role="alert" className="text-sm text-danger">{errors[n]?.message as string}</p> : null);

  if (createdId) {
    return (
      <div className="space-y-4">
        <Card className="flex items-center gap-3 p-4" role="status"><Loader2 className="h-5 w-5 animate-spin text-primary" aria-hidden /><p className="font-medium">Finding suitable farmers…</p></Card>
        <MatchList requirementId={createdId} poll />
      </div>
    );
  }
  return (
    <Card className="p-4 sm:p-6" data-tour="requirement-form">
      <form onSubmit={handleSubmit((v) => create.mutate(v, { onSuccess: (r) => setCreatedId(r.id) }))} className="grid gap-4 sm:grid-cols-2" noValidate>
        <div className="space-y-1.5"><Label htmlFor="r-crop">Crop</Label><Input id="r-crop" placeholder="Tomato" {...register("crop")} /><E n="crop" /></div>
        <div className="space-y-1.5"><Label htmlFor="r-qty">Quantity (kg)</Label><Input id="r-qty" type="number" inputMode="numeric" {...register("quantityKg")} /><E n="quantityKg" /></div>
        <div className="space-y-1.5"><Label htmlFor="r-grade">Desired grade</Label>
          <Select id="r-grade" {...register("desiredGrade")}><option value="A">Grade A</option><option value="B">Grade B</option><option value="C">Grade C</option></Select><E n="desiredGrade" /></div>
        <div className="space-y-1.5"><Label htmlFor="r-dest">Destination</Label><Input id="r-dest" placeholder="Bangalore" {...register("destination")} /><E n="destination" /></div>
        <div className="space-y-1.5"><Label htmlFor="r-date">Delivery date</Label><Input id="r-date" type="date" {...register("deliveryDate")} /><E n="deliveryDate" /></div>
        <div className="space-y-1.5"><Label htmlFor="r-budget">Maximum budget (₹)</Label><Input id="r-budget" type="number" inputMode="numeric" {...register("maxBudget")} /><E n="maxBudget" /></div>
        {create.isError && <p role="alert" className="text-sm text-danger sm:col-span-2">{create.error.message}</p>}
        <div className="sm:col-span-2"><Button type="submit" size="lg" className="w-full sm:w-auto" loading={create.isPending}>Find farmers</Button></div>
      </form>
    </Card>
  );
}
