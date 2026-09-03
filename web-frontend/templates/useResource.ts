/**
 * The per-concern custom-hook pattern for server state.
 *
 * This is the shape worth copying: components call `useRecentActivity()` and
 * never see a query key, a fetch, or a timeout. Query keys live in one place, so
 * invalidation can't drift from the key that populated the cache.
 *
 * Read the WRONG example at the bottom first — it is what this replaces, and
 * it's the most common data bug in React.
 *
 * See the web-frontend skill's references/state-data.md for the reasoning.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { z } from "zod";

// ---------------------------------------------------------------------------
// One HTTP helper with a timeout. `fetch()` has NO default timeout — a hung
// request leaves the spinner spinning forever, and the user has no recourse
// but to reload.
// ---------------------------------------------------------------------------

const DEFAULT_TIMEOUT_MS = 10_000;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: string,
  ) {
    super(`API ${status}`);
    this.name = "ApiError";
  }
}

async function api<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit & { timeoutMs?: number },
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal, ...rest } = init ?? {};

  // AbortSignal.any combines react-query's cancellation signal (it aborts on
  // unmount and on refetch) with our own deadline. Without the query's signal,
  // a navigated-away request keeps running and still resolves into the cache.
  const timeout = AbortSignal.timeout(timeoutMs);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

  const res = await fetch(`/api${path}`, {
    ...rest,
    signal: combined,
    headers: { "content-type": "application/json", ...rest.headers },
  });

  if (!res.ok) {
    // Bound the read: a 500 page can be megabytes of HTML.
    throw new ApiError(res.status, (await res.text()).slice(0, 500));
  }

  // Parse at the boundary. The server's contract can drift; failing here with a
  // clear schema error beats `undefined is not an object` three components deep.
  return schema.parse(await res.json());
}

// ---------------------------------------------------------------------------
// Schemas + keys
// ---------------------------------------------------------------------------

const ActivityItem = z.object({
  id: z.string(),
  kind: z.enum(["login", "purchase", "refund"]),
  occurredAt: z.coerce.date(),
  summary: z.string(),
});
export type ActivityItem = z.infer<typeof ActivityItem>;

/**
 * Query keys in ONE place, as a factory.
 *
 * The failure this prevents: a mutation invalidating `["activity"]` while the
 * query registered `["activity", "recent", userId]`. Nothing matches, the cache
 * is never refreshed, and the UI silently shows stale data after a successful
 * write. Centralising the keys makes that impossible.
 */
export const activityKeys = {
  all: ["activity"] as const,
  recent: (userId: string, limit: number) =>
    [...activityKeys.all, "recent", userId, limit] as const,
};

// ---------------------------------------------------------------------------
// The hook components actually use
// ---------------------------------------------------------------------------

export function useRecentActivity(
  userId: string,
  limit = 20,
): UseQueryResult<ActivityItem[], Error> {
  return useQuery({
    queryKey: activityKeys.recent(userId, limit),
    // react-query passes an AbortSignal — forward it, or cancellation does nothing.
    queryFn: ({ signal }) =>
      api(
        `/users/${userId}/activity?limit=${limit}`,
        z.array(ActivityItem),
        { signal },
      ),

    // staleTime: how long the data is considered fresh (no refetch on mount or
    // focus). Default 0 means every mount refetches — usually not what you want.
    staleTime: 30_000,
    // gcTime: how long an UNUSED cache entry is kept before eviction. Must be
    // >= staleTime or you evict data you still consider fresh.
    gcTime: 5 * 60_000,

    // Don't retry a client error — the request is wrong and will stay wrong.
    // Retrying a 404 four times just delays the error the user needs to see.
    retry: (failureCount, error) =>
      error instanceof ApiError && error.status < 500 ? false : failureCount < 3,

    enabled: Boolean(userId), // don't fire with an empty id on first render
  });
}

// ---------------------------------------------------------------------------
// A mutation with optimistic update + rollback
// ---------------------------------------------------------------------------

export function useDismissActivity(userId: string) {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api(`/activity/${id}/dismiss`, z.object({ ok: z.boolean() }), {
        method: "POST",
      }),

    onMutate: async (id) => {
      // Cancel in-flight refetches, or one could land after our optimistic
      // write and clobber it with pre-mutation data.
      await qc.cancelQueries({ queryKey: activityKeys.all });

      const previous = qc.getQueriesData({ queryKey: activityKeys.all });
      qc.setQueriesData<ActivityItem[]>({ queryKey: activityKeys.all }, (old) =>
        old?.filter((a) => a.id !== id),
      );
      return { previous }; // handed to onError for rollback
    },

    onError: (_err, _id, ctx) => {
      // Roll back to the exact snapshot. Without this the UI keeps showing the
      // item as dismissed even though the server rejected it.
      ctx?.previous.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: () => {
      // Reconcile with the server regardless of outcome.
      void qc.invalidateQueries({ queryKey: activityKeys.all });
    },
  });
}

// ---------------------------------------------------------------------------
// WHAT THIS REPLACES — the useEffect-fetch anti-pattern
// ---------------------------------------------------------------------------

/*
function RecentActivity({ userId }: { userId: string }) {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/users/${userId}/activity`)     // 1. no timeout — hangs forever
      .then((r) => r.json())                   // 2. no !r.ok check — a 500 becomes
                                               //    a "successful" parse of an error page
      .then(setItems)                          // 3. NO CANCELLATION: navigate away and
                                               //    back quickly and a stale response
                                               //    resolves AFTER the fresh one, so the
                                               //    UI shows the older data. Intermittent,
                                               //    load-dependent, near-impossible to
                                               //    reproduce locally on a fast network.
      .catch(setError)
      .finally(() => setLoading(false));       // 4. setState after unmount
  }, [userId]);

  // 5. Two components rendering this = two identical requests, no dedupe.
  // 6. No refetch on window focus — data goes stale and stays stale.
  // 7. No shared cache — every mount refetches from scratch.
  // 8. After a mutation elsewhere, nothing tells this component to update.
}
*/

// All eight problems are structural, not oversights: `useState` + `useEffect` has
// no vocabulary for cancellation, deduplication, staleness or cache invalidation.
// That is why server state needs a data library and client state does not.
