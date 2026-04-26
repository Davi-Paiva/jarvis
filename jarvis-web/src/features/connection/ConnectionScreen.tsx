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
        <div className="jv-connect-top">
          <div className="jv-connect-logo">
            <span className="jv-connect-title">Jarvis</span>
            <span className="jv-connect-sub">AI Control Interface</span>
          </div>

          <p className="jv-connect-hint">
            Jarvis Web connects directly to the local backend websocket.
          </p>
        </div>

        <Card className="jv-connect-card">
          <Button onClick={onConnect} fullWidth disabled={connecting}>
            {connecting ? 'Connecting…' : 'Connect to Local Backend'}
          </Button>
        </Card>

        <p className="jv-connect-status">
          Backend socket: {socketConnected ? 'available' : 'waiting for ws://localhost:8000/ws'}
        </p>
      </div>
    </div>
  );
}
