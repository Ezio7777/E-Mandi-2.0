"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import type { z } from "zod";
import { CheckCircle2, ChevronLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorState } from "@/components/feedback/error-state";
import { ImageDropzone } from "@/features/upload/image-dropzone";
import { useImageUpload } from "@/features/upload/use-image-upload";
import { GradeCard, GradingProgress } from "@/features/grading/grade-card";
import { PriceCard } from "@/features/pricing/price-card";
import { useGradingJob, usePriceSuggestion, useStartGrading } from "@/services/grading";
import { useCreateListing } from "@/services/listings";
import { useAppDispatch } from "@/store/hooks";
import { wizardDraftChanged } from "@/store/slices/ui.slice";
import { toastPushed } from "@/store/slices/notifications.slice";
import { formatKg, formatPerKg, formatINR } from "@/utils/format";
import { useT } from "@/lib/i18n";
import { cropSchema, locationSchema, priceSchema, quantitySchema } from "./sell.schema";

const TITLE_KEYS = ["wizard.step0", "wizard.step1", "wizard.step2", "wizard.step3", "wizard.step4", "wizard.step5", "wizard.step6", "wizard.step7"] as const;

function TextStep<S extends z.ZodTypeAny>({ schema, name, label, hint, type = "text", inputMode, defaultValue, onValid }: {
  schema: S; name: string; label: string; hint?: string; type?: string; inputMode?: "text" | "numeric" | "decimal";
  defaultValue?: string | number; onValid: (v: Record<string, unknown>) => void;
}) {
  const { t } = useT();
  const { register, handleSubmit, formState: { errors } } = useForm<Record<string, unknown>>({ resolver: zodResolver(schema), defaultValues: { [name]: defaultValue } });
  const err = errors[name]?.message as string | undefined;
  return (
    <form onSubmit={handleSubmit(onValid)} className="space-y-4" noValidate>
      <div className="space-y-1.5">
        <Label htmlFor={name} className="text-base">{label}</Label>
        <Input id={name} type={type} inputMode={inputMode} className="min-h-12 text-lg" autoFocus aria-invalid={!!err} aria-describedby={err ? `${name}-err` : undefined} {...register(name)} />
        {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
        {err && <p id={`${name}-err`} role="alert" className="text-sm text-danger">{err}</p>}
      </div>
      <Button type="submit" size="lg" className="w-full sm:w-auto">{t("wizard.cont")}</Button>
    </form>
  );
}

export function SellWizard() {
  const dispatch = useAppDispatch();
  const { t } = useT();
  const upload = useImageUpload();
  const [step, setStep] = useState(0);
  const [crop, setCrop] = useState("");
  const [qty, setQty] = useState<number>(0);
  const [loc, setLoc] = useState("");
  const [price, setPrice] = useState<number | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const start = useStartGrading();
  const job = useGradingJob(jobId);
  const result = job.data?.result;
  const suggestion = usePriceSuggestion(crop, result?.grade, loc);
  const create = useCreateListing();
  const published = create.isSuccess;

  useEffect(() => { dispatch(wizardDraftChanged(step > 0 && !published)); return () => void dispatch(wizardDraftChanged(false)); }, [step, published, dispatch]);
  useEffect(() => { if (price === null && suggestion.data) setPrice(suggestion.data.suggested); }, [suggestion.data, price]);

  // Kick off grading when entering step 4 (index) once.
  const beginGrading = () => {
    setStep(4);
    start.mutate({ imageKeys: upload.keys, cropName: crop }, { onSuccess: (r) => setJobId(r.jobId) });
  };
  const gradingDone = job.data?.status === "ready" && result;
  const back = () => setStep((s) => Math.max(0, s - 1));

  if (published) {
    return (
      <Card className="flex flex-col items-center gap-3 p-8 text-center">
        <CheckCircle2 className="h-12 w-12 text-success" aria-hidden />
        <h2 className="text-2xl font-bold">{t("wizard.published")}</h2>
        <p className="text-muted-foreground">{crop} {t("wizard.publishedBody")}</p>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <Button asChild><Link href="/farmer/listings">{t("wizard.viewListings")}</Link></Button>
          <Button variant="outline" onClick={() => location.reload()}>{t("wizard.sellAnother")}</Button>
        </div>
      </Card>
    );
  }

  return (
    <div data-tour="sell-wizard" className="mx-auto max-w-2xl">
      <div className="mb-5">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">{t("farmer.step")} {step + 1} {t("farmer.of")} {TITLE_KEYS.length}: {t(TITLE_KEYS[step]!)}</span>
          {step > 0 && <Button variant="ghost" size="sm" onClick={back}><ChevronLeft /> {t("common.back")}</Button>}
        </div>
        <div className="mt-2 flex gap-1" role="progressbar" aria-valuemin={1} aria-valuemax={TITLE_KEYS.length} aria-valuenow={step + 1} aria-label="Progress">
          {TITLE_KEYS.map((s, i) => <span key={s} className={`h-1.5 flex-1 rounded-full ${i <= step ? "bg-primary" : "bg-muted"}`} />)}
        </div>
      </div>

      <Card className="p-4 sm:p-6">
        {step === 0 && (
          <div className="space-y-4">
            <ImageDropzone upload={upload} />
            <Button size="lg" className="w-full sm:w-auto" disabled={!upload.ready} onClick={() => setStep(1)}>{t("wizard.cont")}</Button>
            {!upload.ready && upload.items.length > 0 && <p className="text-sm text-muted-foreground">{t("wizard.waiting")}</p>}
          </div>
        )}
        {step === 1 && <TextStep schema={cropSchema} name="crop" label={t("wizard.cropQ")} hint={t("wizard.cropHint")} defaultValue={crop} onValid={(v) => { setCrop(String(v.crop)); setStep(2); }} />}
        {step === 2 && <TextStep schema={quantitySchema} name="quantityKg" label={t("wizard.qtyQ")} type="number" inputMode="decimal" defaultValue={qty || undefined} onValid={(v) => { setQty(Number(v.quantityKg)); setStep(3); }} />}
        {step === 3 && <TextStep schema={locationSchema} name="location" label={t("wizard.locQ")} hint={t("wizard.locHint")} defaultValue={loc} onValid={(v) => { setLoc(String(v.location)); beginGrading(); }} />}

        {step === 4 && (
          <div className="space-y-4">
            {start.isError && <ErrorState error={start.error} onRetry={beginGrading} title="Couldn't start grading" />}
            {job.isError && <ErrorState error={job.error} onRetry={() => job.refetch()} />}
            {job.data?.status === "failed" && <ErrorState title="Grading failed" error={new Error("The image could not be analyzed. Try a clearer photo.")} onRetry={beginGrading} />}
            {!gradingDone && !start.isError && job.data?.status !== "failed" && <GradingProgress job={job.data} />}
            {gradingDone && <GradeCard result={result} />}
            <Button size="lg" className="w-full sm:w-auto" disabled={!gradingDone} onClick={() => setStep(5)}>{t("wizard.seePrice")}</Button>
          </div>
        )}

        {step === 5 && (
          <div className="space-y-4">
            <PriceCard crop={crop} grade={result?.grade} location={loc} />
            <TextStep schema={priceSchema} name="pricePerKg" label={t("wizard.priceLabel")} hint={t("wizard.priceHint")} type="number" inputMode="decimal" defaultValue={price ?? undefined} onValid={(v) => { setPrice(Number(v.pricePerKg)); setStep(6); }} />
          </div>
        )}

        {step === 6 && result && price !== null && (
          <div className="space-y-4">
            <dl className="divide-y rounded-lg border text-sm">
              {[["Crop", crop], ["Quantity", formatKg(qty)], ["Location", loc], ["AI grade", `${result.grade} (${Math.round(result.confidence * 100)}% confidence)`], ["Your price", formatPerKg(price)], ["Estimated value", formatINR(qty * price)], ["Photos", String(upload.keys.length)]].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 px-4 py-3"><dt className="text-muted-foreground">{k}</dt><dd className="text-right font-medium">{v}</dd></div>
              ))}
            </dl>
            {result.manualReviewRecommended && <p className="rounded-md bg-warning/15 px-3 py-2 text-sm text-warning">Manual review is recommended. Your listing may need admin approval before it goes live.</p>}
            <Button size="lg" className="w-full sm:w-auto" onClick={() => setStep(7)}>{t("wizard.looksGood")}</Button>
          </div>
        )}

        {step === 7 && result && price !== null && (
          <div className="space-y-4">
            <p className="text-muted-foreground">{t("wizard.readyToGo")}</p>
            {create.isError && <ErrorState error={create.error} onRetry={() => create.reset()} title="Couldn't publish" />}
            <Button size="lg" className="w-full sm:w-auto" loading={create.isPending} data-tour="publish-btn"
              onClick={() => create.mutate({ crop, quantityKg: qty, location: loc, pricePerKg: price, imageKeys: upload.keys, gradingJobId: result.jobId }, { onSuccess: () => dispatch(toastPushed("success", "Published")) })}>
              {t("farmer.publish")}
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
