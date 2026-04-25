export type AgentStatus = 'idle' | 'running' | 'waiting_approval';

export type Agent = {
  id: string;
  name: string;
  status: AgentStatus;
};

export type Message = {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  streaming?: boolean;
};

export type ApprovalRequest = {
  id: string;
  title: string;
  description: string;
  affectedFiles?: string[];
  metadata?: Record<string, unknown>;
};
