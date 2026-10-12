import { api } from "./client";
import type { Locale, VoiceReplyDto } from "@/types";

export const voiceApi = {
  ask: (audio: Blob, language: Locale) => {
    const form = new FormData();
    form.append("audio", audio, "question.webm");
    form.append("language", language);
    return api.post<VoiceReplyDto>("/voice/ask", form);
  },
};
