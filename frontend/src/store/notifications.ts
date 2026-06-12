// Notification center + toast surface. Awaiting-input is the highest
// priority and must be impossible to miss (phase 6 behavior requirement).

import { create } from "zustand";

export type NotificationKind =
  | "awaiting_input"
  | "run_complete"
  | "budget_approaching"
  | "stopped_early"
  | "significant_finding"
  | "output_ready"
  | "error";

export interface AppNotification {
  id: string;
  kind: NotificationKind;
  title: string;
  body?: string;
  link?: string;
  projectId?: string;
  createdAt: string;
  read: boolean;
}

interface NotificationState {
  items: AppNotification[];
  toasts: AppNotification[];
  push: (n: Omit<AppNotification, "id" | "createdAt" | "read"> & { id?: string }) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  dismissToast: (id: string) => void;
  clear: () => void;
}

let counter = 0;

export const useNotifications = create<NotificationState>((set) => ({
  items: [],
  toasts: [],

  push: (n) =>
    set((state) => {
      const id = n.id ?? `n-${Date.now()}-${counter++}`;
      // Collapse duplicate awaiting-input notifications for the same project.
      if (
        n.kind === "awaiting_input" &&
        state.items.some(
          (existing) =>
            existing.kind === "awaiting_input" &&
            existing.projectId === n.projectId &&
            !existing.read,
        )
      ) {
        return state;
      }
      const item: AppNotification = {
        ...n,
        id,
        createdAt: new Date().toISOString(),
        read: false,
      };
      return {
        items: [item, ...state.items].slice(0, 100),
        toasts: [...state.toasts, item].slice(-4),
      };
    }),

  markRead: (id) =>
    set((state) => ({
      items: state.items.map((n) => (n.id === id ? { ...n, read: true } : n)),
    })),

  markAllRead: () => set((state) => ({ items: state.items.map((n) => ({ ...n, read: true })) })),

  dismissToast: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),

  clear: () => set({ items: [], toasts: [] }),
}));
