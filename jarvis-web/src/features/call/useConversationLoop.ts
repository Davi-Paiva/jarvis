import { useCallback, useEffect, useRef, useState } from 'react';
import { useVoice } from '../../voice/context/VoiceProvider';

export function useConversationLoop() {
  const { listening, speaking, startListening, stopListening } = useVoice();
  const [inCall, setInCall] = useState(false);

  // Refs so effects always read current values without re-subscribing
  const inCallRef = useRef(false);
  const prevSpeakingRef = useRef(false);

  // Detect speaking → silent transition → agent finished → restart mic
  useEffect(() => {
    const wasSpeaking = prevSpeakingRef.current;
    prevSpeakingRef.current = speaking;

    if (wasSpeaking && !speaking && inCallRef.current && !listening) {
      const t = setTimeout(() => {
        if (inCallRef.current) startListening();
      }, 400);
      return () => clearTimeout(t);
    }
  }, [speaking, listening, startListening]);

  const startCall = useCallback(() => {
    inCallRef.current = true;
    setInCall(true);
    startListening();
  }, [startListening]);

  const endCall = useCallback(() => {
    inCallRef.current = false;
    setInCall(false);
    stopListening();
  }, [stopListening]);

  return { inCall, startCall, endCall };
}
