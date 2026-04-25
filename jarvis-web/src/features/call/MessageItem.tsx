import type { Message } from '../../shared/types';

type Props = { message: Message };

export function MessageItem({ message }: Props) {
  const { role, content, streaming } = message;

  if (role === 'system') {
    return (
      <div className="jv-msg jv-msg--system">
        <span>{content}</span>
      </div>
    );
  }

  return (
    <div className={`jv-msg jv-msg--${role}`}>
      <div className="jv-msg-bubble">
        {content}
        {streaming && <span className="jv-cursor" aria-hidden>▋</span>}
      </div>
    </div>
  );
}
