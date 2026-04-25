import type { ApprovalRequest } from '../../shared/types';
import { Card } from '../../shared/components/Card';

type Props = {
  approval: ApprovalRequest;
};

export function ApprovalModal({ approval }: Props) {
  return (
    <div className="jv-modal-overlay">
      <Card className="jv-modal">
        <p className="jv-modal-eyebrow">Waiting for approval</p>
        <h2 className="jv-modal-title">{approval.title}</h2>
        <p className="jv-modal-desc">{approval.description}</p>

        {approval.affectedFiles && approval.affectedFiles.length > 0 && (
          <div className="jv-modal-files">
            {approval.affectedFiles.map(f => (
              <code key={f} className="jv-file-chip">{f}</code>
            ))}
          </div>
        )}

        <p className="jv-modal-voice-hint">Respond verbally to approve or reject.</p>
      </Card>
    </div>
  );
}
