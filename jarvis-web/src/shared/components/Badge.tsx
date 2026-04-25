type Variant = 'ok' | 'warn' | 'err' | 'idle' | 'running' | 'waiting_approval';

type Props = {
  label: string;
  variant?: Variant;
};

export function Badge({ label, variant = 'idle' }: Props) {
  return (
    <span className={`jv-badge jv-badge--${variant}`}>{label}</span>
  );
}
