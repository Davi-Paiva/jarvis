import { Card } from '../../shared/components/Card';
import { Button } from '../../shared/components/Button';

type Props = {
  onConnect: () => void;
  socketConnected: boolean;
  connecting: boolean;
};

export function ConnectionScreen({ onConnect, socketConnected, connecting }: Props) {
  return (
    <div className="jv-screen jv-connect-screen">
      <div className="jv-connect-inner">
        <div className="jv-connect-logo">
          <span className="jv-connect-title">Jarvis</span>
          <span className="jv-connect-sub">AI Control Interface</span>
        </div>

        <Card className="jv-connect-card">
          <p className="jv-connect-hint">
            Jarvis Web connects directly to the local backend websocket.
          </p>
          <Button onClick={onConnect} fullWidth disabled={connecting}>
            {connecting ? 'Connecting…' : 'Connect to Local Backend'}
          </Button>
          <p className="jv-connect-hint">
            Backend socket: {socketConnected ? 'available' : 'waiting for ws://localhost:8000/ws'}
          </p>
        </Card>
      </div>
    </div>
  );
}
