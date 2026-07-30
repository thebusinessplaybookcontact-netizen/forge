import { createContext, useContext, type ReactNode } from "react";

import { useChat } from "./useChat";
import { useReplySpeech } from "./voice";

type ChatState = ReturnType<typeof useChat>;

const ChatContext = createContext<ChatState | null>(null);

/**
 * One chat session for the whole app.
 *
 * Two reasons this is lifted out of the Chat screen. The conversation survives
 * navigating between tabs (previously each mount of /chat started a fresh session), and
 * the Home dashboard can watch `changed` to refetch the moment the coach edits
 * something — the counter is useless to it while it lives in a hook on another screen.
 *
 * Speaking lives here too, so a reply is read aloud once regardless of which screen
 * you're on when it lands.
 */
export function ChatProvider({ children }: { children: ReactNode }) {
  const chat = useChat();
  useReplySpeech(chat.lastReply);
  return <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>;
}

export function useChatContext(): ChatState {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChatContext must be used inside <ChatProvider>");
  return ctx;
}
