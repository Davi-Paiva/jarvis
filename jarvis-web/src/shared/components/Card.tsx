import React from 'react';

type Props = {
  children: React.ReactNode;
  className?: string;
};

export function Card({ children, className = '' }: Props) {
  return (
    <div className={`jv-card ${className}`}>
      {children}
    </div>
  );
}
