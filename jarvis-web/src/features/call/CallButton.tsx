type Props = {
  inCall: boolean;
  onStart: () => void;
  onEnd: () => void;
};

// Simple phone handset SVG
function PhoneIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M6.62 10.79a15.05 15.05 0 0 0 6.59 6.59l2.2-2.2a1 1 0 0 1 1.02-.24 11.47 11.47 0 0 0 3.58.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.58a1 1 0 0 1-.25 1.02L6.62 10.79z" />
    </svg>
  );
}

function PhoneOffIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M1.41 1.41 0 2.83l4.39 4.39A16.95 16.95 0 0 0 3 11a1 1 0 0 0 1 1h3.5a1 1 0 0 0 1-1c0-.61.08-1.21.21-1.79L11.62 13c-.2.06-.41.1-.62.1a1 1 0 0 0-1 1v.09l2.45 2.45A15.05 15.05 0 0 1 7.83 12l-1.44 1.44A17 17 0 0 0 20 21l1.41 1.41 1.41-1.41L1.41 1.41zm19.92 15.17-.01-.01-2.52-2.52a1 1 0 0 0-1.02-.24 11.47 11.47 0 0 1-3.58.57 1 1 0 0 0-1 1V20a1 1 0 0 0 1 1A17 17 0 0 0 21 4a1 1 0 0 0-.49.09L18.1 6.5A15.1 15.1 0 0 1 21 12a1 1 0 0 0 1 1h.01l-.68-5.42z" />
    </svg>
  );
}

export function CallButton({ inCall, onStart, onEnd }: Props) {
  return (
    <button
      type="button"
      className={`jv-call-btn ${inCall ? 'jv-call-btn--end' : 'jv-call-btn--start'}`}
      onClick={inCall ? onEnd : onStart}
      aria-label={inCall ? 'End call' : 'Start call'}
    >
      {inCall ? <PhoneOffIcon /> : <PhoneIcon />}
    </button>
  );
}
