import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";

export const sessionKeys = {
  me: ["me"] as const,
  setup: ["setup-status"] as const,
};

export function useSetupStatus() {
  return useQuery({ queryKey: sessionKeys.setup, queryFn: api.setupStatus, staleTime: 30_000 });
}

/** Current user, or null when signed out (401 is not an error here). */
export function useMe() {
  return useQuery<User | null>({
    queryKey: sessionKeys.me,
    queryFn: async () => {
      try {
        return (await api.me()).user;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

export function useSessionActions() {
  const qc = useQueryClient();
  return {
    setUser: (u: User | null) => qc.setQueryData(sessionKeys.me, u),
    refreshSetup: () => qc.invalidateQueries({ queryKey: sessionKeys.setup }),
    signOut: async () => {
      try {
        await api.logout();
      } finally {
        qc.clear();
        qc.setQueryData(sessionKeys.me, null);
      }
    },
  };
}
