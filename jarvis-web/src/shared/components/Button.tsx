import React from 'react';

type Variant = 'primary' | 'approve' | 'reject' | 'ghost';

type Props = {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: Variant;
  disabled?: boolean;
  fullWidth?: boolean;
};

export function Button({ children, onClick, variant = 'primary', disabled, fullWidth }: Props) {
  return (
    <button
      type="button"
      className={`jv-btn jv-btn--${variant}${fullWidth ? ' jv-btn--full' : ''}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}
