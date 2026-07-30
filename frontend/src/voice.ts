import { useCallback, useEffect, useRef, useState } from "react";

import { loadSettings } from "./settings";
import type { VoiceMode } from "./types";

/* ------------------------------------------------------------------ *
 * Speech to text — the phone's own engine, so it's free and offline.
 * ------------------------------------------------------------------ */

// The Web Speech API isn't in TypeScript's DOM lib, so declare the slice we use.
interface RecognitionAlternative {
  transcript: string;
}
interface RecognitionResult {
  0: RecognitionAlternative;
  isFinal: boolean;
  length: number;
}
interface RecognitionEvent {
  resultIndex: number;
  results: { length: number; [i: number]: RecognitionResult };
}
interface RecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: RecognitionEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
}
type RecognitionCtor = new () => RecognitionLike;

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const dictationSupported = (): boolean => recognitionCtor() !== null;

/**
 * Push-to-talk dictation.
 *
 * `transcript` updates live while speaking (including interim, unconfirmed words) so
 * there's visible feedback that it's hearing you. Stopping resolves to the final text.
 */
export function useDictation(onFinal: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recognition = useRef<RecognitionLike | null>(null);
  const finalText = useRef("");
  // Keep the latest callback without restarting recognition when it changes identity.
  const handler = useRef(onFinal);
  handler.current = onFinal;

  const stop = useCallback(() => {
    recognition.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor) {
      setError("This browser can't do speech recognition. Type instead.");
      return;
    }
    if (recognition.current) return; // already listening

    // Playing audio later must be unlocked by this gesture — see primeAudio.
    primeAudio();

    const rec = new Ctor();
    rec.lang = navigator.language || "en-US";
    rec.continuous = true; // rambling is the point; don't cut off at the first pause
    rec.interimResults = true;
    finalText.current = "";
    setTranscript("");
    setError(null);

    rec.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) finalText.current += result[0].transcript;
        else interim += result[0].transcript;
      }
      setTranscript((finalText.current + interim).trim());
    };

    rec.onerror = (e) => {
      // "aborted" and "no-speech" are normal outcomes of tapping stop, not failures.
      if (e.error !== "aborted" && e.error !== "no-speech") {
        setError(
          e.error === "not-allowed"
            ? "Microphone permission denied."
            : `Speech recognition error: ${e.error}`,
        );
      }
    };

    rec.onend = () => {
      recognition.current = null;
      setListening(false);
      const said = finalText.current.trim();
      setTranscript("");
      if (said) handler.current(said);
    };

    recognition.current = rec;
    setListening(true);
    rec.start();
  }, []);

  // Don't leave the microphone open if the screen unmounts mid-sentence.
  useEffect(() => () => recognition.current?.abort(), []);

  return { listening, transcript, error, start, stop, toggle: () => (listening ? stop() : start()) };
}

/* ------------------------------------------------------------------ *
 * Text to speech — human voice via the backend, or the free browser one.
 * ------------------------------------------------------------------ */

let audio: HTMLAudioElement | null = null;
let unlocked = false;

/**
 * Mobile browsers only allow audio that a user gesture started. The reply arrives
 * seconds after the tap, well outside the gesture, so play a moment of silence during
 * the tap to unlock the element for later use.
 */
export function primeAudio(): void {
  if (unlocked) return;
  audio ??= new Audio();
  audio.src =
    "data:audio/mpeg;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4LjI5LjEwMAAAAAAAAAAAAAAA//tAwAAAAAAAAAAAAAAAAAAAAAAASW5mbwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u///////////////////////////////////////////8AAAAATGF2YzU4LjU0AAAAAAAAAAAAAAAAJAAAAAAAAAAAAYbCu0DUAAAAAAAAAAAAAAAAAAAA//sQxAADwAABpAAAACAAADSAAAAETEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//sQxB2DwAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV";
  audio.play().then(
    () => {
      audio?.pause();
      unlocked = true;
    },
    () => {
      /* still blocked; speaking will just fail quietly and the text is on screen anyway */
    },
  );
}

export function stopSpeaking(): void {
  window.speechSynthesis?.cancel();
  if (audio) {
    audio.pause();
    audio.src = "";
  }
}

function speakWithBrowser(text: string): void {
  const synth = window.speechSynthesis;
  if (!synth) return;
  synth.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = navigator.language || "en-US";
  synth.speak(utterance);
}

async function speakWithHumanVoice(text: string): Promise<void> {
  const res = await fetch("/api/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });

  // 503 means no provider is configured — that's a fallback, not an error.
  if (res.status === 503) {
    speakWithBrowser(text);
    return;
  }
  if (!res.ok) throw new Error(`Speech failed: ${res.status}`);

  const url = URL.createObjectURL(await res.blob());
  audio ??= new Audio();
  audio.src = url;
  audio.onended = () => URL.revokeObjectURL(url);
  await audio.play();
}

/** Speak text using the configured voice, falling back to the browser on any failure. */
export async function speak(text: string, mode: VoiceMode): Promise<void> {
  const body = text.trim();
  if (!body) return;
  stopSpeaking();

  if (mode === "browser") {
    speakWithBrowser(body);
    return;
  }
  try {
    await speakWithHumanVoice(body);
  } catch {
    // Never leave the user in silence because the paid voice broke.
    speakWithBrowser(body);
  }
}

/** Speaks each completed reply, if the user has that turned on. */
export function useReplySpeech(lastReply: { seq: number; text: string } | null): void {
  const spokenSeq = useRef(0);

  useEffect(() => {
    if (!lastReply || lastReply.seq === spokenSeq.current) return;
    spokenSeq.current = lastReply.seq;

    const settings = loadSettings();
    if (!settings.speakReplies) return;
    void speak(lastReply.text, settings.voiceMode);
  }, [lastReply]);
}
