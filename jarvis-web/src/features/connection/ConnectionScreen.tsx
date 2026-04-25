import { useState } from 'react';
import { Card } from '../../shared/components/Card';
import { Button } from '../../shared/components/Button';

type Props = {
  onConnect: (code: string) => void;
};

export function ConnectionScreen({ onConnect }: Props) {
  const [code, setCode] = useState('');

  return (
    <div className="jv-screen jv-connect-screen">
      <div className="jv-connect-inner">
        <div className="jv-connect-logo">
          <span className="jv-connect-title">Jarvis</span>
          <span className="jv-connect-sub">AI Control Interface</span>
        </div>

        <Card className="jv-connect-card">
          <label className="jv-label" htmlFor="pairing-code">
            Pairing Code
          </label>
          <input
            id="pairing-code"
            className="jv-input"
            type="text"
            placeholder="Enter your pairing code"
            value={code}
            onChange={e => setCode(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && onConnect(code)}
            autoComplete="off"
            autoFocus
          />
          <Button onClick={() => onConnect(code)} fullWidth disabled={code.trim().length === 0}>
            Connect
          </Button>
          <p className="jv-connect-hint">Find your pairing code in the Jarvis desktop app.</p>
        </Card>
      </div>
    </div>
  );
}
