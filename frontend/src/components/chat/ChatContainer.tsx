import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { SuggestionChips } from './SuggestionChips';
import { useChatStore } from '../../stores/chatStore';

interface ChatContainerProps {
  onSendMessage: (message: string) => void;
}

export function ChatContainer({ onSendMessage }: ChatContainerProps) {
  const isStreaming = useChatStore((state) => state.isStreaming);
  
  return (
    <div className="flex-1 flex flex-col min-h-0">
      <MessageList />
      <SuggestionChips onSelect={onSendMessage} />
      <ChatInput onSend={onSendMessage} disabled={isStreaming} />
    </div>
  );
}
