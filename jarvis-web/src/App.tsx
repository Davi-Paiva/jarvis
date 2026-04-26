import { useJarvisSession } from './app/useJarvisSession';
import { ConnectionScreen } from './features/connection/ConnectionScreen';
import { CallScreen } from './features/call/CallScreen';
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

  return (
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
  );
}

export default App;
