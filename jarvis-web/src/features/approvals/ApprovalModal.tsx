import type { ApprovalRequest } from '../../shared/types';
import { Card } from '../../shared/components/Card';
import { Button } from '../../shared/components/Button';

type Props = {
  approval: ApprovalRequest;
  onApprove?: (id: string) => void;
  onReject?: (id: string) => void;
};

export function ApprovalModal({ approval, onApprove, onReject }: Props) {
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

        {(onApprove || onReject) && (
          <div className="jv-modal-actions">
            {onReject && (
              <Button variant="ghost" fullWidth onClick={() => onReject(approval.id)}>
                Reject
              </Button>
            )}
            {onApprove && (
              <Button fullWidth onClick={() => onApprove(approval.id)}>
                Approve
              </Button>
            )}
          </div>
        )}

        <p className="jv-modal-voice-hint">Respond verbally to approve or reject.</p>
      </Card>
    </div>
  );
}
