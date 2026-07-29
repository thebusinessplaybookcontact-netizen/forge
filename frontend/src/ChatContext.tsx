import { createContext, useContext, type ReactNode } from "react";

import { useChat } from "./useChat";

type ChatState = ReturnType<typeof useChat>;

const ChatContext = createContext<ChatState | null>(null);

/**
 * One chat session for the whole app.
 *
 * Two reasons this is lifted out of the Chat screen. The conversation now survives
 * navigating between tabs (previously each mount of /chat started a fresh session), and
 * the Home dashboard can watch `changed` to refetch the moment the coach edits
 * something — the counter is useless to it while it lives in a hook on another screen.
 */
export function ChatProvider({ children }: { children: ReactNode }) {
  return <ChatContext.Provider value={useChat()}>{children}</ChatContext.Provider>;
}

export function useChatContext(): ChatState {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChatContext must be used inside <ChatProvider>");
  return ctx;
}
