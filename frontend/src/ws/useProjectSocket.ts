// Hook that keeps one ProjectSocket alive for the project being viewed and
// resets the live-run store when the project changes.

import { useEffect } from "react";

import { useLiveRun } from "../store/liveRun";
import { ProjectSocket } from "./client";

export function useProjectSocket(projectId: string | undefined): void {
  useEffect(() => {
    if (!projectId) return;
    useLiveRun.getState().reset(projectId);
    const socket = new ProjectSocket(projectId);
    socket.connect();
    return () => socket.close();
  }, [projectId]);
}
