const preparedConnections = new Map<string, Promise<void>>();

function createLazyAsync<T>(factory: () => Promise<T>): () => Promise<T> {
  let promise: Promise<T> | null = null;

  return () => {
    if (!promise) {
      promise = factory().catch((error) => {
        promise = null;
        throw error;
      });
    }

    return promise;
  };
}

function singleFlight<T>(
  cache: Map<string, Promise<T>>,
  key: string,
  factory: () => Promise<T>,
): Promise<T> {
  const cached = cache.get(key);
  if (cached) return cached;

  const promise = factory().catch((error) => {
    cache.delete(key);
    throw error;
  });

  cache.set(key, promise);
  return promise;
}

export const loadLiveKit = createLazyAsync<typeof import('livekit-client')>(
  () => import('livekit-client'),
);

export function preloadLiveKit() {
  void loadLiveKit().catch(() => undefined);
}

function shouldPrepareConnection(livekitUrl: string) {
  try {
    return new URL(livekitUrl).hostname !== 'mock.livekit.local';
  } catch {
    return false;
  }
}

export function prepareLiveKitConnection(livekitUrl: string, token: string) {
  if (!shouldPrepareConnection(livekitUrl)) {
    return loadLiveKit().then(() => undefined);
  }

  const key = `${livekitUrl}\n${token}`;
  return singleFlight(preparedConnections, key, () =>
    loadLiveKit().then(async ({ Room }) => {
      const room = new Room();
      await room.prepareConnection(livekitUrl, token);
      await room.disconnect(false);
    }),
  );
}
