import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { VoiceAssistant } from "@/features/voice/voice-assistant";

export const metadata: Metadata = { title: "Voice assistant" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.assistant.title" descriptionKey="pages.assistant.desc" />
      <VoiceAssistant />
    </>
  );
}
