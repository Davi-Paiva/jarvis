import { useJarvisSession } from './app/useJarvisSession';
import { ConnectionScreen } from './features/connection/ConnectionScreen';
import { CallScreen } from './features/call/CallScreen';
import { ApprovalModal } from './features/approvals/ApprovalModal';
import './App.css';

function App() {
  const session = useJarvisSession();

  if (session.connectionState !== 'connected') {
    return (
      <ConnectionScreen
        onConnect={session.connect}
        socketConnected={session.socketConnected}
        connecting={session.connectionState === 'connecting'}
      />
    );
  }

  const pendingApproval = session.approvals[0] ?? null;

  return (
    <>
      <CallScreen
        socketConnected={session.socketConnected}
        listening={session.listening}
        speaking={session.speaking}
        transcript={session.transcript}
        messages={session.messages}
        activeAgent={session.activeAgent}
        getVolume={session.getVolume}
        onSendMessage={session.sendMessage}
      />
      {pendingApproval && (
        <ApprovalModal
          approval={pendingApproval}
          onApprove={session.approveAction}
          onReject={session.rejectAction}
        />
      )}
    </>
  );
}

export default App;
